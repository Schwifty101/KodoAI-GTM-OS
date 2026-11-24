"""Autopilot: each worker loop `autopilot_tick` looks at where leads wait and enqueues at most one existing pass.
`decide` is pure over `AutoState`; `load_state` builds that state from the database. It never approves, sends or changes a cap."""
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from gtm.batches import BATCH_SIZE
from gtm.budget import spent_since
from gtm.db import fetch_all
from gtm.jobs import enqueue
from gtm.settings_store import set_setting, setting

PIPELINE = ["walk", "clean", "verify-sheet", "enrich", "signals", "select", "draft"]
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
VERIFY_CREDITS = 0.5  # Hunter credits per verified email (bucket hunter_import)


@dataclass
class BatchStage:
    batch_id: str
    scraped: int = 0
    sheet_email_cleaned: int = 0  # cleaned sheet leads with an unverified email: verify-sheet picks them
    cleaned: int = 0  # all cleaned leads, sheet ones included
    enriched: int = 0
    signalled: int = 0
    approved_undrafted: int = 0  # selected and approved on /review


@dataclass
class AutoState:
    on: bool = False
    paused_reason: str | None = None
    spent_usd: float = 0.0
    limit_usd: float = 0.0  # 0 = no limit
    started_at: str = ""
    target: int = 100
    open_job: bool = False
    tried: set = field(default_factory=set)  # (kind, batch_id) with a done job since started_at
    batches: list = field(default_factory=list)
    current_fill: int = 0  # numbered leads in the current batch incl. batch_base
    in_flight: int = 0  # cleaned + enriched + signalled across batches
    unapproved_selected: int = 0
    last_budget: tuple | None = None  # (kind, error) of the newest paused_budget job since start
    recent_failures: int = 0  # consecutive failed pipeline jobs, newest first
    tiles_left: bool = False
    walk_tiles: int = 3  # not in the plan's field list: the walk argv needs it and decide is pure
    verify_allowed: bool = True  # not in the plan's field list: false once the import allowance cannot cover one more email


@dataclass
class Decision:
    state: str  # off | running | waiting_approval | paused: <reason>
    enqueue: tuple | None = None


STAGES = [("clean", "scraped", []), ("verify-sheet", "sheet_email_cleaned", ["--confirm"]), ("enrich", "cleaned", []),
          ("signals", "enriched", []), ("select", "signalled", []), ("draft", "approved_undrafted", [])]


def decide(s: AutoState) -> Decision:
    if not s.on:
        return Decision("off")
    if s.paused_reason:
        return Decision(f"paused: {s.paused_reason}")
    if s.open_job:
        return Decision("running")
    if s.limit_usd > 0 and s.spent_usd >= s.limit_usd:
        return Decision("paused: spend limit")
    if s.last_budget:
        kind, err = s.last_budget
        return Decision("paused: daily cap" if kind == "daily" else f"paused: {err}")
    if s.recent_failures >= 3:
        return Decision("paused: errors")
    for kind, field_, extra in STAGES:
        if kind == "verify-sheet" and not s.verify_allowed:
            continue
        for b in s.batches:
            if getattr(b, field_) and (kind, b.batch_id) not in s.tried:
                return Decision("running", (kind, ["--batch", b.batch_id, *extra]))
    if s.current_fill + s.in_flight >= s.target or s.unapproved_selected >= s.target:
        return Decision("waiting_approval")
    if not s.tiles_left:
        return Decision("paused: no tiles left")
    return Decision("running", ("walk", ["--tiles", str(s.walk_tiles)]))


def _last_budget(jobs: list[dict], now: datetime) -> tuple | None:
    """Newest paused_budget job (jobs are newest first) as (kind, message). A daily pause from an earlier UTC day is over."""
    for j in jobs:
        if j["status"] != "paused_budget":
            continue
        m = re.match(r"\[(daily|credit)\] (.*)", j.get("error") or "", re.S)
        kind, err = (m.group(1), m.group(2)) if m else ("credit", j.get("error") or "")
        when = datetime.fromisoformat(j.get("finished_at") or j["created_at"])
        return None if kind == "daily" and when.astimezone(timezone.utc).date() < now.astimezone(timezone.utc).date() else (kind, err)
    return None


def _failures(jobs: list[dict]) -> int:
    n = 0
    for j in jobs:
        if j["status"] == "failed":
            n += 1
        elif j["status"] in ("done", "paused_budget"):
            break
    return n


def load_state(db, now: datetime) -> AutoState:
    started = setting("autopilot_started_at", db)
    since = started or EPOCH.isoformat()
    jobs = fetch_all(lambda: db.table("jobs").select("kind,payload,status,error,created_at,finished_at").in_("kind", PIPELINE).gte("created_at", since).order("created_at", desc=True).order("id"))
    tried = set()
    for j in jobs:
        argv = (j["payload"] or {}).get("argv", [])
        if j["status"] == "done" and "--batch" in argv:
            tried.add((j["kind"], argv[argv.index("--batch") + 1]))
    open_job = bool(db.table("jobs").select("id").in_("kind", PIPELINE).in_("status", ["queued", "running"]).limit(1).execute().data)
    # one pass over every lead still moving through the pipeline, counted per source batch in Python (no per-batch queries)
    leads = fetch_all(lambda: db.table("leads").select("batch_id,status,email_source,email_verified,owner_email,approved").in_("status", ["scraped", "cleaned", "enriched", "signalled", "selected"]).order("id"))
    stages: dict[str, BatchStage] = {}
    unapproved = 0
    for r in leads:
        b = stages.setdefault(r["batch_id"], BatchStage(r["batch_id"]))
        st = r["status"]
        if st == "selected":
            if r["approved"]:
                b.approved_undrafted += 1
            else:
                unapproved += 1
            continue
        setattr(b, st, getattr(b, st) + 1)
        if st == "cleaned" and r["email_source"] == "sheet" and r["email_verified"] is False and r["owner_email"]:
            b.sheet_email_cleaned += 1
    numbered = Counter(r["batch_no"] for r in fetch_all(lambda: db.table("leads").select("batch_no").not_.is_("batch_no", "null").order("id")))
    base = {int(k): v for k, v in setting("batch_base", db).items()}
    cur = max([*numbered, *base], default=1)
    fill = numbered.get(cur, 0) + base.get(cur, 0)
    spent = sum(r["usd"] or 0 for r in fetch_all(lambda: db.table("cost_log").select("usd").gte("created_at", since).order("id")))
    tiles = bool(db.table("coverage").select("id").eq("status", "pending").limit(1).execute().data)
    allowance_left = setting("import_hunter_allowance_credits", db) - spent_since(db, "hunter_import", EPOCH)
    return AutoState(
        on=setting("autopilot_on", db), spent_usd=spent, limit_usd=setting("autopilot_limit_usd", db), started_at=started,
        target=setting("autopilot_target", db), open_job=open_job, tried=tried, batches=list(stages.values()),
        current_fill=0 if fill >= BATCH_SIZE else fill, in_flight=sum(b.cleaned + b.enriched + b.signalled for b in stages.values()),
        unapproved_selected=unapproved, last_budget=_last_budget(jobs, now), recent_failures=_failures(jobs), tiles_left=tiles,
        walk_tiles=setting("walk_tiles_per_run", db), verify_allowed=allowance_left >= VERIFY_CREDITS)


def autopilot_tick(db, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    d = decide(load_state(db, now)) if setting("autopilot_on", db) else Decision("off")
    if setting("autopilot_state", db) != d.state:
        set_setting(db, "autopilot_state", d.state)
    return enqueue(db, d.enqueue[0], {"argv": d.enqueue[1]}) if d.enqueue else None

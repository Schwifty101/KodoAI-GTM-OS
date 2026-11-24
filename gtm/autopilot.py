"""Autopilot: each worker loop `autopilot_tick` looks at where leads wait and enqueues at most one existing pass.
`decide` is pure over `AutoState`; `load_state` builds that state from the database. It never approves, sends or changes a cap."""
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from gtm.budget import spent_since
from gtm.db import fetch_all
from gtm.jobs import enqueue
from gtm import settings_store
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
    walk_dud: int = 0  # consecutive newest walk jobs that scraped 0 tiles (every tile failed)
    out_of_credits: bool = False  # newest enrich/signals/verify-sheet job ended with out_of_credits > 0
    walk_tiles: int = 3  # not in the plan's field list: the walk argv needs it and decide is pure
    verify_allowed: bool = True  # not in the plan's field list: false once the import allowance cannot cover one more email


@dataclass
class Decision:
    state: str  # off | running | waiting_approval | paused: <reason>
    enqueue: tuple | None = None
    n: int | None = None  # draft only: approved leads waiting, stored in the job payload so more approvals redraft but stuck leads do not loop


STAGES = [("clean", "scraped", []), ("verify-sheet", "sheet_email_cleaned", ["--confirm"]), ("enrich", "cleaned", []),
          ("signals", "enriched", []), ("select", "signalled", []), ("draft", "approved_undrafted", [])]


def decide(s: AutoState) -> Decision:
    if not s.on:
        return Decision("off")
    if s.open_job:
        return Decision("running")
    if s.limit_usd > 0 and s.spent_usd >= s.limit_usd:
        return Decision("paused: spend limit")
    if s.last_budget:
        kind, err = s.last_budget
        return Decision("paused: daily cap" if kind == "daily" else f"paused: {err}")
    if s.out_of_credits:
        return Decision("paused: out of credits")
    if s.recent_failures >= 3:
        return Decision("paused: errors")
    for kind, field_, extra in STAGES:
        if kind == "verify-sheet" and not s.verify_allowed:
            continue
        for b in s.batches:
            n = getattr(b, field_)
            if n and ((kind, b.batch_id, n) if kind == "draft" else (kind, b.batch_id)) not in s.tried:
                return Decision("running", (kind, ["--batch", b.batch_id, *extra]), n if kind == "draft" else None)
    if s.current_fill + s.in_flight >= s.target or s.unapproved_selected >= s.target:
        return Decision("waiting_approval")
    if not s.tiles_left:
        return Decision("paused: no tiles left")
    if s.walk_dud >= 3:
        return Decision("paused: walk found nothing (3 in a row)")
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


def _out(j: dict) -> str:
    return (j.get("result") or {}).get("output") or ""


def _walk_dud(jobs: list[dict]) -> int:
    """Consecutive newest done walk jobs whose output says 'tiles': 0 (run_walk marks failed tiles and still ends done)."""
    n = 0
    for j in jobs:
        if j["kind"] != "walk" or j["status"] != "done":
            continue
        m = re.search(r"'tiles': (\d+)", _out(j))
        if not m or int(m.group(1)) > 0:
            break
        n += 1
    return n


def _out_of_credits(jobs: list[dict]) -> bool:
    """The newest done enrich/signals/verify-sheet job reported out_of_credits > 0 (leads stay cleaned, so this is not a failure)."""
    for j in jobs:
        if j["kind"] in ("enrich", "signals", "verify-sheet") and j["status"] == "done":
            m = re.search(r"'out_of_credits': (\d+)", _out(j))
            return bool(m and int(m.group(1)) > 0)
    return False


def _tried(jobs: list[dict]) -> set:
    """(kind, batch) passes already run since start; draft also carries the approved count it ran for. A user-cancelled job counts, a deploy-interrupted one reruns."""
    tried = set()
    for j in jobs:
        argv = (j["payload"] or {}).get("argv", [])
        if (j["status"] == "done" or (j["status"] == "cancelled" and j.get("error") != "interrupted")) and "--batch" in argv:
            key = (j["kind"], argv[argv.index("--batch") + 1])
            tried.add((*key, j["payload"].get("n")) if j["kind"] == "draft" else key)
    return tried


def _fresh(key: str, db):
    """A setting read that skips the 60 s cache, so Pause and Start act at once."""
    settings_store._cache.pop(key, None)
    return setting(key, db)


def _fill(fill: int, target: int) -> int:
    """Leads in the current batch towards `target`: a batch holding target or more counts as full (0), so a target below 100 never stalls the walk."""
    return fill % target if target > 0 else fill


def _failures(jobs: list[dict]) -> int:
    n = 0
    for j in jobs:
        if j["status"] == "failed":
            n += 1
        elif j["status"] in ("done", "paused_budget"):
            break
    return n


def load_state(db, now: datetime) -> AutoState:
    on = _fresh("autopilot_on", db)
    # cheap exit: off, or a pipeline job is already queued or running, so no scan below is needed
    open_job = bool(db.table("jobs").select("id").in_("kind", PIPELINE).in_("status", ["queued", "running"]).limit(1).execute().data)
    if not on or open_job:
        return AutoState(on=on, open_job=open_job)
    started = _fresh("autopilot_started_at", db)
    since = started or EPOCH.isoformat()
    jobs = fetch_all(lambda: db.table("jobs").select("kind,payload,status,error,result,created_at,finished_at").in_("kind", PIPELINE).gte("created_at", since).order("created_at", desc=True).order("id"))
    # one pass over every lead still moving through the pipeline, counted per source batch in Python (no per-batch queries)
    leads = fetch_all(lambda: db.table("leads").select("batch_id,status,email_source,email_verified,owner_email,approved,reject_reason").in_("status", ["scraped", "cleaned", "enriched", "signalled", "selected"]).order("id"))
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
        if st == "signalled" and r["reject_reason"]:
            continue  # select skipped it (no_handoff, no_email, already_contacted): it never advances, so it neither blocks nor throttles
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
    target = _fresh("autopilot_target", db)
    return AutoState(
        on=on, spent_usd=spent, limit_usd=_fresh("autopilot_limit_usd", db), started_at=started,
        target=target, open_job=False, tried=_tried(jobs), batches=list(stages.values()),
        current_fill=_fill(fill, target), in_flight=sum(b.cleaned + b.enriched + b.signalled for b in stages.values()),
        unapproved_selected=unapproved, last_budget=_last_budget(jobs, now), recent_failures=_failures(jobs), tiles_left=tiles,
        walk_dud=_walk_dud(jobs), out_of_credits=_out_of_credits(jobs),
        walk_tiles=setting("walk_tiles_per_run", db), verify_allowed=allowance_left >= VERIFY_CREDITS)


def autopilot_tick(db, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    d = decide(load_state(db, now)) if _fresh("autopilot_on", db) else Decision("off")
    if _fresh("autopilot_state", db) != d.state:
        set_setting(db, "autopilot_state", d.state)
    if not d.enqueue:
        return None
    return enqueue(db, d.enqueue[0], {"argv": d.enqueue[1], **({"n": d.n} if d.n else {})})

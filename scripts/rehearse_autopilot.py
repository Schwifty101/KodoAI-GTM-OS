"""Rehearse gtm.autopilot on TEST_AP_ leads. Settings and enqueue are dict-backed fakes; passes are simulated straight in the DB.
Real rows in the pipeline are tolerated: their decisions are printed, never executed. Run: uv run python scripts/rehearse_autopilot.py"""
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gtm import autopilot as ap
from gtm import batches as gb
from gtm.db import get_db
from gtm.settings_store import DEFAULTS

db = get_db()
now = datetime.now(timezone.utc)
FAKE = {**DEFAULTS, "autopilot_on": True, "autopilot_limit_usd": 2.0, "autopilot_started_at": now.isoformat(),
        "autopilot_target": 8, "batch_base": {}}
QUEUED: list = []  # what the fake enqueue received: nothing real is ever queued
fake_setting = lambda k, db=None: FAKE[k]  # noqa: E731
fake_set = lambda db, k, v: FAKE.__setitem__(k, v)  # noqa: E731
ap.setting, ap.set_setting, gb.setting = fake_setting, fake_set, fake_setting
ap.enqueue = lambda db, kind, payload=None, run_after=None: QUEUED.append((kind, payload)) or "fake-job"
N, SKIP = 12, {0, 1}  # leads 0 and 1 get no_handoff and stay signalled
jobs_before = db.table("jobs").select("id", count="exact").execute().count


def stage(b, frm, to, **extra):
    db.table("leads").update({"status": to, **extra}).eq("batch_id", b).like("place_id", "TEST_AP_%").eq("status", frm).execute()


def simulate(kind, b):
    if kind == "clean": stage(b, "scraped", "cleaned")
    elif kind == "enrich": stage(b, "cleaned", "enriched", owner_name="Test Owner", owner_email="o@test.invalid", email_verified=True)
    elif kind == "signals": stage(b, "enriched", "signalled")
    elif kind == "select":
        for i in SKIP:
            db.table("leads").update({"reject_reason": "no_handoff"}).eq("place_id", f"TEST_AP_{i:02d}").execute()
        ids = [r["id"] for r in db.table("leads").select("id").eq("batch_id", b).eq("status", "signalled").is_("reject_reason", "null").execute().data]
        db.table("leads").update({"status": "selected"}).in_("id", ids).execute()
        gb.assign_batches(db, ids)
    elif kind == "draft":
        db.table("leads").update({"status": "drafted"}).eq("batch_id", b).eq("status", "selected").eq("approved", True).execute()
    else:
        raise SystemExit(f"unsimulated pass {kind}")


def approve(b, k):
    ids = [r["id"] for r in db.table("leads").select("id").eq("batch_id", b).eq("status", "selected").eq("approved", False).order("place_id").limit(k).execute().data]
    db.table("leads").update({"approved": True}).in_("id", ids).execute()
    return len(ids)


def cleanup():
    db.table("cost_log").delete().eq("provider", "TEST_ap").execute()
    db.table("leads").delete().like("place_id", "TEST_AP_%").execute()
    db.table("batches").delete().like("name", "TEST_AP%").execute()


try:
    cleanup()
    bid = db.table("batches").insert({"name": "TEST_AP rehearsal", "city": "Test", "state": "TX", "query": "test"}).execute().data[0]["id"]
    db.table("leads").insert([{"place_id": f"TEST_AP_{i:02d}", "name": f"TEST_AP lead {i}", "batch_id": bid, "status": "scraped"} for i in range(N)]).execute()
    first = ap.load_state(db, now)
    print(f"real pipeline batches present (decisions printed, never executed): {len([b for b in first.batches if b.batch_id != bid])}; open real job: {first.open_job}")
    print(f"autopilot_tick via fakes -> {ap.autopilot_tick(db, now)}; fake queue {QUEUED}; fake state {FAKE.get('autopilot_state')!r}")
    QUEUED.clear()
    skipped, tranches, executed, end = set(), [6, 4], [], "50 iterations"
    for it in range(1, 51):
        s = ap.load_state(db, now)
        s.tried |= skipped
        d = ap.decide(s)
        what = f"{d.enqueue[0]} {d.enqueue[1]}" if d.enqueue else "-"
        print(f"{it:2d} {d.state:18s} {what}" + (f" n={d.n}" if d.n else ""))
        if d.enqueue:
            kind, argv = d.enqueue
            b = argv[argv.index("--batch") + 1] if "--batch" in argv else None
            if b != bid:
                print("   ^ real batch or non-batch pass: NOT executed")
                if b is None:
                    end = f"would queue {kind} (not simulated)"
                    break
                skipped.add((kind, b, d.n) if kind == "draft" else (kind, b))
                continue
            simulate(kind, b)
            executed.append(kind)
        elif d.state == "waiting_approval":
            if not tranches:
                end = "waiting_approval, both tranches approved and drafted"
                break
            print(f"   owner approves {approve(bid, tranches.pop(0))} leads")
        else:
            end = d.state
            break
    final: dict = {}
    for r in db.table("leads").select("status,batch_no,reject_reason").like("place_id", "TEST_AP_%").execute().data:
        k = r["status"] + (f"/{r['reject_reason']}" if r["reject_reason"] else "")
        final[k] = final.get(k, 0) + 1
    print("final TEST_AP_ statuses:", final)
    # spend limit demo: a TEST_ap cost row above the limit, counted because started_at is moved back
    row = db.table("cost_log").insert({"provider": "TEST_ap", "units": 1, "usd": 5.0, "note": "rehearsal", "batch_id": bid}).execute().data[0]["id"]
    FAKE["autopilot_started_at"] = datetime(1970, 1, 2, tzinfo=timezone.utc).isoformat()
    s = ap.load_state(db, now)
    lim = ap.decide(s).state
    # same state with limit 0; old real paused_budget/failed jobs (visible from epoch) are cleared so only the limit differs
    nolim = ap.decide(replace(s, limit_usd=0.0, last_budget=None, recent_failures=0)).state
    print(f"spend demo: spent ${s.spent_usd:.2f} vs limit $2 -> {lim!r}; limit 0 -> {nolim!r}")
    assert s.spent_usd >= 5 and lim == "paused: spend limit" and not nolim.startswith("paused")
    assert not QUEUED and db.table("jobs").select("id", count="exact").execute().count == jobs_before
    print(f"SUMMARY ended: {end}; simulated passes: {executed}; real jobs created: 0; fake queue empty")
finally:
    cleanup()
    left = (db.table("leads").select("id", count="exact").like("place_id", "TEST_AP_%").execute().count,
            db.table("batches").select("id", count="exact").like("name", "TEST%").execute().count,
            db.table("cost_log").select("id", count="exact").eq("provider", "TEST_ap").execute().count)
    print("cleanup check (TEST_AP_ leads, TEST batches, TEST_ap cost rows):", left)

"""`uv run python -m gtm.cli <pass> ...`: one command per pass."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from gtm import budget
from gtm.budget import BudgetExceeded
from gtm.apify import MIN_CAP, run_places
from gtm.db import fetch_all, get_db
from gtm.tz import lead_tz
from gtm.clean import run_clean
from gtm.config import get_settings
from gtm.enrich import hunter_domain_finder, run_enrich, site_owner_finder
from gtm.harvest import HarvestClient, harvest_finder
from gtm.hunter import HunterPool
from gtm.jobs import enqueue
from gtm.import_history import parse_line, run_import
from gtm.llm import complete_json
from gtm.prospeo import ProspeoClient, prospeo_finder
from gtm.owner_search import search_owner_finder
from gtm.researcher import gemini_step, research_owner_finder
from gtm.search import serper_search
from gtm.sitescrape import http_fetch
from gtm.draft import run_draft, run_followups
from gtm.gmail import gmail_service
from gtm.replies import run_replies
from gtm.select import run_select
from gtm.send import allowance, send_with_reply_check
from gtm.signals import fetch_evidence, run_signals
from gtm.scrape import DEFAULT_QUERIES, new_batch, scrape_city


def cmd_scrape(a: argparse.Namespace) -> None:
    budget.require("apify", a.max_usd)  # before new_batch: a blocked scrape leaves no empty batch
    queries = a.query or DEFAULT_QUERIES
    est = a.max_places * len(queries) * 0.005
    print(f"Scraping {a.city}, {a.state}: {queries}; up to ~${est:.2f} (hard cap ${a.max_usd:.2f}, listed price $0.005/place)")
    db = get_db()
    batch = new_batch(db, a.city, a.state, queries)
    new, known = scrape_city(db, lambda inp: run_places(inp, a.max_usd), a.city, a.state, queries, batch, a.max_places)
    print(f"batch {batch}: {new} new leads, {known} already known")


def cmd_clean(a: argparse.Namespace) -> None:
    print(run_clean(get_db(), a.batch))


def cmd_enrich(a: argparse.Namespace) -> None:
    pool = HunterPool(get_settings().hunter_keys, batch_id=a.batch)
    available = {
        "site": site_owner_finder(pool),  # free scrape for a name, then Hunter Email Finder
        "search": search_owner_finder(pool, serper_search, complete_json),  # "owner of <domain>" search, then Hunter Email Finder
        "research": research_owner_finder(pool, serper_search, http_fetch, gemini_step, budget=a.research_budget),  # LLM web-research loop for a named owner, code-validated, then Hunter Email Finder
        "prospeo": prospeo_finder(ProspeoClient(get_settings().prospeo_api_key, batch_id=a.batch)),  # verified email for a named owner; pays only on a find
        "harvest": harvest_finder(HarvestClient(get_settings().harvest_api_key, a.harvest_budget, batch_id=a.batch), serper_search),  # LinkedIn lookup of a named owner
        "hunter": hunter_domain_finder(pool),  # Hunter Domain Search
    }
    finders = [available[n] for n in a.finders.split(",")]
    print(run_enrich(get_db(), finders, a.batch, a.limit, a.retry_no_buyer))


def cmd_signals(a: argparse.Namespace) -> None:
    age = a.max_age_days or get_settings().signal_max_age_days
    if not age:
        sys.exit("No signal recency window is set. MedSpa/ does not define one: set SIGNAL_MAX_AGE_DAYS in .env or pass --max-age-days.")
    print(run_signals(get_db(), complete_json, fetch_evidence, a.batch, date.today(), age))


def cmd_select(a: argparse.Namespace) -> None:
    print(f"selected {run_select(get_db(), complete_json, a.batch)} leads")


def cmd_draft(a: argparse.Namespace) -> None:
    db = get_db()
    only = {m["id"] for m in db.table("mailboxes").select("id,address").in_("address", a.mailbox).execute().data} if a.mailbox else None
    print(f"drafted {run_draft(db, complete_json, gmail_service, a.batch, date.today(), only)} Touch 1 emails in Gmail Drafts (nothing sent)")


def cmd_followups(a: argparse.Namespace) -> None:
    db = get_db()
    run_replies(db, gmail_service, complete_json)  # a lead who already said stop gets no follow-up draft
    print(f"drafted {run_followups(db, gmail_service, date.today())} follow-ups in Gmail Drafts (nothing sent)")


def cmd_send(a: argparse.Namespace) -> None:
    db, s = get_db(), get_settings()
    if not a.confirm:
        for mb in db.table("mailboxes").select("*").execute().data:
            room = allowance(mb, date.today(), s.ramp_start, s.ramp_step, min(s.daily_cap, mb["daily_cap"]))
            print(f"{mb['address']}: paused={mb['paused']} allowance today={room}")
        sys.exit("Dry run only. Sending is a separate, explicit action: add --confirm to send due drafts.")
    print(send_with_reply_check(db, gmail_service, complete_json, date.today(), s))  # replies first, then send


def cmd_import_history(a: argparse.Namespace) -> None:
    recs = [parse_line(l) for l in open(a.file) if l.strip()]
    print(f"read {len(recs)} history rows;", run_import(get_db(), recs), "suppression rows added")


def cmd_replies(a: argparse.Namespace) -> None:
    print(run_replies(get_db(), gmail_service, complete_json))


def cmd_tz_backfill(a: argparse.Namespace) -> None:
    db = get_db()
    rows = fetch_all(lambda: db.table("leads").select("id,city,state").is_("tz", "null").order("id"))
    n = 0
    for r in rows:
        if tz := lead_tz(r["state"], r["city"]):
            db.table("leads").update({"tz": tz}).eq("id", r["id"]).execute()
            n += 1
    print(f"tz set on {n} of {len(rows)} leads")


def cmd_mailbox(a: argparse.Namespace) -> None:
    if a.action == "unpause":
        get_db().table("mailboxes").update({"paused": False, "paused_reason": None}).eq("address", a.address).execute()
        print(f"mailbox {a.address} unpaused")
    else:
        cmd_mailbox_add(a)


def cmd_mailbox_add(a: argparse.Namespace) -> None:
    get_db().table("mailboxes").upsert({"address": a.address, "daily_cap": a.cap, "enabled_on": a.enabled_on or str(date.today())}, on_conflict="address").execute()
    print(f"mailbox {a.address} enabled from {a.enabled_on or date.today()}, cap {a.cap}/day")


def cmd_worker(a: argparse.Namespace) -> None:
    from gtm.worker import main as worker_main

    worker_main(a.poll)


def cmd_enqueue(a: argparse.Namespace) -> None:
    flags = a.flags[1:] if a.flags[:1] == ["--"] else a.flags
    print("queued job", enqueue(get_db(), a.kind, {"argv": flags}))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gtm")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("--city", required=True)
    s.add_argument("--state", required=True)
    s.add_argument("--query", action="append")
    s.add_argument("--max-places", type=int, default=40, help="per query")
    s.add_argument("--max-usd", type=float, default=MIN_CAP)
    s.set_defaults(fn=cmd_scrape)
    c = sub.add_parser("clean")
    c.add_argument("--batch", required=True)
    c.set_defaults(fn=cmd_clean)
    e = sub.add_parser("enrich")
    e.add_argument("--batch", required=True)
    e.add_argument("--limit", type=int, help="max leads this run (each can cost Hunter credits)")
    e.add_argument("--finders", default="site,search,research,prospeo", help="comma list, tried in order, cheapest first. hunter (Domain Search: 33 credits for 1 lead in the Houston run) and harvest (no emails found) are opt-in")
    e.add_argument("--harvest-budget", type=float, default=1.0, help="USD cap on HarvestAPI spend this run")
    e.add_argument("--research-budget", type=int, default=150, help="max Serper searches the research finder may spend this run")
    e.add_argument("--retry-no-buyer", action="store_true", help="also re-run leads already marked no_buyer (spends credits again)")
    e.set_defaults(fn=cmd_enrich)
    g = sub.add_parser("signals")
    g.add_argument("--batch", required=True)
    g.add_argument("--max-age-days", type=int)
    g.set_defaults(fn=cmd_signals)
    x = sub.add_parser("select")
    x.add_argument("--batch", required=True)
    x.set_defaults(fn=cmd_select)
    d = sub.add_parser("draft", help="Touch 1 drafts for selected AND approved leads")
    d.add_argument("--batch", required=True)
    d.add_argument("--mailbox", action="append", help="only assign these mailbox addresses (repeatable)")
    d.set_defaults(fn=cmd_draft)
    f = sub.add_parser("followups", help="Touch 2 (Day 3) and Touch 3 (Day 7) drafts that are due")
    f.set_defaults(fn=cmd_followups)
    m = sub.add_parser("mailbox")
    m.add_argument("action", choices=["add", "unpause"])
    m.add_argument("--address", required=True)
    m.add_argument("--cap", type=int, default=get_settings().daily_cap)
    m.add_argument("--enabled-on", help="YYYY-MM-DD; a new mailbox needs its own warm-up first")
    m.set_defaults(fn=cmd_mailbox)
    h = sub.add_parser("import-history", help="load Notion history lines (email|website|status|reply|DNC) into suppression")
    h.add_argument("file")
    h.set_defaults(fn=cmd_import_history)
    r = sub.add_parser("replies", help="read replies and bounces; stop sequences; honour opt-outs")
    r.set_defaults(fn=cmd_replies)
    x2 = sub.add_parser("send", help="send due drafts (dry run unless --confirm)")
    x2.add_argument("--confirm", action="store_true")
    x2.set_defaults(fn=cmd_send)
    w = sub.add_parser("worker", help="run queued jobs (poll the jobs table)")
    w.add_argument("--poll", type=int, default=15)
    w.set_defaults(fn=cmd_worker)
    q = sub.add_parser("enqueue", help="queue a pass as a job: enqueue <kind> -- <pass flags>")
    q.add_argument("kind")
    q.add_argument("flags", nargs=argparse.REMAINDER)
    q.set_defaults(fn=cmd_enqueue)
    t = sub.add_parser("tz-backfill", help="set tz on leads that have none (free)")
    t.set_defaults(fn=cmd_tz_backfill)
    return p


def main(argv: list[str] | None = None) -> None:
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except BudgetExceeded as e:
        sys.exit(f"budget cap reached: {e}")


if __name__ == "__main__":
    main()

"""`uv run python -m gtm.cli <pass> ...`: one command per pass."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from gtm.apify import MIN_CAP, run_places
from gtm.db import get_db
from gtm.clean import run_clean
from gtm.config import get_settings
from gtm.enrich import hunter_domain_finder, run_enrich, site_owner_finder
from gtm.hunter import HunterPool
from gtm.llm import complete_json
from gtm.owner_search import search_owner_finder
from gtm.search import serper_search
from gtm.signals import fetch_evidence, run_signals
from gtm.scrape import DEFAULT_QUERIES, new_batch, scrape_city


def cmd_scrape(a: argparse.Namespace) -> None:
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
        "hunter": hunter_domain_finder(pool),  # Hunter Domain Search
    }
    finders = [available[n] for n in a.finders.split(",")]
    print(run_enrich(get_db(), finders, a.batch, a.limit))


def cmd_signals(a: argparse.Namespace) -> None:
    age = a.max_age_days or get_settings().signal_max_age_days
    if not age:
        sys.exit("No signal recency window is set. MedSpa/ does not define one: set SIGNAL_MAX_AGE_DAYS in .env or pass --max-age-days.")
    print(run_signals(get_db(), complete_json, fetch_evidence, a.batch, date.today(), age))


def main() -> None:
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
    e.add_argument("--finders", default="site,search,hunter", help="comma list, tried in order, cheapest first")
    e.set_defaults(fn=cmd_enrich)
    g = sub.add_parser("signals")
    g.add_argument("--batch", required=True)
    g.add_argument("--max-age-days", type=int)
    g.set_defaults(fn=cmd_signals)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

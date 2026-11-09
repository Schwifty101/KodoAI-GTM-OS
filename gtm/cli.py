"""`uv run python -m gtm.cli <pass> ...`: one command per pass."""

from __future__ import annotations

import argparse

from gtm.apify import MIN_CAP, run_places
from gtm.db import get_db
from gtm.scrape import DEFAULT_QUERIES, new_batch, scrape_city


def cmd_scrape(a: argparse.Namespace) -> None:
    queries = a.query or DEFAULT_QUERIES
    est = a.max_places * len(queries) * 0.005
    print(f"Scraping {a.city}, {a.state}: {queries}; up to ~${est:.2f} (hard cap ${a.max_usd:.2f}, listed price $0.005/place)")
    db = get_db()
    batch = new_batch(db, a.city, a.state, queries)
    new, known = scrape_city(db, lambda inp: run_places(inp, a.max_usd), a.city, a.state, queries, batch, a.max_places)
    print(f"batch {batch}: {new} new leads, {known} already known")


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
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

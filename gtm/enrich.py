"""Enrich pass: find a verified decision-maker email per cleaned lead. A lead with none is no_buyer, kept, never re-bought."""

from __future__ import annotations

from gtm.buyer import is_decision_maker, is_role_email, pick_buyer  # noqa: F401  (re-exported: the plan's interface)
from gtm.hunter import HunterPool, OutOfCredits
from gtm.sitescrape import find_owner_candidates, http_fetch
from gtm.status import Status


def hunter_domain_finder(pool: HunterPool):
    return lambda lead: pool.domain_search(lead["domain"])


def site_owner_finder(pool: HunterPool, fetch=http_fetch):
    """Free scrape for an owner's name, then Hunter Email Finder (1 credit only if it finds one)."""

    def find(lead: dict) -> list[dict]:
        domain, out = lead["domain"], []
        for n in find_owner_candidates(domain, fetch)[:2]:
            c = pool.email_finder(domain, n["first_name"], n["last_name"])
            if c:
                out.append({**c, "position": n["position"], "source": "site+hunter"})  # the site's title is the evidence
        return out

    return find


def run_enrich(db, finders: list, batch_id: str, limit: int | None = None) -> dict[str, int]:
    q = db.table("leads").select("id,domain,name,city").eq("batch_id", batch_id).eq("status", Status.CLEANED.value)
    rows = (q.limit(limit) if limit else q).execute().data
    counts: dict[str, int] = {}
    for done, r in enumerate(rows):
        try:
            buyer = None
            for f in finders:
                buyer = pick_buyer(f(r))
                if buyer:
                    break
        except OutOfCredits:
            counts["out_of_credits"] = len(rows) - done  # stay `cleaned`: running out of credits is not "no buyer"
            break
        if buyer:
            patch = {"status": Status.ENRICHED.value, "owner_name": f"{buyer['first_name']} {buyer['last_name']}", "owner_title": buyer["position"],
                     "owner_email": buyer["email"], "email_source": buyer["source"], "email_verified": True}
        else:
            patch = {"status": Status.NO_BUYER.value}
        db.table("leads").update(patch).eq("id", r["id"]).execute()
        key = "enriched" if buyer else "no_buyer"
        counts[key] = counts.get(key, 0) + 1
    return counts

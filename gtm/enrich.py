"""Enrich pass: find a verified decision-maker email per cleaned lead. A lead with none is no_buyer, kept, never re-bought."""

from __future__ import annotations

from gtm.buyer import is_decision_maker, is_role_email, pick_buyer, seniority  # noqa: F401  (re-exported: the plan's interface)
from gtm.budget import BudgetExceeded
from gtm.hunter import HunterPool, OutOfCredits
from gtm.sitescrape import find_owner_candidates, fetch_with_fallback
from gtm.costs import spend_context
from gtm.status import Status


def hunter_domain_finder(pool: HunterPool):
    return lambda lead: pool.domain_search(lead["domain"])


def site_owner_finder(pool: HunterPool, fetch=fetch_with_fallback):
    """Free scrape for an owner's name, then Hunter Email Finder (1 credit only if it finds one)."""

    def find(lead: dict) -> list[dict]:
        domain, out = lead["domain"], []
        for n in find_owner_candidates(domain, fetch)[:2]:
            c = pool.email_finder(domain, n["first_name"], n["last_name"])
            if c:
                out.append({**c, "position": n["position"], "source": "site+hunter"})  # the site's title is the evidence
            else:
                out.append({"email": None, "first_name": n["first_name"], "last_name": n["last_name"], "position": n["position"], "source": "site"})
        return out

    return find


def _contact(seen: list[dict]) -> dict:
    """Best owner a failed lead still taught us: a named decision-maker, with the email only if it is not a role address.
    Saved as an unverified contact; the lead stays `no_buyer`, so nothing can draft or send to it."""
    named = [c for c in seen if c.get("first_name") and c.get("last_name") and is_decision_maker(c.get("position"))]
    if not named:
        return {}
    best = min(named, key=lambda c: (c.get("email") is None, seniority(c["position"])))
    email = best.get("email") if best.get("email") and not is_role_email(best["email"]) else None
    return {"owner_name": f"{best['first_name']} {best['last_name']}", "owner_title": best["position"], "owner_email": email,
            "email_source": best.get("source"), "email_verified": False}


def run_enrich(db, finders: list, batch_id: str, limit: int | None = None, retry_no_buyer: bool = False, named_only: bool = False) -> dict[str, int]:
    statuses = [Status.CLEANED.value] + ([Status.NO_BUYER.value] if retry_no_buyer else [])
    q = db.table("leads").select("id,status,domain,name,city,owner_name,owner_title,owner_email").eq("batch_id", batch_id).in_("status", statuses)
    named_only = named_only and retry_no_buyer  # no-op without a retry
    rows = (q.limit(limit) if limit and not named_only else q).execute().data
    if named_only:  # unnamed no_buyer leads are the parked bucket: skip them before any finder runs; limit counts what is left
        rows = [r for r in rows if r["status"] == Status.CLEANED.value or r.get("owner_name")][:limit]
    counts: dict[str, int] = {}
    for done, r in enumerate(rows):
        seen: list[dict] = []
        if r.get("owner_name") and r.get("owner_title"):  # a name saved by an earlier run
            first, _, last = r["owner_name"].partition(" ")
            seen.append({"email": r.get("owner_email"), "first_name": first, "last_name": last, "position": r["owner_title"], "source": "saved"})  # keep a saved email too: a retry must not erase it
        try:
            buyer = None
            with spend_context(batch_id=batch_id, lead_id=r["id"]):
                for f in finders:
                    r["known"] = seen  # names found so far, for finders that look a named person up
                    found = f(r)
                    seen += found
                    buyer = pick_buyer(found)
                    if buyer:
                        break
        except OutOfCredits:
            counts["out_of_credits"] = len(rows) - done  # stay `cleaned`: running out of credits is not "no buyer"
            break
        if buyer:
            patch = {"status": Status.ENRICHED.value, "owner_name": f"{buyer['first_name']} {buyer['last_name']}", "owner_title": buyer["position"],
                     "owner_email": buyer["email"], "email_source": buyer["source"], "email_verified": True}
        else:
            patch = {"status": Status.NO_BUYER.value, **_contact(seen)}
        db.table("leads").update(patch).eq("id", r["id"]).execute()
        key = "enriched" if buyer else "no_buyer"
        counts[key] = counts.get(key, 0) + 1
    return counts

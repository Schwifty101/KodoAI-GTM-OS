"""Import the Notion tracker history (Batch01-03) into `suppression`, so the OS never emails a company, address, bounce or opt-out already handled there.

Input lines are `email|website|status|reply type|DNC`. Only those five fields matter."""

from __future__ import annotations

from gtm.clean import PLATFORM_DOMAINS
from gtm.db import fetch_all
from gtm.replies import FREE_MAIL
from gtm.scrape import _domain


def parse_line(line: str) -> dict:
    email, website, status, reply, flag = (line.rstrip("\n").split("|") + [""] * 5)[:5]
    return {"email": email.strip().lower() or None, "domain": _domain(website.strip()), "status": status.strip(), "reply": reply.strip(), "dnc": flag.strip() == "DNC"}


def _reason(r: dict) -> str:
    if r["dnc"]:
        return "do-not-contact"
    if r["reply"] == "Bounce" or r["status"] == "Bounced":
        return "bounce"
    if r["reply"] == "Negative" or r["status"] == "Not Interested":
        return "not-interested"
    return "notion-contacted"


def history_rows(records: list[dict], have_emails: set[str], have_domains: set[str]) -> list[dict]:
    """Suppression rows still to insert. A bounce blocks the address; the company is still 'contacted', so its domain is blocked too.
    Shared platforms and free-mail domains never become domain rows: that would block every business that uses them."""
    out, emails, domains = [], set(have_emails), set(have_domains)
    for r in records:
        reason = _reason(r)
        if r["email"] and r["email"] not in emails:
            out.append({"email": r["email"], "reason": reason})
            emails.add(r["email"])
        d = r["domain"]
        if d and d not in domains and d not in FREE_MAIL and not any(p in d for p in PLATFORM_DOMAINS):
            out.append({"domain": d, "reason": reason if reason in ("do-not-contact", "not-interested") else "notion-contacted"})
            domains.add(d)
    return out


def run_import(db, records: list[dict]) -> dict[str, int]:
    have = fetch_all(lambda: db.table("suppression").select("email,domain").order("id"))
    rows = history_rows(records, {r["email"] for r in have if r["email"]}, {r["domain"] for r in have if r["domain"]})
    for i in range(0, len(rows), 200):
        db.table("suppression").insert(rows[i : i + 200]).execute()
    return {"emails": sum(1 for r in rows if "email" in r), "domains": sum(1 for r in rows if "domain" in r)}

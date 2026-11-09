"""Pure rules for who counts as a buyer: a decision-maker with a verified personal email."""

from __future__ import annotations

import re

ROLE_LOCALS = {
    "info", "contact", "hello", "hi", "office", "admin", "support", "sales", "team", "appointments", "appointment", "booking",
    "bookings", "frontdesk", "reception", "care", "help", "service", "services", "marketing", "billing", "mail", "enquiries",
    "inquiries", "manager", "hr", "careers", "jobs", "press", "webmaster", "noreply", "no-reply", "concierge", "scheduling",
    "schedule", "clinic", "medspa", "staff", "customerservice", "patientcare",
}
_AUTHORITY = re.compile(r"\b(founder|co-?founder|owner|co-?owner|ceo|chief executive|proprietor)\b", re.I)
_PRESIDENT = re.compile(r"\bpresident\b", re.I)
_NOT_PRESIDENT = re.compile(r"\b(vice|assistant|associate)\b", re.I)


def is_role_email(email: str) -> bool:
    return email.split("@")[0].strip().lower() in ROLE_LOCALS


def is_decision_maker(title: str | None) -> bool:
    """Founder, owner, CEO or equivalent. Directors, managers and VPs are not (conservative; Soban can widen)."""
    if not title:
        return False
    if _AUTHORITY.search(title):
        return True
    return bool(_PRESIDENT.search(title)) and not _NOT_PRESIDENT.search(title)


def seniority(title: str) -> int:
    t = title.lower()
    if re.search(r"\bceo\b|chief executive|(?<!co-)(?<!co)\bfounder\b", t):
        return 0
    if re.search(r"(?<!co-)(?<!co)\bowner\b|\bpresident\b", t):
        return 1
    return 2


def pick_buyer(candidates: list[dict]) -> dict | None:
    ok = [
        c for c in candidates
        if c.get("email") and not is_role_email(c["email"]) and c.get("verification_status") == "valid" and is_decision_maker(c.get("position"))
    ]
    return min(ok, key=lambda c: seniority(c["position"])) if ok else None

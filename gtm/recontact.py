"""Recontact policy core (Plan 9). Pure: no database, no network, no environment.

Fail closed everywhere: a missing, None or unparseable outcome, date or round means "not clear", so a block is lifted only by
positive evidence (a clean outcome and an old enough date), never by missing data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from gtm.status import Status

COOLDOWN_REASONS = frozenset({"notion-contacted", "sheet-sent"})  # every other suppression reason (or none) is permanent
CLEAR_OUTCOMES = frozenset({"no_reply", "auto_reply"})
OUTCOMES = ("no_reply", "auto_reply", "replied", "bounce", "negative", "opt_out", "do_not_contact", "disqualified", "booked", "client", "unknown")
OPEN_TOUCH_STATUSES = frozenset({"drafted", "held", "edited", "approved", "scheduled", "sending"})  # a touch that may still go out
TEST_PREFIXES = ("TEST_", "REHEARSAL_")  # same as gtm.send.is_test_lead, which cannot be imported here (it pulls in the database)


def _in(value, allowed) -> bool:
    return isinstance(value, str) and value in allowed


def _day(value) -> date | None:
    """A date, or an ISO date or timestamp cut to its date. Anything else is None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _round(row: dict) -> int | None:
    """Missing or None means round 1 (the column does not exist before the migration); unparseable is None."""
    value = row.get("round")
    if value is None:
        return 1
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _old_enough(last: date | None, today: date, days: int) -> bool:
    return days >= 1 and last is not None and last + timedelta(days=days) <= today


def keys(email: str | None, domain: str | None) -> set[str]:
    """Lowercase, stripped, empties dropped. The domain is not derived from the email."""
    return {s for v in (email, domain) if isinstance(v, str) and (s := v.strip().lower())}


def _row_keys(row: dict) -> set[str]:
    return keys(row.get("email"), row.get("domain"))


def _clear(row: dict, today: date, days: int, max_rounds: int) -> bool:
    rnd = _round(row)
    return _in(row.get("outcome"), CLEAR_OUTCOMES) and _old_enough(_day(row.get("last_sent_on")), today, days) and rnd is not None and rnd < max_rounds


def released_keys(sup: list[dict], hist: list[dict], today: date, days: int, max_rounds: int) -> set[str]:
    """Suppression keys (emails and domains) that may be approached again.

    Keys of clear ledger rows, minus the keys of every non-clear row, minus every permanent key. A clear row that carries a
    permanent key counts as non-clear, so a bounced address blocks its company's domain too.
    """
    permanent = {k for s in sup if not _in(s.get("reason"), COOLDOWN_REASONS) for k in _row_keys(s)}
    clear: set[str] = set()
    other: set[str] = set()
    for h in hist:
        ks = _row_keys(h)
        (clear if _clear(h, today, days, max_rounds) and not ks & permanent else other).update(ks)
    return clear - other - permanent


def clear_rows(sup: list[dict], hist: list[dict], today: date, days: int, max_rounds: int) -> list[dict]:
    """Ledger rows that are recontact candidates: every key released. Input order kept.

    A row with a non-clear outcome, date or round, or a permanent key, has its keys in the removed set, so it never passes.
    """
    released = released_keys(sup, hist, today, days, max_rounds)
    return [h for h in hist if (ks := _row_keys(h)) and ks <= released]


def lead_released(lead: dict, touches: list[dict], today: date, days: int, max_rounds: int) -> bool:
    """An OS-mailed lead is released only when it is still `sent` with nothing open and its newest sent touch is old enough."""
    place_id = lead.get("place_id")
    if lead.get("status") != Status.SENT.value or not isinstance(place_id, str) or not place_id or place_id.startswith(TEST_PREFIXES):
        return False
    if any(_in(t.get("status"), OPEN_TOUCH_STATUSES) for t in touches):
        return False
    sent = [_day(t.get("sent_at")) for t in touches if t.get("status") == Status.SENT.value]
    rnd = _round(lead)
    return bool(sent) and None not in sent and _old_enough(max(sent), today, days) and rnd is not None and rnd < max_rounds


def _norm(value) -> str:
    return " ".join(value.lower().split()) if isinstance(value, str) else ""


def notion_outcome(status: str, reply: str, dnc: bool) -> str:
    """Notion tracker row -> ledger outcome. Strictest wins, in this order; case and spacing are ignored."""
    s, r = _norm(status), _norm(reply)
    if dnc:
        return "do_not_contact"
    if r == "bounce" or s == "bounced":
        return "bounce"
    if r == "negative" or s == "not interested":
        return "negative"
    if "disqualified" in (s, r):
        return "disqualified"
    if "call booked" in (s, r):
        return "booked"
    if "client" in (s, r):
        return "client"
    if (r and r != "out of office") or s == "replied":
        return "replied"  # includes Status Replied with Reply Type Out of Office: the stricter reading
    if r == "out of office":
        return "auto_reply"
    if s in ("sent", "follow-up due", "cadence complete") or s.startswith("sent at touch"):
        return "no_reply"
    return "unknown"


def last_sent_bound(initial: date, last: date | None) -> date:
    """Never earlier than provable: the cadence is Day 0/3/7, so follow-ups may have gone out unlogged up to Day 7."""
    day_seven = initial + timedelta(days=7)
    return day_seven if last is None else max(last, day_seven)

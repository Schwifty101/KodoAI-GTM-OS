"""Daily provider caps and the paid-Gemini gate. Day and month boundaries are UTC. Call budget.require() before every paid call."""
from datetime import date, datetime, timezone

from gtm.db import fetch_all, get_db
from gtm.settings_store import setting


class BudgetExceeded(RuntimeError):
    pass


CAP_KEYS = {
    "apify": "cap_apify_usd_day", "serper": "cap_serper_queries_day", "gemini": "cap_gemini_usd_day",
    "hunter": "cap_hunter_credits_day", "prospeo": "cap_prospeo_credits_day", "harvest": "cap_harvest_usd_day",
    "serper_maps": "cap_serper_maps_credits_day",
}
USD = {"apify", "gemini", "harvest"}


def _cost_rows(db, provider: str, since: datetime) -> list[dict]:
    d = db or get_db()
    return fetch_all(lambda: d.table("cost_log").select("units,usd,created_at").eq("provider", provider).gte("created_at", since.isoformat()).order("id"))


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def spent_since(db, provider: str, since: datetime) -> float:
    col = "usd" if provider in USD else "units"
    return sum(r[col] or 0 for r in _cost_rows(db, provider, since))


def credit_remaining_usd(db=None, now: datetime | None = None) -> float:
    since = _midnight(date.fromisoformat(setting("credit_balance_as_of", db)))
    return max(0.0, setting("credit_balance_usd", db) - spent_since(db, "gemini", since))


def gemini_allowed(db=None, today: date | None = None) -> bool:
    today = today or datetime.now(timezone.utc).date()
    if today < date.fromisoformat(setting("credit_end_date", db)) and credit_remaining_usd(db) > 0:
        return True
    return bool(setting("allow_paid_gemini", db)) and spent_since(db, "gemini", _midnight(today.replace(day=1))) < setting("paid_gemini_monthly_cap_usd", db)


def require(provider: str, amount: float = 1.0, db=None, now: datetime | None = None) -> None:
    key = CAP_KEYS.get(provider)
    if key is None:
        return
    now = now or datetime.now(timezone.utc)
    if provider == "gemini" and not gemini_allowed(db, now.date()):
        raise BudgetExceeded("gemini: credit ended or used up and paid Gemini is off or at its monthly cap")
    cap = setting(key, db)
    if spent_since(db, provider, _midnight(now.date())) + amount > cap:
        raise BudgetExceeded(f"{provider}: daily cap {cap} reached ({key})")

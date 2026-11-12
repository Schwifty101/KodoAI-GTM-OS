"""Owner-editable settings in the settings table. A missing, unknown or wrong-typed stored value falls back to the default."""
import time
from datetime import date
from typing import Any

from gtm.db import get_db

DEFAULTS: dict[str, bool | int | float | str] = {
    "monthly_budget_pkr": 25000, "pkr_per_usd": 276, "weekly_target": 200,
    "allow_paid_gemini": False, "paid_gemini_monthly_cap_usd": 0.0,
    "credit_end_date": "2027-02-09", "credit_balance_usd": 298.0, "credit_balance_as_of": "2026-11-12",
    "gemini_input_usd_per_m": 1.5, "gemini_output_usd_per_m": 9.0,  # third-party prices, unconfirmed
    "gemini_lite_input_usd_per_m": 0.25, "gemini_lite_output_usd_per_m": 1.5,
    # proposed daily caps, owner adjusts
    "cap_apify_usd_day": 2.0, "cap_serper_queries_day": 700, "cap_gemini_usd_day": 5.0,
    "cap_hunter_credits_day": 100, "cap_prospeo_credits_day": 20, "cap_harvest_usd_day": 0.5,
}
TTL = 60
_cache: dict[str, tuple[float, Any]] = {}


def _ok(key: str, v: Any) -> bool:
    d = DEFAULTS[key]
    if isinstance(d, bool) or isinstance(v, bool):
        return isinstance(d, bool) and isinstance(v, bool)
    if isinstance(d, float):
        return isinstance(v, (int, float))
    if key in ("credit_end_date", "credit_balance_as_of"):
        try:
            return isinstance(v, str) and bool(date.fromisoformat(v))
        except ValueError:
            return False
    return isinstance(v, type(d))


def clear_cache() -> None:
    _cache.clear()


def setting(key: str, db=None) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    rows = (db or get_db()).table("settings").select("value").eq("key", key).execute().data
    v = rows[0]["value"] if rows and _ok(key, rows[0]["value"]) else DEFAULTS[key]
    _cache[key] = (time.monotonic(), v)
    return v


def set_setting(db, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key}")
    if not _ok(key, value):
        raise ValueError(f"{key} needs a {type(DEFAULTS[key]).__name__}, got {value!r}")
    db.table("settings").upsert({"key": key, "value": value, "updated_at": "now()"}).execute()
    clear_cache()


def all_settings(db) -> dict[str, Any]:
    stored = {r["key"]: r["value"] for r in db.table("settings").select("key,value").execute().data}
    return {k: stored[k] if k in stored and _ok(k, stored[k]) else d for k, d in DEFAULTS.items()}

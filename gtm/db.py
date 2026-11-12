from supabase import Client, create_client

from gtm.config import get_settings


def get_db() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_secret_key)


def fetch_all(build, page: int = 1000) -> list[dict]:
    """The Data API returns at most 1000 rows per request. Read every page; build() returns a fresh query each call
    (give it an .order() so pages are stable). Without this, suppression and dedupe checks silently fail open past 1000 rows."""
    rows: list[dict] = []
    lo = 0
    while True:
        chunk = build().range(lo, lo + page - 1).execute().data
        rows += chunk
        if len(chunk) < page:
            return rows
        lo += page

from supabase import Client, create_client

from gtm.config import get_settings


def get_db() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_secret_key)

"""The only reader of the environment. Everything tunable resolves through Settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _keys(env: Mapping[str, str], base: str) -> list[str]:
    """BASE, BASE_2 .. BASE_9 in order, blanks skipped."""
    names = [base] + [f"{base}_{i}" for i in range(2, 10)]
    return [env[n].strip() for n in names if env.get(n, "").strip()]


@dataclass(frozen=True)
class Settings:
    supabase_url: str = ""
    supabase_secret_key: str = ""
    supabase_publishable_key: str = ""
    apify_keys: list[str] = field(default_factory=list)
    hunter_keys: list[str] = field(default_factory=list)
    groq_api_key: str = ""
    gemini_api_key: str = ""
    serper_api_key: str = ""  # env SERP_API_KEY (SERP_PROVIDER=serper)
    google_oauth_client_file: str = ""
    # Sending. Defaults are placeholders until the Task 7 gate sets them.
    daily_cap: int = 40
    ramp_start: int = 10
    ramp_step: int = 5
    pause_bounce_rate: float = 0.03
    pause_min_sends: int = 20
    # 0 = not set. Task 11 reads MedSpa/ for the real value and refuses to run on 0.
    signal_max_age_days: int = 0
    # Footer values: empty by default, appended only if set. Never invented.
    postal_address: str = ""
    ad_disclosure: str = ""
    opt_out_line: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        def s(name: str) -> str:
            return env.get(name, "").strip()

        def n(name: str, default):
            return type(default)(s(name)) if s(name) else default

        d = cls()
        return cls(
            supabase_url=s("SUPABASE_URL"),
            supabase_secret_key=s("SUPABASE_SECRET_KEY"),
            supabase_publishable_key=s("SUPABASE_PUBLISHABLE_KEY"),
            apify_keys=_keys(env, "APIFY_API_KEY"),
            hunter_keys=_keys(env, "HUNTER_API_KEY"),
            groq_api_key=s("GROQ_API_KEY"),
            gemini_api_key=s("GEMINI_API_KEY"),
            serper_api_key=s("SERP_API_KEY"),
            google_oauth_client_file=s("GOOGLE_OAUTH_CLIENT_FILE"),
            daily_cap=n("DAILY_CAP", d.daily_cap),
            ramp_start=n("RAMP_START", d.ramp_start),
            ramp_step=n("RAMP_STEP", d.ramp_step),
            pause_bounce_rate=n("PAUSE_BOUNCE_RATE", d.pause_bounce_rate),
            pause_min_sends=n("PAUSE_MIN_SENDS", d.pause_min_sends),
            signal_max_age_days=n("SIGNAL_MAX_AGE_DAYS", d.signal_max_age_days),
            postal_address=s("POSTAL_ADDRESS"),
            ad_disclosure=s("AD_DISCLOSURE"),
            opt_out_line=s("OPT_OUT_LINE"),
        )


def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    return Settings.from_env(os.environ)

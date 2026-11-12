"""Apify Google Maps runs, with a hard per-run spend cap."""

from __future__ import annotations

import time

import httpx

from gtm import budget
from gtm.config import get_settings

ACTOR = "compass~crawler-google-places"
API = "https://api.apify.com/v2"
MIN_CAP = 0.50  # Apify rejects maxTotalChargeUsd below this (measured)


def choose_key(remaining: dict[str, float]) -> str:
    key, left = max(remaining.items(), key=lambda kv: kv[1])
    if left < MIN_CAP:
        raise RuntimeError(f"no Apify key has the ${MIN_CAP:.2f} minimum run cap left (best: ${left:.2f})")
    return key


def remaining_usd(key: str) -> float:
    d = httpx.get(f"{API}/users/me/limits", headers={"Authorization": f"Bearer {key}"}, timeout=30).json()["data"]
    return d["limits"]["maxMonthlyUsageUsd"] - d["current"]["monthlyUsageUsd"]


def run_places(run_input: dict, max_usd: float = MIN_CAP) -> tuple[list[dict], float | None]:
    """One actor run, stopped by Apify at max_usd. Returns (items, usd charged)."""
    budget.require("apify", max_usd)
    keys = get_settings().apify_keys
    key = choose_key({k: remaining_usd(k) for k in keys})
    h = {"Authorization": f"Bearer {key}"}
    r = httpx.post(f"{API}/acts/{ACTOR}/runs", params={"maxTotalChargeUsd": max_usd}, headers=h, json=run_input, timeout=60)
    r.raise_for_status()
    info = r.json()["data"]
    while info["status"] in ("READY", "RUNNING"):
        time.sleep(5)
        info = httpx.get(f"{API}/actor-runs/{info['id']}", headers=h, timeout=60).json()["data"]
    items = httpx.get(f"{API}/datasets/{info['defaultDatasetId']}/items", params={"clean": "true"}, headers=h, timeout=120).json()
    return items, info.get("usageTotalUsd")

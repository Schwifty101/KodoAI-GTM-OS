"""Prospeo Enrich Person: name + company website to a verified email. Measured 2026-11-10: 2 of 20 owners found, both VERIFIED;
a no-match is free, a find costs 1 credit. The free plan rate-limits hard, so calls are spaced and 429s retried."""

from __future__ import annotations

import time

import httpx

from gtm.buyer import is_decision_maker
from gtm import budget
from gtm.costs import log_cost

URL = "https://api.prospeo.io/enrich-person"


def _post(body: dict, key: str) -> tuple[int, dict]:
    r = httpx.post(URL, headers={"X-KEY": key}, json=body, timeout=60)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


class ProspeoClient:
    def __init__(self, key: str, http=_post, sleep=time.sleep, log=None, batch_id: str | None = None, gap: float = 2.0):
        self.key, self.http, self.sleep, self.gap, self.dead = key, http, sleep, gap, not key
        self.log = log or (lambda note: log_cost("prospeo", 1, None, batch_id=batch_id, note=note))

    def find(self, domain: str, first: str, last: str) -> dict | None:
        """The verified person record, or None (no match, or the account is out of credits: then the client stops asking)."""
        if self.dead:
            return None
        budget.require("prospeo", 1)
        body = {"only_verified_email": True, "data": {"first_name": first, "last_name": last, "company_website": domain}}
        for attempt in range(4):
            self.sleep(self.gap)
            status, j = self.http(body, self.key)
            if status == 429 and attempt < 3:
                self.sleep(5 * (attempt + 1))
                continue
            break
        if status == 429 or j.get("error_code") in {"INSUFFICIENT_CREDITS", "INVALID_API_KEY"}:
            self.dead = True
            return None
        email = ((j.get("person") or {}).get("email") or {})
        if j.get("error") or not email.get("email") or email.get("status") != "VERIFIED":
            return None
        self.log(f"enrich-person:{domain}")
        return j["person"]


def prospeo_finder(client: ProspeoClient):
    """Finder for run_enrich: asks Prospeo about each owner an earlier finder named. Never searches without a name."""

    def find(lead: dict) -> list[dict]:
        out, done = [], set()
        for o in lead.get("known") or []:
            key = (o["first_name"].lower(), o["last_name"].lower())
            if key in done or len(done) >= 2 or not is_decision_maker(o.get("position")):
                continue
            done.add(key)
            p = client.find(lead["domain"], o["first_name"], o["last_name"])
            if not p:
                continue
            same = (p.get("first_name") or "").lower() == key[0] and (p.get("last_name") or "").lower() == key[1]
            if not same:
                continue  # a different person at that company
            # ponytail: Prospeo gives no score field; `only_verified_email` returns only its VERIFIED tier, so it counts as score 100.
            out.append({"email": p["email"]["email"], "first_name": o["first_name"], "last_name": o["last_name"], "position": o["position"],
                        "verification_status": "valid", "score": 100, "source": "prospeo"})
        return out

    return find

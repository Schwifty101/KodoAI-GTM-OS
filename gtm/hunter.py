"""Hunter API with key rotation. Credit costs are the measured ones (docs/spikes/hunter.md):
Domain Search = 1 credit if it returns any email, else 0; Email Finder = 1 credit only if it finds one."""

from __future__ import annotations

import time

import httpx

from gtm.costs import log_cost


class OutOfCredits(RuntimeError):
    pass


def _http(path: str, params: dict, key: str) -> tuple[int, dict]:
    r = httpx.get(f"https://api.hunter.io/v2/{path}", headers={"X-API-KEY": key}, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def _spent(body: dict) -> bool:
    return any("billing period" in (e.get("details") or "") for e in body.get("errors", []))


class HunterPool:
    def __init__(self, keys: list[str], http=_http, log=None, sleep=time.sleep, batch_id: str | None = None):
        self.keys, self.http, self.sleep, self.idx = keys, http, sleep, 0
        self.log = log or (lambda units, note: log_cost("hunter", units, None, batch_id=batch_id, note=note))

    def _call(self, path: str, params: dict) -> dict:
        retries = 0
        while self.idx < len(self.keys):
            status, body = self.http(path, params, self.keys[self.idx])
            if status == 200:
                return body
            if status == 401 or (status == 429 and _spent(body)):
                self.idx += 1  # dead or spent key: move on and remember
            elif status == 429 and retries < 3:
                retries += 1
                self.sleep(1)
            else:
                raise RuntimeError(f"hunter {path} failed: {status} {body}")
        raise OutOfCredits("every Hunter key is spent or invalid")

    def domain_search(self, domain: str) -> list[dict]:
        emails = (self._call("domain-search", {"domain": domain, "limit": 10}).get("data") or {}).get("emails") or []
        if emails:
            self.log(1, f"domain-search:{domain}")
        return [
            {"email": e["value"], "first_name": e.get("first_name"), "last_name": e.get("last_name"), "position": e.get("position"),
             "verification_status": (e.get("verification") or {}).get("status"), "score": e.get("confidence"), "source": "hunter"}
            for e in emails
        ]

    def email_finder(self, domain: str, first: str, last: str) -> dict | None:
        d = self._call("email-finder", {"domain": domain, "first_name": first, "last_name": last}).get("data") or {}
        if not d.get("email"):
            return None
        self.log(1, f"email-finder:{domain}")
        return {"email": d["email"], "first_name": d.get("first_name") or first, "last_name": d.get("last_name") or last,
                "position": d.get("position"), "verification_status": (d.get("verification") or {}).get("status"), "score": d.get("score"),
                "source": "hunter"}

"""HarvestAPI: LinkedIn profile lookup with email finding. Used only for an owner we already have a name for.
Cost is read from the account balance around each call (the docs publish no price; 3 test calls measured ~$0.004 each)."""

from __future__ import annotations

import httpx

from gtm.buyer import is_decision_maker
from gtm import budget
from gtm.costs import log_cost
from gtm.owner_search import _about_business

BASE = "https://api.harvestapi.io"


class HarvestBudget(RuntimeError):
    pass


def _http(path: str, params: dict, key: str) -> tuple[int, dict]:
    r = httpx.get(f"{BASE}{path}", headers={"X-API-Key": key}, params=params, timeout=120)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


class HarvestClient:
    def __init__(self, key: str, budget_usd: float, http=_http, log=None, batch_id: str | None = None):
        self.key, self.http, self.budget, self.spent = key, http, budget_usd, 0.0
        self.log = log or (lambda usd, note: log_cost("harvest", 1, usd, batch_id=batch_id, note=note))

    def _balance(self) -> float:
        status, body = self.http("/users/my-api-user", {}, self.key)
        if status != 200:
            raise RuntimeError(f"harvest balance failed: {status}")
        return float(body["usage"]["balance"])

    def profile(self, url: str) -> dict | None:
        """One profile with email search. None if Harvest has no such profile. Raises HarvestBudget once the cap is reached."""
        budget.require("harvest", 0.01)
        if self.spent >= self.budget:
            raise HarvestBudget(f"Harvest spend cap ${self.budget:.2f} reached")
        before = self._balance()
        status, body = self.http("/linkedin/profile", {"query": url, "main": "true", "findEmail": "true"}, self.key)
        cost = max(before - self._balance(), 0.0)
        self.spent += cost
        self.log(cost, f"profile:{url}")
        if status in (401, 402, 403):
            raise HarvestBudget(f"Harvest refused the call ({status})")
        return (body.get("element") or body) if status == 200 else None


def _same(a: str | None, b: str) -> bool:
    return (a or "").strip().lower() == b.strip().lower()


def _emails(profile: dict, position: str) -> list[dict]:
    """Harvest marks an address `valid` only when it is deliverable and the domain is not catch-all (those come back `risky`)."""
    out = []
    for e in profile.get("emails") or []:
        if not e.get("email"):
            continue
        ok = bool(e.get("deliverable")) and not e.get("catchAllDomain")
        out.append({"email": e["email"], "first_name": profile.get("firstName"), "last_name": profile.get("lastName"), "position": position,
                    "verification_status": "valid" if ok else "unverified", "score": e.get("qualityScore"), "source": "harvest"})
    return out


def harvest_finder(client: HarvestClient, search):
    """Finder for run_enrich. Takes the owners earlier finders named, finds their LinkedIn profile, and accepts a profile only if
    the person and their current company both match the lead. Never searches without a name."""

    def find(lead: dict) -> list[dict]:
        out, done = [], set()
        for o in lead.get("known") or []:
            key = (o["first_name"].lower(), o["last_name"].lower())
            if key in done or len(done) >= 2 or not is_decision_maker(o.get("position")):
                continue
            done.add(key)
            res = search(f'"{o["first_name"]} {o["last_name"]}" {lead["name"]} {lead.get("city") or ""} linkedin')
            url = next((r["link"] for r in res if "linkedin.com/in/" in r["link"]), None)
            if not url:
                continue
            try:
                p = client.profile(url)
            except HarvestBudget:
                return out
            if not p or not (_same(p.get("firstName"), o["first_name"]) and _same(p.get("lastName"), o["last_name"])):
                continue
            companies = [c.get("companyName") or "" for c in p.get("currentPosition") or []]
            if not any(_about_business(c, lead) for c in companies if c):
                continue  # right name, wrong business (e.g. an MD with the same name at a medical-device firm)
            out += _emails(p, o["position"])  # the title is the evidence the earlier finder found, already a decision-maker
        return out

    return find

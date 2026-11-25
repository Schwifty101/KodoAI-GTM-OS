"""20-lead email-finder pilot: Icypeas vs Anymail Finder on no_buyer leads whose owner is already named.
Files hold personal data (.secrets/, git-ignored); the terminal gets counts only.

  uv run python scripts/email_pilot.py sample                      read-only DB; writes .secrets/email_pilot_sample.json
  uv run python scripts/email_pilot.py run --arm icypeas|anymail [--limit N]   PAID vendor calls
  uv run python scripts/email_pilot.py score                       PAID Hunter verifies (0.5 credit each), prints verdicts
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gtm.buyer import is_role_email  # noqa: E402
from gtm.clean import CHAIN_MIN, CHAINS, brand_key  # noqa: E402
from gtm.config import get_settings  # noqa: E402

SECRETS = Path(__file__).resolve().parent.parent / ".secrets"
SAMPLE = SECRETS / "email_pilot_sample.json"
ICY = "https://app.icypeas.com/api"
ANY = "https://api.anymailfinder.com/v5.1/find-email/person"
KEYS = {"icypeas": "icypeas_api_key", "anymail": "anymail_api_key"}
ICY_DONE = {"FOUND", "DEBITED", "NOT_FOUND", "DEBITED_NOT_FOUND", "BAD_INPUT", "INSUFFICIENT_FUNDS", "ABORTED"}


def select_sample(rows: list[dict], n: int = 20) -> list[dict]:
    brands: dict[str, int] = {}
    for r in rows:
        brands[brand_key(r.get("name") or "")] = brands.get(brand_key(r.get("name") or ""), 0) + 1
    out, domains = [], set()
    for r in rows:
        parts = (r.get("owner_name") or "").split()
        name = (r.get("name") or "").lower()
        dom = (r.get("domain") or "").strip().lower()
        if (r.get("status") != "no_buyer" or len(parts) < 2 or not dom or r.get("owner_email") or dom in domains
                or any(c in name for c in CHAINS) or brands[brand_key(r.get("name") or "")] >= CHAIN_MIN):
            continue
        domains.add(dom)
        out.append({"id": r["id"], "first": parts[0], "last": parts[-1], "domain": dom})
        if len(out) == n:
            break
    return out


def _http(method: str, url: str, headers: dict, body: dict) -> tuple[int, dict]:
    r = httpx.request(method, url, headers=headers, json=body, timeout=180)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


class Stop(Exception):
    """Auth failure or out of credits: end the run, no retry."""


def _icypeas(key: str, s: dict, http, sleep) -> dict:
    h = {"Authorization": key, "Content-Type": "application/json"}  # key as-is, no Bearer (api-doc.icypeas.com getting-started)
    code, body = http("POST", f"{ICY}/email-search", h, {"firstname": s["first"], "lastname": s["last"], "domainOrCompany": s["domain"]})
    if code in (401, 402, 403):
        raise Stop(f"icypeas {code}")
    sid = (body.get("item") or {}).get("_id")
    if code != 200 or not sid:
        return {"email": None, "status": f"error_{code}", "credits": 0}
    status, emails = "TIMEOUT", []  # UNVERIFIED: whether a polled search can still debit after TIMEOUT; docs say wait 5-10 s, we poll 6 x 5 s
    for _ in range(6):
        sleep(5)
        code, body = http("POST", f"{ICY}/bulk-single-searchs/read", h, {"id": sid})  # UNVERIFIED: request/response schema inferred from the getting-started page
        if code in (401, 402, 403):
            raise Stop(f"icypeas {code}")
        items = body.get("items") or [{}]
        status = items[0].get("status") or "NONE"
        if status in ICY_DONE:
            emails = (items[0].get("results") or {}).get("emails") or []
            break
    e = emails[0] if emails else {}
    if status == "INSUFFICIENT_FUNDS":
        raise Stop("icypeas out of credits")
    # UNVERIFIED: certainty value list beyond "ultra_sure"; credit rule (1 when FOUND/DEBITED, else 0) is from the getting-started page
    return {"email": e.get("email"), "status": e.get("certainty") or status, "credits": 1 if status in ("FOUND", "DEBITED") else 0}


def _anymail(key: str, s: dict, http, sleep) -> dict:
    code, body = http("POST", ANY, {"Authorization": key, "Content-Type": "application/json"}, {"first_name": s["first"], "last_name": s["last"], "domain": s["domain"]})
    if code in (401, 402):  # 401 unauthorized, 402 upgrade_needed (no credits)
        raise Stop(f"anymail {code}")
    if code != 200:
        return {"email": None, "status": f"error_{code}", "credits": 0}
    return {"email": body.get("email"), "status": body.get("email_status"), "credits": body.get("credits_charged") or 0}


def run(arm: str, sample: list[dict], settings, out: Path, http=_http, log=None, sleep=time.sleep) -> list[dict]:
    key = getattr(settings, KEYS[arm])
    if not key:
        raise SystemExit(f"{KEYS[arm].upper()} is not set; sign up and add it to .env first")
    if log is None:
        from gtm.costs import log_cost as log
    done = json.loads(out.read_text()) if out.exists() else []
    have = {r["id"] for r in done}
    call = _icypeas if arm == "icypeas" else _anymail
    for s in sample:
        if s["id"] in have:  # already paid for: never repeat a call
            continue
        try:
            res = call(key, s, http, sleep)
        except Stop as e:
            print(f"stopped: {e}")
            break
        done.append({"id": s["id"], **res})
        log(arm, res["credits"], 0, lead_id=s["id"], note=f"pilot:{res['status']}")  # usd 0 until prices are set
        SECRETS.mkdir(exist_ok=True)
        out.write_text(json.dumps(done))  # saved after every call, so a crash loses nothing
    return done


def score_rows(rows: list[dict], verify) -> dict:
    r = {"lookups": len(rows), "returned": 0, "role": 0, "verified_calls": 0, "hits": 0, "credits": sum(x.get("credits") or 0 for x in rows)}
    for x in rows:
        if not x.get("email"):
            continue
        r["returned"] += 1
        if is_role_email(x["email"]):
            r["role"] += 1  # can never qualify: no verify credit spent
            continue
        v = verify(x["email"])
        r["verified_calls"] += 1
        r["hits"] += v.get("verification_status") == "valid" and (v.get("score") or 0) >= 75
    return r


def verdict(hits: int) -> str:
    return "buy a month" if hits >= 4 else "supplement only" if hits >= 2 else "drop"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    r = sub.add_parser("run")
    r.add_argument("--arm", choices=list(KEYS), required=True)
    r.add_argument("--limit", type=int, default=20)
    sub.add_parser("score")
    a = ap.parse_args(argv)
    cfg = get_settings()
    if a.cmd == "sample":
        from gtm.db import fetch_all, get_db

        db = get_db()
        rows = fetch_all(lambda: db.table("leads").select("id,name,domain,owner_name,owner_email,status").eq("status", "no_buyer")
                         .not_.is_("owner_name", "null").not_.is_("domain", "null").is_("owner_email", "null").order("id"))
        s = select_sample(rows)
        SECRETS.mkdir(exist_ok=True)
        SAMPLE.write_text(json.dumps(s))
        print(f"candidates {len(rows)}, sampled {len(s)}, distinct domains {len({x['domain'] for x in s})}")
    elif a.cmd == "run":
        if not getattr(cfg, KEYS[a.arm]):
            raise SystemExit(f"{KEYS[a.arm].upper()} is not set; sign up and add it to .env first")
        sample = json.loads(SAMPLE.read_text())[: a.limit]
        res = run(a.arm, sample, cfg, SECRETS / f"email_pilot_{a.arm}.json")
        print(f"{a.arm}: {len(res)} lookups saved, {sum(x['email'] is not None for x in res)} returned, {sum(x['credits'] for x in res)} credits")
    else:
        from gtm.hunter import HunterPool

        pool = HunterPool(cfg.hunter_keys)
        for arm in KEYS:
            f = SECRETS / f"email_pilot_{arm}.json"
            if not f.exists():
                continue
            s = score_rows(json.loads(f.read_text()), pool.verify_email)  # budget.require + cost_log inside verify_email
            print(f"{arm}: lookups {s['lookups']}, returned {s['returned']}, verified hits {s['hits']}, role addresses {s['role']}, "
                  f"credits used {s['credits']} (+{s['verified_calls'] * 0.5} Hunter), hit rate {s['hits']}/20 -> {verdict(s['hits'])}")
        print("verdict: 4+ of 20 = buy a month; 2-3 = supplement only; under 2 = drop")


if __name__ == "__main__":
    main()

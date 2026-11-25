import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import email_pilot as ep  # noqa: E402

from gtm.config import Settings  # noqa: E402


def lead(i, name="Dana Whitfield", domain=None, status="no_buyer", email=None, biz=None):
    return {"id": f"L{i}", "name": biz or f"Glow Studio {i}", "domain": domain or f"glow{i}.com", "owner_name": name, "owner_email": email, "status": status}


def test_sample_filters_and_mixes_domains():
    rows = [
        lead(1), lead(2, name=None), lead(3, domain=" "), lead(4, email="x@y.com"), lead(5, status="enriched"),
        lead(6, name="Cher"),  # one token: cannot split into first/last
        lead(7, biz="Massage Envy Downtown"),  # chain list
        lead(8, domain="same.com"), lead(9, domain="same.com"),
        lead(10, biz="Aura Lounge"), lead(11, biz="Aura Lounge"), lead(12, biz="Aura Lounge"),  # brand x3 = group
    ]
    ids = [s["id"] for s in ep.select_sample(rows, 20)]
    assert ids == ["L1", "L8"]  # L8/L9 share a domain, one kept


def test_sample_caps_at_n():
    assert len(ep.select_sample([lead(i) for i in range(30)], 20)) == 20


def test_split_name():
    s = ep.select_sample([lead(1, name="Dana  van Whitfield")], 5)[0]
    assert (s["first"], s["last"]) == ("Dana", "Whitfield")


def test_run_refuses_without_key(tmp_path):
    with pytest.raises(SystemExit):
        ep.run("icypeas", [{"id": "a"}], Settings(), tmp_path / "o.json", http=lambda *a, **k: pytest.fail("called"), log=lambda *a, **k: None)


S1 = {"id": "a", "first": "Dana", "last": "W", "domain": "a.com"}
S2 = {"id": "b", "first": "Eve", "last": "K", "domain": "b.com"}


def test_icypeas_polls_then_returns_email_and_logs(tmp_path):
    script = [(200, {"success": True, "item": {"_id": "s1", "status": "NONE"}}),
              (200, {"items": [{"status": "SCHEDULED", "results": {}}]}),
              (200, {"items": [{"status": "FOUND", "results": {"emails": [{"email": "dana@a.com", "certainty": "ultra_sure"}]}}]})]
    calls, logs = [], []

    def http(method, url, headers, body):
        calls.append((url, headers, body))
        return script.pop(0)

    out = tmp_path / "o.json"
    res = ep.run("icypeas", [S1], Settings(icypeas_api_key="K"), out, http=http, log=lambda *a, **k: logs.append(a), sleep=lambda s: None)
    assert calls[0][0].endswith("/email-search") and calls[0][1]["Authorization"] == "K"
    assert calls[0][2] == {"firstname": "Dana", "lastname": "W", "domainOrCompany": "a.com"}
    assert calls[1][0].endswith("/bulk-single-searchs/read") and calls[1][2] == {"id": "s1"}
    assert res[0]["email"] == "dana@a.com" and res[0]["status"] == "ultra_sure" and res[0]["credits"] == 1
    assert [l[:3] for l in logs] == [("icypeas", 1, 0)] and json.loads(out.read_text())[0]["email"] == "dana@a.com"


def test_anymail_call_shape_and_credits(tmp_path):
    calls = []

    def http(method, url, headers, body):
        calls.append((url, headers, body))
        return 200, {"email": "dana@a.com", "email_status": "valid", "credits_charged": 1}

    res = ep.run("anymail", [S1], Settings(anymail_api_key="K"), tmp_path / "o.json", http=http, log=lambda *a, **k: None)
    assert calls[0][0] == "https://api.anymailfinder.com/v5.1/find-email/person" and calls[0][1]["Authorization"] == "K"
    assert calls[0][2] == {"first_name": "Dana", "last_name": "W", "domain": "a.com"}
    assert (res[0]["email"], res[0]["status"], res[0]["credits"]) == ("dana@a.com", "valid", 1)


@pytest.mark.parametrize("arm", ["icypeas", "anymail"])
def test_stops_after_first_auth_error(arm, tmp_path):
    calls = []

    def http(*a):
        calls.append(a)
        return 401, {}

    ep.run(arm, [S1, S2], Settings(icypeas_api_key="K", anymail_api_key="K"), tmp_path / "o.json", http=http, log=lambda *a, **k: None)
    assert len(calls) == 1


def test_resume_skips_leads_already_paid(tmp_path):
    out = tmp_path / "o.json"
    out.write_text(json.dumps([{"id": "a", "email": "x@a.com", "status": "valid", "credits": 1}]))
    calls = []

    def http(*a):
        calls.append(a)
        return 200, {"email": None, "email_status": "not_found", "credits_charged": 0}

    res = ep.run("anymail", [S1, S2], Settings(anymail_api_key="K"), out, http=http, log=lambda *a, **k: None)
    assert len(calls) == 1 and [r["id"] for r in res] == ["a", "b"]


@pytest.mark.parametrize("status,score,role,hit", [
    ("valid", 75, False, True), ("valid", 74, False, False), ("accept_all", 99, False, False), ("valid", 99, True, False)])
def test_score_rule(status, score, role, hit):
    email = "info@a.com" if role else "dana@a.com"
    v = lambda e: {"verification_status": status, "score": score}  # noqa: E731
    out = ep.score_rows([{"id": "a", "email": email, "credits": 1}], v)
    assert out["hits"] == int(hit) and out["role"] == int(role) and out["verified_calls"] == (0 if role else 1)


def test_verdict_thresholds():
    assert [ep.verdict(n) for n in (4, 20, 3, 2, 1, 0)] == ["buy a month"] * 2 + ["supplement only"] * 2 + ["drop"] * 2

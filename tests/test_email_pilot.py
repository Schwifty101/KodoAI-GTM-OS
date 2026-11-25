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


def test_exception_after_first_post_records_error_and_stops(tmp_path):
    calls = []

    def http(method, url, headers, body):
        calls.append(url)
        if url.endswith("/email-search"):
            return 200, {"item": {"_id": "s1"}}
        raise TimeoutError("poll")

    out = tmp_path / "o.json"
    res = ep.run("icypeas", [S1, S2], Settings(icypeas_api_key="K"), out, http=http, log=lambda *a, **k: None, sleep=lambda s: None)
    assert len(calls) == 2 and res[0]["status"] == "error_exc" and res[0]["credits"] is None and res[0]["search_id"] == "s1"
    n = len(calls)
    ep.run("icypeas", [S1], Settings(icypeas_api_key="K"), out, http=http, log=lambda *a, **k: None, sleep=lambda s: None)
    assert len(calls) == n  # recorded lead is skipped


def test_result_is_saved_before_cost_is_logged(tmp_path):
    out = tmp_path / "o.json"

    def log(*a, **k):
        assert json.loads(out.read_text())[0]["id"] == "a"
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        ep.run("anymail", [S1], Settings(anymail_api_key="K"), out, http=lambda *a: (200, {"email": None, "email_status": "not_found"}), log=log)


def test_timeout_row_keeps_search_id_and_is_reread_once_without_new_search(tmp_path):
    out = tmp_path / "o.json"
    stuck = lambda m, u, h, b: (200, {"item": {"_id": "s1"}}) if u.endswith("/email-search") else (200, {"items": [{"status": "IN_PROGRESS"}]})  # noqa: E731
    res = ep.run("icypeas", [S1], Settings(icypeas_api_key="K"), out, http=stuck, log=lambda *a, **k: None, sleep=lambda s: None)
    assert res[0]["status"] == "TIMEOUT" and res[0]["search_id"] == "s1"
    calls = []

    def found(m, u, h, b):
        calls.append(u)
        return 200, {"items": [{"status": "FOUND", "results": {"emails": [{"email": "d@a.com", "certainty": "sure"}]}}]}

    res = ep.run("icypeas", [S1], Settings(icypeas_api_key="K"), out, http=found, log=lambda *a, **k: None, sleep=lambda s: None)
    assert calls == [f"{ep.ICY}/bulk-single-searchs/read"] and res[0]["email"] == "d@a.com" and res[0]["credits"] == 1
    ep.run("icypeas", [S1], Settings(icypeas_api_key="K"), out, http=found, log=lambda *a, **k: None, sleep=lambda s: None)
    assert len(calls) == 1


def test_still_stuck_timeout_is_not_reread_twice(tmp_path):
    out = tmp_path / "o.json"
    calls = []

    def stuck(m, u, h, b):
        calls.append(u)
        return (200, {"item": {"_id": "s1"}}) if u.endswith("/email-search") else (200, {"items": [{"status": "IN_PROGRESS"}]})

    for _ in range(3):
        ep.run("icypeas", [S1], Settings(icypeas_api_key="K"), out, http=stuck, log=lambda *a, **k: None, sleep=lambda s: None)
    assert calls.count(f"{ep.ICY}/email-search") == 1 and calls.count(f"{ep.ICY}/bulk-single-searchs/read") == 6 + 1


def test_verify_cache_reuses_verdicts_across_runs(tmp_path):
    f, calls = tmp_path / "v.json", []

    def verify(e):
        calls.append(e)
        return {"verification_status": "valid", "score": 90}

    ep.cached_verify(verify, f)("Dana@A.com")
    assert ep.cached_verify(verify, f)("dana@a.com")["score"] == 90 and calls == ["Dana@A.com"]


def test_budget_exceeded_returns_partial_scores():
    from gtm.budget import BudgetExceeded

    def verify(e):
        if e.startswith("b"):
            raise BudgetExceeded("cap")
        return {"verification_status": "valid", "score": 90}

    rows = [{"id": "1", "email": "a@x.com"}, {"id": "2", "email": "b@x.com"}, {"id": "3", "email": "c@x.com"}]
    out = ep.score_rows(rows, verify)
    assert out["hits"] == 1 and out["budget_stopped"] is True


def test_report_uses_lookups_not_20():
    s = ep.score_rows([{"id": "1", "email": "a@x.com"}, {"id": "2", "email": None}], lambda e: {"verification_status": "valid", "score": 90})
    assert "1/2" in ep.fmt("anymail", s) and "/20" not in ep.fmt("anymail", s)
    assert [ep.verdict(1, n) for n in (5, 10, 20)] == ["buy a month", "supplement only", "drop"]


def test_verdict_thresholds():
    assert [ep.verdict(n) for n in (4, 20, 3, 2, 1, 0)] == ["buy a month"] * 2 + ["supplement only"] * 2 + ["drop"] * 2

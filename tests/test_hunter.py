import pytest

from gtm.hunter import HunterPool, OutOfCredits

SPENT = (429, {"errors": [{"id": "too_many_requests", "code": 429, "details": "You've reached the limit for the number of searches per billing period included in your plan."}]})
FAST = (429, {"errors": [{"id": "too_many_requests", "code": 429, "details": "Too many requests per second."}]})
BAD_KEY = (401, {"errors": [{"id": "authentication_failed", "code": 401}]})
EMAIL = {"value": "dana@glowspa.com", "first_name": "Dana", "last_name": "Whitfield", "position": "Owner", "type": "personal", "confidence": 94, "verification": {"status": "valid"}}


def pool(keys, script):
    calls, logs = [], []

    def http(path, params, key):
        calls.append((path, key))
        return script.pop(0)

    return HunterPool(keys, http=http, log=lambda units, note: logs.append((units, note)), sleep=lambda s: None), calls, logs


def test_domain_search_maps_candidates_and_charges_one_credit():
    p, calls, logs = pool(["k1"], [(200, {"data": {"emails": [EMAIL]}})])
    assert p.domain_search("glowspa.com") == [
        {"email": "dana@glowspa.com", "first_name": "Dana", "last_name": "Whitfield", "position": "Owner",
         "verification_status": "valid", "score": 94, "source": "hunter"}
    ]
    assert [u for u, _ in logs] == [1]


def test_empty_domain_search_costs_nothing():
    p, _, logs = pool(["k1"], [(200, {"data": {"emails": []}})])
    assert p.domain_search("x.com") == [] and logs == []


def test_exhausted_key_rotates_to_next_and_is_remembered():
    p, calls, _ = pool(["k1", "k2"], [SPENT, (200, {"data": {"emails": []}}), (200, {"data": {"emails": []}})])
    p.domain_search("a.com")
    p.domain_search("b.com")
    assert [k for _, k in calls] == ["k1", "k2", "k2"]


def test_all_keys_exhausted_raises_out_of_credits():
    p, _, _ = pool(["k1", "k2"], [SPENT, SPENT])
    with pytest.raises(OutOfCredits):
        p.domain_search("a.com")


def test_invalid_key_is_skipped():
    p, calls, _ = pool(["bad", "k2"], [BAD_KEY, (200, {"data": {"emails": []}})])
    p.domain_search("a.com")
    assert [k for _, k in calls] == ["bad", "k2"]


def test_plain_rate_limit_retries_same_key():
    p, calls, _ = pool(["k1"], [FAST, (200, {"data": {"emails": []}})])
    p.domain_search("a.com")
    assert [k for _, k in calls] == ["k1", "k1"]


def test_email_finder_returns_candidate_when_found_and_charges_one_credit():
    data = {"data": {"email": "dana@glowspa.com", "first_name": "Dana", "last_name": "Whitfield", "position": None, "score": 91, "verification": {"status": "valid"}}}
    p, _, logs = pool(["k1"], [(200, data)])
    c = p.email_finder("glowspa.com", "Dana", "Whitfield")
    assert c["email"] == "dana@glowspa.com" and c["verification_status"] == "valid" and c["score"] == 91 and c["source"] == "hunter"
    assert [u for u, _ in logs] == [1]


def test_email_finder_returns_none_and_is_free_when_not_found():
    p, _, logs = pool(["k1"], [(200, {"data": {"email": None}})])
    assert p.email_finder("glowspa.com", "Dana", "Whitfield") is None and logs == []

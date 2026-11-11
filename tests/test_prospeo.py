from gtm.prospeo import ProspeoClient, prospeo_finder

LEAD = {"domain": "glow.com", "name": "Glow", "known": [{"first_name": "Dana", "last_name": "Whitfield", "position": "Owner", "email": None, "source": "search"}]}
HIT = (200, {"error": False, "person": {"first_name": "Dana", "last_name": "Whitfield", "email": {"status": "VERIFIED", "email": "dana@glow.com"}}})
MISS = (400, {"error": True, "error_code": "NO_MATCH"})


def client(*responses, **kw):
    script, logs, calls = list(responses), [], []

    def http(body, key):
        calls.append(body)
        return script.pop(0)

    return ProspeoClient("k", http=http, sleep=lambda s: None, log=logs.append, **kw), logs, calls


def test_verified_match_becomes_a_valid_score_100_candidate_and_costs_one_credit():
    c, logs, calls = client(HIT)
    out = prospeo_finder(c)(LEAD)
    assert out == [{"email": "dana@glow.com", "first_name": "Dana", "last_name": "Whitfield", "position": "Owner",
                    "verification_status": "valid", "score": 100, "source": "prospeo"}]
    assert logs == ["enrich-person:glow.com"] and calls[0]["only_verified_email"] is True


def test_no_match_is_free():
    c, logs, _ = client(MISS)
    assert prospeo_finder(c)(LEAD) == [] and logs == []


def test_unverified_status_is_ignored():
    c, logs, _ = client((200, {"error": False, "person": {"first_name": "Dana", "last_name": "Whitfield", "email": {"status": "UNVERIFIED", "email": "d@glow.com"}}}))
    assert prospeo_finder(c)(LEAD) == [] and logs == []


def test_a_different_person_is_rejected():
    c, _, _ = client((200, {"error": False, "person": {"first_name": "Sam", "last_name": "Ortiz", "email": {"status": "VERIFIED", "email": "sam@glow.com"}}}))
    assert prospeo_finder(c)(LEAD) == []


def test_rate_limit_is_retried():
    c, _, calls = client((429, {}), HIT)
    assert prospeo_finder(c)(LEAD) and len(calls) == 2


def test_out_of_credits_stops_all_further_calls():
    c, _, calls = client((402, {"error": True, "error_code": "INSUFFICIENT_CREDITS"}))
    f = prospeo_finder(c)
    assert f(LEAD) == [] and f(LEAD) == [] and len(calls) == 1


def test_no_known_owner_or_non_decision_maker_means_no_call():
    c, _, calls = client()
    f = prospeo_finder(c)
    assert f({**LEAD, "known": []}) == [] and f({**LEAD, "known": [{**LEAD["known"][0], "position": "Practice Manager"}]}) == [] and calls == []

import pytest

from gtm.llm import Throttle, complete_json


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_throttle_waits_for_the_token_window_to_free():
    c = Clock()
    th = Throttle(limit=7000, window=60, clock=c.now, sleep=c.sleep)
    th.wait(6000)
    th.wait(2000)  # 8000 inside one minute: must wait until the first 6000 ages out
    assert c.slept and sum(c.slept) >= 60


def test_throttle_does_not_wait_under_the_limit():
    c = Clock()
    th = Throttle(limit=7000, window=60, clock=c.now, sleep=c.sleep)
    th.wait(3000)
    th.wait(3000)
    assert c.slept == []


def test_primary_answer_is_used_when_valid():
    out = complete_json("sys", "prompt", primary=lambda s, p: '{"a": 1}', fallback=lambda s, p: pytest.fail("fallback not needed"))
    assert out == {"a": 1}


def test_falls_back_when_primary_fails():
    def boom(s, p):
        raise RuntimeError("429")

    assert complete_json("sys", "prompt", primary=boom, fallback=lambda s, p: '{"b": 2}') == {"b": 2}


def test_falls_back_when_primary_returns_invalid_json():
    assert complete_json("sys", "prompt", primary=lambda s, p: "not json", fallback=lambda s, p: '{"c": 3}') == {"c": 3}


def test_raises_when_both_fail():
    def boom(s, p):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        complete_json("sys", "prompt", primary=boom, fallback=boom)


def test_log_gemini_usage_prices_input_and_output_separately(monkeypatch):
    import gtm.llm as llm
    rows = []
    monkeypatch.setattr(llm, "log_cost", lambda *a, **k: rows.append((a, k)))
    monkeypatch.setattr(llm, "setting", lambda key, db=None: {"gemini_input_usd_per_m": 1.5, "gemini_output_usd_per_m": 9.0}[key])
    llm.log_gemini_usage({"promptTokenCount": 1_000_000, "candidatesTokenCount": 1_000_000, "totalTokenCount": 2_000_000})
    assert rows == [(("gemini", 2_000_000, 10.5), {"note": "tokens"})]


def test_thinking_tokens_count_as_output(monkeypatch):
    import gtm.llm as llm
    rows = []
    monkeypatch.setattr(llm, "log_cost", lambda *a, **k: rows.append(a))
    monkeypatch.setattr(llm, "setting", lambda key, db=None: {"gemini_input_usd_per_m": 1.5, "gemini_output_usd_per_m": 9.0}[key])
    llm.log_gemini_usage({"promptTokenCount": 0, "candidatesTokenCount": 500_000, "thoughtsTokenCount": 500_000, "totalTokenCount": 1_000_000})
    assert rows[0][2] == 9.0


def test_vertex_not_called_when_gemini_not_allowed(monkeypatch):
    import gtm.budget as budget
    import gtm.llm as llm
    monkeypatch.setattr(budget, "gemini_allowed", lambda *a, **k: False)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: pytest.fail("Vertex must not be called"))
    assert complete_json("sys", "prompt", fallback=lambda s, p: '{"g": 1}') == {"g": 1}


def test_reply_classifier_uses_flash_lite_and_prices_its_tokens(monkeypatch):
    import gtm.llm as llm
    from gtm.replies import classify_reply

    requests, rows = [], []
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"kind":"other"}'}]}}],
                    "usageMetadata": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 500_000,
                                      "thoughtsTokenCount": 500_000, "totalTokenCount": 2_000_000}}
    monkeypatch.setattr(llm.budget, "require", lambda *a: None)
    monkeypatch.setattr(llm, "get_settings", lambda: type("Settings", (), {"vertex_api_key": "test"})())
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kwargs: (requests.append(url), Response())[1])
    monkeypatch.setattr(llm, "setting", lambda key: {"gemini_lite_input_usd_per_m": .25, "gemini_lite_output_usd_per_m": 1.5}[key])
    monkeypatch.setattr(llm, "log_cost", lambda *a, **k: rows.append((a, k)))
    assert classify_reply({"body": "Can we revisit this next month?"}, llm.complete_reply_json) == "other"
    assert "/gemini-3.1-flash-lite:generateContent" in requests[0]
    assert rows == [(('gemini', 2_000_000, 1.75), {'note': 'gemini-3.1-flash-lite'})]


@pytest.mark.parametrize("model,prefix,note", [("gemini-3.1-flash-lite", "lite", "gemini-3.1-flash-lite"), ("gemini-3.5-flash", "norm", "tokens"), ("other-model", "norm", "tokens")])
def test_log_gemini_usage_prices_lite_only_for_reply_model(monkeypatch, model, prefix, note):
    import gtm.llm as llm
    rows = []
    monkeypatch.setattr(llm, "log_cost", lambda *a, **k: rows.append((a, k)))
    prices = {"gemini_input_usd_per_m": 1.0, "gemini_output_usd_per_m": 2.0, "gemini_lite_input_usd_per_m": 10.0, "gemini_lite_output_usd_per_m": 20.0}
    monkeypatch.setattr(llm, "setting", lambda key, db=None: prices[key])
    llm.log_gemini_usage({"promptTokenCount": 1_000_000, "candidatesTokenCount": 1_000_000, "totalTokenCount": 2_000_000}, model)
    assert rows == [(("gemini", 2_000_000, 30.0 if prefix == "lite" else 3.0), {"note": note})]


def test_lite_call_is_budget_gated_and_falls_back_to_groq(monkeypatch):
    import gtm.llm as llm
    from gtm.budget import BudgetExceeded
    gated = []

    def deny(*a):
        gated.append(a)
        raise BudgetExceeded("no")
    monkeypatch.setattr(llm.budget, "require", deny)
    urls = []

    class Groq:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": 1}'}}]}
    monkeypatch.setattr(llm.httpx, "post", lambda url, **k: (urls.append(url), Groq())[1])
    monkeypatch.setattr(llm, "get_settings", lambda: type("S", (), {"groq_api_key": "t"})())
    monkeypatch.setattr(llm, "log_cost", lambda *a, **k: None)
    assert llm.complete_reply_json("sys", "prompt") == {"ok": 1}
    assert gated == [("gemini", 0)] and len(urls) == 1 and "groq.com" in urls[0]

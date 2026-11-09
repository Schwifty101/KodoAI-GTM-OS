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


def test_groq_answer_is_used_when_valid():
    out = complete_json("sys", "prompt", groq=lambda s, p: '{"a": 1}', gemini=lambda s, p: pytest.fail("fallback not needed"))
    assert out == {"a": 1}


def test_falls_back_to_gemini_when_groq_fails():
    def boom(s, p):
        raise RuntimeError("429")

    assert complete_json("sys", "prompt", groq=boom, gemini=lambda s, p: '{"b": 2}') == {"b": 2}


def test_falls_back_when_groq_returns_invalid_json():
    assert complete_json("sys", "prompt", groq=lambda s, p: "not json", gemini=lambda s, p: '{"c": 3}') == {"c": 3}


def test_raises_when_both_fail():
    def boom(s, p):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        complete_json("sys", "prompt", groq=boom, gemini=boom)

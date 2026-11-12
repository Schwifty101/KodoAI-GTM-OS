"""LLM calls for judging and phrasing. Gemini on Vertex AI primary (paid from the Google Cloud credit, no 8K tokens/min wall),
Groq fallback (free, 8K tokens/min). The free AI Studio Gemini tier was flaky and its prepaid credit is spent. Measured in docs/spikes/llm.md."""

from __future__ import annotations

import json
import time
from collections import deque

import httpx

from gtm import budget
from gtm.config import get_settings
from gtm.costs import log_cost
from gtm.settings_store import setting

GROQ_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-3.5-flash"


class Throttle:
    """Keeps tokens-per-window under a limit by sleeping until old usage ages out."""

    def __init__(self, limit: int = 7000, window: float = 60, clock=time.monotonic, sleep=time.sleep):
        self.limit, self.window, self.clock, self.sleep, self.events = limit, window, clock, sleep, deque()

    def wait(self, tokens: int) -> None:
        while True:
            now = self.clock()
            while self.events and now - self.events[0][0] >= self.window:
                self.events.popleft()
            if not self.events or sum(t for _, t in self.events) + tokens <= self.limit:
                break
            self.sleep(self.window - (now - self.events[0][0]))
        self.events.append((self.clock(), tokens))


_THROTTLE = Throttle()


def _groq(system: str, prompt: str) -> str:
    _THROTTLE.wait((len(system) + len(prompt)) // 4 + 600)
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {get_settings().groq_api_key}", "User-Agent": "curl/8"},
        json={"model": GROQ_MODEL, "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
        timeout=90,
    )
    r.raise_for_status()
    j = r.json()
    log_cost("groq", (j.get("usage") or {}).get("total_tokens", 0), None, note="tokens")
    return j["choices"][0]["message"]["content"]


def log_gemini_usage(meta: dict) -> None:
    """Cost row for one Gemini reply: input and output (thinking included) priced separately."""
    out = (meta.get("candidatesTokenCount") or 0) + (meta.get("thoughtsTokenCount") or 0)
    usd = ((meta.get("promptTokenCount") or 0) * setting("gemini_input_usd_per_m") + out * setting("gemini_output_usd_per_m")) / 1_000_000
    log_cost("gemini", meta.get("totalTokenCount") or 0, usd, note="tokens")


def _vertex(system: str, prompt: str) -> str:
    """Gemini on Vertex AI (paid, billed to the Google Cloud credit). The Agent Platform key works on this endpoint without ADC."""
    budget.require("gemini", 0)
    for attempt in range(3):
        r = httpx.post(
            f"https://aiplatform.googleapis.com/v1/publishers/google/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": get_settings().vertex_api_key},
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"responseMimeType": "application/json"}},
            timeout=90,
        )
        if r.status_code in (429, 503) and attempt < 2:
            time.sleep(2 ** (attempt + 1))
            continue
        r.raise_for_status()
        j = r.json()
        log_gemini_usage(j.get("usageMetadata") or {})
        return j["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("vertex unavailable")


def complete_json(system: str, prompt: str, *, primary=_vertex, fallback=_groq) -> dict:
    try:
        return json.loads(primary(system, prompt))
    except Exception:
        return json.loads(fallback(system, prompt))

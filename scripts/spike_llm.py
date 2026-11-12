"""Spike C: Groq and Gemini free-tier behaviour on a small JSON judging task. Aggregates and rate-limit headers only.
Gemini calls retry on 429/503 with backoff; every attempt's status is recorded.
Usage: PYTHONPATH=. uv run python scripts/spike_llm.py [GEMINI_MODEL]
"""
import json
import statistics
import sys
import time

import httpx

from gtm.config import get_settings

s = get_settings()
GEM = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.5-flash"
SYSTEM = "You judge med spa leads. Reply with JSON only: {\"vector\": \"conversion_recovery\"|\"capacity\"|\"rebooking_retention\"|null, \"signal_led\": bool, \"reason\": str}."
SNIPS = [
    "Reviews mention 'called three times, nobody picked up' and 'hard to book online'. 4.1 stars, 210 reviews.",
    "Website announces a new second location opening next month and hiring two injectors.",
    "Brand new spa, 6 reviews, website is a single page with a phone number.",
    "Reviews praise staff; several say they come back every 6 weeks for Botox. Membership page exists.",
]
lat = {"groq": [], GEM: []}
attempts = {"groq": [], GEM: []}
ok_json = {"groq": 0, GEM: 0}
hdrs = {}


def groq(snip):
    return httpx.post("https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {s.groq_api_key}", "User-Agent": "curl/8"},
        json={"model": "openai/gpt-oss-120b", "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": snip}]}, timeout=90)


def gemini(payload, tries=4):
    codes = []
    for n in range(tries):
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEM}:generateContent",
                       headers={"x-goog-api-key": s.gemini_api_key}, json=payload, timeout=90)
        codes.append(r.status_code)
        if r.status_code not in (429, 503):
            break
        time.sleep(2 ** (n + 1))
    return r, codes


for i in range(20):
    snip = SNIPS[i % 4]
    t = time.time()
    r = groq(snip)
    lat["groq"].append(time.time() - t)
    attempts["groq"].append([r.status_code])
    if i == 0 or r.status_code == 429:
        hdrs["groq"] = {k: v for k, v in r.headers.items() if k.lower().startswith(("x-ratelimit", "retry-after"))}
    if r.status_code == 200:
        try:
            json.loads(r.json()["choices"][0]["message"]["content"])
            ok_json["groq"] += 1
        except Exception:
            pass
    t = time.time()
    r, codes = gemini({"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"parts": [{"text": snip}]}],
                       "generationConfig": {"responseMimeType": "application/json"}})
    lat[GEM].append(time.time() - t)
    attempts[GEM].append(codes)
    if r.status_code == 200:
        try:
            json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            ok_json[GEM] += 1
        except Exception:
            pass
    elif i == 0:
        print("gemini first error:", r.text[:200])

for k in lat:
    flat = [c for a in attempts[k] for c in a]
    print(k, "| calls 20 | valid JSON:", ok_json[k], "| attempt status counts:", {c: flat.count(c) for c in sorted(set(flat))},
          "| median s:", round(statistics.median(lat[k]), 2), "| max s:", round(max(lat[k]), 2))
print("groq rate-limit headers:", json.dumps(hdrs.get("groq"), indent=1))

r, codes = gemini({"contents": [{"parts": [{"text": "What is the website of Radiance Medical Spa in Houston TX? One line, with the source."}]}],
                   "tools": [{"google_search": {}}]})
print("gemini grounding attempts:", codes)
if r.status_code == 200:
    c = r.json()["candidates"][0]
    print("  answer:", c["content"]["parts"][0]["text"][:200].replace("\n", " "))
    print("  groundingMetadata:", "groundingMetadata" in c, "| chunks:", len(c.get("groundingMetadata", {}).get("groundingChunks", [])))
else:
    print("  error:", r.text[:400])

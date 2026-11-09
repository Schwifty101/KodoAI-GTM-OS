# Spike C: Groq and Gemini free tiers (2026-11-10)

Script: `scripts/spike_llm.py`. Task: 20 small JSON-mode judging calls per provider (vector + signal_led + reason on a 1-2 sentence med spa snippet), run back to back.

## Measured

| | Groq `openai/gpt-oss-120b` | Gemini `gemini-3.5-flash` |
|---|---|---|
| Valid JSON out of 20 | **20** | 10 |
| Status counts across all attempts | 200 x 20 | 200 x 10, **429 x 34**, **503 x 13** (retried with backoff) |
| Median / max latency per call | 0.95 s / 1.37 s | 32 s / 69 s (includes retries) |
| Grounded search (`google_search` tool) | not offered | **429 on 4 of 4 attempts** (`RESOURCE_EXHAUSTED`, "exceeded your current quota") |

- **Groq limits (response headers of this key):** 1,000 requests and 8,000 tokens per window (`x-ratelimit-limit-requests: 1000`, `x-ratelimit-limit-tokens: 8000`). Groq's rate-limit page (fetched 2026-11-10) lists for this model **30 RPM, 1K RPD, 8K TPM, 200K TPD**, but its text did not say whether those are free-tier numbers; confirm in the Groq console limits page. The 8K tokens per minute is the binding limit: a judging call with real evidence (website text, reviews) of 3-4K tokens allows only 2-3 calls a minute, about 50-60 leads a day at 200K tokens a day.
- **Gemini free tier is not dependable here.** The old `gemini-2.5-flash` and `flash-lite` models return 404 "no longer available to new users" for this key. `gemini-3.5-flash` answers, but half of 20 calls failed after retries, with a mix of 429 (quota) and 503 ("high demand"). I fired 20 calls back to back, so some 429s may be per-minute rate limiting rather than a hard daily quota; I did not separate the two. Google's docs (aistudio.google.com/docs/rate-limits) give no free-tier numbers and say grounding on Gemini 3 and newer has a 1,500 requests/day default limit, which this key could not reach.

## Decision (Task 11's `gtm/llm.py`)

- **Primary: Groq `openai/gpt-oss-120b`.** Fast, reliable, JSON mode works.
- **Fallback: Gemini `gemini-3.5-flash`** with retry and backoff on 429/503, accepting slow answers; never the only path.
- **Pacing:** the code must throttle to the token-per-minute limit (about 8K), not just the request limit, and cap evidence text per call.
- **Grounded search is not available to rely on.** Signal finding uses the lead's own website and Apify review data (the spec's v1 mandatory sources). `qwen/qwen3.8-27b` and `gpt-oss-20b` are listed on Groq but were not tested.

# Spike D: other enrichment keys in `.env` (2026-11-10)

Method: read each provider's docs for a free account/credits endpoint, call it only if the docs confirm it is read-only. No keys printed.

| Provider | Endpoint (from docs) | Result |
|---|---|---|
| Prospeo | `GET https://api.prospeo.io/account-information`, header `X-KEY`, docs say free | **FREE plan, 88 credits remaining (12 used), renews 2026-11-24** |
| Tomba | `GET https://api.tomba.io/v1/me`, headers `X-Tomba-Key` + `X-Tomba-Secret` (docs do not state cost) | **Free plan: 25 domain searches (1 used), 50 verifications (0 used), window ends 2026-11-28** |
| Apollo | `POST https://api.apollo.io/api/v1/usage_stats/api_usage_stats`, header `x-api-key`, docs say 0 credits | **403: this key lacks the scope for that endpoint.** Plan and credits unknown; check in the Apollo dashboard |
| `SERP_API_KEY` | `SERP_PROVIDER=serper`, so this is a Serper (serper.dev) key; SerpAPI's account endpoint correctly returned 401 | Serper's free tier is "2,500 free queries" (serper.dev homepage); remaining balance unverified (no account endpoint found in the docs read) |
| Lusha | `GET https://api.lusha.com/v3/account/usage`, header `api_key`; docs do not say whether it consumes credits | **Not called** (cost unstated). Check in dashboard |
| Snov.io | token via `POST https://api.snov.io/v1/oauth/access_token`; the balance endpoint path was not in the part of the docs I could read | **Not checked** |
| RocketReach | docs returned HTTP 403 to my fetch | **Not checked** |
| ContactOut | auth header `token`; the usage-stats section was cut off in what I could read | **Not checked** |

**Update 2026-11-11:** Prospeo and the other finders were later tested on saved names; results in `owner_routes.md`. Prospeo is now a default finder. The recommendation below is superseded.

## Recommendation

There is no evidence yet to buy a paid fallback. Two keys have free credits worth testing: **Prospeo (88) and Tomba (25 searches)**. Task 10 should run both on the same 45 Houston domains used in the Hunter spike, because Hunter's weak point is owner names and titles (55% of emails had no title), and measure which one adds verified decision-makers. Buy a paid plan for a fallback only if one of them clearly lifts yield, and only after the Task 7 funnel is written. The four unchecked providers (Apollo scope, Lusha, Snov, RocketReach, ContactOut) need a look in their dashboards by Soban, or a docs page I can actually read, before they are considered.

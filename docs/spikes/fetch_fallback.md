# Spike: fetch fallback for blocked or gone sites (2026-11-13)

Question: when a plain fetch of a lead's site fails, can Serper scrape or Apify website-content-crawler get the page text.

## Measured

- 98 lead sites checked with plain fetches: 79 ok, 9 blocked, 10 gone.
- Serper scrape (`POST scrape.serper.dev {url}`) works: 2 credits on a simple page, 10 on Sisu Clinic's page. Serper credit price in USD: **unverified**.
- Apify `website-content-crawler` works: $0.0047 and $0.0077 per page.
- Both returned about 2.4k characters for sisuclinic.com.
- botoxrn.com returned an "Account Suspended" page (104 chars); the 200-char minimum rejects it.
- Total: $0.0124 Apify and 12 Serper credits.

## Decision

Fallback order stays Serper first, then Apify. Wired into the research finder (`12d9a96`).

## Not verified

Behaviour on a full batch; fallback hit rate on blocked sites beyond these samples.

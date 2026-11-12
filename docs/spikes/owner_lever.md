# Task 10: the owner-name lever, measured (2026-11-10)

Question from the Hunter spike: Hunter Domain Search alone gives a verified decision-maker on about 9% of domains because most results have no title. Can finding the owner's name another way, then asking Hunter's Email Finder (name + domain), do better? Sample: 45 Houston med spa domains (all with "Medical spa" among their Google categories). Counts only; no names or emails kept in the repo.

## Measured
| Finder | Owner name found | Verified decision-maker email | Credits |
|---|---|---|---|
| Hunter Domain Search (earlier spike, a similar 45) | n/a | 4 of 45 (9%) | 19 |
| **Site scrape** of the lead's own About/Team pages (free) | 5 of 45 (11%): CEO, founder, "our founder and medical director" | not run | 0 |
| **Search "owner of <domain>"** (Serper) + Groq reads the results + code guard | **24 of 45 (53%)** validated names | 4 of 45 (9%) after Hunter Email Finder | 7 (Hunter returned an email for 7 of the 24; 4 were `valid`, 3 `accept_all`) |

- **Finding the name works; turning it into a verified email is the bottleneck.** Hunter Email Finder returned no email for 17 of 24 known owners (71%), and 3 of the 7 it did return were accept-all, which cannot be verified.
- **The guard earns its keep.** Search for "owner of psmedspa.com" put a *different* business's founder on top ("Founder, Medical Spa Owners Network"). A naive parser would have emailed that person. The code accepts a name only if it appears verbatim in a result that also matches this business (distinctive name token, domain stem or full name) and the title is a decision-maker.
- **Evidence mix** for the 7 emails: 4 LinkedIn result pages, 3 the business's own pages.
- Hunter Email Finder: 1 credit only when it finds an email; free when it finds nothing (matches Hunter's pricing page).

## Not finished, and why
- **Prospeo and Tomba email finders were not tested** on these names. Both have name + domain finders (Prospeo `POST /enrich-person` with `company_website`, option `only_verified_email`, 1 credit per email found, no-match free; Tomba `GET /v1/email-finder`, cost unstated). I need the names again to test them, and
- **the Serper key ran out of credits** (400 "Not enough credits") after about 50 queries in total, so the names could not be recaptured. Serper's homepage says "2,500 free queries" but this key did not have that. Serper's price list was not readable (pricing page 404): check the dashboard before topping up.

## Decision for the code
`gtm enrich` tries finders cheapest first: `site` (free) then `search` then `hunter` (Domain Search). A spent Serper or Hunter key raises `OutOfCredits`, which stops the run and leaves leads `cleaned` instead of marking them `no_buyer`. Re-ordering waits for the Prospeo/Tomba comparison and a measured union of the three.

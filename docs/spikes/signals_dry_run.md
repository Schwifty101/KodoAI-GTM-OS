# Task 11 dry run: website-only signals on 6 Houston med spas (2026-11-10)

Evidence = the lead's own pages (home, book, contact, about, careers, jobs, news, blog, locations, memberships, specials), judged by Groq `openai/gpt-oss-120b` against `gtm/data/signal_prompt.md` (a condensed copy of MedSpa Touch-1 prompt sections 4-5). Nothing was saved.

| | Result |
|---|---|
| Had a dated, current signal on their own site | **0 of 6** |
| Model proposed a signal and a handoff but neither quote was on the pages (guard dropped both) | 1 (nakedmd.com) |
| Relevance-led with a handoff | 5 of 6, all `conversion_recovery` |
| Handoffs found | a "Book now" call to action, a contact form, phone-based booking |
| Booking platform seen in links | PatientNow on 2 of 6 |

**What this means.** Website-only evidence gives a handoff for most leads but almost never a dated signal, and the handoffs are generic. Expect nearly every lead to be relevance-led with the same vector, so personalisation is thin. The signals Soban listed as the real problem (hiring, new locations, ads, promotions) mostly live off the site: Instagram and Facebook posts, Google Business updates, job boards, news. Reaching them needs a working search (Serper is out of credits) and/or Apify social scrapers (not measured).

**Guard limit.** Code checks that each quote appears verbatim on a fetched page and that a signal has a real, recent date. It does not check that the model's one-line summary of a quote is faithful (e.g. "routed to staff for manual follow-up" is an inference from a contact form). The Review page shows quote and summary side by side.

**Open decision for Soban.** MedSpa/ defines no recency window for a "current" signal. `gtm signals` refuses to run until `SIGNAL_MAX_AGE_DAYS` is set. Proposal: 90 days.

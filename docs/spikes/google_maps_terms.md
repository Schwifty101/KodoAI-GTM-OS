# Spike: Google Maps Platform terms on storing Places data (2026-11-14, desk research, no keys, no paid calls)

Not legal advice. Quotes are verbatim from the fetched text (the fetch tool trims quotes to about 125 characters, so some are fragments). UNVERIFIED = I could not read the primary text in full.

## What I could and could not read
- READ in full: Places API policies page, Geocoding policies page, and the Service Specific Terms as archived 2024-05-22 (sections 3 Geocoding, 5 Places).
- NOT READ: the current Maps Platform Terms of Service (https://cloud.google.com/maps-platform/terms) and the current Service Specific Terms (https://cloud.google.com/maps-platform/terms/maps-service-terms). Every fetch returned only the title or a "truncated" stub, and offset reads returned nothing. Archive.org is blocked for the tool. So the old section 3.2.3 text ("No Scraping", "No Caching") is UNVERIFIED verbatim; the policies page now carries equivalent wording (below). One monitoring site says the old clause "is no longer published" (https://conductatlas.com/platform/google-maps/google-maps-platform-terms-of-service/no-scraping-or-content-extraction/), i.e. the terms were restructured; numbering UNVERIFIED.

## (1) Caching and storage
Places policies, https://developers.google.com/maps/documentation/places/web-service/policies :
- "Cache or store Google Maps Content only as expressly permitted under the Google Maps Platform Service Specific Terms."
- "Don't pre-fetch, index, store, or redistribute Google Maps Content outside the Services."
- "Don't create content based on Google Maps Content."
- Lat/lng: "values for up to 30 consecutive calendar days, after which you must delete the cached coordinates."
- Place IDs: "You can therefore store place ID values indefinitely." and "Store exempt identifiers such as the place ID to fetch fresh details when a user interacts with a place."
- Listed as prohibited: "or copy and save business names, addresses, or user reviews." (fragment; the full sentence's lead-in is UNVERIFIED).
- Derived use also prohibited: "use Places latitude and longitude values as input for point-in-polygon analysis".

Service Specific Terms (archived 2024-05-22, https://cloud.google.com/maps-platform/terms/maps-service-terms/index-20240522), section 5.4 Places API:
"Customer can temporarily cache latitude (lat) and longitude (lng) values from the Places API for up to 30 consecutive calendar days, after which Customer must delete the cached latitude and longitude values. Customer can cache Places API Place ID (place_id) values, in accordance with the Places API Policies."
So the owner's 30-day recollection is right, but it is for lat/lng only. The only things permitted to be kept are lat/lng (30 days) and place_id (no expiry). Name, address, website, phone, rating, review count, category, hours: no caching permission appears anywhere I read. In the Service Specific Terms the permissions are an allow-list ("only as expressly permitted").

## (2) No export, scraping, databases, lead lists
- "Don't export, extract, or scrape Google Maps Content for use outside the Services." (Places policies.)
- Prohibited list includes "bulk download map tiles, Street View images, geocodes, directions" (fragment).
- Exact words "lead generation", "business directory", "mailing list": the Places policies page has NO match for "lead", "directory" or "mailing" (checked this session). Only "contact": "contact Sales if your use case requires custom licensing." In the current Terms of Service itself: UNVERIFIED. Blogs claim the terms ban "lead lists, telemarketing lists, or substitute directories" (https://thunderbit.com/blog/is-scraping-google-maps-legal; Portuguese copy fetched via search), but no official text with those words was found; treat as paraphrase of the old 3.2.3 text, which (from my memory, not verified) read about "a copy of Google Maps Content ... lead-generation, telemarketing, or substitute for Google Maps". Do not rely on it. The caching, no-copy-and-save and no-export lines above already cover a leads table without any "lead" wording.

## (3) Display with a map or attribution
- Service Specific Terms 5.1 (archived): "Customer may use Google Maps Content from the Places API in Customer Applications without a corresponding Google Map." 5.2: attribution "in accordance with the Documentation" if used without a Google Map. 5.3: "Customer must not use Google Maps Content from the Places API in conjunction with a non-Google map."
- Policies: "You don't need to add extra attribution if the Content is shown on a Google Map where the attribution is already visible." Otherwise "Attribution should take the form of the Google Maps logo whenever possible"; "Don't remove included attribution regardless of where it is displayed."; "Always visually distinguish Google Maps Platform Content from other content".
- Net: a map is NOT required, attribution is. A sent email or an internal CRM row is not a display surface, so this rule is not our blocker; the storing rule is.

## (4) Places API (New) vs Geocoding
- Same rules. Places policies page covers "all applications developed with the Places API (New)" and Legacy together (fragment). Geocoding policies (https://developers.google.com/maps/documentation/geocoding/policies) carry the same quotes: place ID "indefinitely", lat/lng "up to 30 consecutive calendar days", "Don't pre-fetch, index, store, or redistribute". Archived Service Specific Terms 3.4 (Geocoding) is word-for-word 5.4 with "Geocoding API". Places (New) caching clause in the current terms: UNVERIFIED (current page unreadable); the policies page is current and says the same.
- One difference: Geocoding returns addresses and coordinates only (no website, rating, category), so little else to want to store anyway.

## (5) Our use, plainly
We store place_id, name, website, address, category, rating, review count, city, state, for months, from Apify.
- ALLOWED from the Google API: place_id forever; lat/lng 30 days. Nothing else, going by the policy text.
- NOT ALLOWED from the Google API: keeping name, address, website, rating, review count, category in `leads`; building a database of them; exporting for outreach. Our `leads` table is that.
- If we ever call the Google API: log place_id, fetch the rest at point of use, keep nothing else. Not a workable lead pipeline (spike maps_sources.md, option a).
- Cost-free reading of "we are fine": none exists. The 30-day limit is for coordinates, not a general 30-day window that we could just refresh monthly.

## Apify and Serper: what exposure do WE carry
- We have not accepted Google's Maps Platform terms for Apify/Serper data (we hold no Maps Platform contract for it; fact from our setup, not from a source). Google's API terms bind API customers. What binds a scraper's customer is mainly: (i) the vendor's terms, (ii) general law (contract/ToS claims against the scraper, copyright/DMCA theories). I have no primary Google statement about customers of scrapers; treat the legal exposure as UNVERIFIED and low-probability but real. Context: Google sued SerpApi on 2025-12-19 (N.D. Cal., 5:25-cv-10826) on DMCA anti-circumvention; both DMCA claims were dismissed on 2026-07-20 with a narrower Knowledge Panel claim allowed to be re-pleaded (https://searchengineland.com/google-loses-key-dmca-claims-against-serpapi-in-scraping-lawsuit-483185, https://ppc.land/google-loses-dmca-bid-to-treat-search-scraping-like-dvd-piracy/; status of the amendment UNVERIFIED). Google targeted the scraper, not its customers.
- Apify General Terms, https://docs.apify.com/legal/general-terms-and-conditions : 5.8 "You are solely responsible for the legality, accuracy, quality, appropriateness, and use of all Customer Data."; 5.4 third-party services "subject solely to the terms and conditions of the applicable third party"; 11.1 "You agree to indemnify, defend and hold us ... harmless" for claims from your use in breach of the Agreement. Acceptable Use Policy (https://docs.apify.com/legal/acceptable-use-policy): 1.2 "only for legal and legitimate purposes"; 2.1(2) bans "unsolicited mass messaging"; no clause on lead generation or on third-party site terms. Net: Apify puts the use of scraped data, including Google compliance, on us, and says nothing against lead generation as such.
- Serper Terms, https://serper.dev/terms : "Serper is not affiliated with or endorsed by Google in any way."; no Maps-data clause, no clause on complying with Google's terms, no resale clause (only "Mirror the materials on any other server as-is with no-value-added"); mutual indemnity ("Both parties agree to defend, indemnify, and hold harmless each other"); data license bars misrepresenting source and removing attribution notices. Net: Serper gives us no Google licence and no protection; its terms do not forbid our use.
- Neither vendor grants a Google licence. Using them does not make storage "permitted by Google"; it moves who does the scraping (agrees with maps_sources.md).

## Safe or not for a lead database (ranking)
1. Safe by licence: sources whose terms allow storing and reuse, e.g. our own site crawl, owner research from the business's own pages, paid B2B data vendors with a stated licence (Prospeo/Hunter results we already store), Google place_id only.
2. Grey, commercially common: Apify, Serper, DataForSEO, Outscraper for Maps fields. Vendor terms do not forbid it, vendors carry the scraping, Google has gone after scrapers not customers, but Google's own terms say no, so a cease-and-desist or data-deletion demand is the realistic downside (we would delete rows; low cost for a small outreach list).
3. Not safe: Google Places/Geocoding API as the store for name, website, rating etc. (explicit breach of the very terms we would have signed, with an account that can be suspended and the Google Cloud trial billing attached).

## Recommendation
- Do NOT move the lead store to the official Google API. It is the one path where we knowingly breach terms we click through.
- Keep Apify or move to Serper as in maps_sources.md; it is the same grey tier. Minimise: store only the fields we use, keep Google-derived ratings/review counts short-lived (they feed `select`, not email copy), never publish or resell the data, honour deletion requests, keep suppression by place_id.
- Optional hedge for no extra cost: for any Google API call (e.g. tile verification via Geocoding, already done), keep place_id and coordinates only, delete lat/lng after 30 days.
- To close the UNVERIFIED items: read https://cloud.google.com/maps-platform/terms section "Restrictions Against Misusing the Services" and the current Service Specific Terms in a browser; ask counsel if the list grows beyond a few thousand leads.

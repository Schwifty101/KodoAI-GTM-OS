"""Agentic owner finder: a Gemini loop with web_search + fetch_page tools finds the owner; code (never the model) validates the name."""

from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import urlparse

import httpx

from gtm.buyer import is_decision_maker
from gtm.config import get_settings
from gtm.costs import log_cost
from gtm.llm import GEMINI_MODEL
from gtm.owner_search import _about_business
from gtm.sitescrape import _clean_name

TOOLS = [{"functionDeclarations": [
    {"name": "web_search", "description": "Google search. Returns title/link/snippet.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "fetch_page", "description": "Fetch a URL, returns page text (first ~6000 chars).", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "answer", "description": "Final answer. Use nulls if owner/founder/CEO not found.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "title": {"type": "string"}, "evidence_url": {"type": "string"}, "quote": {"type": "string"}}}}]}]
SYSTEM = """You research who OWNS a US med spa. Find the named owner / founder / CEO / president / co-owner (or owner + medical director) of THIS specific business. Tools: web_search, fetch_page, answer. Budget: at most 6 tool-using turns, 8 searches, 10 fetches. Try varied tactics: '<business> <city> owner/founder/medical director'; the site's About/Team/Meet-the-doctor/Contact/footer/privacy-policy/terms pages (copyright/'owned by' lines); linkedin.com/in and linkedin.com/company results; Facebook/Instagram/Yelp/BBB/Google profiles; booking-platform staff pages; press/local magazine features; Texas Medical Board / NPI listings. Only report a person whose name you saw verbatim in a fetched page or search snippet, tied to THIS business (not a same-named one elsewhere). evidence_url must be the exact url where you saw it; quote the exact sentence. Call answer when done, with nulls if not found. Several tool calls per turn are allowed."""
MAX_TURNS, MAX_FETCHES = 6, 10
_CREDS = re.compile(r"(?:,?\s+(?:MD|M\.D\.|DO|NP|NP-C|FNP-C|RN|MSN|BSN|APRN|DNP|PA-C|PhD|MBA))+\s*$", re.I)
_NEAR = re.compile(r"owner|founder|ceo|chief executive|president|founded\b[^.]{0,30}\bby\b", re.I)
_FOUNDER = re.compile(r"\bfounder\b|founded\b[^.]{0,30}\bby\b", re.I)
# ponytail: URL-shape guess at "page lists several businesses"; parse the page for repeated business names if it misses
_DIRECTORY = re.compile(r"/(?:search|directory|list|best|top)[-/\w]*|[?&](?:find_desc|q)=|\b(?:yellowpages|mapquest|healthgrades|zocdoc|groupon|manta|chamberofcommerce)\.", re.I)


def gemini_step(contents: list, last: bool = False) -> list | None:
    """One function-calling turn on Vertex Gemini (same endpoint, key and cost log as gtm.llm._vertex). Returns the reply parts."""
    cfg = {"mode": "ANY", **({"allowedFunctionNames": ["answer"]} if last else {})}
    for attempt in range(3):
        try:
            r = httpx.post(f"https://aiplatform.googleapis.com/v1/publishers/google/models/{GEMINI_MODEL}:generateContent",
                           headers={"x-goog-api-key": get_settings().vertex_api_key},
                           json={"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "tools": TOOLS,
                                 "toolConfig": {"functionCallingConfig": cfg}, "generationConfig": {"temperature": 0.2}}, timeout=90)
        except httpx.HTTPError:
            continue
        if r.status_code == 200:
            j = r.json()
            log_cost("gemini", (j.get("usageMetadata") or {}).get("totalTokenCount", 0), None, note="tokens")
            return ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or None
        if r.status_code in (429, 503):
            time.sleep(2 ** (attempt + 1))
    return None


def _text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", unescape(re.sub(r"(?s)<[^>]+>", " ", html))).strip()


def validate(a: dict, corpus: dict, lead: dict) -> dict | None:
    """Code guard. corpus maps url -> text actually seen (fetched page or search result)."""
    name, title, url = a.get("name"), a.get("title") or "", (a.get("evidence_url") or "").rstrip("/")
    key = next((k for k in corpus if k.rstrip("/") == url), None)
    n = name and _clean_name(_CREDS.sub("", name.split(",")[0].strip().rstrip(".,")))
    if not (key and n) or _DIRECTORY.search(key):
        return None
    text = corpus[key]
    first, last = (re.escape(t.lower()) for t in n)
    hits = list(re.finditer(rf"\b{first}\b(?:\s+[a-z][a-z.'’-]*){{0,2}}?\s+{last}\b", text.lower()))
    if not hits or not _about_business(text[:3000] + " " + key if len(text) < 7000 else text + " " + key, lead):
        return None
    near = [text[max(0, h.start() - 250): h.end() + 250] for h in hits]
    if not any(_NEAR.search(w) for w in near):
        return None
    if not is_decision_maker(title):
        if not any(_FOUNDER.search(w) for w in near):
            return None
        title = "Founder"
    return {"first_name": n[0], "last_name": n[1], "position": title, "url": key}


def research_owner_finder(pool, search, fetch, llm, max_searches=8, budget=150):
    """Finder for run_enrich: LLM tool loop, code-validated name, then Hunter Email Finder. `budget` caps searches for the whole run."""
    left = [budget]

    def find(lead: dict) -> list[dict]:
        if any(is_decision_maker(o.get("position")) for o in lead.get("known") or []) or left[0] <= 0:
            return []
        corpus, ns, nf, ans = {}, 0, 0, None
        contents = [{"role": "user", "parts": [{"text": f"Business: {lead['name']}\nWebsite: {lead.get('website') or lead['domain']}\nAddress: {lead.get('address')}\nCity: {lead.get('city')}, {lead.get('state')}"}]}]
        for turn in range(1, MAX_TURNS + 1):
            parts = llm(contents, turn == MAX_TURNS)
            calls = [p["functionCall"] for p in parts or [] if "functionCall" in p]
            if not calls:
                break
            contents.append({"role": "model", "parts": parts})
            resp = []
            for c in calls:
                a, n = c.get("args") or {}, c["name"]
                if n == "answer":
                    ans = a
                    break
                if n == "web_search" and (ns >= max_searches or left[0] <= 0):
                    out = {"error": "search budget exhausted"}
                elif n == "web_search":
                    ns, left[0] = ns + 1, left[0] - 1
                    try:
                        res = search(a.get("query", ""), 6)
                    except (httpx.HTTPError, ValueError) as e:  # OutOfCredits is not caught: it stops the run like the other finders
                        res, out = [], {"error": str(e)[:80]}
                    else:
                        out = {"results": res}
                    for r in res:
                        corpus[r["link"]] = corpus.get(r["link"], "") + f" {r['title']} {r['snippet']}"
                elif n == "fetch_page" and nf < MAX_FETCHES:
                    nf += 1
                    html = fetch(a.get("url", ""))
                    if html is None:
                        out = {"error": "fetch failed"}
                    else:
                        t = _text(html)[:6000]
                        corpus[a.get("url", "")] = corpus.get(a.get("url", ""), "") + " " + t
                        out = {"text": t}
                else:
                    out = {"error": "unavailable"}
                resp.append({"functionResponse": {"name": n, "response": out}})
            if ans is not None:
                break
            contents.append({"role": "user", "parts": resp})
        owner = validate(ans or {}, corpus, lead)
        if not owner:
            return []
        c = pool.email_finder(lead["domain"], owner["first_name"], owner["last_name"])
        if not c:  # keep the validated name: later finders can still use it
            return [{"email": None, "first_name": owner["first_name"], "last_name": owner["last_name"], "position": owner["position"],
                     "source": "research", "evidence_url": owner["url"]}]
        return [{**c, "position": owner["position"], "source": "research+hunter", "evidence_url": owner["url"]}]

    return find

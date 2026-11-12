"""Find an owner's name on the lead's own About/Team pages (free). Hunter then finds the email."""

from __future__ import annotations

import json
import re
from html import unescape

import httpx

from gtm.buyer import is_decision_maker

PATHS = ["/", "/about", "/about-us", "/our-team", "/team", "/meet-the-team", "/meet-our-team", "/our-story", "/contact"]
STOP = {"our", "the", "meet", "med", "spa", "founder", "owner", "contact", "about", "team", "medical", "director", "chief", "executive",
        "officer", "co", "president", "welcome", "learn", "more", "book", "now", "ceo", "and", "of", "us", "story", "staff"}
_CRED = re.compile(r"(?:,?\s+(?:MD|M\.D\.|DO|NP|RN|PA-C|PA|DNP|FNP-C|APRN|MBA|BSN|RN-BSN|PhD))+$", re.I)
_NAME = re.compile(r"^[A-Z][a-z'’-]+(?: [A-Z]\.?)?(?: [A-Z][a-zA-Z'’-]+){1,2}$")
_SPLIT = re.compile(r"\s*(?:,|\s[-–—|•:]\s|:)\s*")


def _clean_name(s: str) -> tuple[str, str] | None:
    s = _CRED.sub("", re.sub(r"^(?:Dr|Mr|Mrs|Ms)\.?\s+", "", s.strip()))
    if not _NAME.match(s):
        return None
    toks = s.split()
    if any(t.lower().strip(".") in STOP for t in toks):
        return None
    return toks[0], toks[-1]


def _lines(html: str) -> list[str]:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|tr|td|section|article|span)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def _jsonld(html: str):
    for m in re.finditer(r'(?is)<script[^>]*ld\+json[^>]*>(.*?)</script>', html):
        try:
            stack = [json.loads(m.group(1))]
        except ValueError:
            continue
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack += o
            elif isinstance(o, dict):
                if "Person" in str(o.get("@type")) and o.get("name") and o.get("jobTitle"):
                    yield o["name"], o["jobTitle"]
                stack += list(o.values())


def owner_names_from_html(html: str) -> list[dict]:
    found: dict[tuple[str, str], str] = {}

    def add(name: str, title: str):
        n = _clean_name(name)
        if n and is_decision_maker(title) and len(title.split()) <= 8:
            found.setdefault((n[0].lower(), n[1].lower()), title)
            names[(n[0].lower(), n[1].lower())] = n

    names: dict[tuple[str, str], tuple[str, str]] = {}
    for nm, title in _jsonld(html):
        add(nm, title)
    lines = _lines(html)
    for i, ln in enumerate(lines):
        parts = [p for p in _SPLIT.split(ln) if p]
        if len(parts) > 1:
            for a in parts:
                for b in parts:
                    if a is not b:
                        add(a, b)
        if len(ln.split()) <= 4:
            for j in (i + 1, i - 1):
                if 0 <= j < len(lines):
                    add(ln, lines[j])
    return [{"first_name": names[k][0], "last_name": names[k][1], "position": t} for k, t in found.items()]


def find_owner_candidates(domain: str, fetch) -> list[dict]:
    """Fetch the standard pages in order and stop at the first one that names an owner."""
    for path in PATHS:
        html = fetch(f"https://{domain}{path}")
        if html:
            found = owner_names_from_html(html)
            if found:
                return found
    return []


BLOCK_CODES = {401, 403, 406, 429, 503}
CHALLENGE = ("just a moment", "attention required", "captcha", "cf-chl", "verify you are human", "access denied")
MIN_TEXT = 200


def _visible(html: str) -> str:
    return " ".join(_lines(html))


def _is_challenge(text: str) -> bool:
    # ponytail: markers only checked on short pages, a long real page may mention reCAPTCHA in a form footer
    return len(text) < 2000 and any(m in text.lower() for m in CHALLENGE)


def fetch_page(url: str) -> tuple[str | None, str]:
    """(html, outcome): ok, blocked (paid fallback may help) or gone (never worth paying for)."""
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; KodoAI research)"})
    except httpx.HTTPError:
        return None, "gone"
    if r.status_code in BLOCK_CODES:
        return None, "blocked"
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "") or len(r.content) > 1_500_000:
        return None, "gone"
    vis = _visible(r.text)
    if _is_challenge(vis) or (len(vis) < MIN_TEXT and "<script" in r.text.lower()):
        return None, "blocked"
    return r.text, "ok"


def http_fetch(url: str) -> str | None:
    return fetch_page(url)[0]


def fetch_with_fallback(url: str) -> str | None:
    """Direct fetch; only when it is blocked (and the setting is on) try Serper, then Apify (cheapest first)."""
    from gtm import apify, search  # late: both import paid-call plumbing
    from gtm.budget import BudgetExceeded
    from gtm.settings_store import setting

    text, outcome = fetch_page(url)
    if outcome != "blocked" or not setting("fetch_fallback"):
        return text
    for route in (search.serper_scrape, apify.crawl_page):
        try:
            got = route(url)
        except BudgetExceeded:
            raise
        except Exception:
            continue
        if got and len(got) >= MIN_TEXT and not _is_challenge(got):
            return got
    return None

"""Recon spike — NY med spas: who owns them, and can we reach them? (Phase 9 recon)

§8 is the one stage that still raises ``StageNotImplementedError``, and its
prose was written for Pakistan (SECP, Zameen agents, "Malik Sahib"). Pointing it
at a US vertical changes every source, so — as with §5.3 and §6 — nothing is
assumed. This script measures, per source, how often a New York med spa yields
a **named economic buyer** and how often that name yields an **email**, so the
Phase 9 design is built on numbers rather than on what the tooling vendors say.

The manual process this is measuring against: Maps → website → LinkedIn Sales
Navigator → ContactOut extension, falling back to Hunter with a name and a
domain. Sales Navigator is a logged-in surface and is *not* automated here
(§6.1: never automate past an access control). What replaces it is a public
search-engine lookup of ``site:linkedin.com/in``, which returns the profile URL
and headline without touching LinkedIn.

Stages, each idempotent over ``--out`` and each re-runnable at zero request
cost because every body goes through ``core/cache.py`` (§7):

  ``--discover``  Stage 1 as it already exists, aimed at Manhattan tiles and
                  med-spa synonyms. Deterministic sample of ``--limit``.
  ``--website``   §5.2's crawl (homepage, /contact, /about, /team) plus the
                  provider pages med spas actually use, then a *name* pass:
                  JSON-LD ``founder``, and "Founder / Owner / Medical Director"
                  patterns in the visible text. Also any LinkedIn URL the site
                  itself links — the cheapest possible LinkedIn join.
  ``--npi``       NPPES NPI Registry (free, public, JSON). An organisation NPI
                  record names an *authorized official* with title and phone.
                  Joined to the Maps record by phone, then by zip + name; the
                  join tier is recorded, never assumed.
  ``--dos``       NY Department of State entity search (public form, JSON
                  behind it). Corporations file a CEO on the biennial
                  statement; LLCs do not — measured, not asserted.
  ``--linkedin``  Serper ``site:linkedin.com/in`` lookup, name-anchored when a
                  name is already known, role-anchored otherwise. The join is
                  the business name appearing in the SERP title.
  ``--qualify``   MedSpa/ §3's account and buyer gates (``core/icp.py``), from
                  the cached pages — no network. Writes an ``icp`` block per
                  row. ``--email`` refuses to run without it.
  ``--email``     Qualified accounts first, hard stops never; ``--retry-missing``
                  re-walks the no-email backlog, ``--qualified-only`` holds
                  ambiguous accounts back. Then the waterfall, per row:
                  a personal-looking email on the site itself →
                  ContactOut by LinkedIn URL → Hunter Email Finder (name +
                  domain) → ContactOut enrich (name + company) → Hunter Domain
                  Search (people at the domain, for businesses with no name).
                  Hunter is behind a **gate**, not just an order
                  (``icp.hunter_eligible``): qualified account, qualified
                  named buyer, own domain, nothing found yet, domain not
                  already called. ``--hunter-key {1..4}`` picks the key
                  (``--hunter-keys 3,1,4,2`` rotates through several),
                  ``--hunter-budget N`` caps live calls, domain search needs
                  ``--allow-domain-search``. ``--dry-run`` prints the exact
                  spend plan — show it to the operator before a live run.
  ``--slice``     Cut a batch (category, in-state ZIP, own domain) from a
                  discovery pool into ``--into``, honouring ``--exclude``.
  ``--master``    Append the batch's leads to the Texas master list: ``email``
                  (never accept-all) or a qualified buyer's ``linkedin``.
  ``--buyers``    Print every chosen buyer with role, source and snippet, to
                  eyeball for extractor noise before any spend.
  ``--report``    The numbers. Name yield per source, email yield per source,
                  and the intersection — the only figure that is a lead.

Usage (from ``backend/``, datastores up, ``PROXY_REQUIRED_SOURCES=""``):

    set PYTHONIOENCODING=utf-8
    uv run python scripts/spike_medspa_ny.py --discover --tiles 3 --synonyms 2 --limit 50
    uv run python scripts/spike_medspa_ny.py --website
    uv run python scripts/spike_medspa_ny.py --npi
    uv run python scripts/spike_medspa_ny.py --dos
    uv run python scripts/spike_medspa_ny.py --linkedin
    uv run python scripts/spike_medspa_ny.py --email --dry-run
    uv run python scripts/spike_medspa_ny.py --email
    uv run python scripts/spike_medspa_ny.py --report

Texas is discovered per metro (``--region tx --metro houston --tiles 0``); each
row records ``metro`` and ``address_city``, and the CSV carries both.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode

from rapidfuzz.fuzz import token_set_ratio, token_sort_ratio

from leadscraper.config import get_settings
from leadscraper.core import icp
from leadscraper.core.cache import FetchCache, FetchKind
from leadscraper.core.textnorm import normalise_name, registrable_domain
from leadscraper.db.session import session_scope

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30.0

# --------------------------------------------------------------------------- #
# Discovery plan — a hypothesis, like every non-Lahore tile set in cities.yaml
# --------------------------------------------------------------------------- #

CITY = "New York, NY"
TILES = (
    "Upper East Side",
    "Midtown Manhattan",
    "SoHo",
    "Tribeca",
    "Chelsea",
    "Flatiron District",
    "Upper West Side",
    "Financial District",
    "Greenwich Village",
    "Williamsburg Brooklyn",
    "Park Slope Brooklyn",
    "Astoria Queens",
)
SYNONYMS = ("med spa", "medical spa", "aesthetic clinic", "botox clinic", "laser clinic")

NYC_COUNTIES = {"New York", "Kings", "Queens", "Bronx", "Richmond"}


@dataclass(frozen=True, slots=True)
class Region:
    """Everything region-specific. A row records its region at --discover, so
    every later stage asks the row, not a flag the operator must repeat."""

    code: str
    label: str  # the SERP/report phrase
    state: str  # two-letter, for NPPES
    locations: tuple[str, ...]  # fully-qualified Maps query locations
    zip_re: re.Pattern[str]
    # NY DOS is the only state registry this script knows. Utah's Division of
    # Corporations has not been reconned; a region without one skips --dos
    # and says so, rather than querying New York for a Utah business.
    has_registry: bool
    # Metro slug → its query locations. A region with metros is discovered one
    # metro at a time (``--metro``), and every row records the metro whose
    # query found it, so a CSV can be split without re-deriving geography.
    metros: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def metro_cities(self, metro: str) -> frozenset[str]:
        """The cities a metro's tiles name: ``"Montrose, Houston, TX"`` →
        montrose and houston, ``"Katy, TX"`` → katy. What an address city is
        checked against — a tile list, not a census definition of the metro.

        Both parts count because some areas are their own postal city: the
        first Houston run filed 59 "Kingwood, TX" addresses as outside the
        metro whose "Kingwood, Houston, TX" tile had found them.
        """
        return frozenset(
            _fold_city(part) for loc in self.metros.get(metro, ()) for part in loc.split(",")[:-1]
        )


def _fold_city(city: str) -> str:
    return re.sub(r"\s+", " ", city).strip().casefold()


# The Houston tiles are a hypothesis, like every tile set here: core
# neighbourhoods as "<area>, Houston, TX", suburbs as "<city>, TX".
HOUSTON_TILES = (
    *(
        f"{area}, Houston, TX"
        for area in (
            "Downtown",
            "Midtown",
            "Montrose",
            "River Oaks",
            "Uptown Galleria",
            "The Heights",
            "Memorial",
            "Rice Village",
            "Kingwood",
            "Clear Lake",
        )
    ),
    "Bellaire, TX",
    "The Woodlands, TX",
    "Sugar Land, TX",
    "Katy, TX",
    "Pearland, TX",
    "Cypress, TX",
    "Spring, TX",
    "League City, TX",
    "Friendswood, TX",
    "Missouri City, TX",
    "Humble, TX",
    "Tomball, TX",
    "Conroe, TX",
)
# Oct 2026, for the four-key run: Houston's pool was used up. Same shape and
# the same status — a hypothesis until --discover's metro check has been read.
DFW_TILES = (
    *(
        f"{area}, Dallas, TX"
        for area in (
            "Uptown",
            "Downtown",
            "Highland Park",
            "Preston Hollow",
            "Lakewood",
            "Oak Lawn",
            "Bishop Arts",
        )
    ),
    *(f"{area}, Fort Worth, TX" for area in ("Downtown", "West 7th", "TCU", "Near Southside")),
    "Plano, TX",
    "Frisco, TX",
    "McKinney, TX",
    "Allen, TX",
    "Richardson, TX",
    "Addison, TX",
    "Irving, TX",
    "Southlake, TX",
    "Grapevine, TX",
    "Colleyville, TX",
    "Keller, TX",
    "Arlington, TX",
    "Mansfield, TX",
    "Flower Mound, TX",
    "Denton, TX",
    "Rockwall, TX",
    "Prosper, TX",
)
SAN_ANTONIO_TILES = (
    *(
        f"{area}, San Antonio, TX"
        for area in ("Downtown", "Alamo Heights", "Stone Oak", "The Dominion", "Medical Center")
    ),
    "New Braunfels, TX",
    "Boerne, TX",
    "Schertz, TX",
    "Helotes, TX",
)
AUSTIN_TILES = (
    *(
        f"{area}, Austin, TX"
        for area in ("Downtown", "South Congress", "Westlake", "The Domain", "Mueller")
    ),
    "Round Rock, TX",
    "Cedar Park, TX",
    "Georgetown, TX",
    "Lakeway, TX",
    "Bee Cave, TX",
    "Pflugerville, TX",
    "Kyle, TX",
)
TEXAS_METROS: dict[str, tuple[str, ...]] = {
    "houston": HOUSTON_TILES,
    "dfw": DFW_TILES,
    "san_antonio": SAN_ANTONIO_TILES,
    "austin": AUSTIN_TILES,
}


REGIONS: dict[str, Region] = {
    "ny": Region(
        "ny",
        "New York",
        "NY",
        tuple(f"{t}, {CITY}" for t in TILES),
        re.compile(r"\b(1[0-9]{4})(?:-\d{4})?\b"),
        has_registry=True,
    ),
    # A hypothesis, like every non-Lahore tile set in cities.yaml: the Wasatch
    # Front, where ~80% of Utahns live, plus Park City and St. George.
    "ut": Region(
        "ut",
        "Utah",
        "UT",
        (
            "Salt Lake City, UT",
            "Sugar House, Salt Lake City, UT",
            "Holladay, UT",
            "Murray, UT",
            "Draper, UT",
            "Sandy, UT",
            "South Jordan, UT",
            "Lehi, UT",
            "American Fork, UT",
            "Orem, UT",
            "Provo, UT",
            "Bountiful, UT",
            "Layton, UT",
            "Ogden, UT",
            "Park City, UT",
            "St. George, UT",
        ),
        re.compile(r"\b(8[45][0-9]{3})(?:-\d{4})?\b"),
        has_registry=False,
    ),
    # No Texas registry stage: the Comptroller's franchise-tax search may list
    # officers, but that is unverified and needs its own recon spike first.
    "tx": Region(
        "tx",
        "Texas",
        "TX",
        tuple(loc for tiles in TEXAS_METROS.values() for loc in tiles),
        # The second branch is El Paso (885xx–889xx).
        re.compile(r"\b(7[5-9][0-9]{3}|88[5-9][0-9]{2})(?:-\d{4})?\b"),
        has_registry=False,
        metros=TEXAS_METROS,
    ),
}


def region_of(row: dict) -> Region:
    """Rows discovered before regions existed are New York's."""
    return REGIONS[row.get("region") or "ny"]


def address_city(address: str | None, state: str) -> str | None:
    """``"123 Main St, Katy, TX 77494, United States"`` → ``"Katy"``."""
    match = re.search(rf",\s*([^,]+?),\s*{state}\s+\d{{5}}", address or "")
    return match.group(1).strip() if match else None


# --------------------------------------------------------------------------- #
# Name extraction from a page's visible text (§8 Tier D, US shapes)
# --------------------------------------------------------------------------- #

_CREDS = r"(?:MD|DO|NP|PA-?C|RN|FNP|DNP|PA|FAAD|FACS|BSN|MSN|APRN|NP-?C|CRNA|PhD|MBA|LE|CME)"
_NAME = (
    r"((?:Dr\.?\s+)?[A-Z][a-zA-Z'\-]+(?:\s+(?:[A-Z]\.?\s+)?[A-Z][a-zA-Z'\-]+){1,2}"
    rf"(?:,?\s*{_CREDS}\.?)*)"
)
_TITLE = (
    r"((?:Co-?)?Founder|(?:Co-?)?Owner|CEO|Medical Director|Clinical Director|"
    r"Director|President|Principal|Proprietor|Lead Injector|Founding Physician)"
)
_PEOPLE_PATTERNS = (
    # "Jane Doe, NP — Founder". The separator is optional because flattened
    # page text loses the line break: "Dr. Ahmed Elsoury Medical Director" is
    # how a team page reads once the markup is gone.
    re.compile(rf"{_NAME}\s*[,–\-|•:]?\s*(?:the\s+|our\s+)?{_TITLE}\b"),
    # "Founder: Dr. Jane Doe" / "Medical Director Dr Jane Doe"
    re.compile(rf"\b{_TITLE}\s*[,:–\-|•]?\s*{_NAME}"),
    # "founded by Dr. Jane Doe" / "owned and operated by Jane Doe"
    re.compile(
        r"\b(?:founded|owned|established|created|started|led)"
        rf"(?:\s+and\s+(?:operated|run|led))?\s+by\s+{_NAME}"
    ),
    # "Jane Doe is the founder"
    re.compile(rf"{_NAME}\s+is\s+(?:the|our|a)\s+{_TITLE}\b"),
)
# Tokens that pass the capitalised-words shape and are never a person.
_NOT_A_NAME = frozenset(
    re.findall(
        r"\w+",
        "med spa medspa medical new york nyc our team the book now meet about us contact "
        "skin laser beauty aesthetics aesthetic clinic center centre wellness health "
        "manhattan brooklyn queens upper east west side midtown botox filler facial body "
        "hair removal privacy policy terms learn more read call today schedule appointment "
        "january february march april may june july august september october november "
        "december monday tuesday wednesday thursday friday saturday sunday inc llc pllc "
        # Words the first live crawl produced as "names": role nouns, nav text
        # and corporate suffixes that sit next to a real title in flattened text.
        "co founder founders owner owners director directors president ceo board "
        "certified plastic surgeon nurse aesthetician esthetician injector sales media "
        "ventures careers paper white click full after why faces management "
        "trailblazers podcast host officer corporate vp chief members staff "
        "providers provider physician physicians doctor doctors your free consultation "
        "talent casting desk front affiliations young reconstructive surgery view all "
        "massage associazione coming soon "
        # Utah batch 1 (Sep 2026): "Nursing Practice", "Frequently Asked
        # Questions", "Practitioner Monica", "Jaden Schoenrock Marketing".
        "nursing practice practitioner frequently asked questions marketing "
        # Houston batch 1 (Oct 2026): "CEO Tyshiba Harrison Operations
        # Manager", "Scan Consultations Meet the Director".
        "operations consultations reviews payment plans "
        # Houston batch 2: page phrases and a web agency's JSON-LD "founder"
        # that passed as people ("Executive Vice", "Finally Feeling Like",
        # "Clinical Precision", "Digital Innovation Solutions", "Los
        # Angeles-born Lisa", "Principal Investigator").
        "vice finally feeling like clinical precision optimization programs digital "
        "innovation solutions solutio los principal investigator associate residency "
        # Houston batch 3 (non-"Medical spa" categories): "Gameday Men",
        # "Package Anti-aging", "Pledge Class", "American Society", "Master
        # Artist", "Facts Accreditation Office", "Elevate Menu Technology".
        "men package pledge class american society master artist facts accreditation "
        "office menu technology superior results administrative fellowship selected "
        "leadership positi positions "
        # San Antonio (Oct 2026): "Licensed Cosmetologist", "Regenerative
        # Medicine" as founders.
        "cosmetologist regenerative medicine "
        # DFW: "Professional Activities" (a CV heading), "Pediatric Cancer",
        # "Plano Texas". "Texas" is also edge noise, which is stripped first,
        # so "Texas Nwando Okafor" still yields the person.
        "professional activities pediatric cancer plano texas "
        # Austin: "Led Care" ("Owner-Led Care"), "Cosmetic Injection
        # Specialist", "Implants Pioneer", "Courses Premium Salon".
        "led cosmetic injection specialist implants pioneer courses premium salon "
        # DFW b1: a street address ("President George Bush Hwy"), "Recognition
        # Awards", "My Account", "Guest Experience Expert", "National Trainer",
        # "Small Family Business", "At Age", "Introducing Tonya".
        "hwy highway pkwy blvd recognition awards account guest experience expert "
        "national trainer small family business age introducing "
        # DFW b2q: "Operated Expertise Every" ("Owner-Operated Expertise").
        "operated expertise",
    )
)
# Words that sit *next to* a real name in flattened text and get swept into
# it: "Book A Visit Jillian Brooke RN", "📍 Utah Savinder Virk, APRN",
# "Heidi Goodrich Registered Nurse", "Blake Bennion Co-Founder". Stripped from
# either end before validation, so the person survives and the noise does not.
# Rejecting instead would lose the name; keeping it spends a credit on "Visit".
_EDGE_NOISE = frozenset(
    [
        "visit",
        "utah",
        "provider",
        "meet",
        "book",
        "registered",
        "licensed",
        "co",
        "co-",
        "dr",
        "executive",
        # Houston batch 1: "Slim Fit Beauty Team Dashaun Fields CEO" lost the
        # real CEO to the word "Team" (rejected whole, so the CEO title went
        # to the next name on the page); "Brittany Harris Regional Director".
        "team",
        "regional",
        # Houston batch 2: "Story Betty Rogers", "Zoom Jessica Fields",
        # "Facility Tracey Allely", "Care Sarika Diaz", "In Adriana Rubio",
        # "Jayson Weir Powered", "Daniel Acevedo Administrat(or)", "Gladys
        # Adame Creative", "Hydrafacial Rachel Snider", "Karen Thampoe As".
        "story",
        "zoom",
        "facility",
        "care",
        "in",
        "powered",
        "administrat",
        "administrator",
        "creative",
        "hydrafacial",
        "explore",
        "patient",
        "managing",
        "as",
        # Houston batch 3: "Farrah Louviere With", "Jeanni Nguyen Get".
        "with",
        "get",
        "billing",
        # San Antonio: "Texas Nwando Okafor", "Instructors Huma Siwani",
        # "Button Crystal Ramirez" (a site's per-person "Button" link label).
        "texas",
        "instructors",
        "button",
        # DFW: "Ebele Chioma From" ("… From Struggle to Passion").
        "from",
        # Austin: "Specialist Ayla Gaines", "Ashley Szulim-Sabean Services",
        # "Sarah Wiser Introduction", "Claudia Ward Owned", "Administration
        # Heidi Fischer".
        "specialist",
        "services",
        "introduction",
        "owned",
        "administration",
        # DFW b1: "Bio Mandy Cotten" ("Read Bio"), "Professionals Jeffrey
        # Adelglass", "Family Jon Ricks", "Amy Zevallos Businesss", "Terry
        # Gannon Hi", "Natan Yaker For".
        "bio",
        "professionals",
        "family",
        "business",
        "businesss",
        "hi",
        "for",
        # Austin: "Robert Caridi Westlake" — split_name would send "Westlake".
        "westlake",
    ]
)
_CREDS_SET = frozenset(re.findall(r"[A-Z]+", _CREDS)) | {
    "MD",
    "DO",
    "NP",
    "PA",
    "RN",
    "DNP",
    "FNP",
    "PAC",
    "NPC",
    "PHD",
    "MBA",
}
_HONORIFIC_RE = re.compile(r"^(?:Dr\.?|Mr\.?|Ms\.?|Mrs\.?|Nurse)\s+", re.IGNORECASE)
_CRED_TAIL_RE = re.compile(rf"(?:,?\s*{_CREDS}\.?)+$")

_LINKEDIN_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(in|company)/([A-Za-z0-9_%\-\.]+)", re.IGNORECASE
)
# Med-spa "who we are" pages use vocab §5.2's about-regex never needed in PK.
_PROVIDER_LINK_RE = re.compile(
    r"""href=["']([^"']*/(?:providers?|our-providers|meet-[a-z\-]+|staff|doctors?|"""
    r"""physicians?|founder|our-founder|injectors?|practitioners?|team|our-team|about[a-z\-]*)"""
    r"""(?:/|\.html?)?(?:\?[^"']*)?)["']""",
    re.IGNORECASE,
)
_SUFFIX_RE = re.compile(
    r"\b(?:med\s*spa|medspa|medical\s+spa|aesthetics?|clinic|nyc|new\s+york|ny|"
    r"llc|pllc|inc\.?|corp\.?|p\.?c\.?|of\s+manhattan|manhattan|brooklyn|"
    r"laser(?:\s+center)?|skin(?:care)?|wellness|center|centre|&|and|the)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Person:
    name: str
    role: str
    # site_jsonld | site_text | site_linkedin | npi | dos_ceo | dos_other |
    # linkedin | hunter_domain
    source: str
    evidence_url: str
    snippet: str = ""
    credentials: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "source": self.source,
            "evidence_url": self.evidence_url,
            "snippet": self.snippet,
            "credentials": self.credentials,
        }


def clean_person_name(raw: str) -> tuple[str, str] | None:
    """``"Dr. Jane A. Doe, MD, FAAD"`` → ``("Jane A. Doe", "MD, FAAD")`` or None."""
    name = _HONORIFIC_RE.sub("", raw.strip())
    creds = ""
    tail = _CRED_TAIL_RE.search(name)
    if tail:
        creds = tail.group(0).strip(", ")
        name = name[: tail.start()].strip(", ")
    tokens = name.split()
    while len(tokens) > 2 and tokens[0].lower().strip(".") in _EDGE_NOISE:
        tokens = tokens[1:]
    while len(tokens) > 2 and tokens[-1].lower().strip(".") in _EDGE_NOISE:
        tokens = tokens[:-1]
    # "Ruslana Parker Ruslana ..." — the bio's opening word repeats the name.
    if len(tokens) > 2 and tokens[-1].lower() == tokens[0].lower():
        tokens = tokens[:-1]
    # "Johanna Johanna Chaidez", "Marissa Marissa" (Houston batch 2): a
    # heading followed by the same name. Collapse; a lone name then fails.
    tokens = [t for i, t in enumerate(tokens) if i == 0 or t.lower() != tokens[i - 1].lower()]
    # "Jen Jennifer Quesada" (Austin): a nickname heading the full name.
    # split_name would send Hunter "Jen"; keep the name it is short for.
    if len(tokens) > 2 and tokens[1].lower().startswith(tokens[0].lower()):
        tokens = tokens[1:]
    # "Lynda Okafor F" (San Antonio): "FNP-C" split at the hyphen left an "F".
    # A trailing initial is never a surname, and split_name would send it to
    # Hunter as one.
    # "Megan F" (DFW, "Megan FNP-C") is the two-token case: no surname left.
    while tokens and len(tokens[-1].strip(".")) == 1:
        tokens = tokens[:-1]
    if tokens and tokens[-1].endswith("-"):
        tokens[-1] = tokens[-1].rstrip("-")
        if not tokens[-1] or tokens[-1].lower() in _EDGE_NOISE:
            tokens = tokens[:-1]
    name = " ".join(tokens)
    if len(tokens) < 2 or len(tokens) > 4:
        return None
    # A theme's placeholder team page, live on a DFW med spa ("John Doe CEO
    # Lorem ipsum dolor sit amet").
    if name.lower() in {"john doe", "jane doe"}:
        return None
    # Hyphen parts too: "Chloe Co-Founder Melissa" (San Antonio) hid its role
    # noun inside one token, where a whole-token check never sees it.
    if any(p in _NOT_A_NAME for t in tokens for p in t.lower().strip(".").split("-")):
        return None
    if not all(t[0].isupper() for t in tokens):
        return None
    # "CLICK FOR FULL", "NE-C Co": shouted nav text and stray credentials;
    # "Next Health's" is a possessive, never a surname.
    if any(len(t) > 1 and t.isupper() for t in tokens) or any("'" in t for t in tokens):
        return None
    return name, creds


def people_from_text(text: str, url: str) -> list[Person]:
    found: list[Person] = []
    seen: set[str] = set()
    flat = re.sub(r"\s+", " ", text)
    for pattern in _PEOPLE_PATTERNS:
        for match in pattern.finditer(flat):
            groups = match.groups()
            # Each pattern has a name group and, except "founded by", a title group;
            # the order differs, so pick by shape rather than by index.
            name_raw = next((g for g in groups if g and clean_person_name(g)), None)
            title = next((g for g in groups if g and g != name_raw), "founded_by")
            if not name_raw:
                continue
            cleaned = clean_person_name(name_raw)
            if cleaned is None:
                continue
            name, creds = cleaned
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            start, end = max(0, match.start() - 40), min(len(flat), match.end() + 40)
            found.append(
                Person(
                    name=name,
                    role=title.lower().replace(" ", "_"),
                    source="site_text",
                    evidence_url=url,
                    snippet=flat[start:end],
                    credentials=creds,
                )
            )
            if len(found) >= 6:
                return found
    return found


def name_from_slug(url: str) -> str:
    """``linkedin.com/in/carolyn-treasure-md-1a2b3c`` → ``"Carolyn Treasure"``.

    Trailing hash segments and credential tokens are dropped; anything that
    does not then look like a two-to-three-word name yields "" rather than a
    guess.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    parts = [t for t in re.split(r"[-_.]+", slug.lower()) if t]
    parts = [t for t in parts if not re.fullmatch(r"[0-9a-f]{5,}|\d+", t)]
    parts = [t for t in parts if t.upper() not in _CREDS_SET and t.isalpha()]
    if 2 <= len(parts) <= 3:
        cleaned = clean_person_name(" ".join(t.capitalize() for t in parts))
        return cleaned[0] if cleaned else ""
    return ""


def short_name(name: str) -> str:
    """``"SKINNEY Medspa NYC"`` → ``"SKINNEY"``: the token(s) a registry files under."""
    stripped = _SUFFIX_RE.sub(" ", name)
    stripped = re.sub(r"[^\w\s']", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped or name


def name_ratio(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 0
    return int(token_set_ratio(a.lower(), b.lower()))


# Hosts Maps hands over as a "website" that are not the business's own domain.
# A Hunter domain search on x.com returns X Corp's staff, not the spa's — the
# first live pass produced exactly that ("peter@x.com" for a Midtown spa).
_PLATFORM_HOSTS = frozenset(
    re.findall(
        r"[\w.]+",
        "x.com twitter.com instagram.com facebook.com linktr.ee tiktok.com youtube.com "
        "yelp.com vagaro.com booksy.com squareup.com square.site glossgenius.com "
        "zocalabs.com zoca.com mindbodyonline.com fresha.com wix.com wixsite.com "
        "godaddysites.com business.site visibook.com schedulicity.com "
        # Booking and site builders med spas hand Maps as their "website". A
        # domain search on any of these returns the platform's staff, and a
        # business living on one has no corporate inbox to find.
        "booker.com joinblvd.com boulevard.io janeapp.com zenoti.com setmore.com "
        "acuityscheduling.com squarespace.com weebly.com wordpress.com carrd.co "
        "sites.google.com google.com groupon.com linkin.bio beacons.ai "
        # Houston batch 2: tenant hosts that subdomain reduction would
        # otherwise have turned into the platform's own domain.
        "as.me airoapp.ai univer.se",
    )
)


def business_domain(website: str | None) -> str | None:
    domain = registrable_domain(website or "")
    if not domain:
        return None
    # Suffix, not equality: multi-tenant hosts keep the tenant label through
    # ``registrable_domain`` — "labellalasernewyork.zoca.com",
    # "ivparty.janeapp.com" — so an exact match let both through as a
    # "business domain" although zoca.com was already on the list.
    host = domain.lower()
    if any(host == p or host.endswith(f".{p}") for p in _PLATFORM_HOSTS):
        return None
    # A chain's store locator ("locations.livehydrationspa.com", Houston batch
    # 1) is not the domain its inboxes live on, and Hunter indexes the
    # registrable one. Checked *after* the platform list, so a tenant label on
    # zoca.com is still refused rather than reduced to zoca.com. Two labels
    # unless the second-level label is itself a registry suffix (".co.uk").
    # Only under the generic TLDs US businesses actually register: a tenant of
    # an unlisted platform on ".me"/".ai"/".se" ("bodylifthouston.as.me",
    # Houston batch 2) must not be reduced to the platform itself.
    labels = host.split(".")
    if len(labels) > 2 and labels[-1] in {"com", "net", "org", "us", "health", "clinic", "spa"}:
        return ".".join(labels[-2:])
    return domain


def digits(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else d


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Spend:
    """Every live call, by API, so the report can price the pipeline."""

    live: dict[str, int] = field(default_factory=dict)
    cached: dict[str, int] = field(default_factory=dict)

    def note(self, api: str, from_cache: bool) -> None:
        bucket = self.cached if from_cache else self.live
        bucket[api] = bucket.get(api, 0) + 1


def load_state(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


def require_state(path: Path) -> list[dict]:
    rows = load_state(path)
    if not rows:
        print(f"No businesses yet — run --discover first ({path}).")
        sys.exit(1)
    return rows


# --------------------------------------------------------------------------- #
# Cache-first JSON fetch shared by every API stage
# --------------------------------------------------------------------------- #


_ACCOUNT_STATE_STATUSES = frozenset({402, 429})


async def cached_json(
    client,
    cache: FetchCache,
    spend: Spend,
    api: str,
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: dict | None = None,
    cache_key: str | None = None,
    delay: float = 1.0,
) -> tuple[int, dict | list | None, bool]:
    """Returns (status, parsed JSON or None, from_cache).

    Keyed on the URL (plus the body for POSTs) so a re-run costs nothing and a
    second opinion on a parse never re-spends a credit. The body rides in the
    query string, not a fragment: ``normalise_url`` drops fragments, and the
    first DOS run served one business's answer to all fifty.
    """
    if cache_key is None:
        cache_key = url
        if body is not None:
            joiner = "&" if "?" in url else "?"
            cache_key = f"{url}{joiner}__body={quote(json.dumps(body, sort_keys=True))}"
    key = cache_key
    hit = cache.get(key)
    # A cached 402/429 is a fact about the *account* on the day it was fetched
    # ("out of searches"), not about this query. Replaying it made the whole
    # no-email backlog unretryable: every row whose Hunter call hit the
    # exhausted allowance would answer 429 from cache for 30 days after the
    # allowance reset. Refetch instead; `put` overwrites the stale entry.
    if hit is not None and hit.status in _ACCOUNT_STATE_STATUSES:
        hit = None
    if hit is not None:
        spend.note(api, True)
        try:
            return hit.status, json.loads(hit.text() or "null"), True
        except json.JSONDecodeError:
            return hit.status, None, True

    if spend.live.get(api):
        await asyncio.sleep(delay)
    spend.note(api, False)
    try:
        if method == "POST":
            response = await client.post(url, headers=headers, json=body)
        else:
            response = await client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001 — a dead host is a finding
        print(f"    !! {api} {type(exc).__name__}: {str(exc)[:100]}")
        return 0, None, False

    status = response.status_code
    raw = response.content
    try:
        payload = json.loads(raw or b"null")
    except json.JSONDecodeError:
        payload = None
    # 5xx is transient and is not remembered; everything else is a durable fact
    # about this query, including 404 and a 402 "out of credits".
    if status < 500:
        cache.put(
            key,
            raw,
            status=status,
            content_type="application/json",
            source=api,
            kind=FetchKind.DETAIL,
        )
        cache.session.commit()
    if status != 200:
        print(f"    !! {api} HTTP {status}: {raw[:160]!r}")
    return status, payload, False


def new_client(**kwargs):
    import httpx

    return httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
        follow_redirects=True,
        headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# --discover
# --------------------------------------------------------------------------- #


async def run_discover(args) -> int:
    from leadscraper.sources.google_maps import GoogleMapsSource, merge_results

    if load_state(args.out) and not args.force:
        # A sample is a measurement set. Re-sampling replaced the first 50
        # with a different 50 mid-spike: the cached Maps re-parse sees fewer
        # results than the live run did (``GoogleMapsSource._store`` keeps
        # one payload per query; a live query merges every scroll's), so the
        # seeded shuffle lands on different businesses and the enrichment
        # already paid for no longer applies to the rows in the file.
        print(f"{args.out} already holds a sample; pass --force to replace it.")
        return 1

    settings = get_settings()
    region = REGIONS[args.region]
    locations = region.locations
    if region.metros:
        if args.metro not in region.metros:
            print(
                f"--region {region.code} is discovered one metro at a time: --metro "
                f"{{{','.join(sorted(region.metros))}}}"
            )
            return 1
        locations = region.metros[args.metro]
    elif args.metro:
        print(f"--region {region.code} has no metros; drop --metro")
        return 1
    tiles = locations[: args.tiles] if args.tiles else locations
    synonyms = SYNONYMS[: args.synonyms] if args.synonyms else SYNONYMS
    queries = [f"{syn} in {tile}" for tile in tiles for syn in synonyms]
    print(
        f"Plan ({region.label}{f' / {args.metro}' if args.metro else ''}): {len(queries)} "
        f"queries ({len(tiles)} tiles × {len(synonyms)} synonyms)"
    )
    for q in queries[:4]:
        print(f"   {q}")

    with session_scope() as session:
        cache = FetchCache(session, settings)
        source = GoogleMapsSource(cache=cache, settings=settings)
        outcomes = await source.discover(queries)
        session.commit()

    by_place: dict[str, dict] = {}
    blocked = errors = empty = 0
    for outcome in outcomes:
        if outcome.blocked:
            blocked += 1
        if outcome.error:
            errors += 1
        if not outcome.results:
            empty += 1
        for result in merge_results([outcome.results]):
            key = result.place_id or f"{result.name}|{result.address}"
            if key in by_place:
                continue
            zip_match = region.zip_re.search(result.address or "")
            by_place[key] = {
                "region": region.code,
                # From the query that found it, not from the address: Maps
                # returns neighbours at a tile's edge, and the check below
                # reports those instead of silently re-filing or dropping them.
                "metro": args.metro,
                "address_city": address_city(result.address, region.state),
                "name": result.name,
                "place_id": result.place_id,
                "address": result.address,
                "zip": zip_match.group(1) if zip_match else None,
                "lat": result.lat,
                "lng": result.lng,
                "phone_raw": result.phone_raw,
                "phone_digits": digits(result.phone_raw),
                "website": result.website,
                "domain": business_domain(result.website),
                "rating": result.rating,
                "review_count": result.review_count,
                "category": result.category,
                "maps_url": result.maps_url,
                "query": outcome.query,
            }
    print(
        f"\nqueries={len(outcomes)} from_cache={sum(o.from_cache for o in outcomes)} "
        f"blocked={blocked} errors={errors} empty={empty} unique={len(by_place)}"
    )
    if blocked or errors:
        for o in outcomes:
            if o.blocked or o.error:
                print(f"   {'BLOCKED' if o.blocked else 'ERROR'} {o.query} {o.error or ''}")

    rows = list(by_place.values())

    # §10.1's rule, applied across samples: a business already measured in an
    # earlier sample must not reappear in this one. Matched on place_id, and
    # also on registrable domain and normalised name — Maps lists some chains
    # once per branch, and a second branch of a business we already have is a
    # duplicate *lead* even though it is a distinct place.
    if args.exclude:
        before = len(rows)
        rows = exclude_seen(rows, args.exclude)
        print(f"excluded {before - len(rows)} already-sampled businesses ({len(rows)} left)")

    rows.sort(key=lambda r: r["place_id"] or r["name"] or "")
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]

    # Keep enrichment already done on rows that survive a re-discover.
    previous = {r["place_id"]: r for r in load_state(args.out) if r.get("place_id")}
    for row in rows:
        old = previous.get(row["place_id"])
        if old:
            for k in ("site", "npi", "dos", "linkedin", "email"):
                if k in old:
                    row[k] = old[k]
    save_state(args.out, rows)

    with_site = sum(1 for r in rows if r["website"])
    with_phone = sum(1 for r in rows if r["phone_digits"])
    print(f"\nsampled {len(rows)}  with website {with_site}  with phone {with_phone}")
    cats: dict[str, int] = {}
    for r in rows:
        cats[r["category"] or "?"] = cats.get(r["category"] or "?", 0) + 1
    print(f"categories: {dict(sorted(cats.items(), key=lambda kv: -kv[1])[:8])}")
    if args.metro:
        report_metro_check(rows, region, args.metro)
    print(f"-> {args.out.resolve()}")
    return 0


def exclude_seen(rows: list[dict], paths: list[str]) -> list[dict]:
    """Drop rows already in another state file, on place_id, registrable
    domain or normalised name (§10.1's rule, applied across samples)."""
    seen_ids, seen_domains, seen_names = set(), set(), set()
    for path in paths:
        for old in load_state(Path(path)):
            if old.get("place_id"):
                seen_ids.add(old["place_id"])
            if old.get("domain"):
                seen_domains.add(old["domain"].lower())
            seen_names.add(normalise_name(old.get("name") or ""))
    return [
        r
        for r in rows
        if r.get("place_id") not in seen_ids
        and (r.get("domain") or "").lower() not in seen_domains
        and normalise_name(r.get("name") or "") not in seen_names
    ]


def run_slice(args) -> int:
    """A reproducible batch from a discovery pool: category, an in-state ZIP
    and the business's own domain, in the pool's already-shuffled order.

    Utah's batch 1 was cut with a few ad hoc lines; this is those lines, so
    batch 2 is cut the same way with ``--exclude <batch 1>``. The pool file is
    never written: it is the live discovery, and a cached re-run is thinner.
    """
    if not args.into:
        print("--slice needs --into <batch.json>")
        return 1
    if load_state(args.into) and not args.force:
        print(f"{args.into} already holds a batch; pass --force to replace it.")
        return 1
    pool = require_state(args.out)
    want = {c.strip().casefold() for c in args.category.split(",") if c.strip()}
    rows = [r for r in pool if (r.get("category") or "").casefold() in want]
    n_cat = len(rows)
    rows = [r for r in rows if r.get("zip")]
    n_zip = len(rows)
    for r in rows:
        r["domain"] = business_domain(r.get("website"))
    rows = [r for r in rows if r["domain"]]
    n_dom = len(rows)
    if args.exclude:
        rows = exclude_seen(rows, args.exclude)
    batch = rows[: args.size]
    print(
        f"pool {len(pool)} → {args.category!r} {n_cat} → in-state ZIP {n_zip} → own domain "
        f"{n_dom} → after --exclude {len(rows)} → batch {len(batch)}"
    )
    metros: dict[str, int] = {}
    for r in batch:
        metros[r.get("metro") or "-"] = metros.get(r.get("metro") or "-", 0) + 1
    print(f"  by metro: {metros}")
    save_state(args.into, batch)
    print(f"-> {args.into.resolve()}")
    return 0


def run_buyers(args) -> int:
    """Every chosen buyer, for a human to eyeball before any credit is spent.

    The name extractor is a regex over flattened page text, and Utah's first
    pass put "Nursing Practice" and "Frequently Asked Questions" forward as
    people. The fix is cheap (``clean_person_name``, then ``--website
    --force`` re-parses from cache); spotting the noise needs eyes.
    """
    rows = require_state(args.out)
    shown = 0
    for r in rows:
        c = best_candidate(r)
        if c is None:
            continue
        shown += 1
        snippet = ""
        for p in (r.get("site") or {}).get("people") or []:
            if p.get("name") == c.name and p.get("snippet"):
                snippet = p["snippet"]
                break
        verdict = c.verdict.verdict.value if c.verdict else "?"
        corr = f" +{','.join(c.corroborated_by)}" if c.corroborated_by else ""
        print(
            f"{verdict:9} {c.name[:26]:26} {(c.role or '-')[:30]:30} "
            f"{c.source}{corr}  |  {r['name'][:40]}"
        )
        if snippet:
            print(f"          “{snippet[:150]}”")
        if c.evidence_url:
            print(f"          {c.evidence_url[:110]}")
    print(f"\n{shown} of {len(rows)} rows have a chosen buyer")
    return 0


def report_metro_check(rows: list[dict], region: Region, metro: str) -> None:
    """How many rows' address city is not one of the metro's tile cities.

    Reported, never filtered: a Stafford or Webster address is in the Houston
    metro by any definition but not in this tile list, and a Katy query can
    equally surface a San Antonio chain's listing. A human reads the list.
    """
    cities = region.metro_cities(metro)
    outside: dict[str, int] = {}
    unparsed = 0
    for r in rows:
        city = r.get("address_city")
        if not city:
            unparsed += 1
        elif _fold_city(city) not in cities:
            outside[city] = outside.get(city, 0) + 1
    n_out = sum(outside.values())
    print(
        f"metro check ({metro}): {n_out} of {len(rows)} rows have an address city outside "
        f"the tile list, {unparsed} with no parseable city (kept, not dropped)"
    )
    for city, k in sorted(outside.items(), key=lambda kv: -kv[1])[:25]:
        print(f"   {k:>4}  {city}")


# --------------------------------------------------------------------------- #
# --website
# --------------------------------------------------------------------------- #


async def run_website(args) -> int:
    from leadscraper.sources.website import WebsiteSource

    rows = require_state(args.out)
    settings = get_settings()
    targets = [r for r in rows if r.get("website") and (args.force or "site" not in r)]
    print(f"{len(targets)} sites to crawl ({len(rows) - len(targets)} skipped)")

    with session_scope() as session:
        cache = FetchCache(session, settings)
        source = WebsiteSource(cache=cache, settings=settings, max_pages=5)
        client = source._new_client()
        try:
            for i, row in enumerate(targets, 1):
                crawl = await source.crawl(row["website"], client=client)
                await _crawl_provider_pages(source, crawl, cache, client)
                session.commit()
                row["site"] = _analyse_site(row, crawl, cache)
                save_state(args.out, rows)
                s = row["site"]
                print(
                    f"  [{i:>3}] pages={len(crawl.pages)} cache={crawl.from_cache} "
                    f"people={len(s['people'])} emails={len(s['emails'])} "
                    f"li={len(s['linkedin_urls'])} {row['name'][:40]}"
                    + (f"  !{s['error']}" if s.get("error") else ""),
                    flush=True,
                )
                if source.breaker.is_open():
                    print("  website source breaker open — stopping")
                    break
        finally:
            await client.aclose()
    return 0


async def _crawl_provider_pages(source, crawl, cache: FetchCache, client) -> None:
    """Follow the provider/team links §5.2's about-regex does not know about."""
    if not crawl.pages or crawl.stopped:
        return
    home = cache.get(crawl.pages[0].url)
    if home is None:
        return
    html = home.body.decode("utf-8", errors="replace")
    seen = {p.url.rstrip("/").lower() for p in crawl.pages}
    extra = 0
    for match in _PROVIDER_LINK_RE.finditer(html):
        from urllib.parse import urljoin

        url = urljoin(crawl.pages[0].url, match.group(1))
        if registrable_domain(url) != crawl.domain or url.rstrip("/").lower() in seen:
            continue
        seen.add(url.rstrip("/").lower())
        await asyncio.sleep(source.policy.next_delay())
        page = await source._fetch_page(crawl, url, client)
        if page is not None:
            crawl.pages.append(page)
            extra += 1
        if extra >= 2 or crawl.stopped:
            return


def _analyse_site(row: dict, crawl, cache: FetchCache) -> dict:
    people: list[Person] = []
    linkedin: list[str] = []
    emails: list[str] = []
    seen_people: set[str] = set()

    for page in crawl.pages:
        for block in page.jsonld:
            for name, key in block.people:
                cleaned = clean_person_name(name)
                if cleaned and cleaned[0].lower() not in seen_people:
                    seen_people.add(cleaned[0].lower())
                    people.append(
                        Person(
                            cleaned[0],
                            f"jsonld_{key}",
                            "site_jsonld",
                            page.url,
                            credentials=cleaned[1],
                        )
                    )
        for person in people_from_text(page.text, page.url):
            if person.name.lower() not in seen_people:
                seen_people.add(person.name.lower())
                people.append(person)
        for email in page.emails:
            if email.lower() not in emails:
                emails.append(email.lower())
        body = cache.get(page.url)
        if body is not None:
            for m in _LINKEDIN_RE.finditer(body.body.decode("utf-8", errors="replace")):
                url = f"https://www.linkedin.com/{m.group(1).lower()}/{m.group(2)}"
                if url not in linkedin:
                    linkedin.append(url)

    # A profile URL on the business's own site is the strongest LinkedIn join
    # there is: the business chose to publish it. The name is on LinkedIn,
    # which we do not fetch; the profile slug usually carries it
    # ("carolyn-treasure-md") and is recorded as an *inferred* name, because a
    # slug is a vanity string the person chose, not a record.
    for url in linkedin:
        if "/in/" in url:
            people.append(Person(name_from_slug(url), "linkedin_on_site", "site_linkedin", url))

    # The business's own name is not a person. "Derm Haven Founder Tina..."
    # yields "Derm Haven" as a founder at Derm Haven. Only a *prefix* of the
    # business name is dropped: "Tina Moussally" is also inside "Derm Haven
    # Tina Moussally MPAS", and she is exactly who we want.
    biz = (row.get("name") or "").lower().split()
    people = [
        p for p in people if not (p.name and biz[: len(p.name.split())] == p.name.lower().split())
    ]
    # A business-name prefix glued to a real name — "Intra-V Samer Faysal" at
    # Intra-V (Houston batch 2) — loses the prefix and keeps the person. With
    # fewer than two tokens left ("Gameday Clayton" at Gameday Men's Health,
    # batch 3) there is no full name to keep, and it is not a person.
    kept: list[Person] = []
    for p in people:
        tokens = p.name.split()
        k = 0
        while k < len(tokens) and k < len(biz) and tokens[k].lower() == biz[k]:
            k += 1
        if k and len(tokens) - k >= 2:
            p.name = " ".join(tokens[k:])
        elif k:
            continue
        kept.append(p)
    people = kept

    return {
        "pages": [p.url for p in crawl.pages],
        "from_cache": crawl.from_cache,
        "error": crawl.error,
        "people": [p.as_dict() for p in people],
        "emails": emails[:10],
        "linkedin_urls": linkedin[:5],
    }


# --------------------------------------------------------------------------- #
# --npi
# --------------------------------------------------------------------------- #

NPI_API = "https://npiregistry.cms.hhs.gov/api/"


async def run_npi(args) -> int:
    rows = require_state(args.out)
    settings = get_settings()
    spend = Spend()
    targets = [r for r in rows if args.force or "npi" not in r]
    print(f"{len(targets)} businesses to look up in NPPES")

    with session_scope() as session:
        cache = FetchCache(session, settings)
        async with new_client() as client:
            for i, row in enumerate(targets, 1):
                row["npi"] = await _npi_lookup(client, cache, spend, row)
                save_state(args.out, rows)
                n = row["npi"]
                flag = (
                    f"{n['join']:>7} {n['official']['first']} {n['official']['last']} "
                    f"({n['official']['title']})"
                    if n.get("matched")
                    else f"{'-':>7} candidates={n.get('candidates', 0)}"
                )
                print(f"  [{i:>3}] {flag[:60]:60} {row['name'][:36]}", flush=True)
    print(f"\nNPI calls live={spend.live} cached={spend.cached}")
    return 0


async def _npi_lookup(client, cache, spend, row: dict) -> dict:
    """Org (NPI-2) records whose name, DBA, phone or address matches this business."""
    short = short_name(row["name"] or "")
    queries = []
    state = region_of(row).state
    if len(short) >= 2:
        queries.append({"organization_name": f"{short}*", "state": state})
    if row.get("zip"):
        # A Manhattan zip holds more than the API's 200-row page, so page it;
        # the PC that files under the physician's name while trading as the
        # spa is only findable this way, and only the phone proves the join.
        for skip in (0, 200, 400):
            queries.append({"postal_code": row["zip"][:5], "state": state, "skip": skip})
    candidates: dict[str, dict] = {}
    for q in queries:
        params = {"version": "2.1", "enumeration_type": "NPI-2", "limit": 200, **q}
        url = f"{NPI_API}?{urlencode(params)}"
        status, payload, _ = await cached_json(client, cache, spend, "npi", url, delay=0.5)
        if status != 200 or not isinstance(payload, dict):
            continue
        results = payload.get("results") or []
        for rec in results:
            candidates[str(rec.get("number"))] = rec
        if "skip" in q and len(results) < 200:
            break

    # The first pass used token_set_ratio at 60 and matched "Beauty" to
    # "BEAUTY BY CHOICE LLC" (a prosthetics supplier) at 100 — a subset is a
    # perfect token-set match. Both sides are reduced to their distinguishing
    # tokens and compared with token_sort_ratio, which has no subset shortcut.
    best, join, best_score = None, None, 0
    for rec in candidates.values():
        basic = rec.get("basic") or {}
        names = [basic.get("organization_name") or ""] + [
            o.get("organization_name") or "" for o in rec.get("other_names") or []
        ]
        addresses = rec.get("addresses") or []
        phones = {digits(a.get("telephone_number")) for a in addresses} | {
            digits(basic.get("authorized_official_telephone_number"))
        }
        zips = {(a.get("postal_code") or "")[:5] for a in addresses}
        ratio = max(
            (int(token_sort_ratio(short.lower(), short_name(n).lower())) for n in names if n),
            default=0,
        )
        score, tier = 0, None
        if row.get("phone_digits") and row["phone_digits"] in phones:
            score, tier = 100 + ratio, "phone"
        elif row.get("zip") and row["zip"][:5] in zips and ratio >= 85 and len(short) >= 4:
            score, tier = 50 + ratio, "zip+name"
        elif ratio >= 95 and len(short) >= 6:
            score, tier = ratio, "name"
        if score > best_score:
            best, join, best_score = rec, tier, score

    result = {"queried": True, "candidates": len(candidates), "matched": best is not None}
    if best is not None:
        basic = best["basic"]
        result.update(
            join=join,
            npi=best.get("number"),
            org_name=basic.get("organization_name"),
            other_names=[o.get("organization_name") for o in best.get("other_names") or []],
            official={
                "first": basic.get("authorized_official_first_name"),
                "last": basic.get("authorized_official_last_name"),
                "title": basic.get("authorized_official_title_or_position"),
                "phone": basic.get("authorized_official_telephone_number"),
                "credential": basic.get("authorized_official_credential"),
            },
            taxonomies=[t.get("desc") for t in best.get("taxonomies") or []][:4],
            evidence_url=f"https://npiregistry.cms.hhs.gov/provider-view/{best.get('number')}",
        )
    return result


# --------------------------------------------------------------------------- #
# --dos
# --------------------------------------------------------------------------- #

DOS_SEARCH = (
    "https://apps.dos.ny.gov/PublicInquiryWeb/api/PublicInquiry/GetComplexSearchMatchingEntities"
)
DOS_ENTITY = "https://apps.dos.ny.gov/PublicInquiryWeb/api/PublicInquiry/GetEntityRecordByID"
DOS_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


async def run_dos(args) -> int:
    rows = require_state(args.out)
    settings = get_settings()
    spend = Spend()
    targets = [r for r in rows if args.force or "dos" not in r]
    skipped = [r for r in targets if not region_of(r).has_registry]
    if skipped:
        # No row gets a "dos" block: absent means "not looked up", which is the
        # truth. Writing {"matched": False} would read as "looked, not found".
        print(f"{len(skipped)} rows are in a region with no state registry — skipped")
        targets = [r for r in targets if region_of(r).has_registry]
    print(f"{len(targets)} businesses to look up at NY DOS")

    with session_scope() as session:
        cache = FetchCache(session, settings)
        async with new_client() as client:
            for i, row in enumerate(targets, 1):
                row["dos"] = await _dos_lookup(client, cache, spend, row)
                save_state(args.out, rows)
                d = row["dos"]
                if d.get("matched"):
                    who = d.get("ceo_name") or d.get("po_exec_name") or d.get("sop_name") or "-"
                    flag = f"{d['entity_type'][:12]:12} ceo={who[:28]}"
                else:
                    flag = f"{'-':12} candidates={d.get('candidates', 0)}"
                print(f"  [{i:>3}] {flag[:52]:52} {row['name'][:36]}", flush=True)
    print(f"\nDOS calls live={spend.live} cached={spend.cached}")
    return 0


async def _dos_lookup(client, cache, spend, row: dict) -> dict:
    short = short_name(row["name"] or "").upper()
    if len(short) < 2:
        return {"queried": False, "reason": "no_usable_name"}
    body = {
        "searchValue": short,
        "searchByTypeIndicator": "EntityName",
        "searchExpressionIndicator": "BeginsWith",
        "entityStatusIndicator": "AllStatuses",
        "entityTypeIndicator": [
            "Corporation",
            "LimitedLiabilityCompany",
            "LimitedPartnership",
            "LimitedLiabilityPartnership",
        ],
        "listPaginationInfo": {"listStartRecord": 1, "listEndRecord": 50},
    }
    status, payload, _ = await cached_json(
        client,
        cache,
        spend,
        "nydos",
        DOS_SEARCH,
        method="POST",
        headers=DOS_HEADERS,
        body=body,
        delay=1.5,
    )
    if status != 200 or not isinstance(payload, dict):
        return {"queried": True, "error": f"http_{status}"}
    matches = payload.get("entitySearchResultList") or []

    def rank(m: dict) -> tuple:
        # token_sort, not token_set: "Beso" is a perfect *subset* of "BESO AUTO
        # REPAIR LLC", and the first pass matched exactly that. Both sides are
        # reduced to their distinguishing tokens first.
        entity = short_name(m.get("entityName") or "")
        ratio = int(token_sort_ratio(short.lower(), entity.lower()))
        return (
            ratio >= 85 and len(short) >= 4,
            m.get("county") in NYC_COUNTIES,
            m.get("entityStatus") == "Active",
            ratio,
        )

    matches.sort(key=rank, reverse=True)
    best = matches[0] if matches and rank(matches[0])[0] else None
    result = {"queried": True, "candidates": len(matches), "matched": best is not None}
    if best is None:
        return result

    status, record, _ = await cached_json(
        client,
        cache,
        spend,
        "nydos",
        DOS_ENTITY,
        method="POST",
        headers=DOS_HEADERS,
        body={
            "SearchID": best["dosID"],
            "EntityName": best["entityName"],
            "AssumedNameFlag": "false",
        },
        delay=1.5,
    )
    if status != 200 or not isinstance(record, dict):
        result["error"] = f"entity_http_{status}"
        return result
    info = record.get("entityGeneralInfo") or {}

    def person(block: dict | None) -> str | None:
        name = ((block or {}).get("name") or "").strip()
        # The SOP/registered-agent slot is usually the entity itself, "THE
        # CORPORATION", or a formation service; only a *different* name that
        # is not an organisation is a person lead. "C/O Jane Doe" is one.
        name = re.sub(r"^C/O\s+", "", name, flags=re.IGNORECASE)
        if not name or name_ratio(name, best["entityName"]) >= 80:
            return None
        if re.search(
            r"\b(LLC|INC|CORP|CORPORATION|COMPANY|SERVICES?|AGENTS?|REGISTERED|LEGAL|"
            r"FILINGS?|HOLDINGS?|P\.?A\.?|P\.?C\.?|PLLC|THE)\b",
            name.upper(),
        ):
            return None
        return name

    result.update(
        dos_id=best["dosID"],
        entity_name=best["entityName"],
        entity_type=best.get("entityType"),
        entity_status=info.get("entityStatus"),
        county=best.get("county"),
        statement_status=info.get("statementStatus"),
        ceo_name=((record.get("ceo") or {}).get("name") or "").strip() or None,
        sop_name=person(record.get("sopAddress")),
        po_exec_name=person(record.get("poExecAddress")),
        agent_name=person(record.get("registeredAgent")),
        evidence_url=f"https://apps.dos.ny.gov/publicInquiry/EntityDisplay?dosId={best['dosID']}",
    )
    return result


# --------------------------------------------------------------------------- #
# --linkedin  (SERP, never LinkedIn itself)
# --------------------------------------------------------------------------- #

_LI_TITLE_SPLIT = re.compile(r"\s+[-–|]\s+")


# Who to write to, when a page names several people. Ownership first, then
# the physician who signs for the practice, then anyone else with a title.
_ROLE_ORDER = (
    "owner",
    "co-owner",
    "founder",
    "co-founder",
    "founded_by",
    "ceo",
    "president",
    "principal",
    "proprietor",
    "jsonld founder",
    "medical_director",
    "founding_physician",
    "clinical_director",
    "director",
    "lead_injector",
)


def _role_rank(role: str) -> int:
    key = role.lower().replace("jsonld_", "").replace(" ", "_")
    for i, r in enumerate(_ROLE_ORDER):
        if key.replace("_", "-") == r or key == r.replace("-", "_"):
            return i
    return len(_ROLE_ORDER)


# Evidence order (strongest record first) lives in ``icp.EVIDENCE_ORDER``: it
# breaks ties *within* an ICP verdict here, and ranks the Hunter spend plan.
_EVIDENCE_ORDER = icp.EVIDENCE_ORDER


def buyer_candidates(row: dict) -> list[icp.Candidate]:
    """Every person any stage recorded, each with its ICP buyer verdict.

    Nobody is dropped here (§10.1): a staff member Hunter listed and a
    service-of-process agent are candidates with a ``hard_stop`` or
    ``ambiguous`` verdict, kept so the CSV can show who was passed over and
    why. Records naming the same person are corroborated, so a Medical
    Director who is also the DOS CEO is the owner medical director §3 allows.
    """
    out: list[icp.Candidate] = []
    npi = row.get("npi") or {}
    if npi.get("matched"):
        o = npi.get("official") or {}
        if o.get("first") and o.get("last"):
            strong = npi.get("join") in ("phone", "zip+name")
            out.append(
                icp.Candidate(
                    f"{o['first'].title()} {o['last'].title()}",
                    "npi" if strong else "npi_name_only",
                    o.get("title") or "authorized official",
                    npi.get("evidence_url", ""),
                )
            )
    for p in (row.get("site") or {}).get("people") or []:
        if p.get("name"):
            out.append(icp.Candidate(p["name"], p["source"], p["role"], p["evidence_url"]))
    dos = row.get("dos") or {}
    for key in ("ceo_name", "po_exec_name", "sop_name"):
        if dos.get(key):
            out.append(
                icp.Candidate(
                    dos[key].title(),
                    f"dos_{key.removesuffix('_name')}",
                    None,
                    dos.get("evidence_url", ""),
                )
            )
    li = row.get("linkedin") or {}
    if li.get("matched") and li.get("person_name"):
        # The verdict is set here, with the business name, so the headline's
        # employer is checked against *this* business (icp: "Owner at
        # Brilliance Communications" is not the owner of Brilliance MedSpa).
        out.append(
            icp.Candidate(
                li["person_name"],
                "linkedin",
                li.get("headline"),
                li.get("url", ""),
                verdict=icp.qualify_buyer(
                    role=li.get("headline"), source="linkedin", business=row.get("name")
                ),
            )
        )
    email = row.get("email") or {}
    seen_hd: set[str] = set()
    if email.get("person") and email.get("person_source") == "hunter_domain":
        seen_hd.add(email["person"])
        out.append(icp.Candidate(email["person"], "hunter_domain", email.get("position")))
    for p in email.get("hunter_domain_people") or []:
        if p.get("name") and p["name"] not in seen_hd:
            seen_hd.add(p["name"])
            out.append(icp.Candidate(p["name"], "hunter_domain", p.get("position")))
    return icp.corroborate(out)


def _candidate_key(c: icp.Candidate) -> tuple[int, int, int]:
    source = _EVIDENCE_ORDER.index(c.source) if c.source in _EVIDENCE_ORDER else 99
    # Within a source, the economic buyer outranks the clinician: JECT's page
    # names its CEO after its medical director, and page order is not seniority.
    return (
        icp.verdict_rank(c.verdict.verdict if c.verdict else None),
        source,
        _role_rank(c.role or ""),
    )


def best_candidate(row: dict) -> icp.Candidate | None:
    """The person to put forward as the buyer, or None.

    **ICP verdict first, evidence order second.** Before qualification this
    walked sources in evidence order and took the first name it found, so a
    service-of-process agent or a Hunter-listed staff member became
    ``buyer_name`` whenever nothing ranked above it — measured at roughly half
    of the 82 named buyers. Now a qualified founder from any source beats an
    ambiguous record from a stronger one, and a ``hard_stop`` person is never
    chosen at all.
    """
    pool = [c for c in buyer_candidates(row) if icp.promotable(c)]
    return min(pool, key=_candidate_key) if pool else None


def best_person(row: dict) -> tuple[str, str] | None:
    """(name, source) of ``best_candidate`` — the shape every stage already uses."""
    c = best_candidate(row)
    return (c.name, c.source) if c else None


def serper_queue(rows: list[dict], args) -> list[dict]:
    """The rows ``--linkedin`` may spend Serper on, most useful first.

    Serper was the second budget of the four-key run (1,025 credits against
    Houston's ~1,000 for 855 rows). Once ``--qualify`` has run, only
    ``qualified`` accounts are searched — no Hunter credit can follow on the
    rest. Rows with no qualified buyer go first, biggest by reviews: LinkedIn
    is the only way they become Hunter-eligible. Rows that already have one
    follow; for them LinkedIn adds only the fallback URL a ``linkedin`` lead
    needs if Hunter misses. Rows left over keep no ``linkedin`` key, so a
    later run picks them up.
    """
    targets = [r for r in rows if args.force or "linkedin" not in r]
    if not targets or any("icp" not in r for r in targets):
        return targets
    queue = [r for r in targets if r["icp"]["account"]["verdict"] == icp.Verdict.QUALIFIED]
    print(f"skipping {len(targets) - len(queue)} rows whose account is not qualified")

    def key(r: dict) -> tuple:
        c = best_candidate(r)
        has_buyer = bool(c and c.verdict and c.verdict.verdict is icp.Verdict.QUALIFIED)
        reviews = r.get("review_count")
        return (has_buyer, reviews is None, -(reviews or 0))

    return sorted(queue, key=key)


async def run_linkedin(args) -> int:
    rows = require_state(args.out)
    settings = get_settings()
    if not settings.serp_api_key or settings.serp_provider != "serper":
        print("SERP_API_KEY (serper) is not set. Nothing to measure.")
        return 1
    spend = Spend()
    targets = serper_queue(rows, args)
    print(f"{len(targets)} SERP lookups")

    with session_scope() as session:
        cache = FetchCache(session, settings)
        async with new_client() as client:
            for i, row in enumerate(targets, 1):
                if args.serper_budget is not None and spend.live.get("serper", 0) >= (
                    args.serper_budget
                ):
                    print(f"  --serper-budget {args.serper_budget} spent — stopping")
                    break
                # A re-run must not anchor on its own previous answer.
                row.pop("linkedin", None)
                known = best_person(row)
                short = short_name(row["name"] or "")
                role_query = (
                    f'site:linkedin.com/in "{short}" '
                    f'(owner OR founder OR "medical director") "{region_of(row).label}"'
                )
                # Name-anchored first when a name is held — the join is then
                # true by construction if the title carries the business. The
                # first live pass showed that form returns nothing for most
                # names (the exact-phrase business name is too strict), so it
                # falls through to the role form rather than recording a miss.
                queries = [role_query]
                if known:
                    queries.insert(0, f'site:linkedin.com/in "{known[0]}" "{short}"')
                result, status = None, 200
                for query in queries:
                    status, payload, _ = await cached_json(
                        client,
                        cache,
                        spend,
                        "serper",
                        "https://google.serper.dev/search",
                        method="POST",
                        headers={
                            "X-API-KEY": settings.serp_api_key,
                            "Content-Type": "application/json",
                        },
                        body={"q": query, "gl": "us", "hl": "en", "num": 10},
                        delay=1.0,
                    )
                    if status not in (200, 0):
                        break
                    organic = (payload or {}).get("organic") or [] if status == 200 else []
                    result = _pick_profile(row, organic, query, known)
                    if result["matched"]:
                        break
                row["linkedin"] = result or {"matched": False, "hits": 0, "error": f"http_{status}"}
                save_state(args.out, rows)
                li = row["linkedin"]
                print(
                    f"  [{i:>3}] {li.get('anchored_on', '-')[:5]:5} hits={li['hits']:>2} "
                    f"{li.get('join') or '-':7} "
                    f"{(li.get('person_name') or '-')[:22]:22} "
                    f"{row['name'][:34]}",
                    flush=True,
                )
                if status not in (200, 0):
                    # A refusal (401/403/429) is the same for every later call;
                    # a 0 is our network, not theirs, and is worth continuing.
                    print("  serper refused — stopping")
                    break
    print(f"\nSERP calls live={spend.live} cached={spend.cached}")
    return 0


# Tokens of a business name that carry no identity. "Lake Medical Spa" is
# "lake" once these go; "SKINNEY Medspa" is "skinney".
_GENERIC_NAME_TOKENS = frozenset(
    re.findall(
        r"\w+",
        "spa med medspa medical the and of at in nyc new york ny upper east west side "
        "midtown park avenue ave st street inc llc pllc corp center centre clinic studio "
        "salon wellness health beauty skin skincare laser aesthetic aesthetics day "
        "massage nail nails hair body for men women best",
    )
)


def distinctive_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in _GENERIC_NAME_TOKENS]


def title_join(business: str, text: str) -> list[str]:
    """Which of the business's distinctive tokens appear in ``text``.

    The first live pass scored "Lake Medical Spa" → "Mike Lake, CEO" at 100,
    because a fuzzy ratio rewards the one token they share. A join needs two
    distinctive tokens, or one that is distinctive enough on its own (six
    characters: "skinney", "contōr", "trifecta" pass; "lake", "haven", "thai"
    do not).
    """
    lowered = text.lower()
    hits = [t for t in distinctive_tokens(business) if t in lowered]
    if len(hits) >= 2 or any(len(t) >= 6 for t in hits):
        return hits
    return []


def _pick_profile(row: dict, organic: list[dict], query: str, known) -> dict:
    best, best_rank = None, (0, 0)
    for hit in organic:
        link = hit.get("link") or ""
        if "linkedin.com/in/" not in link:
            continue
        title = hit.get("title") or ""
        parts = [p.strip() for p in _LI_TITLE_SPLIT.split(title) if p.strip()]
        parts = [p for p in parts if p.lower() != "linkedin"]
        person = parts[0] if parts else ""
        headline = " ".join(parts[1:])
        person_ok = not known or name_ratio(known[0], person) >= 85
        if not person_ok:
            continue
        in_title = title_join(row["name"] or "", headline)
        in_snippet = [] if in_title else title_join(row["name"] or "", hit.get("snippet") or "")
        join = "title" if in_title else ("snippet" if in_snippet else None)
        if join is None:
            continue
        rank = (2 if join == "title" else 1, len(in_title or in_snippet))
        if rank > best_rank:
            best_rank = rank
            best = {
                "url": link.split("?")[0],
                "title": title,
                "snippet": (hit.get("snippet") or "")[:200],
                "person_name": person if clean_person_name(person) else None,
                "headline": headline or None,
                "join": join,
                "join_tokens": in_title or in_snippet,
                "person_matches_known": bool(known),
            }
    result = {"query": query, "hits": len(organic), "anchored_on": known[1] if known else "role"}
    if best:
        result.update(best)
        # Only a title join counts as found. A snippet mention is recorded so
        # the report can say how much a looser rule would have added.
        result["matched"] = best["join"] == "title"
    else:
        result["matched"] = False
        if organic:
            result["top_unmatched"] = {
                "url": organic[0].get("link"),
                "title": organic[0].get("title"),
            }
    return result


# --------------------------------------------------------------------------- #
# --email  (the waterfall)
# --------------------------------------------------------------------------- #

HUNTER = "https://api.hunter.io/v2"
CONTACTOUT = "https://api.contactout.com/v1"
_GENERIC_LOCAL = {
    "info",
    "hello",
    "contact",
    "admin",
    "office",
    "support",
    "team",
    "booking",
    "bookings",
    "appointments",
    "frontdesk",
    "reception",
    "sales",
    "marketing",
    "care",
    "help",
    "inquiries",
    "enquiries",
    "concierge",
    "hi",
    "mail",
    "email",
}


def split_name(full: str) -> tuple[str, str]:
    # "Jennifer Chilek, MD" (a LinkedIn display name) would otherwise reach
    # Hunter as last_name="MD": credentials after a comma, and bare
    # credential tokens, are not a surname.
    full = _HONORIFIC_RE.sub("", full.split(",")[0])
    tokens = [
        t for t in full.replace(".", " ").split() if t and t.upper().strip("-") not in _CREDS_SET
    ]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], tokens[-1]


def personal_email_on_site(row: dict, person: str | None) -> str | None:
    """An address on the business's own site whose local part is the person."""
    emails = (row.get("site") or {}).get("emails") or []
    if not person:
        return None
    first, last = (t.lower() for t in split_name(person))
    for email in emails:
        local = email.split("@")[0].lower()
        if local in _GENERIC_LOCAL:
            continue
        if first and (local.startswith(first) or (last and last in local and local[0] == first[0])):
            return email
    return None


def linkedin_url_for(row: dict) -> str | None:
    urls = [u for u in (row.get("site") or {}).get("linkedin_urls") or [] if "/in/" in u]
    if urls:
        return urls[0]
    li = row.get("linkedin") or {}
    if not li.get("matched"):
        return None
    # The SERP profile belongs to a person with a role. A demoted one (Utah
    # batch 1: Degree Wellness's *franchise* owner) must not get a Prospeo
    # credit the buyer gate already refused them.
    if icp.qualify_buyer(role=li.get("headline")).verdict is icp.Verdict.HARD_STOP:
        return None
    return li.get("url")


# Vendors, in the order the waterfall tries them. Measured Sep 2026 (§8's
# vendor table); each sits where it does for a reason:
#
#   site_personal   free        an address the business itself published
#   tomba           name+domain sync, one call, and returns a LinkedIn URL too
#   hunter          name+domain the largest free allowance (50/mo)
#   snov            name+domain async, 49 credits, email only
#   prospeo         linkedin    100 credits, but email is often UNAVAILABLE
#   rocketreach     name+empl.  richest (personal + work), only 3 lookups/mo
#   hunter_domain   domain      last: returns *an* employee, not the owner
VENDOR_ORDER = ("tomba", "hunter", "snov", "prospeo", "rocketreach")

TOMBA = "https://api.tomba.io/v1"
SNOV_OAUTH = "https://api.snov.io/v1/oauth/access_token"
SNOV = "https://api.snov.io/v2"
PROSPEO = "https://api.prospeo.io"
ROCKETREACH = "https://api.rocketreach.co/api/v2"

# Statuses that mean "this vendor is done for the month", not "no data for this
# person". The difference is the whole point of the run: an exhausted vendor
# must stop being called, and must not be recorded as having found nothing.
_QUOTA_STATUSES = frozenset({401, 402, 403, 429})

# A 429 whose body says "per minute" is a throttle, not an exhausted plan.
_THROTTLE_RE = re.compile(r"rpm|per minute|requests? per|slow down|too fast", re.IGNORECASE)

# Seconds to leave between live calls to a vendor that throttles. Tomba's free
# plan allows 2 requests per minute; everything else is comfortable at 1s.
_VENDOR_DELAY = {"tomba": 31.0}


class Quota:
    """Which vendors are still answering, and why each one stopped."""

    def __init__(self, keys: dict[str, bool]) -> None:
        self.enabled = dict(keys)
        self.stopped: dict[str, str] = {}
        self.throttled: dict[str, int] = {}

    def live(self, vendor: str) -> bool:
        return self.enabled.get(vendor, False) and vendor not in self.stopped

    def note(self, vendor: str, status: int, body: str = "") -> bool:
        """Record a call's status. Returns True if the vendor just stopped.

        A 429 is two different facts wearing one status code, and the first
        run conflated them: Tomba's free plan throttles at **2 requests per
        minute** and says so ("Rate limit exceeded (rpm)"), while Hunter's and
        RocketReach's 429s mean the monthly allowance is gone. Stopping on the
        throttle retired Tomba after 3 calls with 24 of its 25 credits still
        unspent. A throttle is a reason to wait; only a quota is a reason to
        stop.
        """
        if status == 429 and _THROTTLE_RE.search(body):
            self.throttled[vendor] = self.throttled.get(vendor, 0) + 1
            return False
        if status in _QUOTA_STATUSES:
            self.stopped[vendor] = f"http_{status}"
            print(f"  ** {vendor} exhausted ({status}) {body[:90]}", flush=True)
            return True
        return False

    def summary(self) -> str:
        live = [v for v in self.enabled if self.live(v)]
        return f"live={live} stopped={self.stopped} throttled={self.throttled}"


async def snov_token(client, settings) -> str | None:
    """Snov is the only OAuth vendor; the token lasts an hour, so cache it."""
    if getattr(snov_token, "_cached", None):
        return snov_token._cached
    try:
        response = await client.post(
            SNOV_OAUTH,
            json={
                "grant_type": "client_credentials",
                "client_id": settings.snov_api_user_id,
                "client_secret": settings.snov_api_key,
            },
        )
        token = (response.json() or {}).get("access_token")
    except Exception as exc:  # noqa: BLE001 — a dead vendor is a finding
        print(f"  !! snov oauth {type(exc).__name__}: {str(exc)[:80]}")
        return None
    snov_token._cached = token
    return token


def hunter_key(settings, slot: int) -> str:
    """Slot 1 is ``HUNTER_API_KEY``; 2–4 are ``HUNTER_API_KEY_<n>``. Never printed."""
    return {
        1: settings.hunter_api_key,
        2: settings.hunter_api_key_2,
        3: settings.hunter_api_key_3,
        4: settings.hunter_api_key_4,
    }[slot]


def spendable_keys(
    keys: list[tuple[int, str]], balances: dict[int, dict | None]
) -> list[tuple[int, str]]:
    """Drop keys the live balance shows spent. San Antonio b2q opened on key
    3 at 0 searches and paid a 429 to learn it. An unknown balance is kept —
    Hunter's own 429 is still what ends a key."""
    return [
        (slot, key) for slot, key in keys if (balances.get(slot) or {}).get("searches_left", 1) > 0
    ]


def _hunter_slots(value: str) -> list[int]:
    """``"3,1,4,2"`` → ``[3, 1, 4, 2]``: distinct slots 1–4, order kept."""
    slots = [int(s) for s in value.split(",") if s.strip()]
    if not slots or any(s not in (1, 2, 3, 4) for s in slots) or len(set(slots)) != len(slots):
        raise argparse.ArgumentTypeError("distinct key slots from 1-4, e.g. 3,1,4,2")
    return slots


async def hunter_balance(client, key: str) -> dict | None:
    """Live searches/verifications left on one key, from the free ``/account``.

    Deliberately *not* through ``cached_json``: a balance is a fact about the
    account at this moment, the same reason a cached 402/429 is refetched.
    Replaying yesterday's balance is how a run plans spend it cannot make.
    """
    try:
        response = await client.get(f"{HUNTER}/account", params={"api_key": key})
        data = (response.json() or {}).get("data") or {}
    except Exception as exc:  # noqa: BLE001 — a dead vendor is a finding
        print(f"  !! hunter account {type(exc).__name__}: {str(exc)[:80]}")
        return None
    if response.status_code != 200 or not data:
        print(f"  !! hunter account HTTP {response.status_code}")
        return None
    req = data.get("requests") or {}
    s, v = req.get("searches") or {}, req.get("verifications") or {}
    return {
        "searches_left": (s.get("available") or 0) - (s.get("used") or 0),
        "searches": s.get("available"),
        "verifications_left": (v.get("available") or 0) - (v.get("used") or 0),
        "verifications": v.get("available"),
        "reset_date": data.get("reset_date"),
    }


@dataclass(slots=True)
class HunterSpend:
    """One run's Hunter keys, hard budget and the domains it has already called.

    The gate itself is ``icp.hunter_eligible`` (pure, pinned by tests); this
    holds the run state it needs — the budget and the domain set — so the
    dry-run plan and the live waterfall ask exactly the same question.

    ``keys`` is ``(slot, key)`` in spend order, soonest reset first: an unused
    search is lost at reset, so the expiring key goes first. ``rotate`` moves
    to the next one when Hunter reports the current one spent.
    """

    keys: list[tuple[int, str]]
    budget: int
    allow_domain_search: bool = False
    gate_all_metered: bool = False
    spent: int = 0
    domains: set[str] = field(default_factory=set)
    index: int = 0
    spent_by_slot: dict[int, int] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.keys[self.index][1] if self.keys else ""

    @property
    def slot(self) -> int:
        return self.keys[self.index][0] if self.keys else 0

    def rotate(self) -> bool:
        """Move to the next key. False when the last one is spent."""
        if self.index + 1 >= len(self.keys):
            return False
        self.index += 1
        return True

    def gate(self, row: dict, call: icp.HunterCall, *, already_found: bool = False):
        chosen = best_candidate(row)
        domain = row.get("domain")
        verdict = icp.hunter_eligible(
            call=call,
            account=row["icp"]["account"]["verdict"],
            buyer=chosen.verdict.verdict if chosen and chosen.verdict else None,
            buyer_name=chosen.name if chosen else None,
            own_domain=domain,
            already_found=already_found,
            domain_already_called=bool(domain and domain.lower() in self.domains),
            allow_domain_search=self.allow_domain_search,
        )
        if verdict.eligible and self.spent >= self.budget:
            return icp.HunterGate(False, f"--hunter-budget {self.budget} spent")
        return verdict

    def called(self, domain: str | None, *, live: bool) -> None:
        if domain:
            self.domains.add(domain.lower())
        if live:
            self.spent += 1
            self.spent_by_slot[self.slot] = self.spent_by_slot.get(self.slot, 0) + 1


async def hunter_get(
    client, cache, spend, quota: Quota, hs: HunterSpend, path: str, params: dict, cache_key: str
):
    """One Hunter call, moved to the next key when the current one is spent.

    ``params`` and ``cache_key`` exclude the key on purpose: a cached "not
    found" is a fact about the query, so rotation never re-pays for one. A
    429/402 is a fact about the *key* — ``cached_json`` already refuses to
    replay it — so the same query is retried on the next key, and the row is
    answered rather than recorded as a miss. Hunter stops for the run only when
    the last key is spent.
    """
    while True:
        status, payload, cached = await cached_json(
            client,
            cache,
            spend,
            "hunter",
            f"{HUNTER}/{path}?{urlencode({**params, 'api_key': hs.key})}",
            cache_key=cache_key,
        )
        if cached:
            return status, payload, cached
        stopped = quota.note("hunter", status, json.dumps(payload)[:120] if payload else "")
        if stopped and hs.rotate():
            quota.stopped.pop("hunter", None)
            print(f"  ** hunter: switching to key slot {hs.slot}", flush=True)
            continue
        return status, payload, cached


def row_priority(row: dict, chosen: icp.Candidate | None) -> str | None:
    """§3's tier from the stored account block and the *current* buyer, so a
    buyer that changed after --qualify (a new LinkedIn match) is ranked as it
    is now, not as it was."""
    a = row["icp"]["account"]
    account = icp.AccountVerdict(
        icp.Verdict(a["verdict"]),
        tuple(a.get("reasons") or ()),
        tuple(a.get("services") or ()),
        bool(a.get("multi_location")),
    )
    return icp.priority(account, chosen.verdict if chosen else None)[0]


def hunter_order(row: dict) -> tuple:
    chosen = best_candidate(row)
    return icp.hunter_rank(
        priority=row_priority(row, chosen),
        evidence_sources=[chosen.source, *chosen.corroborated_by] if chosen else [],
        review_count=row.get("review_count"),
    )


def print_spend_plan(targets: list[dict], hs: HunterSpend) -> None:
    """Every row that will get a Hunter call, in the order it gets one.

    A simulation over a copy of the run state, so the plan and the live run
    apply one gate. Only Tomba can change it live: a Tomba hit on a planned
    row frees that slot for the next eligible row below the line.
    """
    sim = HunterSpend(hs.keys, hs.budget, hs.allow_domain_search)
    planned: list[tuple[dict, icp.HunterCall]] = []
    waiting: list[dict] = []
    skipped: dict[str, int] = {}
    free = 0
    for r in targets:
        chosen = best_candidate(r)
        if chosen and personal_email_on_site(r, chosen.name):
            free += 1
            continue
        call = icp.HunterCall.FINDER if chosen else icp.HunterCall.DOMAIN_SEARCH
        g = sim.gate(r, call)
        if g.eligible:
            sim.called(r.get("domain"), live=True)
            planned.append((r, call))
        elif g.reason.startswith("--hunter-budget"):
            waiting.append(r)
        else:
            skipped[g.reason] = skipped.get(g.reason, 0) + 1

    slots = ",".join(str(slot) for slot, _ in hs.keys)
    print(f"\n=== HUNTER SPEND PLAN — key slots {slots}, budget {hs.budget} ===")
    print(f"  {len(planned)} calls planned; {free} rows already have a personal site email")
    print(f"  {'#':>3} pri {'buyer':24} {'role':22} {'source':12} {'domain':26} rev  business")
    for i, (r, call) in enumerate(planned, 1):
        c = best_candidate(r)
        role = (c.role or "").replace("jsonld_", "").replace("_", " ") if c else "-"
        src = c.source + ("+" if c and c.corroborated_by else "") if c else "-"
        who = c.name if c else "[domain search]"
        print(
            f"  {i:>3} {row_priority(r, c) or '-':>3} {who[:24]:24} "
            f"{role[:22]:22} {src[:12]:12} {(r.get('domain') or '-')[:26]:26} "
            f"{r.get('review_count') if r.get('review_count') is not None else '?':>4} "
            f"{r['name'][:34]}" + ("" if call is icp.HunterCall.FINDER else "  (domain search)")
        )
    if waiting:
        print(
            f"\n  {len(waiting)} more eligible rows wait below the budget line "
            "(they move up only if Tomba answers a planned row):"
        )
        for r in waiting[:10]:
            c = best_candidate(r)
            print(
                f"      {(c.name if c else '-')[:24]:24} {(r.get('domain') or '-')[:26]:26} "
                f"{r['name'][:34]}"
            )
    print("\n  rows the gate refused, by reason:")
    for why, k in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"    {k:>4}  {why}")


async def run_email(args) -> int:
    rows = require_state(args.out)
    settings = get_settings()
    slots = args.hunter_keys or [args.hunter_key]
    keys = [(slot, hunter_key(settings, slot)) for slot in slots]
    for slot, key in keys:
        if not key:
            print(f"  hunter key slot {slot}: not set in .env")
    keys = [(slot, key) for slot, key in keys if key]
    quota = Quota(
        {
            "tomba": bool(settings.tomba_api_key and settings.tomba_api_secret),
            "hunter": bool(keys),
            "snov": bool(settings.snov_api_user_id and settings.snov_api_key),
            "prospeo": bool(settings.prospeo_api_key),
            "rocketreach": bool(settings.rocketreach_api_key),
        }
    )
    if not any(quota.enabled.values()):
        print("No vendor keys set.")
        return 1
    spend = Spend()
    targets = email_queue(rows, args)
    if targets is None:
        return 1
    print(f"{len(targets)} businesses; vendors {quota.summary()}")

    budget = args.hunter_budget
    balances: dict[int, dict | None] = {}
    async with new_client() as client:
        for slot, key in keys:
            balances[slot] = await hunter_balance(client, key)
    for slot, _ in keys:
        balance = balances[slot]
        if balance is None:
            print(f"  hunter key slot {slot}: balance unavailable")
            continue
        print(
            f"  hunter key slot {slot}: {balance['searches_left']}/"
            f"{balance['searches']} searches, {balance['verifications_left']}/"
            f"{balance['verifications']} verifications left, resets {balance['reset_date']}"
        )
        # Not capped by the balance: Hunter charges a search only when the
        # finder returns an address (Houston batch 1: 12 calls, 3 searches
        # charged). Capping calls at searches-left stopped spend at roughly a
        # quarter of the allowance. The budget caps *calls*; Hunter's own
        # quota answer (429/402 → rotate, then Quota.stopped) ends a key.
        if balance["searches_left"] <= 0:
            print(f"  hunter key slot {slot} has no searches left — skipped this run")
    if any(b is None for b in balances.values()) and not args.dry_run:
        print("  refusing a live run without a known Hunter balance on every key")
        return 1
    keys = spendable_keys(keys, balances)
    hs = HunterSpend(
        keys,
        budget,
        allow_domain_search=args.allow_domain_search,
        gate_all_metered=args.gate_all_metered,
    )

    if args.dry_run:
        with_name = sum(1 for r in targets if best_person(r) and r.get("domain"))
        with_li = sum(1 for r in targets if linkedin_url_for(r))
        print(f"  name+domain (tomba/hunter/snov/rocketreach): {with_name}")
        print(f"  linkedin url (prospeo): {with_li}")
        print_spend_plan(targets, hs)
        return 0

    with session_scope() as session:
        cache = FetchCache(session, settings)
        async with new_client() as client:
            for i, row in enumerate(targets, 1):
                old = row.get("email") or {}
                new = await _email_waterfall(client, cache, spend, quota, settings, row, hs)
                if not new.get("email") and any(
                    a.get("status") == 0 for a in new.get("attempts") or []
                ):
                    # A vendor call that never connected is not "no email".
                    # The first Utah run lost DNS for 17 rows mid-queue —
                    # the *best* 17, it being a priority queue — and recorded
                    # each as searched-and-missed while spending the credits
                    # on the rows below. Leave the row untried and stop.
                    if not old:
                        row.pop("email", None)
                    save_state(args.out, rows)
                    print(
                        f"\n  network failure at business {i}/{len(targets)} "
                        f"({row['name'][:40]}) — stopping; row left untried"
                    )
                    break
                # Evidence only moves up. A retry that finds nothing must not
                # erase the address or the domain-search people an earlier run
                # recorded — those people are buyer candidates now.
                if old.get("email") and not new.get("email"):
                    new = old
                elif old.get("hunter_domain_people") and not new.get("hunter_domain_people"):
                    new["hunter_domain_people"] = old["hunter_domain_people"]
                row["email"] = new
                save_state(args.out, rows)
                e = row["email"]
                print(
                    f"  [{i:>3}] {(e.get('source') or '-'):16} "
                    f"{(e.get('email') or '-')[:32]:32} {row['name'][:28]}",
                    flush=True,
                )
                if not any(quota.live(v) for v in VENDOR_ORDER):
                    print(f"\n  all vendors exhausted at business {i}/{len(targets)}")
                    break
                if args.until_hunter_exhausted and (
                    not quota.live("hunter") or hs.spent >= hs.budget
                ):
                    print(f"\n  hunter exhausted at business {i}/{len(targets)} — stopping")
                    break
    print(f"\nemail calls live={spend.live} cached={spend.cached}")
    print(
        f"hunter: {hs.spent} live calls of a {hs.budget} budget, by key slot "
        f"{hs.spent_by_slot} (ended on slot {hs.slot})"
    )
    print(f"vendors {quota.summary()}")
    return 0


def email_queue(rows: list[dict], args) -> list[dict] | None:
    """The rows ``--email`` may spend on, best first. None if unqualified.

    Qualification must run first — this refuses rather than falling back to
    the old file order, because the old order is how a credit got spent on a
    dentist. **Only ``qualified`` accounts are queued** — operator decision,
    30 Sep 2026: credits are never spent on ambiguous rows. ``ambiguous`` and
    ``unknown`` accounts wait for a human; ``hard_stop`` ones never come back.
    """
    unqualified = [r["name"] for r in rows if "icp" not in r]
    if unqualified:
        print(
            f"{len(unqualified)} rows have no ICP verdict (e.g. {unqualified[0]!r}). "
            "Run --qualify first; --email will not spend credits on unscreened rows."
        )
        return None

    def wanted(r: dict) -> bool:
        if args.force:
            return True
        if args.retry_missing:
            # The backlog: waterfall ran, no address came back. Cheap to
            # re-walk — every vendor answer that was a real "not found" replays
            # from cache, and only the calls that hit an exhausted quota go live.
            return "email" not in r or not (r.get("email") or {}).get("email")
        return "email" not in r

    held = {"hard_stop": 0, "not_qualified": 0}
    queue: list[dict] = []
    for r in rows:
        # ``domain`` was fixed at --discover time; re-derive it so a platform
        # host added to the list since then cannot be searched as a business.
        r["domain"] = business_domain(r.get("website"))
        if not wanted(r):
            continue
        account = r["icp"]["account"]["verdict"]
        if account == icp.Verdict.HARD_STOP:
            held["hard_stop"] += 1
            continue
        if account != icp.Verdict.QUALIFIED:
            held["not_qualified"] += 1
            continue
        queue.append(r)

    static = HunterSpend([], budget=10**9, allow_domain_search=args.allow_domain_search)

    def key(r: dict) -> tuple:
        # Hunter-eligible rows first, in spend order (priority, evidence,
        # size), so the budget lands on the top of the list; everything
        # else after, in the old verdict order, for the free and other steps.
        c = best_candidate(r)
        if static.gate(r, icp.HunterCall.FINDER).eligible:
            return (0, *hunter_order(r))
        if static.gate(r, icp.HunterCall.DOMAIN_SEARCH).eligible:
            return (1, *hunter_order(r))
        return (
            2,
            *icp.queue_key(
                r["icp"]["account"]["verdict"],
                c.verdict.verdict if c and c.verdict else None,
                own_domain=bool(r.get("domain")),
            ),
            0,
        )

    queue.sort(key=key)  # stable: file order breaks ties
    print(
        f"queue {len(queue)}; held back {held['hard_stop']} hard-stop and "
        f"{held['not_qualified']} ambiguous/unknown accounts (no credits on those)"
    )
    return queue


def contactout_profile(payload) -> dict:
    """The profile block, or empty when the key is a sandbox key.

    Measured live: an API key issued from the extension's account answers every
    query with HTTP 200 and a canned "Example Person" whose email is
    ``email1@example.com``, prefixed with "This is a sample response. To unlock
    full access, please book a call with our sales team". A 200 is not data.
    """
    if not isinstance(payload, dict):
        return {}
    if "sample response" in (payload.get("message") or "").lower():
        return {"sandbox": True}
    return payload.get("profile") or {}


async def _email_waterfall(client, cache, spend, quota, settings, row, hs: HunterSpend) -> dict:
    person = best_person(row)
    domain = row.get("domain")
    li_url = linkedin_url_for(row)
    first, last = split_name(person[0]) if person else ("", "")
    attempts: list[dict] = []
    result: dict = {
        "person": person[0] if person else None,
        "person_source": person[1] if person else None,
    }

    def done(source: str, email: str, extra: dict | None = None) -> dict:
        result.update(email=email, source=source, attempts=attempts, **(extra or {}))
        return result

    def note(source: str, status: int, found: bool, **extra) -> None:
        attempts.append({"source": source, "status": status, "found": found, **extra})

    # ---------------------------------------------------- 0. the site itself
    if person:
        hit = personal_email_on_site(row, person[0])
        if hit:
            return done("site_personal", hit)

    named = bool(person and first and last and domain)

    # The Hunter gate's buyer and account conditions, applied to the other
    # metered vendors too when the operator asks (--gate-all-metered). Off by
    # default: the 7 Oct instruction was about Hunter, and widening it is the
    # operator's call. The domain and budget conditions are Hunter's own.
    metered = True
    if hs.gate_all_metered:
        chosen = best_candidate(row)
        g = icp.hunter_eligible(
            call=icp.HunterCall.FINDER,
            account=row["icp"]["account"]["verdict"],
            buyer=chosen.verdict.verdict if chosen and chosen.verdict else None,
            buyer_name=chosen.name if chosen else None,
            own_domain=domain,
            already_found=False,
            domain_already_called=False,
        )
        if not g.eligible:
            metered = False
            attempts.append({"source": "metered", "skipped": g.reason})
    named = named and metered
    li_url = li_url if metered else None

    # ---------------------------------------------------- 1. Tomba
    if named and quota.live("tomba"):
        params = urlencode({"domain": domain, "first_name": first, "last_name": last})
        data: dict = {}
        status = 0
        for attempt in range(2):
            status, payload, cached = await cached_json(
                client,
                cache,
                spend,
                "tomba",
                f"{TOMBA}/email-finder?{params}",
                headers={
                    "X-Tomba-Key": settings.tomba_api_key,
                    "X-Tomba-Secret": settings.tomba_api_secret,
                },
                delay=_VENDOR_DELAY["tomba"],
            )
            data = (payload or {}).get("data") or {} if isinstance(payload, dict) else {}
            if cached:
                break
            body = json.dumps(payload)[:120] if payload else ""
            quota.note("tomba", status, body)
            if status == 429 and _THROTTLE_RE.search(body) and attempt == 0:
                # Wait out the per-minute window rather than burn the vendor.
                await asyncio.sleep(_VENDOR_DELAY["tomba"])
                continue
            break
        note("tomba", status, bool(data.get("email")), score=data.get("score"))
        if data.get("email"):
            return done(
                "tomba",
                data["email"],
                {
                    "score": data.get("score"),
                    "verification": (data.get("verification") or {}).get("status"),
                    "vendor_linkedin": data.get("linkedin"),
                    "vendor_position": data.get("position"),
                    "email_pattern": data.get("pattern"),
                    "accept_all": data.get("accept_all"),
                },
            )

    # ---------------------------------------------------- 2. Hunter
    # The gate, not the queue order, decides whether this row gets a call;
    # the reason is recorded either way so the CSV can be audited.
    hunter_gate = hs.gate(row, icp.HunterCall.FINDER) if person else None
    if hunter_gate is not None and not hunter_gate.eligible and quota.live("hunter"):
        attempts.append({"source": "hunter", "skipped": hunter_gate.reason})
    if named and quota.live("hunter") and hunter_gate is not None and hunter_gate.eligible:
        status, payload, cached = await hunter_get(
            client,
            cache,
            spend,
            quota,
            hs,
            "email-finder",
            {"domain": domain, "first_name": first, "last_name": last},
            f"{HUNTER}/email-finder?domain={domain}&first_name={first}&last_name={last}",
        )
        data = (payload or {}).get("data") or {} if isinstance(payload, dict) else {}
        if status:  # a call that never connected spent nothing
            hs.called(domain, live=not cached)
        note("hunter", status, bool(data.get("email")), score=data.get("score"))
        if data.get("email"):
            return done(
                "hunter",
                data["email"],
                {
                    "score": data.get("score"),
                    "verification": (data.get("verification") or {}).get("status"),
                },
            )

    # ---------------------------------------------------- 3. Snov (async)
    if named and quota.live("snov"):
        token = await snov_token(client, settings)
        if not token:
            quota.stopped["snov"] = "no_token"
        else:
            headers = {"Authorization": f"Bearer {token}"}
            body = {"rows": [{"first_name": first, "last_name": last, "domain": domain}]}
            status, payload, cached = await cached_json(
                client,
                cache,
                spend,
                "snov",
                f"{SNOV}/emails-by-domain-by-name/start",
                method="POST",
                headers=headers,
                body=body,
            )
            task = ((payload or {}).get("data") or {}).get("task_hash")
            if not cached:
                quota.note("snov", status, json.dumps(payload)[:120] if payload else "")
            emails: list[dict] = []
            if task:
                # The task is queued; poll until it leaves "in_progress".
                for _ in range(8):
                    await asyncio.sleep(2.0)
                    rstatus, rpayload, _c = await cached_json(
                        client,
                        cache,
                        spend,
                        "snov",
                        f"{SNOV}/emails-by-domain-by-name/result?task_hash={task}",
                        headers=headers,
                        delay=0.0,
                    )
                    state = (rpayload or {}).get("status") if rpayload else None
                    if state == "completed":
                        for block in (rpayload or {}).get("data") or []:
                            emails.extend(block.get("result") or [])
                        break
                    if rstatus != 200:
                        break
            valid = [e for e in emails if e.get("smtp_status") == "valid"]
            note("snov", status, bool(valid))
            if valid:
                return done(
                    "snov", valid[0]["email"], {"verification": valid[0].get("smtp_status")}
                )

    # ---------------------------------------------------- 4. Prospeo, by URL
    if li_url and quota.live("prospeo"):
        status, payload, cached = await cached_json(
            client,
            cache,
            spend,
            "prospeo",
            f"{PROSPEO}/enrich-person",
            method="POST",
            headers={"X-KEY": settings.prospeo_api_key, "Content-Type": "application/json"},
            body={"data": {"linkedin_url": li_url}},
        )
        profile = (payload or {}).get("person") or {} if isinstance(payload, dict) else {}
        block = profile.get("email") or {}
        company = (payload or {}).get("company") or {} if isinstance(payload, dict) else {}
        if not cached and status != 400:
            # 400 here is NO_MATCH — a fact about the person, not the quota.
            quota.note("prospeo", status, json.dumps(payload)[:120] if payload else "")
        # Prospeo follows LinkedIn's *current* job, which for one control was a
        # membership body rather than the business. An address is only accepted
        # when the company it came back with is the domain we asked about.
        vendor_site = (company.get("website") or "") if company else ""
        same_company = not domain or not vendor_site or domain in vendor_site
        note(
            "prospeo",
            status,
            bool(block.get("email")),
            email_status=block.get("status"),
            company=vendor_site[:60],
            company_matches=same_company,
        )
        if block.get("email") and same_company:
            return done(
                "prospeo",
                block["email"],
                {
                    "verification": block.get("status"),
                    "vendor_position": profile.get("current_job_title"),
                },
            )

    # ---------------------------------------------------- 5. RocketReach
    if named and quota.live("rocketreach"):
        params = urlencode({"name": person[0], "current_employer": row.get("name") or ""})
        status, payload, cached = await cached_json(
            client,
            cache,
            spend,
            "rocketreach",
            f"{ROCKETREACH}/person/lookup?{params}",
            headers={"Api-Key": settings.rocketreach_api_key},
        )
        if not cached:
            quota.note("rocketreach", status, json.dumps(payload)[:120] if payload else "")
        found = (payload or {}).get("emails") or [] if isinstance(payload, dict) else []
        person_id = (payload or {}).get("id") if isinstance(payload, dict) else None
        if not found and person_id and (payload or {}).get("status") == "progress":
            for _ in range(5):
                await asyncio.sleep(3.0)
                _s, poll, _c = await cached_json(
                    client,
                    cache,
                    spend,
                    "rocketreach",
                    f"{ROCKETREACH}/person/lookup?id={person_id}",
                    headers={"Api-Key": settings.rocketreach_api_key},
                    delay=0.0,
                )
                found = (poll or {}).get("emails") or [] if isinstance(poll, dict) else []
                if found:
                    payload = poll
                    break
        professional = [e for e in found if e.get("type") == "professional"]
        note("rocketreach", status, bool(found), emails=len(found))
        if professional or found:
            best = (professional or found)[0]
            return done(
                "rocketreach",
                best["email"],
                {
                    "verification": best.get("smtp_valid"),
                    "grade": best.get("grade"),
                    "all_emails": [e["email"] for e in found][:4],
                    "vendor_linkedin": (payload or {}).get("linkedin_url"),
                    "vendor_position": (payload or {}).get("current_title"),
                },
            )

    # ------------------------------------- 6. Hunter domain search, no name
    # Off unless --allow-domain-search: Utah spent 32 calls here for 1 email.
    domain_gate = hs.gate(row, icp.HunterCall.DOMAIN_SEARCH) if not person else None
    if domain_gate is not None and not domain_gate.eligible and quota.live("hunter"):
        attempts.append({"source": "hunter_domain", "skipped": domain_gate.reason})
    if (
        not person
        and domain
        and quota.live("hunter")
        and domain_gate is not None
        and domain_gate.eligible
    ):
        status, payload, cached = await hunter_get(
            client,
            cache,
            spend,
            quota,
            hs,
            "domain-search",
            {"domain": domain, "limit": 10},
            f"{HUNTER}/domain-search?domain={domain}",
        )
        if status:
            hs.called(domain, live=not cached)
        data = (payload or {}).get("data") or {} if isinstance(payload, dict) else {}
        people = [
            {
                "name": f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip(),
                "email": e.get("value"),
                "position": e.get("position"),
                "confidence": e.get("confidence"),
            }
            for e in data.get("emails") or []
            if e.get("first_name") and e.get("last_name")
        ]
        note("hunter_domain", status, bool(people), people=len(people))
        result["hunter_domain_people"] = people[:5]
        if people:
            people.sort(
                key=lambda p: (
                    bool(
                        re.search(
                            r"owner|founder|ceo|director|president", (p["position"] or "").lower()
                        )
                    ),
                    p["confidence"] or 0,
                ),
                reverse=True,
            )
            return done(
                "hunter_domain",
                people[0]["email"],
                {
                    "person": people[0]["name"],
                    "person_source": "hunter_domain",
                    "position": people[0]["position"],
                },
            )

    result.update(email=None, source=None, attempts=attempts)
    return result


# --------------------------------------------------------------------------- #
# --qualify  (MedSpa/ research prompt §3; no network)
# --------------------------------------------------------------------------- #


def run_qualify(args) -> int:
    """Write an ``icp`` block per row: account verdict, buyer verdict, priority.

    The service menu comes from re-parsing the pages ``--website`` already
    stored — ``ignore_ttl=True`` is §2's re-parse path, so a sample crawled
    more than 30 days ago still qualifies without a single request. Re-runnable
    at will; it only ever rewrites its own block.
    """
    from leadscraper.core.webparse import parse_page

    rows = require_state(args.out)
    settings = get_settings()
    locations = icp.locations_by_domain(r.get("domain") for r in rows)
    split: dict[str, int] = {}
    buyers: dict[str, int] = {}
    tiers: dict[str, int] = {}
    unread = 0

    with session_scope() as session:
        cache = FetchCache(session, settings)
        for row in rows:
            pages = (row.get("site") or {}).get("pages") or []
            texts: list[str] = []
            for url in pages:
                hit = cache.get(url, ignore_ttl=True)
                if hit is not None:
                    texts.append(parse_page(url, hit.body, hit.content_type).text)
            if pages and not texts:
                unread += 1
            evidence = icp.service_evidence(" ".join(texts))
            account = icp.qualify_account(
                category=row.get("category"),
                name=row.get("name"),
                evidence=evidence,
                locations=locations.get((row.get("domain") or "").lower()),
            )
            people = buyer_candidates(row)
            chosen = best_candidate(row)
            tier, tier_why = icp.priority(account, chosen.verdict if chosen else None)
            row["icp"] = {
                "account": {
                    "verdict": account.verdict.value,
                    "reasons": list(account.reasons),
                    "services": list(account.evidence),
                    "multi_location": account.multi_location,
                    "pages_read": len(texts),
                },
                "buyer": (
                    {
                        "name": chosen.name,
                        "source": chosen.source,
                        "verdict": chosen.verdict.verdict.value,
                        "reasons": list(chosen.verdict.reasons),
                    }
                    if chosen and chosen.verdict
                    else None
                ),
                # Everyone, including the demoted — §10.1, and the operator's
                # audit trail for "why wasn't X the buyer?".
                "people": [
                    {
                        "name": c.name,
                        "source": c.source,
                        "role": c.role,
                        "verdict": c.verdict.verdict.value if c.verdict else None,
                        "reason": c.verdict.reason if c.verdict else "",
                    }
                    for c in people
                ],
                "priority": tier,
                "priority_reason": tier_why,
            }
            split[account.verdict.value] = split.get(account.verdict.value, 0) + 1
            b = chosen.verdict.verdict.value if chosen and chosen.verdict else "none"
            buyers[b] = buyers.get(b, 0) + 1
            tiers[tier or "-"] = tiers.get(tier or "-", 0) + 1

    save_state(args.out, rows)
    n = len(rows)
    print(f"{n} rows qualified from cache  ({unread} with pages recorded but none cached)")
    print(f"  account: {dict(sorted(split.items(), key=lambda kv: icp.verdict_rank(kv[0])))}")
    print(f"  buyer:   {buyers}")
    print(f"  priority:{tiers}")
    by_cat: dict[tuple[str, str], int] = {}
    for r in rows:
        k = (r.get("category") or "?", r["icp"]["account"]["verdict"])
        by_cat[k] = by_cat.get(k, 0) + 1
    print("  by category:")
    for (cat, v), k in sorted(by_cat.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {k:>3}  {v:10} {cat}")

    # §5.5, applied to a filter: a screen that passes nothing has not screened,
    # it has failed. Every NYC sample is majority "Medical spa" by construction.
    if not split.get(icp.Verdict.QUALIFIED):
        print("\n!! DEFECT: zero QUALIFIED accounts. This is not a clean run.")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# --report
# --------------------------------------------------------------------------- #


def run_report(args) -> int:
    rows = require_state(args.out)
    n = len(rows)

    def count(pred) -> int:
        return sum(1 for r in rows if pred(r))

    def pct(k: int) -> str:
        return f"{k:>3} / {n}  ({100 * k / n:>3.0f}%)"

    label = region_of(rows[0]).label
    print(f"\n{'=' * 78}\nMED SPA RECON — {n} businesses, {label}\n{'=' * 78}")
    print(f"  with website               {pct(count(lambda r: r.get('website')))}")
    print(f"  with phone                 {pct(count(lambda r: r.get('phone_digits')))}")

    print("\n--- a NAMED person, by source (a business can count in several) ---")

    def site_people(r: dict, src: str) -> list[dict]:
        people = (r.get("site") or {}).get("people") or []
        return [p for p in people if p["source"] == src and p["name"]]

    def _site_links_profile(r: dict) -> bool:
        return any("/in/" in u for u in (r.get("site") or {}).get("linkedin_urls") or [])

    print(f"  site JSON-LD founder/…     {pct(count(lambda r: site_people(r, 'site_jsonld')))}")
    print(f"  site text pattern          {pct(count(lambda r: site_people(r, 'site_text')))}")
    print(f"  site links a LinkedIn /in/ {pct(count(_site_links_profile))}")
    npi_m = count(lambda r: (r.get("npi") or {}).get("matched"))
    npi_strong = count(lambda r: (r.get("npi") or {}).get("join") in ("phone", "zip+name"))
    print(f"  NPI authorized official    {pct(npi_m)}   strong join (phone/zip) {npi_strong}")
    joins: dict[str, int] = {}
    for r in rows:
        j = (r.get("npi") or {}).get("join")
        if j:
            joins[j] = joins.get(j, 0) + 1
    if joins:
        print(f"      join tiers: {joins}")
    dos_m = count(lambda r: (r.get("dos") or {}).get("matched"))
    dos_ceo = count(lambda r: (r.get("dos") or {}).get("ceo_name"))
    dos_other = count(
        lambda r: (r.get("dos") or {}).get("po_exec_name") or (r.get("dos") or {}).get("sop_name")
    )
    print(
        f"  NY DOS entity matched      {pct(dos_m)}   "
        f"with CEO name {dos_ceo}, other person {dos_other}"
    )
    types: dict[str, int] = {}
    for r in rows:
        t = (r.get("dos") or {}).get("entity_type")
        if t:
            types[t] = types.get(t, 0) + 1
    if types:
        print(f"      entity types: {dict(sorted(types.items(), key=lambda kv: -kv[1]))}")
    print(
        f"  SERP LinkedIn profile      "
        f"{pct(count(lambda r: (r.get('linkedin') or {}).get('matched')))}"
    )
    print(
        f"  Hunter domain-search person"
        f"{pct(count(lambda r: (r.get('email') or {}).get('hunter_domain_people')))}"
    )
    named = count(lambda r: best_person(r) is not None)
    print(f"\n  ** ANY named person         {pct(named)} **")
    by_src: dict[str, int] = {}
    for r in rows:
        p = best_person(r)
        if p:
            by_src[p[1]] = by_src.get(p[1], 0) + 1
    print(f"      first-choice source: {dict(sorted(by_src.items(), key=lambda kv: -kv[1]))}")
    print(f"  any LinkedIn URL (site or SERP) {pct(count(lambda r: linkedin_url_for(r)))}")

    print("\n--- an EMAIL, by winning source ---")
    srcs: dict[str, int] = {}
    for r in rows:
        s = (r.get("email") or {}).get("source")
        if s:
            srcs[s] = srcs.get(s, 0) + 1
    for s, k in sorted(srcs.items(), key=lambda kv: -kv[1]):
        print(f"  {s:26} {pct(k)}")
    emailed = count(lambda r: (r.get("email") or {}).get("email"))
    both = count(lambda r: (r.get("email") or {}).get("email") and best_person(r))
    tried = count(lambda r: "email" in r)
    print(f"\n  ** email found              {pct(emailed)} **   (waterfall run on {tried})")
    print(f"  ** NAME + EMAIL = a lead    {pct(both)} **")
    gmailish = count(
        lambda r: re.search(
            r"@(gmail|yahoo|hotmail|outlook|icloud|aol)\.",
            (r.get("email") or {}).get("email") or "",
        )
    )
    print(f"     of which personal-domain {gmailish}")

    print(f"\n{'-' * 78}\nper business\n{'-' * 78}")
    for r in rows:
        p = best_person(r)
        e = r.get("email") or {}
        li = "L" if linkedin_url_for(r) else "-"
        npi = (r.get("npi") or {}).get("join") or "-"
        print(
            f"  {li} npi={npi:8} {(p[0] if p else '-')[:24]:24} {(p[1] if p else ''):12} "
            f"{(e.get('email') or '-')[:30]:30} {(r['name'] or '')[:30]}"
        )
    return 0


# --------------------------------------------------------------------------- #
# --csv
# --------------------------------------------------------------------------- #

CSV_COLUMNS = (
    "business",
    "maps_category",
    "address",
    "zip",
    "phone",
    "website",
    "rating",
    "review_count",
    "buyer_name",
    "buyer_role",
    "buyer_credentials",
    "buyer_source",
    "buyer_evidence_url",
    "buyer_confidence",
    "linkedin_url",
    "linkedin_headline",
    "email",
    "email_person",
    "email_source",
    "email_score",
    "email_verification",
    "other_people",
    "dos_entity",
    "dos_entity_type",
    "npi_official",
    "maps_url",
    # MedSpa/ §3. Appended, so every column a reader already knows keeps its
    # position.
    "account_verdict",
    "account_reason",
    "buyer_verdict",
    "buyer_reason",
    "icp_priority",
    # Texas, Oct 2026. Appended like the ICP columns. ``metro`` is the metro
    # whose query found the row; ``address_city`` lets a reader see the ones
    # Maps surfaced from just outside it.
    "metro",
    "address_city",
    # Why Hunter was or was not called on this row — the gate's audit trail.
    "hunter_gate",
)

# §8's honesty about tiers, applied to what this spike can actually show. A
# government record or the business's own structured markup is `linked`; a
# name next to a title in page text or a SERP title is `co_occurring`; a person
# Hunter lists at the domain is `inferred` — they work there, nothing says
# they own it.
_SOURCE_CONFIDENCE = {
    "npi": "linked",
    "site_jsonld": "linked",
    "dos_ceo": "linked",
    "dos_sop": "co_occurring",
    "dos_po_exec": "co_occurring",
    "site_text": "co_occurring",
    "site_linkedin": "inferred",
    "linkedin": "co_occurring",
    "npi_name_only": "inferred",
    "hunter_domain": "inferred",
}


def _buyer_details(row: dict, name: str, source: str, role: str | None = None) -> dict:
    """Role, credentials and the URL that proves the name, for the chosen source."""
    if source == "hunter_domain":
        # The candidate's own position. The email block's ``position`` belongs
        # to whoever Hunter's address is for, which is often someone else.
        return {"role": role or "", "credentials": "", "url": ""}
    site = row.get("site") or {}
    if source in ("site_jsonld", "site_text"):
        for p in site.get("people") or []:
            if p["name"] == name and p["source"] == source:
                return {
                    "role": p["role"].replace("jsonld_", "").replace("_", " "),
                    "credentials": p.get("credentials") or "",
                    "url": p["evidence_url"],
                }
    if source.startswith("dos"):
        dos = row.get("dos") or {}
        role = {"dos_ceo": "CEO (biennial statement)", "dos_sop": "service-of-process name"}
        return {
            "role": role.get(source, source),
            "credentials": "",
            "url": dos.get("evidence_url", ""),
        }
    if source.startswith("npi"):
        npi = row.get("npi") or {}
        o = npi.get("official") or {}
        return {
            "role": o.get("title") or "authorized official",
            "credentials": o.get("credential") or "",
            "url": npi.get("evidence_url", ""),
        }
    if source == "linkedin":
        li = row.get("linkedin") or {}
        return {"role": li.get("headline") or "", "credentials": "", "url": li.get("url", "")}
    if source == "hunter_domain":
        e = row.get("email") or {}
        return {"role": e.get("position") or "", "credentials": "", "url": ""}
    return {"role": "", "credentials": "", "url": ""}


def _hunter_gate_column(email: dict) -> str:
    """``called (finder)`` / ``skipped: buyer ambiguous`` / blank if --email never ran."""
    for a in email.get("attempts") or []:
        if a.get("source") in ("hunter", "hunter_domain"):
            kind = "finder" if a["source"] == "hunter" else "domain search"
            return f"skipped: {a['skipped']}" if a.get("skipped") else f"called ({kind})"
    if email.get("source") in ("site_personal", "tomba"):
        return f"not needed: {email['source']} found it"
    return ""


def csv_row(row: dict) -> dict:
    """One business as a ``CSV_COLUMNS`` dict — shared by --csv and --master."""
    chosen = best_candidate(row)
    name, source = (chosen.name, chosen.source) if chosen else ("", "")
    details = _buyer_details(row, name, source, chosen.role) if chosen else {}
    li = row.get("linkedin") or {}
    email = row.get("email") or {}
    dos = row.get("dos") or {}
    npi = row.get("npi") or {}
    account = (row.get("icp") or {}).get("account") or {}
    # Everyone not chosen, with the verdict that passed them over —
    # demoted, never deleted (§10.1).
    others = []
    seen_others: set[str] = set()
    for c in buyer_candidates(row):
        label = f"{c.name}|{c.source}"
        if c.name == name or label in seen_others:
            continue
        seen_others.add(label)
        role = (c.role or c.source).replace("jsonld_", "").replace("_", " ")
        v = c.verdict.verdict.value if c.verdict else "?"
        others.append(f"{c.name} ({role[:40]}; {c.source}; {v})")
    tier = (row.get("icp") or {}).get("priority")
    official = npi.get("official") or {}
    return {
        "business": row.get("name") or "",
        "maps_category": row.get("category") or "",
        "address": row.get("address") or "",
        "zip": row.get("zip") or "",
        "phone": row.get("phone_raw") or "",
        "website": row.get("website") or "",
        "rating": row.get("rating") if row.get("rating") is not None else "",
        "review_count": row.get("review_count") if row.get("review_count") is not None else "",
        "buyer_name": name,
        "buyer_role": details.get("role", ""),
        "buyer_credentials": details.get("credentials", ""),
        "buyer_source": source,
        "buyer_evidence_url": details.get("url", ""),
        "buyer_confidence": _SOURCE_CONFIDENCE.get(source, "") if source else "",
        "linkedin_url": linkedin_url_for(row) or "",
        "linkedin_headline": li.get("headline") or "" if li.get("matched") else "",
        "email": email.get("email") or "",
        # Whose address it is. Hunter's domain search returns a staff
        # member when the owner is not indexed, so this can differ from
        # buyer_name, and the row must say so rather than imply a join.
        "email_person": email.get("person") or "",
        "email_source": email.get("source") or "",
        "email_score": email.get("score") if email.get("score") is not None else "",
        "email_verification": email.get("verification") or "",
        "other_people": "; ".join(others),
        "dos_entity": dos.get("entity_name") or "" if dos.get("matched") else "",
        "dos_entity_type": dos.get("entity_type") or "" if dos.get("matched") else "",
        "npi_official": (
            f"{official.get('first', '')} {official.get('last', '')} ({official.get('title', '')})"
            if npi.get("matched")
            else ""
        ),
        "maps_url": row.get("maps_url") or "",
        # Blank, not "unknown", when --qualify has not run: the
        # column is recording that no one screened this row.
        "account_verdict": account.get("verdict") or "",
        "account_reason": "; ".join(account.get("reasons") or []),
        "buyer_verdict": (chosen.verdict.verdict.value if chosen and chosen.verdict else ""),
        "buyer_reason": chosen.verdict.reason if chosen and chosen.verdict else "",
        "icp_priority": tier or "",
        "metro": row.get("metro") or "",
        "address_city": row.get("address_city") or "",
        "hunter_gate": _hunter_gate_column(email),
    }


def run_csv(args) -> int:
    import csv

    rows = require_state(args.out)
    path = args.out.with_suffix(".csv")
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(csv_row(row))
    named = sum(1 for r in rows if best_person(r))
    emailed = sum(1 for r in rows if (r.get("email") or {}).get("email"))
    screened = sum(1 for r in rows if "icp" in r)
    print(
        f"{len(rows)} rows, {named} with a buyer name, {emailed} with an email, "
        f"{screened} ICP-screened -> {path.resolve()}"
    )
    return 0


# --------------------------------------------------------------------------- #
# --master  (Texas, 29 Oct 2026: one list the operator sends from)
# --------------------------------------------------------------------------- #

MASTER_COLUMNS = (*CSV_COLUMNS, "batch", "lead_tier")
_EMAIL_FIELDS = ("email", "email_person", "email_source", "email_score", "email_verification")


def is_accept_all(email: dict) -> bool:
    """The domain accepts any address, so *this* one is unconfirmed.

    Hunter says so in ``verification``; Tomba also carries a boolean. Operator
    rule, 29 Oct 2026: an accept-all address never reaches the master list,
    whatever its score.
    """
    status = str(email.get("verification") or "").strip().lower().replace("-", "_")
    return status in {"accept_all", "catch_all"} or email.get("accept_all") is True


def is_rejected(email: dict) -> bool:
    """The mail server refused this address — it will bounce.

    Not in the 29 Oct rule's words, which name accept-all; within its intent
    ("… whether these are below 80 or other reason"). San Antonio b1 produced
    the first one: RocketReach, ``smtp_valid: "invalid"``.
    """
    status = str(email.get("verification") or "").strip().lower()
    return status in {"invalid", "undeliverable", "rejected"}


def unstorable(email: dict) -> bool:
    """An address that must never reach the master list."""
    return is_accept_all(email) or is_rejected(email)


def master_row(row: dict, batch: str) -> dict | None:
    """The master-list row for one business, or None if it is not a lead.

    ``email``: an address that is neither accept-all nor rejected.
    ``linkedin``: otherwise, a qualified buyer's LinkedIn URL. An unstorable
    address on a ``linkedin`` row is blanked here and only here — it stays in
    the batch CSV and the state file (§10.1: never discard).
    """
    d = csv_row(row)
    email = row.get("email") or {}
    if d["email"] and not unstorable(email):
        tier = "email"
    elif d["linkedin_url"] and d["buyer_verdict"] == icp.Verdict.QUALIFIED.value:
        tier = "linkedin"
        if d["email"]:
            d.update(dict.fromkeys(_EMAIL_FIELDS, ""))
    else:
        return None
    d.update(batch=batch, lead_tier=tier)
    return d


def _master_keys(d: dict) -> list[tuple]:
    keys: list[tuple] = []
    if d.get("maps_url"):
        keys.append(("maps", d["maps_url"]))
    domain = registrable_domain(d["website"]) if d.get("website") else None
    if domain and d.get("buyer_name"):
        keys.append(("buyer", domain.lower(), d["buyer_name"].casefold()))
    return keys


def merge_master(existing: list[dict], new: list[dict]) -> dict[str, int]:
    """Append ``new`` to ``existing`` in place; returns what happened.

    Deduped on ``maps_url``, then on (website domain, buyer name). The one
    rewrite allowed is an upgrade: a row present as ``linkedin`` that now
    qualifies as ``email`` is replaced where it stands. Evidence only moves up,
    so an ``email`` row is never replaced by a ``linkedin`` one.
    """
    index: dict[tuple, int] = {}
    for i, d in enumerate(existing):
        for k in _master_keys(d):
            index.setdefault(k, i)
    stats = {"email": 0, "linkedin": 0, "upgraded": 0, "already_present": 0}
    for d in new:
        hit = next((index[k] for k in _master_keys(d) if k in index), None)
        if hit is not None:
            if existing[hit]["lead_tier"] == "linkedin" and d["lead_tier"] == "email":
                existing[hit] = d
                stats["upgraded"] += 1
            else:
                stats["already_present"] += 1
            continue
        existing.append(d)
        for k in _master_keys(d):
            index.setdefault(k, len(existing) - 1)
        stats[d["lead_tier"]] += 1
    return stats


def run_master(args) -> int:
    import csv
    import shutil
    from datetime import datetime

    rows = require_state(args.out)
    # medspa_tx_houston_b3q.json → "b3q"; the metro column says which city.
    batch = args.batch or args.out.stem.rsplit("_", 1)[-1]
    path: Path = args.master_file
    existing: list[dict] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if tuple(reader.fieldnames or ()) != MASTER_COLUMNS:
                print(f"{path} has a different header from MASTER_COLUMNS; refusing to write")
                return 1
            existing = list(reader)
    before = len(existing)
    new = [d for d in (master_row(r, batch) for r in rows) if d is not None]
    found = [r["email"] for r in rows if (r.get("email") or {}).get("email")]
    accept_all = sum(1 for e in found if is_accept_all(e))
    rejected = sum(1 for e in found if is_rejected(e) and not is_accept_all(e))
    stats = merge_master(existing, new)
    leaked = sum(1 for d in existing if unstorable({"verification": d["email_verification"]}))
    tiers: dict[str, int] = {}
    for d in existing:
        tiers[d["lead_tier"]] = tiers.get(d["lead_tier"], 0) + 1
    print(
        f"batch {batch!r}: {len(rows)} rows → {len(new)} leads "
        f"({accept_all} accept-all and {rejected} rejected addresses kept off the list); {stats}"
    )
    print(f"master: {before} → {len(existing)} rows, by tier {tiers}")
    if leaked:
        print(f"  !! {leaked} accept-all/rejected rows would be on the master; refusing to write")
        return 1
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    if path.exists():
        backups = args.out.parent / "master_backups"
        backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backups / f"{path.stem}.{datetime.now():%Y%m%d_%H%M%S}.csv")
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=MASTER_COLUMNS)
        writer.writeheader()
        writer.writerows(existing)
    tmp.replace(path)
    print(f"-> {path.resolve()}")
    return 0


# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag, help_ in (
        ("--discover", "Stage 1 Maps over Manhattan tiles × med-spa synonyms"),
        ("--website", "crawl each site; names, emails, LinkedIn links"),
        ("--npi", "NPPES organisation records → authorized official"),
        ("--dos", "NY DOS entity record → CEO / principal"),
        ("--linkedin", "Serper site:linkedin.com/in lookup"),
        ("--qualify", "ICP verdicts per row from cached pages (no network)"),
        ("--email", "vendor waterfall, qualified rows first; needs --qualify"),
        ("--slice", "cut a batch from a discovery pool (--out) into --into"),
        ("--buyers", "print every chosen buyer with its evidence, for eyeballing"),
        ("--report", "print the yields"),
        ("--csv", "write the sample as one row per business, with provenance"),
        ("--master", "append the batch's email/linkedin leads to --master-file"),
    ):
        mode.add_argument(flag, action="store_true", help=help_)
    parser.add_argument("--tiles", type=int, default=3)
    parser.add_argument("--synonyms", type=int, default=2)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--seed", type=int, default=9)
    parser.add_argument("--force", action="store_true", help="redo a stage already recorded")
    parser.add_argument(
        "--dry-run", action="store_true", help="--email: count calls, spend nothing"
    )
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="--email: re-walk rows whose waterfall found no address (the backlog)",
    )
    parser.add_argument(
        "--until-hunter-exhausted",
        action="store_true",
        help="--email: stop as soon as Hunter reports its allowance spent",
    )
    parser.add_argument(
        "--region",
        choices=sorted(REGIONS),
        default="ny",
        help="--discover: which region's tiles to search (stored on each row)",
    )
    parser.add_argument(
        "--metro",
        default=None,
        help="--discover: one metro of a region that has them (tx: houston); stored per row",
    )
    parser.add_argument(
        "--hunter-key",
        type=int,
        choices=(1, 2, 3, 4),
        default=1,
        help="--email: which HUNTER_API_KEY slot to spend (1 = HUNTER_API_KEY)",
    )
    parser.add_argument(
        "--hunter-keys",
        type=_hunter_slots,
        default=None,
        help="--email: key slots in spend order, soonest reset first (e.g. 3,1,4,2); "
        "rotates to the next when one is spent. Overrides --hunter-key",
    )
    parser.add_argument(
        "--hunter-budget",
        type=int,
        default=25,
        help="--email: hard cap on live Hunter calls this run (also capped by the balance)",
    )
    parser.add_argument(
        "--allow-domain-search",
        action="store_true",
        help="--email: permit Hunter domain search on qualified rows with no buyer (off: "
        "Utah measured 32 calls for 1 email)",
    )
    parser.add_argument(
        "--gate-all-metered",
        action="store_true",
        help="--email: apply the Hunter gate's account/buyer rules to Tomba, Snov, "
        "Prospeo and RocketReach as well",
    )
    parser.add_argument("--into", type=Path, help="--slice: the batch file to write")
    parser.add_argument("--size", type=int, default=80, help="--slice: rows per batch")
    parser.add_argument(
        "--category", default="Medical spa", help="--slice: the Maps category to keep"
    )
    parser.add_argument(
        "--serper-budget",
        type=int,
        default=None,
        help="--linkedin: stop after this many live Serper calls (credits)",
    )
    parser.add_argument(
        "--master-file",
        type=Path,
        default=Path("../texas_medspa_leads_master.csv"),
        help="--master: the list to append to (never rewritten from scratch)",
    )
    parser.add_argument(
        "--batch", default=None, help="--master: batch label (default: --out's last _ part)"
    )
    parser.add_argument("--out", type=Path, default=Path("./data/spike/medspa_ny.json"))
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="--discover: a state file whose businesses must not reappear in this sample",
    )
    args = parser.parse_args()

    if args.discover:
        return asyncio.run(run_discover(args))
    if args.website:
        return asyncio.run(run_website(args))
    if args.npi:
        return asyncio.run(run_npi(args))
    if args.dos:
        return asyncio.run(run_dos(args))
    if args.linkedin:
        return asyncio.run(run_linkedin(args))
    if args.qualify:
        return run_qualify(args)
    if args.email:
        return asyncio.run(run_email(args))
    if args.csv:
        return run_csv(args)
    if args.master:
        return run_master(args)
    if args.slice:
        return run_slice(args)
    if args.buyers:
        return run_buyers(args)
    return run_report(args)


if __name__ == "__main__":
    sys.exit(main())

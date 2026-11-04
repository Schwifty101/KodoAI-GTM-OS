"""ICP qualification — ``MedSpa/``'s account and buyer gates, as pure functions.

The research prompt (``Med-Spa-Touch-1-Research-Master-Prompt.md`` §3, and the
operating guide's §5 Stage 2) is written for a person researching **one prospect
at a time**. This module automates only the *screening* that happens before
that: a dentist, a massage parlour, or a service-of-process agent should never
reach a human's attention or an email credit, because the ICP already excludes
them.

Two verdicts, deliberately never merged into one score:

* ``qualify_account`` — is this business a med spa / day spa / wellness spa /
  cosmetic dermatology / aesthetics group whose aesthetics line is material?
* ``qualify_buyer`` — does this person control communications, booking, data or
  integrations? Founder, co-founder, owner, CEO, president, COO, executive
  director, or an **owner** medical director.

A business can pass and its only named person fail, or the reverse; merging the
two would hide which half needs work.

**Four verdicts, not a boolean.** ``UNKNOWN`` is not ``HARD_STOP``: "we have no
category and no crawled text" and "this is a dentist" are different facts, and
the operator who reviews the queue must be able to tell them apart. CLAUDE.md's
"missing data stays missing" applies to a verdict exactly as it applies to a
review count.

**Every verdict carries its reasons as text** (``"maps_category=Dentist"``,
``"role=service-of-process name"``), because the ICP requires evidence
classification and a rejection nobody can audit is a rejection nobody can fix.

**The category map is a measurement, not a list of guesses** (Sep 2026, see
implementation.md §8's ICP note). 200 NYC businesses' cached pages were
re-parsed for aesthetics-service vocabulary before a line of this was written,
and the counts beside each class below are from that pass. The handoff's
prior — that "Massage spa" and "Massage therapist" were ambiguous and needed a
service-menu check — was wrong: **0 of 21** with crawled text mentioned a single
aesthetics service. They are stops.

Pure: no DB, no network. The caller re-parses the cached pages (§7) and hands
this module text; it never fetches anything itself.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

# --------------------------------------------------------------------------- #
# Verdicts
# --------------------------------------------------------------------------- #


class Verdict(StrEnum):
    QUALIFIED = "qualified"
    AMBIGUOUS = "ambiguous"
    HARD_STOP = "hard_stop"
    UNKNOWN = "unknown"


# Best first. Used to pick between records and to order the email queue — a
# ranking, never a score: "ambiguous" is not "half qualified".
VERDICT_ORDER: Final[tuple[Verdict, ...]] = (
    Verdict.QUALIFIED,
    Verdict.AMBIGUOUS,
    Verdict.UNKNOWN,
    Verdict.HARD_STOP,
)


def verdict_rank(verdict: Verdict | str | None) -> int:
    """0 for ``qualified`` … 3 for ``hard_stop``; a missing verdict ranks as unknown."""
    try:
        return VERDICT_ORDER.index(Verdict(verdict)) if verdict else 2
    except ValueError:
        return 2


# --------------------------------------------------------------------------- #
# Service evidence — the menu, read off already-crawled pages
# --------------------------------------------------------------------------- #

# The vocabulary a med spa's own pages use for the services that make it one.
# "Injectable" terms are split out because they are the strongest single
# marker: 46 of the 53 "Medical spa" businesses with crawled text mention one,
# against 0 of 21 massage businesses.
INJECTABLE_TERMS: Final[dict[str, str]] = {
    "botox": r"\bbotox",
    "dysport": r"\bdysport",
    "xeomin": r"\bxeomin",
    "neurotoxin": r"\bneuro-?toxins?\b|\bneuromodulators?\b",
    "filler": r"\bfillers?\b",
    "juvederm": r"\bjuv[eé]derm",
    "restylane": r"\brestylane",
    "sculptra": r"\bsculptra",
    "kybella": r"\bkybella",
    "injectables": r"\binjectables?\b",
}
DEVICE_AND_SKIN_TERMS: Final[dict[str, str]] = {
    "microneedling": r"\bmicro-?needling",
    "morpheus8": r"\bmorpheus\s*8",
    "prp": r"\bprp\b|\bplatelet[- ]rich",
    "coolsculpting": r"\bcool\s*sculpt",
    "emsculpt": r"\bemsculpt",
    "laser": r"\blasers?\b",
    "ipl": r"\bipl\b",
    "chemical_peel": r"\bchemical\s+peels?\b",
    "hydrafacial": r"\bhydra\s*facials?\b",
    "iv_therapy": r"\biv\s+(?:therapy|drips?|infusions?)\b",
    "medical_weight_loss": r"\bsemaglutide|\btirzepatide|\bglp-?1\b|\bmedical\s+weight\s+loss",
}
# Evidence of a *different* business. Only ever used against the aesthetics
# count, to tell "a spa that also does Botox" from "a med spa".
MASSAGE_PATTERN: Final[str] = (
    r"\bmassages?\b|\breflexology\b|\bshiatsu\b|\bswedish\b|\bdeep\s+tissue\b"
)

_INJECTABLE_RE = {k: re.compile(v, re.IGNORECASE) for k, v in INJECTABLE_TERMS.items()}
_DEVICE_RE = {k: re.compile(v, re.IGNORECASE) for k, v in DEVICE_AND_SKIN_TERMS.items()}
_MASSAGE_RE = re.compile(MASSAGE_PATTERN, re.IGNORECASE)

# Below this, a "page" is a JavaScript shell. Equinox's three spa pages parse to
# **1 character** each; treating that as "we read the menu and found nothing"
# would turn an unread page into evidence.
MIN_TEXT_CHARS: Final[int] = 200
MIN_MASSAGE_MENU: Final[int] = 3


@dataclass(frozen=True, slots=True)
class ServiceEvidence:
    """What the crawled pages say the business sells. Counts are mentions."""

    terms: tuple[str, ...]
    injectable_mentions: int
    aesthetic_mentions: int  # injectables + devices/skin, all mentions
    massage_mentions: int
    chars: int

    @property
    def has_aesthetics(self) -> bool:
        return bool(self.terms)

    @property
    def strong_aesthetics(self) -> bool:
        """An injectable, or three distinct aesthetic services.

        "Laser" alone is not strong: a vein clinic and a LASIK surgeon both say
        it. Three distinct services is a menu, not a stray word.
        """
        return self.injectable_mentions > 0 or len(self.terms) >= 3

    @property
    def massage_menu(self) -> bool:
        """Enough massage vocabulary to be a menu rather than a stray word.

        The massage businesses measured at 3–186 mentions; "EuroStyle SkinCare"
        and "Medmom Beauty Studio" had one each and are not massage houses.
        A single mention is not positive evidence of a different business.
        """
        return self.massage_mentions >= MIN_MASSAGE_MENU

    @property
    def massage_dominant(self) -> bool:
        """More massage vocabulary than aesthetics vocabulary — the ICP's
        "aesthetics is a minor add-on" case, as far as text can show it."""
        return self.massage_mentions > self.aesthetic_mentions

    def describe(self) -> str:
        terms = ",".join(self.terms) if self.terms else "none"
        return (
            f"services={terms} (injectable×{self.injectable_mentions}, "
            f"aesthetic×{self.aesthetic_mentions}, massage×{self.massage_mentions})"
        )


def service_evidence(text: str | None) -> ServiceEvidence | None:
    """Scan page text for the aesthetics menu. ``None`` when there is no text.

    ``None`` is not "no services": it is "we did not read a menu", which is
    what a site that was never crawled or a JavaScript shell both are.
    """
    if not text or len(text.strip()) < MIN_TEXT_CHARS:
        return None
    terms: list[str] = []
    injectable = aesthetic = 0
    for key, rx in _INJECTABLE_RE.items():
        hits = len(rx.findall(text))
        if hits:
            terms.append(key)
            injectable += hits
            aesthetic += hits
    for key, rx in _DEVICE_RE.items():
        hits = len(rx.findall(text))
        if hits:
            terms.append(key)
            aesthetic += hits
    return ServiceEvidence(
        terms=tuple(sorted(terms)),
        injectable_mentions=injectable,
        aesthetic_mentions=aesthetic,
        massage_mentions=len(_MASSAGE_RE.findall(text)),
        chars=len(text),
    )


# --------------------------------------------------------------------------- #
# The category map
# --------------------------------------------------------------------------- #


class CategoryClass(StrEnum):
    # Is the ICP by definition. Evidence is recorded, never required.
    CORE = "core"
    # An aesthetics business in all likelihood; the menu confirms it.
    PROBABLE = "probable"
    # Could be either; the menu decides, and must outweigh any massage menu.
    AMBIGUOUS = "ambiguous"
    # "X-only" stops (§3: plastic-surgery-only, unrelated wellness). An
    # aesthetics menu lifts one to AMBIGUOUS — never to QUALIFIED, because that
    # is exactly the "minor add-on" question the operator has to answer.
    CONDITIONAL_STOP = "conditional_stop"
    # Not an aesthetics business whatever its site says. A dentist who offers
    # Botox is still a dentist; the operator's own example.
    STOP = "stop"


# Maps' category strings, casefolded. Counts are from the Sep 2026 re-parse of
# both NYC samples (200 businesses): "n with crawled text / n mentioning any
# aesthetics service / n mentioning an injectable".
CATEGORY_CLASSES: Final[dict[str, CategoryClass]] = {
    # 53 / 49 / 46. The four with text and no term are longevity/IV clinics or
    # JavaScript sites; the category carries them.
    "medical spa": CategoryClass.CORE,
    "med spa": CategoryClass.CORE,
    # 21 / 17 / 11
    "skin care clinic": CategoryClass.PROBABLE,
    # 14 / 14 / 3 — laser hair removal *is* an aesthetics service line
    "laser hair removal service": CategoryClass.PROBABLE,
    "hair removal service": CategoryClass.PROBABLE,
    # 9 / 4 / 4 — half are facial studios with no clinical menu
    "facial spa": CategoryClass.PROBABLE,
    # 3 / 2 / 2
    "dermatologist": CategoryClass.PROBABLE,
    "cosmetic dermatologist": CategoryClass.PROBABLE,
    "esthetics service": CategoryClass.PROBABLE,
    "permanent make-up clinic": CategoryClass.PROBABLE,
    # Named by §3 as in scope, but 3 / 1 / 0 here: all three read as massage
    # houses. In scope by the ICP's words; the menu has to show it.
    "day spa": CategoryClass.PROBABLE,
    "health spa": CategoryClass.PROBABLE,
    "wellness spa": CategoryClass.PROBABLE,
    # 9 / 5 / 3 — the genuinely mixed bucket: Rachel Med Spa and FILD Studio
    # are med spas, Thai New York Spa and Wildflower Spa are massage.
    "spa": CategoryClass.AMBIGUOUS,
    "wellness center": CategoryClass.AMBIGUOUS,
    "medical clinic": CategoryClass.AMBIGUOUS,
    "medical office": CategoryClass.AMBIGUOUS,
    "health and beauty shop": CategoryClass.AMBIGUOUS,
    # 12 / 0 / 0 and 9 / 0 / 0 — measured, and not ambiguous at all.
    "massage spa": CategoryClass.CONDITIONAL_STOP,
    "massage therapist": CategoryClass.CONDITIONAL_STOP,
    "reflexologist": CategoryClass.CONDITIONAL_STOP,
    "acupuncture clinic": CategoryClass.CONDITIONAL_STOP,
    # §3's "plastic-surgery-only" is the stop; a surgical practice running an
    # injectables line (Cosmetic Surgery Associates, 48 injectable mentions)
    # is not "only", so it is lifted to AMBIGUOUS for a human.
    "plastic surgeon": CategoryClass.CONDITIONAL_STOP,
    "plastic surgery clinic": CategoryClass.CONDITIONAL_STOP,
    "beauty salon": CategoryClass.CONDITIONAL_STOP,
    # The operator's literal complaint.
    "dentist": CategoryClass.STOP,
    "cosmetic dentist": CategoryClass.STOP,
    "lasik surgeon": CategoryClass.STOP,
    "chiropractor": CategoryClass.STOP,
    "pain control clinic": CategoryClass.STOP,
    "nail salon": CategoryClass.STOP,
    "hair salon": CategoryClass.STOP,
    "recreation center": CategoryClass.STOP,
}

# The conditional stops the operator's 30 Sep 2026 decision covers: a massage
# business with injectables is in. Plastic surgery and salons are not massage
# businesses and keep going to a human.
MASSAGE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"massage spa", "massage therapist", "reflexologist"}
)

# A business *calling itself* a med spa under a Maps category that is not one.
# Weak evidence — a name is a claim — so it lifts a stop to AMBIGUOUS and no
# further. Measured cases: "The beauty gallery & medi spa" (Massage spa),
# "Timeless MedSpa NYC" (Facial spa), "Jouvence Aesthetics" (Plastic surgery).
_NAME_CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    r"\bmed(?:i|ical)?[\s-]?spa\b|\bmedspa\b|\baesthetics?\b|\bbotox\b|\binjectables?\b",
    re.IGNORECASE,
)

_WS = re.compile(r"\s+")


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WS.sub(" ", stripped).strip().casefold()


def category_class(category: str | None) -> CategoryClass | None:
    """``None`` for a missing category *and* for one the map has never seen.

    An unmapped category is not guessed into a class: Maps has thousands, and
    one this map has no measurement for is unknown, not "probably fine".
    """
    if not category:
        return None
    return CATEGORY_CLASSES.get(_fold(category))


# --------------------------------------------------------------------------- #
# Account qualification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AccountVerdict:
    verdict: Verdict
    reasons: tuple[str, ...]
    # The service terms that matched, so a QUALIFIED "Spa" says *why*.
    evidence: tuple[str, ...] = ()
    # Locations sharing this business's domain in the sample. >1 is §3's
    # Priority C territory (larger / MSO) and its hard stop on a location-level
    # contact — recorded, not decided here: the buyer's role decides that.
    multi_location: bool = False

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def qualify_account(
    *,
    category: str | None,
    name: str | None = None,
    evidence: ServiceEvidence | None = None,
    locations: int | None = None,
) -> AccountVerdict:
    """§3's account gate over a Maps category, a name and the crawled menu.

    Category is the prior, the menu is the evidence, and the evidence only
    moves a verdict in the direction the category allows: a dentist's Botox
    page does not make it a med spa, and a med spa's JavaScript homepage does
    not make it anything less.
    """
    reasons: list[str] = []
    cls = category_class(category)
    reasons.append(f"maps_category={category}" if category else "maps_category=missing")
    if evidence is None:
        reasons.append("services=not read (no crawled text)")
    else:
        reasons.append(evidence.describe())
    terms = evidence.terms if evidence else ()
    name_claim = bool(name and _NAME_CLAIM_RE.search(name))
    if name_claim:
        reasons.append(f"name claims aesthetics ({name})")
    multi = bool(locations and locations > 1)
    if multi:
        reasons.append(f"multi_location={locations} (chain/MSO: Priority C, check authority)")

    def out(verdict: Verdict, why: str) -> AccountVerdict:
        return AccountVerdict(verdict, (why, *reasons), terms, multi)

    if cls is CategoryClass.STOP:
        return out(Verdict.HARD_STOP, "category is not an aesthetics business")

    if cls is CategoryClass.CORE:
        return out(Verdict.QUALIFIED, "category is a med spa")

    # Operator decision, 30 Sep 2026: a spa or massage business with an
    # injectables menu is IN, however small the menu is next to its massage
    # list. That settles §3's "minor add-on" for this vertical, and only for
    # injectables — a stray "laser" or a peel is still not a medical line.
    injectables = evidence is not None and evidence.injectable_mentions > 0

    if cls is CategoryClass.PROBABLE:
        if evidence is not None and evidence.has_aesthetics and not evidence.massage_dominant:
            return out(Verdict.QUALIFIED, "aesthetics category with an aesthetics menu")
        if injectables:
            return out(Verdict.QUALIFIED, "injectables menu alongside massage (operator: in)")
        if evidence is not None and evidence.has_aesthetics:
            return out(Verdict.AMBIGUOUS, "aesthetics menu outweighed by massage (minor add-on?)")
        if evidence is None:
            return out(Verdict.AMBIGUOUS, "aesthetics category, menu not read")
        return out(Verdict.AMBIGUOUS, "aesthetics category, no aesthetics service on its pages")

    if cls is CategoryClass.AMBIGUOUS:
        if evidence is not None and evidence.strong_aesthetics and not evidence.massage_dominant:
            return out(Verdict.QUALIFIED, "aesthetics menu is the main line")
        if injectables:
            return out(Verdict.QUALIFIED, "injectables menu alongside massage (operator: in)")
        if evidence is not None and evidence.has_aesthetics:
            return out(Verdict.AMBIGUOUS, "some aesthetics, not clearly material")
        if evidence is not None and evidence.massage_menu and not name_claim:
            return out(Verdict.HARD_STOP, "massage menu, no aesthetics service")
        return out(Verdict.AMBIGUOUS, "mixed category, menu does not settle it")

    if cls is CategoryClass.CONDITIONAL_STOP:
        if injectables and _fold(category or "") in MASSAGE_CATEGORIES:
            return out(Verdict.QUALIFIED, "massage business with injectables (operator: in)")
        if (evidence is not None and evidence.strong_aesthetics) or name_claim:
            return out(Verdict.AMBIGUOUS, "excluded category, but aesthetics evidence")
        return out(Verdict.HARD_STOP, "excluded category (massage/surgery/salon only)")

    # No category, or one the map has never measured.
    if evidence is not None and evidence.strong_aesthetics:
        return out(Verdict.AMBIGUOUS, "unmapped category, aesthetics menu")
    return out(Verdict.UNKNOWN, "category not in the ICP map" if category else "no category")


# --------------------------------------------------------------------------- #
# Buyer qualification
# --------------------------------------------------------------------------- #

# §3's closed list. Checked first, so "esthetician/owner" is an owner and
# "Owner & Medical Director" is the owner medical director §3 allows.
_BUYER_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:co-?)?owner\b|\bproprietor\b|\b(?:co-?)?founder\b|\bfounded[\s_]by\b|"
    r"\bceo\b|\bchief\s+executive\b|\bpresident\b|\bcoo\b|\bchief\s+operating\b|"
    r"\bexecutive\s+director\b",
    re.IGNORECASE,
)
# Titles that name a *function*, not the business: "Vice President of
# Operations", "Director of Accounting", "Regional Director". Checked before the
# buyer list's "president" so a VP is not read as the president.
_FUNCTIONAL_RE: Final[re.Pattern[str]] = re.compile(
    r"\bvice[\s-]+president\b|\bvp\b|\bdirector\s+of\b|\b(?:regional|area|district|sales|"
    r"marketing|hr|human\s+resources)\s+director\b|\bchief\s+(?:marketing|financial|"
    r"technology|medical)\s+officer\b|\bc[mft]o\b|"
    # §3's "franchise-local contact without authority over the stack": a
    # franchisee owns a location, not the booking/comms platform. Checked
    # before the buyer list, which "Franchise Owner" would otherwise pass.
    r"\bfranchise\b|\bfranchisee\b",
    re.IGNORECASE,
)
# Could be a buyer; the record does not say. §3's "owner medical director" is
# the reason medical director is here and not in the list above.
_MAYBE_RE: Final[re.Pattern[str]] = re.compile(
    r"\bmedical[\s_]+director\b|\bclinical[\s_]+director\b|\bmanaging[\s_]+director\b|"
    r"\bmanaging[\s_]+partner\b|\bprincipal\b|\bdirector\b|\bfounding[\s_]+physician\b|"
    r"\bpartner\b|\bphysician\b|\bservice-of-process\b|\bprincipal\s+executive\b",
    re.IGNORECASE,
)
# Staff. Neither controls the stack nor signs for it; §3 also stops on a
# "location-level contact without authority over the stack", which is what a
# spa's general manager at a chain is.
_STAFF_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:a|e)sthetician\b|\binjector\b|\bnurse\b|\bassistant\b|\bcoordinator\b|"
    r"\bmanager\b|\breceptionist\b|\btechnician\b|\bspecialist\b|\banalyst\b|"
    # schema.org ``employee`` is here; its ``member`` is not — membership says
    # nothing about role, and "James Christian" is a ``member`` of James
    # Christian Cosmetics.
    r"\bacupuncturist\b|\btherapist\b|\bdentist\b|\badministrator\b|\bemployee\b|"
    r"\bpractitioner\b|\bdispatch\b|\bfront\s+desk\b|\bconcierge\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BuyerVerdict:
    verdict: Verdict
    reasons: tuple[str, ...]
    # The field and value that decided it: "role=ceo", "source=dos_sop".
    evidence: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def classify_role(role: str | None) -> tuple[Verdict, str]:
    """A free-text title → a verdict and the rule that produced it."""
    text = _fold((role or "").replace("_", " "))
    if not text:
        return Verdict.UNKNOWN, "no role recorded"
    if _FUNCTIONAL_RE.search(text):
        # "VP, Owner Relations" is not an owner; functional wins over the list.
        return Verdict.HARD_STOP, "functional title, not in §3's buyer list"
    if _BUYER_RE.search(text):
        return Verdict.QUALIFIED, "in §3's buyer list"
    if _STAFF_RE.search(text):
        return Verdict.HARD_STOP, "staff role"
    if _MAYBE_RE.search(text):
        return Verdict.AMBIGUOUS, "authority unverified (owner?)"
    return Verdict.UNKNOWN, "role not recognised"


# Sources whose *role* is a fixed fact about the source, whatever the record's
# free text says. A service-of-process name is whoever accepts legal papers —
# frequently a lawyer or a filing service — and nothing in the filing says they
# own the business. A LinkedIn URL found on the site carries no role at all.
_SOURCE_ROLES: Final[dict[str, str]] = {
    "dos_ceo": "ceo",
    "dos_sop": "service-of-process name",
    "dos_po_exec": "principal executive",
    "dos_agent": "service-of-process name",
}


# Words a LinkedIn headline uses around an employer's name that are not part
# of it: titles, credentials, connectives, and the vertical's own vocabulary
# ("Medspa owner at …"). What is left is the employer's distinctive name.
_HEADLINE_VOCAB: Final[frozenset[str]] = frozenset(
    re.findall(
        r"\w+",
        "owner owners co founder founders founding ceo president coo chief executive officer "
        "operating director managing partner principal proprietor business medical "
        "md do np rn mha mba phd dnp aprn fnp msn bsn crna pac "
        "at and of the in for an llc inc pllc corp company group "
        "spa medspa medispa med aesthetics aesthetic wellness clinic center centre skin "
        "laser beauty health studio",
    )
)


def headline_foreign_tokens(headline: str | None, business: str | None) -> tuple[str, ...]:
    """Distinctive words in a LinkedIn headline that the business's name lacks.

    Houston batch 1 (Oct 2026): the SERP join accepts a profile whose title
    shares one distinctive token with the business, so "Owner at Brilliance
    *Communications* LLC" joined Brilliance MedSpa, "Founder & CEO at Bombshell
    *Influencers*" joined Bombshell Medspa, and "OWNER at Mina's *Nice and
    Clean*" joined Mina's Aesthetics. "Owner" passes §3; owner *of what* was
    never checked. Non-empty means the headline names a different business.

    A token matches by prefix too, because SERP truncates headlines ("Stone
    Creek Wellne…", "LoneStar ...").
    """
    if not headline or not business:
        return ()
    biz = [t for t in re.findall(r"[a-z0-9]+", _fold(business)) if t]
    flat = "".join(biz)
    foreign = []
    for t in re.findall(r"[a-z0-9]+", _fold(headline)):
        if len(t) < 3 or t in _HEADLINE_VOCAB:
            continue
        if t in biz or t in flat or any(b.startswith(t) for b in biz):
            continue
        foreign.append(t)
    return tuple(foreign)


def qualify_buyer(
    *, role: str | None, source: str | None = None, business: str | None = None
) -> BuyerVerdict:
    """§3's buyer gate over one recorded person.

    ``source`` matters only where the source *defines* the role (a DOS CEO
    field) or makes it unknowable (a vanity LinkedIn slug). ``business``, for a
    LinkedIn headline, checks the title is held *at this business*.
    """
    effective = _SOURCE_ROLES.get(source or "", role)
    verdict, why = classify_role(effective)
    evidence = [f"role={effective}" if effective else "role=missing"]
    if source:
        evidence.append(f"source={source}")
    if source == "linkedin" and verdict in (Verdict.QUALIFIED, Verdict.AMBIGUOUS):
        foreign = headline_foreign_tokens(effective, business)
        if foreign:
            verdict = Verdict.AMBIGUOUS
            why = f"headline names another business ({' '.join(foreign)}); was: {why}"
    return BuyerVerdict(verdict, (why, *evidence), tuple(evidence))


# --------------------------------------------------------------------------- #
# Corroboration — one person, several records
# --------------------------------------------------------------------------- #

_HONORIFIC = re.compile(r"^(?:dr|mr|mrs|ms|nurse)\.?\s+", re.IGNORECASE)
_NON_ALPHA = re.compile(r"[^a-z\s]")


def person_key(name: str | None) -> str | None:
    """``"DR. JANE A. DOE, MD"`` and ``"Jane Doe"`` → ``"jane doe"``.

    First and last alphabetic tokens only: DOS files "JANE A DOE", the site
    says "Dr. Jane Doe, NP", LinkedIn says "Jane Doe". Credentials after a
    comma are dropped first.
    """
    if not name:
        return None
    folded = _HONORIFIC.sub("", _fold(name).split(",")[0])
    tokens = [t for t in _NON_ALPHA.sub(" ", folded).split() if len(t) > 1]
    if len(tokens) < 2:
        return None
    return f"{tokens[0]} {tokens[-1]}"


_POSITIVE: Final[frozenset[Verdict]] = frozenset({Verdict.QUALIFIED, Verdict.AMBIGUOUS})


@dataclass(slots=True)
class Candidate:
    """One recorded person, as the caller found them."""

    name: str
    source: str
    role: str | None
    evidence_url: str = ""
    verdict: BuyerVerdict | None = None
    corroborated_by: list[str] = field(default_factory=list)


def corroborate(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Give every record for one person the best verdict any of them earned.

    "Owner medical director" is §3's own example: a site calling someone
    Medical Director (ambiguous) whose name is also the CEO on the state filing
    is the owner medical director. The upgrade only ever moves *up* — evidence
    that a person is a buyer is not cancelled by a page listing them as staff.
    """
    for c in candidates:
        if c.verdict is None:
            c.verdict = qualify_buyer(role=c.role, source=c.source)

    by_person: dict[str, list[Candidate]] = {}
    for c in candidates:
        key = person_key(c.name)
        if key:
            by_person.setdefault(key, []).append(c)

    for group in by_person.values():
        best = min(group, key=lambda c: verdict_rank(c.verdict.verdict if c.verdict else None))
        if best.verdict is None or best.verdict.verdict not in _POSITIVE:
            # Only evidence *for* a buyer propagates. A role-less LinkedIn slug
            # (unknown) must not overwrite a record that says "esthetician".
            continue
        for c in group:
            if c.verdict is None or c is best:
                continue
            if verdict_rank(best.verdict.verdict) >= verdict_rank(c.verdict.verdict):
                continue
            c.corroborated_by.append(best.source)
            c.verdict = BuyerVerdict(
                best.verdict.verdict,
                (
                    f"corroborated by {best.source}",
                    *best.verdict.reasons,
                    f"own record: {c.verdict.reason}",
                ),
                best.verdict.evidence,
            )
    return list(candidates)


def promotable(candidate: Candidate) -> bool:
    """Whether a person may be put forward as *the* buyer.

    ``HARD_STOP`` people stay recorded (§10.1: never discard a contact) but are
    never the name an email credit is spent on. ``UNKNOWN`` is promotable, last:
    an unrecorded role is not a rejected one.
    """
    return candidate.verdict is not None and candidate.verdict.verdict is not Verdict.HARD_STOP


# --------------------------------------------------------------------------- #
# Priority (§3's A/B/C)
# --------------------------------------------------------------------------- #


def priority(account: AccountVerdict, buyer: BuyerVerdict | None) -> tuple[str | None, str]:
    """§3's tier, or ``None`` with the reason it has none.

    **A is not reachable yet.** It requires "strong current signal, observed
    handoff" (§4.1, §4.3), and no stage observes either — the `--signal` stage
    does not exist. Every qualified account is therefore B at best, which is
    §3's own definition of B: "the objective, authority or handoff has a
    material ambiguity". Returning A here would assert a signal nobody saw.
    """
    if account.verdict is not Verdict.QUALIFIED:
        return None, f"account {account.verdict.value}"
    if buyer is None or buyer.verdict in (Verdict.HARD_STOP,):
        return None, "no promotable buyer"
    if account.multi_location:
        return "C", "multi-location / group account"
    if buyer.verdict is Verdict.QUALIFIED:
        return "B", "qualified buyer; current signal not assessed (A needs --signal)"
    return "B", f"buyer {buyer.verdict.value}; current signal not assessed"


def queue_key(
    account: Verdict | str | None,
    buyer: Verdict | str | None,
    *,
    own_domain: bool,
) -> tuple[int, int, int]:
    """Sort key for spending email credits: best accounts, then best buyers,
    then businesses that have a domain an email can exist on.

    Takes verdict *values* so a caller can order rows straight from a stored
    state file. No buyer ranks with ``unknown``: there is still a domain
    search to try, but it comes after every named buyer.
    """
    return (verdict_rank(account), verdict_rank(buyer), 0 if own_domain else 1)


# --------------------------------------------------------------------------- #
# The Hunter gate — eligibility, not just order
# --------------------------------------------------------------------------- #

# Evidence order, strongest record first. NPI (phone/zip join) is a government
# record; JSON-LD is the business's own structured markup; text patterns after;
# a state filing's CEO below those because the filing is often years stale; a
# SERP LinkedIn headline near the bottom, because the join is a business name
# in a search-result title. Breaks ties within a verdict, and ranks the Hunter
# spend plan.
EVIDENCE_ORDER: Final[tuple[str, ...]] = (
    "npi",
    "site_jsonld",
    "site_text",
    "site_linkedin",
    "dos_ceo",
    "dos_po_exec",
    "dos_sop",
    "npi_name_only",
    "linkedin",
    "hunter_domain",
)


def evidence_rank(sources: Iterable[str]) -> int:
    """The strongest of a buyer's own source and the sources that corroborate
    it. A LinkedIn headline backed by the site's own text ranks as site text."""
    ranks = [EVIDENCE_ORDER.index(s) for s in sources if s in EVIDENCE_ORDER]
    return min(ranks) if ranks else len(EVIDENCE_ORDER)


class HunterCall(StrEnum):
    # Name + domain. The only call that targets the buyer.
    FINDER = "finder"
    # Domain only: "returns *an* employee". Utah measured it at 32 calls for
    # 1 email, so it is off unless the operator asks for it by flag.
    DOMAIN_SEARCH = "domain_search"


@dataclass(frozen=True, slots=True)
class HunterGate:
    eligible: bool
    reason: str


def hunter_eligible(
    *,
    call: HunterCall,
    account: Verdict | str | None,
    buyer: Verdict | str | None,
    buyer_name: str | None,
    own_domain: str | None,
    already_found: bool,
    domain_already_called: bool,
    allow_domain_search: bool = False,
) -> HunterGate:
    """Whether one Hunter call may be spent on one row — a gate, not an order.

    Utah batch 1 sorted the queue well and then kept walking it: once the
    named rows were done, the waterfall's last step ran a domain search on
    every row with no buyer, and 32 of its 48 Hunter calls went there for one
    email. Ordering decides *which* good row goes first; only a gate stops the
    walk reaching the bad ones. Every condition below must hold, and the first
    that fails is the reason recorded on the row.
    """

    def no(reason: str) -> HunterGate:
        return HunterGate(False, reason)

    if account != Verdict.QUALIFIED:
        return no(f"account {account or 'unscreened'}")
    if not own_domain:
        return no("no own domain (missing or a booking platform)")
    if already_found:
        return no("address already found by a cheaper step")
    if domain_already_called:
        return no(f"domain {own_domain} already had a Hunter call this run")

    if call is HunterCall.DOMAIN_SEARCH:
        if not allow_domain_search:
            return no("domain search off (pass --allow-domain-search)")
        if buyer is not None:
            # A named buyer gets the finder or nothing: a domain search would
            # return someone else at the business, which is how Utah's
            # email_person came to differ from buyer_name.
            return no("domain search is only for rows with no buyer")
        return HunterGate(True, "domain search allowed by flag, no buyer named")

    if buyer is None:
        return no("no buyer")
    if buyer != Verdict.QUALIFIED:
        return no(f"buyer {buyer}")
    if person_key(buyer_name) is None:
        return no("buyer has no usable first and last name")
    return HunterGate(True, "qualified account, qualified named buyer, own domain")


def hunter_rank(
    *,
    priority: str | None,
    evidence_sources: Iterable[str],
    review_count: int | None,
) -> tuple[int, int, int, int]:
    """The order eligible rows are spent in: §3 priority B before C, then
    buyer evidence strength, then size by review count.

    A missing review count ranks after every known one, never as 0: "Maps did
    not say" is not "nobody has reviewed it" (CLAUDE.md, missing stays
    missing). A row with no priority sorts last; the gate should already have
    kept it out.
    """
    tier = {"A": 0, "B": 1, "C": 2}.get(priority or "", 3)
    reviews_missing = 1 if review_count is None else 0
    return (tier, evidence_rank(evidence_sources), reviews_missing, -(review_count or 0))


def locations_by_domain(domains: Iterable[str | None]) -> dict[str, int]:
    """How many rows share each domain — the sample's only chain signal."""
    counts: dict[str, int] = {}
    for d in domains:
        if d:
            counts[d.lower()] = counts.get(d.lower(), 0) + 1
    return counts

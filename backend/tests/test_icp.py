"""ICP qualification — MedSpa/ research prompt §3, pinned from real records.

Every role string and most page fragments here are copied from the two NYC
samples (``data/spike/medspa_ny*.json``, Sep 2026). Three properties carry the
file:

* **Unknown is not a rejection.** A business with no category and no crawled
  text is ``unknown``; a dentist is ``hard_stop``. The operator reviewing the
  queue treats those differently, so the module must not collapse them.
* **Category is the prior, the menu is the evidence, and each can only move
  the verdict the way the other allows.** A dentist's Botox page leaves it a
  dentist; a med spa's JavaScript homepage leaves it a med spa.
* **Buyer evidence only moves up.** A person corroborated as CEO by the state
  filing is the owner medical director §3 allows; a page listing them as staff
  does not cancel that, and a record with no role at all upgrades nobody.
"""

from __future__ import annotations

import pytest

from leadscraper.core.icp import (
    CATEGORY_CLASSES,
    Candidate,
    CategoryClass,
    HunterCall,
    Verdict,
    classify_role,
    corroborate,
    evidence_rank,
    hunter_eligible,
    hunter_rank,
    person_key,
    priority,
    promotable,
    qualify_account,
    qualify_buyer,
    queue_key,
    service_evidence,
)

PAD = " Book a consultation with our team today." * 6  # clears MIN_TEXT_CHARS

MEDSPA_MENU = (
    "Botox and Dysport from $12/unit. Dermal fillers: Juvederm, Restylane. "
    "Morpheus8, microneedling with PRP, HydraFacial, IPL photofacial." + PAD
)
MASSAGE_MENU = (
    "Swedish massage 60 min. Deep tissue massage. Hot stone massage. "
    "Reflexology. Couples massage." + PAD
)
# Thai Med Spa: botox on the page, drowned in massage — §3's "minor add-on".
ADDON_MENU = (
    "Thai massage, foot massage, Swedish massage, deep tissue massage, "
    "hot stone massage, aromatherapy massage. Also: Botox." + PAD
)


# --------------------------------------------------------------------------- #
# Service evidence
# --------------------------------------------------------------------------- #


def test_no_text_is_no_evidence_not_empty_evidence():
    """Equinox's spa pages parse to one character each. A JavaScript shell is
    an unread menu, and "we read it and found nothing" would be a claim."""
    assert service_evidence(None) is None
    assert service_evidence(" ") is None
    assert service_evidence("x" * 50) is None


def test_the_menu_is_read_into_terms_and_counts():
    ev = service_evidence(MEDSPA_MENU)
    assert ev is not None
    assert {"botox", "dysport", "filler", "juvederm", "morpheus8", "prp"} <= set(ev.terms)
    assert ev.injectable_mentions >= 4
    assert ev.strong_aesthetics and not ev.massage_dominant


def test_laser_alone_is_not_a_strong_menu():
    """A vein clinic and a LASIK surgeon both say "laser". One word is not a
    menu; an injectable or three distinct services is."""
    ev = service_evidence("We use the latest laser technology." + PAD)
    assert ev is not None and ev.has_aesthetics and not ev.strong_aesthetics


def test_massage_outweighing_aesthetics_is_detected():
    ev = service_evidence(ADDON_MENU)
    assert ev is not None and ev.strong_aesthetics and ev.massage_dominant


# --------------------------------------------------------------------------- #
# Account gate
# --------------------------------------------------------------------------- #


def test_the_operators_example_a_dentist_is_a_hard_stop_even_with_botox():
    """NYC Smile Spa (Cosmetic dentist) has 16 injectable mentions. The
    operator's complaint was dentists in the list; a Botox page does not make a
    dental practice a med spa."""
    v = qualify_account(category="Cosmetic dentist", evidence=service_evidence(MEDSPA_MENU))
    assert v.verdict is Verdict.HARD_STOP
    assert "maps_category=Cosmetic dentist" in v.reasons


def test_a_med_spa_is_qualified_without_a_readable_site():
    """15 of 68 "Medical spa" rows have no crawled text. The category is the
    ICP by definition; an unread homepage cannot demote it."""
    v = qualify_account(category="Medical spa", evidence=None)
    assert v.verdict is Verdict.QUALIFIED
    assert any("not read" in r for r in v.reasons)


@pytest.mark.parametrize("category", ["Massage spa", "Massage therapist"])
def test_massage_categories_are_stops_as_measured(category):
    """The handoff guessed these were ambiguous. Measured: 0 of 21 with crawled
    text mentioned a single aesthetics service. Pinned so nobody "softens" them
    back to ambiguous without a new measurement."""
    assert CATEGORY_CLASSES[category.lower()] is CategoryClass.CONDITIONAL_STOP
    v = qualify_account(category=category, evidence=service_evidence(MASSAGE_MENU))
    assert v.verdict is Verdict.HARD_STOP


def test_a_conditional_stop_with_a_real_menu_goes_to_a_human_not_to_qualified():
    """§3 stops "plastic-surgery-only", not a surgical practice with an
    injectables line. Lifting it to QUALIFIED would decide "is aesthetics
    material here?" — the operator's question, not this module's."""
    v = qualify_account(category="Plastic surgery clinic", evidence=service_evidence(MEDSPA_MENU))
    assert v.verdict is Verdict.AMBIGUOUS


def test_a_name_claim_lifts_a_stop_to_ambiguous_and_no_further():
    """Maps files "The beauty gallery & medi spa" under Massage spa, no site.
    A name is a claim, not a menu."""
    v = qualify_account(category="Massage spa", name="The beauty gallery & medi spa")
    assert v.verdict is Verdict.AMBIGUOUS
    probable = qualify_account(category="Facial spa", name="Timeless MedSpa NYC")
    assert probable.verdict is Verdict.AMBIGUOUS


def test_spa_is_decided_by_the_menu():
    """The "Spa" bucket really is mixed: Rachel Med Spa and FILD Studio are med
    spas, Thai New York Spa and Wildflower Spa sell massage.

    Thai Med Spa (Botox under 27 massage mentions) was AMBIGUOUS until the
    operator ruled on 30 Sep 2026 that a spa with an injectables menu is in.
    """
    assert (
        qualify_account(category="Spa", evidence=service_evidence(MEDSPA_MENU)).verdict
        is Verdict.QUALIFIED
    )
    assert (
        qualify_account(category="Spa", evidence=service_evidence(MASSAGE_MENU)).verdict
        is Verdict.HARD_STOP
    )
    assert (
        qualify_account(category="Spa", evidence=service_evidence(ADDON_MENU)).verdict
        is Verdict.QUALIFIED
    )
    assert qualify_account(category="Spa", evidence=None).verdict is Verdict.AMBIGUOUS


def test_the_operators_ruling_covers_injectables_and_massage_businesses_only():
    """30 Sep 2026: a spa or massage place with an injectables menu is in.

    Three edges: a massage spa with Botox qualifies; a massage-heavy spa whose
    only aesthetics word is "laser" does not (that is not an injectables
    menu); and a plastic surgeon with injectables is still a human's call,
    because the ruling was about spas, not surgical practices.
    """
    assert (
        qualify_account(category="Massage spa", evidence=service_evidence(ADDON_MENU)).verdict
        is Verdict.QUALIFIED
    )
    laser_only = service_evidence(MASSAGE_MENU + " Laser hair removal.")
    assert qualify_account(category="Spa", evidence=laser_only).verdict is Verdict.AMBIGUOUS
    assert (
        qualify_account(category="Plastic surgeon", evidence=service_evidence(MEDSPA_MENU)).verdict
        is Verdict.AMBIGUOUS
    )


def test_one_stray_massage_mention_is_not_a_massage_business():
    """EuroStyle SkinCare's page says "massage" once. A mixed-category stop
    needs positive evidence of a different business, and one word is not a
    menu — the measured massage houses said it 3 to 186 times."""
    v = qualify_account(
        category="Health and beauty shop",
        evidence=service_evidence("Facials and a relaxing massage add-on." + PAD),
    )
    assert v.verdict is Verdict.AMBIGUOUS


def test_a_probable_category_needs_its_menu_to_qualify():
    assert (
        qualify_account(
            category="Laser hair removal service",
            evidence=service_evidence("Laser hair removal packages." + PAD),
        ).verdict
        is Verdict.QUALIFIED
    )
    assert qualify_account(category="Day spa", evidence=None).verdict is Verdict.AMBIGUOUS


def test_missing_or_unmapped_category_is_unknown_not_a_stop():
    """CLAUDE.md's "missing data stays missing", applied to a verdict."""
    assert qualify_account(category=None).verdict is Verdict.UNKNOWN
    assert qualify_account(category="Yoga studio").verdict is Verdict.UNKNOWN
    assert qualify_account(category=None).verdict is not Verdict.HARD_STOP


def test_a_chain_is_flagged_not_rejected():
    """LaserAway UES and Park Slope share a domain. §3 makes a group account
    Priority C and stops only a *location-level* contact — which is the
    buyer's role to decide, not the account's."""
    v = qualify_account(category="Medical spa", locations=2)
    assert v.verdict is Verdict.QUALIFIED and v.multi_location


# --------------------------------------------------------------------------- #
# Buyer gate — role strings copied from the samples
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("founder", Verdict.QUALIFIED),
        ("founded_by", Verdict.QUALIFIED),
        ("jsonld_founder", Verdict.QUALIFIED),
        ("CEO and Co-Founder of CONTŌR", Verdict.QUALIFIED),
        ("Chief Operating Officer", Verdict.QUALIFIED),
        ("Medical Business Owner at Tribeca Aesthetics", Verdict.QUALIFIED),
        # §3's own case: an esthetician who owns the place is the owner.
        ("esthetician/owner at ellistic skin + wellness", Verdict.QUALIFIED),
        ("Owner & Medical Director", Verdict.QUALIFIED),
        # Owner-conditional: §3 says *owner* medical director.
        ("medical_director", Verdict.AMBIGUOUS),
        ("clinical_director", Verdict.AMBIGUOUS),
        ("director", Verdict.AMBIGUOUS),
        ("Managing Director at Revival New York", Verdict.AMBIGUOUS),
        ("principal", Verdict.AMBIGUOUS),
        # Functional titles are not the business's owner.
        ("Vice President of Operations", Verdict.HARD_STOP),
        ("Director of Accounting", Verdict.HARD_STOP),
        ("Regional Director", Verdict.HARD_STOP),
        ("Chief Marketing Officer", Verdict.HARD_STOP),
        # §3: franchise-local contact without authority over the stack.
        ("Franchise Owner at Degree Wellness", Verdict.HARD_STOP),
        # Staff, and §3's location-level contact at a chain.
        ("Esthetician at Eureka Body Care and Spa", Verdict.HARD_STOP),
        ("Licensed Acupuncturist at Morningside Acupuncture", Verdict.HARD_STOP),
        ("Spa Manager at Equinox Greenwich", Verdict.HARD_STOP),
        ("General Manager", Verdict.HARD_STOP),
        ("Physician Assistant", Verdict.HARD_STOP),
        ("jsonld_employee", Verdict.HARD_STOP),
        # Membership is not a role: James Christian is a `member` of James
        # Christian Cosmetics.
        ("jsonld_member", Verdict.UNKNOWN),
        ("lead_injector", Verdict.HARD_STOP),
        # No role at all.
        ("", Verdict.UNKNOWN),
        (None, Verdict.UNKNOWN),
        ("linkedin_on_site", Verdict.UNKNOWN),
        ("Trifecta Med Spa", Verdict.UNKNOWN),
    ],
)
def test_role_classification(role, expected):
    assert classify_role(role)[0] is expected


def test_vice_president_is_not_president():
    """§3's list has "president", and every VP title contains it. The
    functional check runs first for exactly this reason."""
    assert classify_role("President")[0] is Verdict.QUALIFIED
    assert classify_role("Vice President, Business Development")[0] is Verdict.HARD_STOP


def test_the_source_defines_the_role_for_state_filings():
    """A service-of-process name is whoever accepts legal papers — often a
    lawyer or a formation service. 14 of the 82 named buyers were one."""
    sop = qualify_buyer(role="", source="dos_sop")
    assert sop.verdict is Verdict.AMBIGUOUS
    assert "role=service-of-process name" in sop.reasons
    assert qualify_buyer(role="", source="dos_ceo").verdict is Verdict.QUALIFIED


def test_person_key_joins_the_spellings_one_person_gets():
    assert person_key("DR. JANE A. DOE, MD") == person_key("Jane Doe") == "jane doe"
    assert person_key("Madonna") is None
    assert person_key(None) is None


def test_corroboration_makes_a_medical_director_the_owner_medical_director():
    """§3 allows an *owner* medical director. The site says Medical Director;
    the state filing says CEO. Same person — so the site record qualifies."""
    site = Candidate("Dr. Jane Doe", "site_text", "medical_director")
    dos = Candidate("JANE A DOE", "dos_ceo", None)
    corroborate([site, dos])
    assert site.verdict is not None and site.verdict.verdict is Verdict.QUALIFIED
    assert site.corroborated_by == ["dos_ceo"]


def test_an_unknown_record_never_upgrades_a_staff_record():
    """Only evidence *for* a buyer propagates. A LinkedIn slug with no role
    must not wash out a page that says esthetician."""
    staff = Candidate("Oxana Raiter", "linkedin", "Esthetician at Eureka")
    slug = Candidate("Oxana Raiter", "site_linkedin", "linkedin_on_site")
    corroborate([staff, slug])
    assert staff.verdict is not None and staff.verdict.verdict is Verdict.HARD_STOP
    assert not promotable(staff)
    assert promotable(slug)


def test_hard_stop_people_are_kept_but_never_promoted():
    """§10.1: never discard a contact. Demoted, not deleted."""
    people = corroborate([Candidate("Nikki Mohead", "linkedin", "Spa Manager at Equinox")])
    assert len(people) == 1
    assert not promotable(people[0])


# --------------------------------------------------------------------------- #
# Priority and queue order
# --------------------------------------------------------------------------- #


def test_priority_a_is_unreachable_without_a_signal():
    """A requires an observed current signal (§4.1). No stage observes one
    yet, so the best any lead can be is B — and saying A would assert a
    signal nobody saw."""
    account = qualify_account(category="Medical spa")
    tier, why = priority(account, qualify_buyer(role="founder"))
    assert tier == "B"
    assert "signal" in why


def test_priority_c_for_a_group_and_none_for_an_unqualified_account():
    chain = qualify_account(category="Medical spa", locations=2)
    assert priority(chain, qualify_buyer(role="CEO"))[0] == "C"
    spa = qualify_account(category="Spa", evidence=None)
    assert priority(spa, qualify_buyer(role="owner"))[0] is None
    med = qualify_account(category="Medical spa")
    assert priority(med, qualify_buyer(role="Spa Manager"))[0] is None


def test_the_queue_spends_on_qualified_accounts_and_buyers_first():
    """§5 of the handoff: at ~5 lookups a day, order is the whole policy."""
    q = qualify_account(category="Medical spa").verdict
    a = qualify_account(category="Spa", evidence=None).verdict
    founder = qualify_buyer(role="founder").verdict
    md = "ambiguous"  # as stored in a state file
    keys = {
        "q_founder": queue_key(q, founder, own_domain=True),
        "q_md": queue_key(q, md, own_domain=True),
        "q_none": queue_key(q, None, own_domain=True),
        "a_founder": queue_key(a, founder, own_domain=True),
        "q_founder_nodomain": queue_key(q, founder, own_domain=False),
    }
    order = sorted(keys, key=keys.__getitem__)
    assert order == ["q_founder", "q_founder_nodomain", "q_md", "q_none", "a_founder"]


# --------------------------------------------------------------------------- #
# The Hunter gate (operator, 7 Oct 2026: "only on good leads which are top
# ranked", never "on low level leads like the previous run")
# --------------------------------------------------------------------------- #

# A row that passes every condition. Each test below breaks exactly one.
GOOD = {
    "call": HunterCall.FINDER,
    "account": "qualified",
    "buyer": "qualified",
    "buyer_name": "Jane Doe",
    "own_domain": "janedoeaesthetics.com",
    "already_found": False,
    "domain_already_called": False,
}


def test_the_good_row_is_eligible():
    gate = hunter_eligible(**GOOD)
    assert gate.eligible, gate.reason


@pytest.mark.parametrize(
    ("override", "reason_part"),
    [
        ({"account": "ambiguous"}, "account ambiguous"),
        ({"account": None}, "unscreened"),
        ({"buyer": "unknown"}, "buyer unknown"),
        ({"buyer": None}, "no buyer"),
        ({"buyer_name": "Madonna"}, "first and last"),
        ({"own_domain": None}, "own domain"),
        ({"already_found": True}, "already found"),
        ({"domain_already_called": True}, "already had a Hunter call"),
    ],
)
def test_each_gate_condition_rejects_on_its_own(override, reason_part):
    """Utah batch 1 had a well-sorted queue and still spent 32 of 48 Hunter
    calls on rows with no buyer, because order is not a gate. Every condition
    must be able to stop a call alone, and say which one did."""
    gate = hunter_eligible(**{**GOOD, **override})
    assert not gate.eligible
    assert reason_part in gate.reason


def test_an_ambiguous_buyer_is_not_eligible():
    """Utah: email-finder ran 3 times on ambiguous buyers (a medical director,
    a bare "director") and found 2 addresses — for people §3 does not count as
    buyers. Ambiguous is a human's call, not a credit."""
    gate = hunter_eligible(**{**GOOD, "buyer": Verdict.AMBIGUOUS})
    assert not gate.eligible
    assert "ambiguous" in gate.reason


def test_no_buyer_means_no_domain_search_unless_the_operator_asks():
    """Utah: domain search on rows with no buyer — 32 calls, 1 email. Off by
    default; on only by an explicit flag, and even then never for a row whose
    buyer has a name (that row gets the finder or nothing)."""
    base = {**GOOD, "call": HunterCall.DOMAIN_SEARCH, "buyer": None, "buyer_name": None}
    assert not hunter_eligible(**base).eligible
    assert "--allow-domain-search" in hunter_eligible(**base).reason
    assert hunter_eligible(**base, allow_domain_search=True).eligible
    named = {**base, "buyer": "ambiguous", "buyer_name": "Jane Doe"}
    assert not hunter_eligible(**named, allow_domain_search=True).eligible
    # The flag waives the buyer, never the account.
    assert not hunter_eligible(
        **{**base, "account": "ambiguous"}, allow_domain_search=True
    ).eligible


def test_the_second_location_on_a_domain_is_skipped():
    """ClubInject Salt Lake City and ClubInject Bountiful returned the same
    person at the same address: two credits, one email. The caller tracks the
    domains it has called; the gate refuses the second."""
    called: set[str] = set()
    results = []
    for _location in ("ClubInject Salt Lake City", "ClubInject Bountiful"):
        gate = hunter_eligible(
            **{
                **GOOD,
                "own_domain": "clubinject.com",
                "domain_already_called": "clubinject.com" in called,
            }
        )
        results.append(gate.eligible)
        if gate.eligible:
            called.add("clubinject.com")
    assert results == [True, False]


def test_evidence_rank_takes_the_strongest_corroborating_source():
    """A LinkedIn-headline buyer that the site's own text also names is as
    strong as the site text."""
    assert evidence_rank(["linkedin"]) > evidence_rank(["site_text"])
    assert evidence_rank(["linkedin", "site_text"]) == evidence_rank(["site_text"])
    assert evidence_rank(["something_new"]) > evidence_rank(["hunter_domain"])


def test_spend_order_is_priority_then_evidence_then_reviews_missing_last():
    """Utah's 21 searches ran out at row 71; the order decides who is inside
    the budget. B before C (a chain's location is weaker), then the business's
    own site before a LinkedIn headline, then larger before smaller — and a
    missing review count after every known one, never as zero."""
    rows = {
        "c_site_big": hunter_rank(priority="C", evidence_sources=["site_jsonld"], review_count=900),
        "b_linkedin_big": hunter_rank(
            priority="B", evidence_sources=["linkedin"], review_count=900
        ),
        "b_site_small": hunter_rank(priority="B", evidence_sources=["site_text"], review_count=3),
        "b_site_big": hunter_rank(priority="B", evidence_sources=["site_text"], review_count=250),
        "b_site_missing": hunter_rank(
            priority="B", evidence_sources=["site_text"], review_count=None
        ),
        "b_site_zero": hunter_rank(priority="B", evidence_sources=["site_text"], review_count=0),
    }
    order = sorted(rows, key=rows.__getitem__)
    assert order == [
        "b_site_big",
        "b_site_small",
        "b_site_zero",
        "b_site_missing",
        "b_linkedin_big",
        "c_site_big",
    ]


@pytest.mark.parametrize(
    ("headline", "business"),
    [
        ("Owner at Brilliance Communications LLC", "Brilliance MedSpa & Wellness"),
        ("Founder & CEO at Bombshell Influencers", "Bombshell Medspa"),
        ("OWNER at Mina's Nice and Clean", "Mina's Aesthetics and Wellness"),
        ("Founder في Jeunesse Global", "Jeunesse MedSpa"),
        ("Owner at New Heights Cellular & Repair", "New Heights Med Spa"),
        ("Owner, Riverpark Dental", "RiverPark Aesthetics"),
    ],
)
def test_a_linkedin_owner_of_another_business_is_not_this_ones_buyer(headline, business):
    """Houston batch 1, 7 Oct 2026: the SERP join needs one shared token, so
    six "owners" of a cleaning company, an influencer agency, an MLM, a phone
    repair shop and a dental practice joined med spas that share a word of
    their name — each a planned Hunter credit. Owner *of what* decides it;
    a human can still rule that the dentist owns the spa too."""
    v = qualify_buyer(role=headline, source="linkedin", business=business)
    assert v.verdict is Verdict.AMBIGUOUS
    assert "another business" in v.reason


@pytest.mark.parametrize(
    ("headline", "business"),
    [
        ("MHA Co-Owner at Live Hydration Spa", "LIVE Hydration Spa Kirby"),
        ("CEO, Co-Founder LoneStar ...", "Lonestar Aesthetics & Wellness Clinic"),
        ("Co-Owner at Stone Creek Wellne", "Stone Creek Wellness & Medical Aesthetics"),
        (
            "Business Owner at 4Ever Young Kingwood",
            "4Ever Young Med Spa & Wellness Center - Kingwood",
        ),
        ("Medspa owner at Body Radiance & Wellness", "Body Radiance & Wellness"),
        ("Co Owner at Les Grandeur", "Les Grandeur Med Spa"),
    ],
)
def test_a_headline_naming_this_business_still_qualifies(headline, business):
    """Credentials, titles, the vertical's vocabulary and SERP's truncation
    ("Wellne", "...") are not a different business."""
    v = qualify_buyer(role=headline, source="linkedin", business=business)
    assert v.verdict is Verdict.QUALIFIED, v.reason

"""The Texas med-spa spike's spend and export rules (``scripts/spike_medspa_ny.py``).

Two operator instructions from 29 Oct 2026 are pinned here:

* **Spend all four Hunter keys in one run.** When Hunter reports a key spent
  (429, "You've reached the limit for the number of searches per billing
  period"), the *same* query goes out again on the next key, so the row is
  answered rather than recorded as a miss. Hunter stops only when the last key
  is spent.
* **Never put an accept-all email on the master list**, whatever its score. An
  accept-all domain takes any address, so the address is unconfirmed. The
  address stays in the state file and batch CSV (§10.1); only the master
  leaves it out.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import spike_medspa_ny as s  # noqa: E402

# --------------------------------------------------------------------------- #
# --hunter-keys
# --------------------------------------------------------------------------- #

_SPENT = {
    "errors": [
        {
            "id": "too_many_requests",
            "code": 429,
            "details": "You've reached the limit for the number of searches per billing period",
        }
    ]
}


class _FakeHunter:
    """Stands in for ``cached_json``: answers each live call from a script of
    statuses and records which key each call went out on."""

    def __init__(self, statuses: list[int]) -> None:
        self.statuses = list(statuses)
        self.keys_used: list[str] = []
        self.cache_keys: list[str] = []

    async def __call__(self, client, cache, spend, api, url, *, cache_key=None, **_):
        self.keys_used.append(url.split("api_key=")[1])
        self.cache_keys.append(cache_key)
        status = self.statuses.pop(0)
        payload = _SPENT if status == 429 else {"data": {"email": None}}
        return status, payload, False


def _call(hs: s.HunterSpend, quota: s.Quota):
    return s.hunter_get(
        None,
        None,
        None,
        quota,
        hs,
        "email-finder",
        {"domain": "example.com", "first_name": "Ann", "last_name": "Lee"},
        f"{s.HUNTER}/email-finder?domain=example.com&first_name=Ann&last_name=Lee",
    )


def test_a_spent_key_moves_the_next_call_to_the_next_key(monkeypatch):
    """200 on key A, 429 on key A, then 200: the retry and every call after
    it go out on key B, and Hunter is still live for the run."""
    fake = _FakeHunter([200, 429, 200, 200])
    monkeypatch.setattr(s, "cached_json", fake)
    hs = s.HunterSpend([(3, "KEY_A"), (1, "KEY_B")], budget=100)
    quota = s.Quota({"hunter": True})

    assert asyncio.run(_call(hs, quota))[0] == 200
    assert asyncio.run(_call(hs, quota))[0] == 200  # 429 on A, retried on B
    assert asyncio.run(_call(hs, quota))[0] == 200

    assert fake.keys_used == ["KEY_A", "KEY_A", "KEY_B", "KEY_B"]
    assert hs.slot == 1
    assert quota.live("hunter")


def test_hunter_stops_only_when_the_last_key_is_spent(monkeypatch):
    fake = _FakeHunter([429, 429])
    monkeypatch.setattr(s, "cached_json", fake)
    hs = s.HunterSpend([(3, "KEY_A"), (1, "KEY_B")], budget=100)
    quota = s.Quota({"hunter": True})

    status, _, _ = asyncio.run(_call(hs, quota))

    assert status == 429
    assert fake.keys_used == ["KEY_A", "KEY_B"]
    assert not quota.live("hunter")


def test_the_cache_key_never_carries_the_api_key(monkeypatch):
    """A cached "not found" is a fact about the query, so rotation must
    never re-pay for one: the stored key is the same on every key."""
    fake = _FakeHunter([429, 200])
    monkeypatch.setattr(s, "cached_json", fake)
    hs = s.HunterSpend([(3, "KEY_A"), (1, "KEY_B")], budget=100)

    asyncio.run(_call(hs, s.Quota({"hunter": True})))

    assert len(set(fake.cache_keys)) == 1
    assert "api_key" not in fake.cache_keys[0]


def test_spend_is_counted_against_the_key_that_made_the_call():
    hs = s.HunterSpend([(3, "A"), (1, "B")], budget=100)
    hs.called("a.com", live=True)
    hs.rotate()
    hs.called("b.com", live=True)
    hs.called("c.com", live=False)  # a cache replay spends nothing
    assert hs.spent_by_slot == {3: 1, 1: 1}
    assert hs.spent == 2


@pytest.mark.parametrize("value", ["3,1,4,2", "2", "4,1"])
def test_hunter_slots_parse_in_the_given_order(value):
    assert s._hunter_slots(value) == [int(v) for v in value.split(",")]


@pytest.mark.parametrize("value", ["3,3", "5", "0,1", ""])
def test_hunter_slots_refuse_repeats_and_unknown_slots(value):
    with pytest.raises(Exception, match="distinct key slots"):
        s._hunter_slots(value)


# --------------------------------------------------------------------------- #
# --master
# --------------------------------------------------------------------------- #


def _row(**email) -> dict:
    """A qualified business whose buyer came from LinkedIn (Houston b1's
    Lonestar shape), with whatever email block the test needs."""
    row = {
        "name": "Lonestar Aesthetics & Wellness Clinic",
        "category": "Medical spa",
        "website": "https://www.lonestarwellnessclinic.com/",
        "maps_url": "https://www.google.com/maps/place/?q=place_id:ChIJvS1om17DQIYRDw6g7zwkdaw",
        "domain": "lonestarwellnessclinic.com",
        "linkedin": {
            "matched": True,
            "url": "https://www.linkedin.com/in/christine-kyle-remmert-7214a6112",
            "person_name": "Christine Kyle-Remmert",
            "headline": "CEO, Co-Founder LoneStar ...",
            "join": "title",
        },
        "icp": {"account": {"verdict": "qualified", "reasons": []}, "priority": "B"},
    }
    if email:
        row["email"] = {"person": "Christine Kyle-Remmert", **email}
    return row


def test_serper_goes_to_qualified_accounts_without_a_buyer_biggest_first():
    """Serper was the second budget (1,025 credits, Houston used ~1,000 for
    855 rows). A row that already has a qualified buyer is Hunter-eligible
    without LinkedIn, so it waits; an unqualified account never gets a credit."""

    def bare(name, reviews, verdict="qualified"):
        return {
            "name": name,
            "review_count": reviews,
            "icp": {"account": {"verdict": verdict, "reasons": []}},
        }

    has_buyer = _row()
    has_buyer.pop("linkedin")  # not yet searched, so it is a target
    has_buyer["site"] = {
        "people": [
            {
                "name": "Christine Kyle-Remmert",
                "role": "founder",
                "source": "site_text",
                "evidence_url": "https://www.lonestarwellnessclinic.com/about",
            }
        ]
    }
    rows = [
        has_buyer,
        bare("Small", 3),
        bare("Dentist", 900, verdict="hard_stop"),
        bare("Unrated", None),
        bare("Big", 400),
    ]

    class Args:
        force = False

    order = [r["name"] for r in s.serper_queue(rows, Args)]
    assert order == ["Big", "Small", "Unrated", has_buyer["name"]]


def test_a_verified_email_is_an_email_lead():
    d = s.master_row(_row(email="ck@x.com", source="hunter", score=91, verification="valid"), "b1")
    assert d["lead_tier"] == "email"
    assert d["email"] == "ck@x.com"
    assert d["batch"] == "b1"


@pytest.mark.parametrize("score", [99, 50])
def test_an_accept_all_email_never_reaches_the_master_whatever_its_score(score):
    """29 Oct: "don't include accept all emails … whether these are below 80
    or other reason". The row falls back to its LinkedIn, with every email
    field blank, so the address cannot be read off the master."""
    d = s.master_row(
        _row(email="ck@x.com", source="hunter", score=score, verification="accept_all"), "b1"
    )
    assert d["lead_tier"] == "linkedin"
    assert all(d[f] == "" for f in s._EMAIL_FIELDS)


def test_tombas_accept_all_flag_counts_even_when_it_says_valid():
    """Houston b1's SkinSpirit Katy: Tomba answered ``verification: valid``
    *and* ``accept_all: true``. A catch-all domain takes any address, so the
    label cannot confirm this one."""
    email = {"verification": "valid", "accept_all": True}
    assert s.is_accept_all(email)


def test_an_unverified_site_address_is_still_an_email_lead():
    """The business's own published address has no verification at all; the
    rule is accept-all, not "verified", so it is stored."""
    d = s.master_row(_row(email="christine@x.com", source="site_personal"), "b1")
    assert d["lead_tier"] == "email"


def test_no_email_and_no_qualified_linkedin_is_not_a_lead():
    row = _row()
    row["linkedin"]["headline"] = "Esthetician at Lonestar Aesthetics"
    assert s.master_row(row, "b1") is None


def _lead(tier: str, maps: str, website: str, buyer: str, email: str = "") -> dict:
    return {
        "lead_tier": tier,
        "maps_url": maps,
        "website": website,
        "buyer_name": buyer,
        "email": email,
    }


def test_merge_appends_new_rows_and_skips_ones_already_present():
    existing = [_lead("email", "m1", "https://a.com", "Ann Lee", "ann@a.com")]
    stats = s.merge_master(
        existing,
        [
            _lead("email", "m1", "https://a.com", "Ann Lee", "ann@a.com"),
            _lead("linkedin", "m2", "https://b.com", "Bo Kim"),
        ],
    )
    assert [d["maps_url"] for d in existing] == ["m1", "m2"]
    assert stats["already_present"] == 1 and stats["linkedin"] == 1


def test_merge_dedupes_a_second_branch_of_the_same_owner():
    """Houston b3q's Gameday Downtown and Gameday Katy: two Maps places, one
    domain, one owner. One person is one lead."""
    existing = [_lead("email", "m1", "https://gameday.com/katy", "Evan Miller", "e@gameday.com")]
    stats = s.merge_master(
        existing, [_lead("linkedin", "m2", "https://gameday.com/dt", "Evan Miller")]
    )
    assert len(existing) == 1
    assert stats["already_present"] == 1


def test_merge_upgrades_linkedin_to_email_in_place_and_never_downgrades():
    existing = [
        _lead("email", "m0", "https://z.com", "Zed Ray", "z@z.com"),
        _lead("linkedin", "m1", "https://a.com", "Ann Lee"),
    ]
    up = s.merge_master(existing, [_lead("email", "m1", "https://a.com", "Ann Lee", "ann@a.com")])
    assert existing[1]["email"] == "ann@a.com" and up["upgraded"] == 1

    down = s.merge_master(existing, [_lead("linkedin", "m0", "https://z.com", "Zed Ray")])
    assert existing[0]["lead_tier"] == "email" and down["upgraded"] == 0


# --------------------------------------------------------------------------- #
# Buyer-name noise, read by hand before each live run
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # San Antonio, Oct 2026: each passed the role regex as a founder.
        ("Licensed Cosmetologist", None),
        ("Regenerative Medicine", None),
        ("Chloe Co-Founder Melissa", None),
        ("Texas Nwando Okafor", "Nwando Okafor"),
        ("Instructors Huma Siwani", "Huma Siwani"),
        ("Button Crystal Ramirez", "Crystal Ramirez"),
        ("Lynda Okafor F", "Lynda Okafor"),
        # DFW, Oct 2026.
        ("Professional Activities", None),
        ("Pediatric Cancer", None),
        ("Plano Texas", None),
        ("Ebele Chioma From", "Ebele Chioma"),
        # Austin, Oct 2026.
        ("Led Care", None),
        ("Cosmetic Injection Specialist", None),
        ("Implants Pioneer", None),
        ("Specialist Ayla Gaines", "Ayla Gaines"),
        ("Ashley Szulim-Sabean Services", "Ashley Szulim-Sabean"),
        ("Sarah Wiser Introduction", "Sarah Wiser"),
        ("Claudia Ward Owned", "Claudia Ward"),
        ("Administration Heidi Fischer", "Heidi Fischer"),
        ("Jen Jennifer Quesada", "Jennifer Quesada"),
        # DFW b1, Oct 2026.
        ("George Bush Hwy", None),
        ("John Doe", None),
        ("Megan F", None),
        ("Recognition Awards", None),
        ("My Account", None),
        ("Guest Experience Expert", None),
        ("Small Family Business", None),
        ("At Age", None),
        ("Bio Mandy Cotten", "Mandy Cotten"),
        ("Professionals Jeffrey Adelglass", "Jeffrey Adelglass"),
        ("Family Jon Ricks", "Jon Ricks"),
        ("Amy Zevallos Businesss", "Amy Zevallos"),
        ("Terry Gannon Hi", "Terry Gannon"),
        ("Natan Yaker For", "Natan Yaker"),
        ("Operated Expertise Every", None),
        ("Robert Caridi Westlake", "Robert Caridi"),
        ("Jane A Doe", "Jane A Doe"),  # a middle initial stays
        # Hyphenated surnames that are people stay people.
        ("Christine Kyle-Remmert", "Christine Kyle-Remmert"),
        ("Stacey Upchurch-McIntyre", "Stacey Upchurch-McIntyre"),
    ],
)
def test_page_words_never_become_a_buyer_name(raw, expected):
    cleaned = s.clean_person_name(raw)
    assert (cleaned[0] if cleaned else None) == expected


def test_a_rejected_address_never_reaches_the_master():
    """San Antonio b1: RocketReach returned an address with ``smtp_valid:
    "invalid"``. It would bounce; it is kept off the list like accept-all."""
    d = s.master_row(_row(email="ck@x.com", source="rocketreach", verification="invalid"), "sa_b1")
    assert d["lead_tier"] == "linkedin"
    assert d["email"] == ""


def test_a_key_the_balance_shows_spent_is_skipped():
    keys = [(3, "A"), (1, "B"), (4, "C")]
    balances = {3: {"searches_left": 0}, 1: {"searches_left": 26}, 4: None}
    assert s.spendable_keys(keys, balances) == [(1, "B"), (4, "C")]

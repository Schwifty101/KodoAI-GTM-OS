import pytest

from gtm.sheet_import import place_key, plan_import
from gtm.sheet_map import MappedRow

MAPS = "https://www.google.com/maps/place/Glow/data=!1s0x1:0x2!8m2!3d1!4d2?place_id=ChIJabc_DEF-123"


def mrow(no=2, colour=None, emails=("dana@glowlab.example",), tab="Texas", block=1, **f):
    fields = {"name": "Glow Lab", "website": "https://www.glowlab.example/x", "owner_name": "Dana Fox", "owner_title": "Owner",
              "owner_linkedin": "https://linkedin.com/in/dana", "category": "Med spa", "city": "Austin", "state": "TX",
              "maps_url": MAPS, "owner_email": " ".join(emails)}
    fields.update(f)
    return MappedRow(tab, block, no, fields, list(emails), colour, 10)


def plan(rows, emails=(), domains=(), places=(), tracked=None):
    return plan_import(rows, set(emails), set(domains), set(places), tracked or {})


def test_green_and_red_rows_become_suppression_with_their_reasons():
    p = plan([mrow(2, "green"), mrow(3, "red", emails=("kim@sun.example",), website="sun.example", maps_url="")])
    assert {(r.get("email"), r.get("domain"), r["reason"]) for r in p.suppress} == {
        ("dana@glowlab.example", None, "sheet-sent"), (None, "glowlab.example", "sheet-sent"),
        ("kim@sun.example", None, "sheet-dropped"), (None, "sun.example", "sheet-dropped")}
    assert p.leads == [] and len(p.tracked_new) == 2


def test_webmail_email_row_suppresses_email_and_website_domain_not_gmail_com():
    p = plan([mrow(2, "red", emails=("owner@gmail.com",))])
    assert {(r.get("email"), r.get("domain")) for r in p.suppress} == {("owner@gmail.com", None), (None, "glowlab.example")}
    p = plan([mrow(2, "green", emails=("a@x.example",), website="https://www.facebook.com/glow")])
    assert [r for r in p.suppress if "domain" in r] == []


def test_row_with_no_email_and_no_website_is_skipped_nothing_to_match():
    p = plan([mrow(5, "green", emails=(), website="")])
    assert p.suppress == [] and p.skipped == [("Texas:5", "nothing_to_match")]


def test_uncoloured_row_with_email_becomes_scraped_lead_with_sheet_source():
    (lead,) = plan([mrow(emails=("dana@glowlab.example", "other@glowlab.example"))]).leads
    assert lead == {"place_id": "ChIJabc_DEF-123", "name": "Glow Lab", "website": "https://www.glowlab.example/x",
                    "domain": "glowlab.example", "category": "Med spa", "categories": ["Med spa"], "city": "Austin", "state": "TX",
                    "owner_name": "Dana Fox", "owner_title": "Owner", "owner_linkedin": "https://linkedin.com/in/dana",
                    "owner_email": "dana@glowlab.example", "email_source": "sheet", "email_verified": False, "status": "scraped"}


def test_place_id_from_maps_url_else_domain_key():
    assert place_key(mrow()) == "ChIJabc_DEF-123"
    assert place_key(mrow(maps_url="https://maps.google.com/?q=x&place_id:ChIJzzz9")) == "ChIJzzz9"
    assert place_key(mrow(maps_url="", website="http://www.Sun.example/a")) == "domain:sun.example"
    with pytest.raises(ValueError):
        place_key(mrow(maps_url="", website=""))
    p = plan([mrow(7, maps_url="", website="")])
    assert p.leads == [] and p.skipped == [("Texas:7", "no_key")]


def test_registered_agent_buyer_is_dropped_from_the_lead():
    for f in ({"owner_name": "Northwest Registered Agent LLC"}, {"owner_title": "Service of Process"}):
        (lead,) = plan([mrow(**f)]).leads
        assert lead["owner_name"] is None and lead["owner_title"] is None and lead["owner_email"] == "dana@glowlab.example"


def test_known_email_or_domain_is_skipped():
    assert plan([mrow()], emails={"dana@glowlab.example"}).skipped == [("Texas:2", "known")]
    assert plan([mrow()], domains={"glowlab.example"}).skipped == [("Texas:2", "known")]
    assert plan([mrow()], places={"ChIJabc_DEF-123"}).skipped == [("Texas:2", "known")]
    t = {("Texas", 1, "ChIJabc_DEF-123"): {"content_hash": "h"}}
    p = plan([mrow(), mrow(3, "green")], tracked=t)
    assert p.leads == [] and p.skipped == [("Texas:2", "tracked"), ("Texas:3", "tracked")]
    # the same email twice in one run: second row is known
    assert len(plan([mrow(2), mrow(3, maps_url="", website="https://other.example")]).leads) == 1


def test_uncoloured_named_row_without_email_counts_left_for_queue():
    p = plan([mrow(2, emails=()), mrow(3, emails=(), owner_name=""), mrow(4, emails=(), owner_name="Acme Registered Agent")])
    assert p.left_for_queue == 1 and p.leads == [] and p.skipped == []

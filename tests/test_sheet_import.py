import pytest

from gtm.sheet_import import content_hash, place_key, plan_import, plan_sync
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


# ---- Task 7: sync ----
KEY = ("Texas", 1, "ChIJabc_DEF-123")


def tr(row, **kw):
    return {"content_hash": content_hash(row), "colour_seen": "none", "colour_written": None, "lead_id": "L1",
            "suppression_id": None, "orphaned": False, **kw}


def lead(status="scraped", **kw):
    return {"status": status, "name": "Glow Lab", "website": "https://www.glowlab.example/x", "domain": "glowlab.example",
            "owner_name": "Dana Fox", "owner_title": "Owner", "owner_linkedin": "https://linkedin.com/in/dana",
            "owner_email": "dana@glowlab.example", **kw}


def test_changed_email_updates_lead_and_queues_reverify():
    old = mrow()
    new = mrow(emails=("new@glowlab.example",), owner_title="Founder")
    s = plan_sync([new], {KEY: tr(old)}, {"L1": lead()})
    assert s.updates == [("L1", {"owner_title": "Founder", "owner_email": "new@glowlab.example",
                                 "status": "cleaned", "email_verified": False})]
    assert s.reverify == ["L1"] and s.frozen == [] and s.orphaned == []


@pytest.mark.parametrize("status", ["drafted", "sent", "replied", "booked", "bounced", "suppressed", "unsubscribed"])
def test_drafted_lead_is_frozen_and_reported_not_changed(status):
    s = plan_sync([mrow(emails=("new@glowlab.example",))], {KEY: tr(mrow())}, {"L1": lead(status)})
    assert s.updates == [] and s.reverify == []
    assert s.frozen == [("L1", {"owner_email": "new@glowlab.example"})]


def test_deleted_or_rekeyed_row_is_orphaned_not_deleted():
    t = {KEY: tr(mrow()), ("Texas", 1, "domain:old.example"): tr(mrow(), lead_id="L2"), ("Utah", 1, "domain:u.example"): tr(mrow(), lead_id="L3")}
    s = plan_sync([mrow()], t, {"L1": lead(), "L2": lead()})  # Utah not read this run: not orphaned
    assert s.orphaned == ["Texas:1:domain:old.example"] and s.updates == []


def test_new_red_colour_adds_suppression():
    s = plan_sync([mrow(colour="red")], {KEY: tr(mrow())}, {"L1": lead()})
    assert {(x.get("email"), x.get("domain"), x["reason"]) for x in s.new_suppress} == {
        ("dana@glowlab.example", None, "sheet-dropped"), (None, "glowlab.example", "sheet-dropped")}


def test_os_written_red_is_not_read_as_owner_mark():
    s = plan_sync([mrow(colour="red")], {KEY: tr(mrow(), colour_written="red")}, {"L1": lead()})
    assert s.new_suppress == []
    assert plan_sync([mrow(colour="green")], {KEY: tr(mrow(), colour_seen="green")}, {"L1": lead()}).new_suppress == []  # not new


def test_unchanged_hash_makes_no_updates():
    s = plan_sync([mrow()], {KEY: tr(mrow())}, {"L1": lead()})
    assert (s.updates, s.reverify, s.frozen, s.orphaned, s.new_suppress) == ([], [], [], [], [])

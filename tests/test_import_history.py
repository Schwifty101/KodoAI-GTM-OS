import pytest

from gtm.db import get_db
from gtm.import_history import history_rows, parse_line, run_import


def test_parse_line_reads_the_five_fields_and_normalises():
    r = parse_line("Dana@Glow.com|https://www.glow.com/about|Cadence Complete||")
    assert r == {"email": "dana@glow.com", "domain": "glow.com", "status": "Cadence Complete", "reply": "", "dnc": False}
    assert parse_line("a@b.com|http://x.com|Bounced|Bounce|DNC")["dnc"] is True


def test_a_row_with_no_email_still_yields_its_domain():
    r = parse_line("|https://www.nakedmd.com/|Bounced||DNC")
    assert r["email"] is None and r["domain"] == "nakedmd.com"


def rows(lines, emails=(), domains=()):
    return history_rows([parse_line(l) for l in lines], set(emails), set(domains))


def test_every_contacted_company_blocks_its_address_and_its_domain():
    out = rows(["dana@glow.com|https://glow.com|Cadence Complete||"])
    assert {(r.get("email"), r.get("domain"), r["reason"]) for r in out} == {("dana@glow.com", None, "notion-contacted"), (None, "glow.com", "notion-contacted")}


@pytest.mark.parametrize("line,reason", [
    ("a@x.com|https://x.com|Disqualified||DNC", "do-not-contact"),
    ("a@x.com|https://x.com|Bounced|Bounce|", "notion-bounce"),
    ("a@x.com|https://x.com|Not Interested|Negative|", "not-interested"),
    ("a@x.com|https://x.com|Replied|Negative|", "not-interested"),
    ("a@x.com|https://x.com|Sent||", "notion-contacted"),
])
def test_the_address_reason_says_why(line, reason):
    assert {r["reason"] for r in rows([line]) if r.get("email")} == {reason}


def test_do_not_contact_and_not_interested_also_block_the_domain_with_that_reason():
    assert [r["reason"] for r in rows(["a@x.com|https://x.com|Not Interested|Negative|DNC"]) if r.get("domain")] == ["do-not-contact"]


def test_a_bounce_blocks_the_address_but_the_domain_is_only_marked_contacted():
    assert [r["reason"] for r in rows(["a@x.com|https://x.com|Bounced|Bounce|"]) if r.get("domain")] == ["notion-contacted"]


@pytest.mark.parametrize("site", ["https://visibook.com/hausofvanity", "https://www.instagram.com/glow", "https://glow.square.site", "https://gmail.com"])
def test_shared_platform_and_free_mail_domains_are_never_domain_suppressed(site):
    assert [r for r in rows([f"a@x.com|{site}|Sent||"]) if r.get("domain")] == []


def test_duplicates_within_the_input_and_against_existing_rows_are_dropped():
    out = rows(["a@x.com|https://x.com|Sent||", "a@x.com|https://x.com|Sent||", "b@x.com|https://x.com|Sent||", "c@y.com|https://y.com|Sent||"],
               emails={"c@y.com"}, domains={"y.com"})
    assert {(r.get("email"), r.get("domain")) for r in out} == {("a@x.com", None), ("b@x.com", None), (None, "x.com")} and len(out) == 3


@pytest.mark.db
def test_run_import_inserts_once_and_is_rerunnable():
    db = get_db()
    recs = [parse_line("pytest-imp-a@glow-imp.example|https://glow-imp.example|Cadence Complete||"), parse_line("pytest-imp-b@other-imp.example|https://other-imp.example|Bounced|Bounce|")]
    try:
        first = run_import(db, recs)
        again = run_import(db, recs)
        assert first == {"emails": 2, "domains": 2} and again == {"emails": 0, "domains": 0}
        got = {(r["email"], r["domain"], r["reason"]) for r in db.table("suppression").select("*").like("reason", "%").execute().data}
        assert ("pytest-imp-b@other-imp.example", None, "notion-bounce") in got and (None, "glow-imp.example", "notion-contacted") in got
    finally:
        db.table("suppression").delete().in_("domain", ["glow-imp.example", "other-imp.example"]).execute()
        db.table("suppression").delete().like("email", "pytest-imp-%").execute()

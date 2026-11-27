"""Tests for gtm/contact_backfill.py. Synthetic data only: fake people, @example.test addresses, fake company names."""
import csv
import io
import re
import uuid
from datetime import date

import pytest

from gtm import contact_backfill as cb
from gtm.contact_backfill import (load_sheet_sent, notion_ledger_rows, parse_notion_csv, plan_backfill, run_backfill,
                                  sheet_ledger_rows)
from gtm.db import get_db
from gtm.import_history import history_rows, parse_line
from gtm.recontact import CLEAR_OUTCOMES, OUTCOMES
from gtm.sheet import SheetRow
from gtm.sheet_map import MappedRow

COLS = ["Founder", "Role", "Company", "Email", "Website", "State", "HQ City", "Status", "Reply Type", "Touch", "Initial Sent",
        "Last Contacted", "Do Not Contact", "Subject", "Email Body", "Vector Used", "Campaign Batch"]
BASE = {"Founder": "Dana Example", "Role": "Founder", "Company": "Glow Example Spa", "Email": "Dana@Example.test",
        "Website": "https://www.glow-example.test/about", "State": "TX", "HQ City": "Austin", "Status": "Cadence Complete",
        "Reply Type": "None", "Touch": "3", "Initial Sent": "2026-09-02", "Last Contacted": "2026-09-12", "Do Not Contact": "No",
        "Subject": "A fake subject", "Email Body": "BODY-TEXT-NOT-KEPT", "Vector Used": "fake-angle", "Campaign Batch": "Batch02"}


def csv_text(*rows: dict, bom: bool = False, cols=COLS) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return ("﻿" if bom else "") + buf.getvalue()


def row(**over) -> dict:
    return {**BASE, **over}


def ledger(*rows: dict):
    return notion_ledger_rows(parse_notion_csv(csv_text(*rows)))


# ----- parse_notion_csv -------------------------------------------------------------------------------------------------

def test_parse_normalises_types_and_drops_the_body():
    [r] = parse_notion_csv(csv_text(row(**{"Do Not Contact": "Yes", "Touch": "2"}), bom=True))
    assert r["email"] == "dana@example.test" and r["initial_sent"] == date(2026, 9, 2) and r["last_contacted"] == date(2026, 9, 12)
    assert r["do_not_contact"] is True and r["touch"] == 2 and r["reply_type"] == "" and r["campaign_batch"] == "Batch02"
    assert r["hq_city"] == "Austin" and r["vector_used"] == "fake-angle"
    assert "BODY-TEXT-NOT-KEPT" not in repr(r)


def test_parse_tolerates_missing_columns_extra_columns_and_blank_lines():
    text = csv_text(row(), {}, cols=["Email", "Extra Thing", "Initial Sent", "Founder"])  # most columns absent, a blank row
    [r] = parse_notion_csv(text)
    assert r["email"] == "dana@example.test" and r["company"] == "" and r["touch"] is None and r["last_contacted"] is None
    assert r["do_not_contact"] is False and r["status"] == "" and "extra_thing" not in r


@pytest.mark.parametrize("text", ["2026-08-29", "2026-08-29T18:36:00.000Z", "2026-08-29 18:36", "August 29, 2026", "August 29, 2026 6:36 PM",
                                  "Aug 29, 2026", "Aug. 29, 2026 6:36 PM (GMT-5)", "August 29 2026"])
def test_datetime_initial_sent_is_cut_to_a_date(text):
    [r] = parse_notion_csv(csv_text(row(**{"Initial Sent": text})))
    assert r["initial_sent"] == date(2026, 8, 29)


@pytest.mark.parametrize("text", ["", "soon", "02/30/2026", "Feb 30, 2026", "Smarch 4, 2026"])
def test_an_unreadable_date_is_none(text):
    [r] = parse_notion_csv(csv_text(row(**{"Initial Sent": text})))
    assert r["initial_sent"] is None


def test_a_date_range_takes_the_later_day():
    [r] = parse_notion_csv(csv_text(row(**{"Last Contacted": "August 29, 2026 → September 2, 2026"})))
    assert r["last_contacted"] == date(2026, 9, 2)


@pytest.mark.parametrize("flag,expected", [("Yes", True), ("yes", True), ("true", True), ("Checked", True), ("__YES__", True), ("1", True),
                                           ("No", False), ("", False), ("false", False), ("__NO__", False)])
def test_do_not_contact_flag(flag, expected):
    assert parse_notion_csv(csv_text(row(**{"Do Not Contact": flag})))[0]["do_not_contact"] is expected


@pytest.mark.parametrize("reply,expected", [("None", ""), ("none", ""), ("N/A", ""), ("-", ""), ("", ""), ("Out of Office", "Out of Office"),
                                            ("Some New Label", "Some New Label")])
def test_reply_type_placeholders_are_empty(reply, expected):
    assert parse_notion_csv(csv_text(row(**{"Reply Type": reply})))[0]["reply_type"] == expected


def test_an_unrecognised_reply_type_is_a_reply_so_the_row_stays_blocked():
    [r], _ = ledger(row(**{"Reply Type": "Some New Label"}))
    assert r["outcome"] == "replied"


# ----- notion_ledger_rows -----------------------------------------------------------------------------------------------

def test_notion_row_becomes_one_ledger_row_with_both_keys():
    rows, skipped = ledger(row())
    assert skipped == []
    assert rows == [{
        "email": "dana@example.test", "domain": "glow-example.test", "business_name": "Glow Example Spa", "owner_name": "Dana Example",
        "owner_title": "Founder", "website": "https://www.glow-example.test/about", "city": "Austin", "state": "TX",
        "subject": "A fake subject", "vector": "fake-angle", "round": 1, "first_sent_on": date(2026, 9, 2),
        "last_sent_on": date(2026, 9, 12), "date_basis": "exact", "touches_sent": 3, "outcome": "no_reply", "source": "notion",
        "source_ref": "Batch02"}]


@pytest.mark.parametrize("last,bound,basis", [
    ("2026-09-12", date(2026, 9, 12), "exact"),       # already the later date: nothing assumed
    ("2026-09-09", date(2026, 9, 9), "exact"),        # exactly Day 7
    ("2026-09-04", date(2026, 9, 9), "upper_bound"),  # follow-ups may have gone out unlogged up to Day 7
    ("", date(2026, 9, 9), "upper_bound"),
    ("2026-08-01", date(2026, 9, 9), "upper_bound"),  # before the first send: bad data, never earlier than provable
])
def test_last_sent_is_never_earlier_than_day_seven_and_exact_only_when_logged(last, bound, basis):
    [r], _ = ledger(row(**{"Last Contacted": last}))
    assert (r["last_sent_on"], r["date_basis"]) == (bound, basis)


@pytest.mark.parametrize("touch,expected", [("3", 3), ("7", 3), ("0", 0), ("", None), ("Touch 2", 2)])
def test_touches_sent_is_clamped_to_the_column_range(touch, expected):
    assert ledger(row(Touch=touch))[0][0]["touches_sent"] == expected


@pytest.mark.parametrize("site", ["https://gmail.com", "https://www.instagram.com/glow", "https://visibook.com/glow", "https://glow.square.site",
                                  "https://glow.as.me/book", "https://calendly.com/glow", "https://glow.fresha.com", ""])
def test_webmail_and_booking_domains_are_never_a_ledger_domain(site):
    [r], skipped = ledger(row(Website=site))
    assert r["domain"] is None and r["email"] == "dana@example.test" and skipped == []


def test_row_without_a_send_date_gets_no_ledger_row_and_is_reported():
    rows, skipped = ledger(row(**{"Initial Sent": ""}), row(Email="b@example.test", **{"Initial Sent": "soon", "Campaign Batch": "Batch01"}))
    assert rows == [] and skipped == [("Batch02:row1", "no_send_date"), ("Batch01:row2", "no_send_date")]
    assert not any("example" in label or "Dana" in label for label, _ in skipped)  # no personal data in the report


def test_row_with_neither_email_nor_usable_domain_is_skipped_no_key():
    rows, skipped = ledger(row(Email="", Website="https://gmail.com"), row(Email="not an email", Website="", **{"Campaign Batch": ""}))
    assert rows == [] and skipped == [("Batch02:row1", "no_key"), ("notion:row2", "no_key")]


def test_row_without_an_email_is_keyed_by_its_domain_alone():
    [r], _ = ledger(row(Email=""))
    assert r["email"] is None and r["domain"] == "glow-example.test"


@pytest.mark.parametrize("status,reply,expected", [("Cadence Complete", "None", "no_reply"), ("Sent at Touch 2", "", "no_reply"), ("Follow-up Due", "N/A", "no_reply"),
                                                   ("Sent", "", "no_reply")])
def test_cadence_complete_with_no_reply_is_no_reply(status, reply, expected):
    assert ledger(row(Status=status, **{"Reply Type": reply}))[0][0]["outcome"] == expected


def test_out_of_office_is_auto_reply_and_dnc_beats_everything():
    assert ledger(row(Status="Sent", **{"Reply Type": "Out of Office"}))[0][0]["outcome"] == "auto_reply"
    assert ledger(row(Status="Replied", **{"Reply Type": "Out of Office"}))[0][0]["outcome"] == "replied"
    for status, reply in [("Cadence Complete", "None"), ("Bounced", "Bounce"), ("Not Interested", "Negative"), ("Replied", "Positive")]:
        assert ledger(row(Status=status, **{"Reply Type": reply, "Do Not Contact": "Yes"}))[0][0]["outcome"] == "do_not_contact"
    assert ledger(row(Status="Bounced", **{"Reply Type": "Bounce"}))[0][0]["outcome"] == "bounce"
    assert ledger(row(Status="Drafted"))[0][0]["outcome"] == "unknown"


def test_same_contact_in_two_batches_merges_to_latest_date_and_strictest_outcome():
    older = row(**{"Initial Sent": "2026-08-04", "Last Contacted": "2026-08-20", "Campaign Batch": "Batch01", "Status": "Not Interested",
                   "Reply Type": "Negative", "Touch": "2", "Subject": "Old subject"})
    newer = row(**{"Initial Sent": "2026-10-10", "Last Contacted": "", "Campaign Batch": "Batch03", "Status": "Sent", "Reply Type": "", "Touch": "1",
                   "Subject": "New subject"})
    for order in ((older, newer), (newer, older)):
        rows, skipped = ledger(*order)
        assert skipped == [] and len(rows) == 1
        r = rows[0]
        assert r["last_sent_on"] == date(2026, 10, 17) and r["date_basis"] == "upper_bound" and r["source_ref"] == "Batch03"
        assert r["outcome"] == "negative" and r["first_sent_on"] == date(2026, 8, 4) and r["touches_sent"] == 2 and r["subject"] == "New subject"


def test_a_later_clear_batch_does_not_hide_an_earlier_unclear_outcome_and_unknown_beats_no_reply():
    a = row(Status="Bounced", **{"Reply Type": "Bounce", "Initial Sent": "2026-08-04"})
    b = row(**{"Initial Sent": "2026-10-10"})
    assert ledger(a, b)[0][0]["outcome"] == "bounce"
    assert ledger(row(Status="Drafted"), b)[0][0]["outcome"] == "unknown"


def test_rows_without_an_email_merge_on_their_domain_but_different_people_stay_separate():
    same_domain_no_email = [row(Email="", **{"Initial Sent": "2026-08-04"}), row(Email="", **{"Initial Sent": "2026-10-10"})]
    assert len(ledger(*same_domain_no_email)[0]) == 1
    two_people = [row(Email="dana@example.test"), row(Email="lee@example.test", Founder="Lee Example")]
    rows, _ = ledger(*two_people)
    assert {r["email"] for r in rows} == {"dana@example.test", "lee@example.test"} and {r["domain"] for r in rows} == {"glow-example.test"}


def test_ledger_rows_are_all_shaped_alike_and_the_strictness_order_covers_every_outcome():
    rows, _ = ledger(row(), row(Email="", Founder=""))
    assert len({tuple(sorted(r)) for r in rows}) == 1
    assert set(cb.STRICTNESS) == set(OUTCOMES) and cb.STRICTNESS[-1] == "no_reply" and cb.STRICTNESS[0] == "do_not_contact"


# ----- the ledger keys are the suppression keys -------------------------------------------------------------------------

LINES = [
    "dana@glow-example.test|https://www.glow-example.test/about|Cadence Complete||",
    "Lee@Spa-Example.test|spa-example.test|Bounced|Bounce|",
    "|https://nakedmd-example.test/|Bounced||DNC",
    "a@gmail.example.test|https://gmail.com|Sent||",
    "b@example.test|https://www.instagram.com/glow|Sent||",
    "c@example.test|https://visibook.com/x|Sent||",
    "d@example.test|https://glow.square.site|Not Interested|Negative|",
    "e@example.test||Sent||",
]


def test_notion_keys_match_import_history_suppression_keys():
    expected = set()
    for r in history_rows([parse_line(l) for l in LINES], set(), set()):
        expected |= {r["email"]} if "email" in r else {r["domain"]}
    recs = []
    for i, line in enumerate(LINES):
        email, site, status, reply, flag = (line.split("|") + [""] * 5)[:5]
        recs.append(row(Email=email, Website=site, Status=status, **{"Reply Type": reply, "Do Not Contact": "Yes" if flag == "DNC" else "No",
                                                                    "Campaign Batch": f"B{i}"}))
    rows, skipped = ledger(*recs)
    assert skipped == []
    got = {k for r in rows for k in (r["email"], r["domain"]) if k}
    assert got == expected


def test_a_ledger_key_is_never_missing_from_suppression_for_a_booking_suffix_domain():
    # the one deliberate difference: import_history stored a booking-suffix domain, the ledger never does (fail closed: stays blocked)
    sup = {r["domain"] for r in history_rows([parse_line("a@example.test|https://calendly.com/x|Sent||")], set(), set()) if "domain" in r}
    [r], _ = ledger(row(Email="a@example.test", Website="https://calendly.com/x"))
    assert sup == {"calendly.com"} and r["domain"] is None


# ----- sheet rows -------------------------------------------------------------------------------------------------------

def mapped(row_no=5, tab="Texas", block=1, email="owner@example.test", site="https://www.sheet-example.test", maps="place_id:ChIJexample1", colour=None,
           owner="Sam Example", title="Owner") -> MappedRow:
    return MappedRow(tab, block, row_no, {"name": "Sheet Example Spa", "website": site, "owner_name": owner, "owner_title": title, "maps_url": maps,
                                          "city": "Houston", "state": "TX"}, [email] if email else [], colour, 8)


KEY = ("Texas", 1, "ChIJexample1")


def test_sheet_green_row_is_no_reply_with_a_placeholder_date_from_its_suppression_row():
    out = sheet_ledger_rows([mapped()], {KEY: date(2026, 11, 18)}, set())
    assert out == [{
        "email": "owner@example.test", "domain": "sheet-example.test", "business_name": "Sheet Example Spa", "owner_name": "Sam Example",
        "owner_title": "Owner", "website": "https://www.sheet-example.test", "city": "Houston", "state": "TX", "subject": None, "vector": None,
        "round": 1, "first_sent_on": None, "last_sent_on": date(2026, 11, 18), "date_basis": "upper_bound", "touches_sent": None,
        "outcome": "no_reply", "source": "sheet", "source_ref": "Texas"}]
    assert out[0]["outcome"] in CLEAR_OUTCOMES


@pytest.mark.parametrize("created,expected", [(date(2026, 11, 10), date(2026, 11, 18)), (date(2026, 11, 18), date(2026, 11, 18)),
                                              (date(2026, 11, 20), date(2026, 11, 20))])
def test_sheet_date_is_never_earlier_than_the_sheet_import_day(created, expected):
    assert sheet_ledger_rows([mapped()], {KEY: created}, set())[0]["last_sent_on"] == expected


def test_sheet_row_already_in_the_notion_ledger_is_skipped():
    sent = {KEY: date(2026, 11, 18), ("Texas", 1, "ChIJother"): date(2026, 11, 18)}
    rows = [mapped(), mapped(row_no=6, email="x@example.test", maps="place_id:ChIJother")]
    skipped = []
    out = sheet_ledger_rows(rows, sent, {"owner@example.test"}, skipped)  # the first row's email is a Notion key
    assert [r["email"] for r in out] == ["x@example.test"] and skipped == [("Texas:5", "known")]
    skipped = []
    assert sheet_ledger_rows(rows, sent, {"sheet-example.test"}, skipped) == []  # both rows share a Notion domain key
    assert skipped == [("Texas:5", "known"), ("Texas:6", "known")]


def test_sheet_red_row_gets_no_ledger_row():
    # the loader only lists green-at-import rows; a red row (or a row the OS painted green later) is absent from sheet_sent
    skipped = []
    assert sheet_ledger_rows([mapped(colour="red"), mapped(row_no=6, colour="green", maps="place_id:ChIJother")], {}, set(), skipped) == []
    assert skipped == []


def test_sheet_green_row_with_no_suppression_date_is_skipped_no_date():
    skipped = []
    assert sheet_ledger_rows([mapped()], {KEY: None}, set(), skipped) == [] and skipped == [("Texas:5", "no_date")]


def test_sheet_green_row_with_no_email_and_no_usable_domain_is_skipped_no_key():
    skipped = []
    assert sheet_ledger_rows([mapped(email="", site="https://gmail.com")], {KEY: date(2026, 11, 18)}, set(), skipped) == []
    assert skipped == [("Texas:5", "no_key")]


def test_sheet_row_without_a_place_key_is_ignored():
    assert sheet_ledger_rows([mapped(maps="", site="")], {KEY: date(2026, 11, 18)}, set()) == []


def test_sheet_registered_agent_is_no_owner_and_two_rows_of_one_contact_merge():
    sent = {KEY: date(2026, 11, 18), ("Utah", 1, "ChIJexample1"): date(2026, 11, 20)}
    rows = sheet_ledger_rows([mapped(title="Registered Agent"), mapped(tab="Utah")], sent, set())
    assert len(rows) == 1 and rows[0]["last_sent_on"] == date(2026, 11, 20) and rows[0]["source_ref"] == "Utah"
    assert sheet_ledger_rows([mapped(title="Registered Agent")], sent, set())[0]["owner_name"] is None


class ReadDB:
    """Read-only fake: select/eq/order/range/execute over dict rows; any write or unknown table raises."""

    def __init__(self, tables: dict[str, list[dict]]):
        self.tables, self.calls = tables, []

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"unexpected table {name}")
        return ReadTable(self, name)


class ReadTable:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.lo, self.hi = db, name, [], 0, None

    def select(self, *_):
        return self

    def order(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def execute(self):
        rows = [r for r in self.db.tables[self.name] if all(r.get(c) == v for c, v in self.filters)]
        return type("R", (), {"data": rows[self.lo:None if self.hi is None else self.hi + 1]})()

    def insert(self, *_):
        raise AssertionError("write")

    upsert = update = delete = insert


def test_load_sheet_sent_lists_green_rows_with_the_sheet_sent_suppression_date_only():
    db = ReadDB({
        "sheet_rows": [
            {"tab": "Texas", "block": 1, "row_key": "g1", "colour_seen": "green", "suppression_id": "s1"},
            {"tab": "Texas", "block": 1, "row_key": "g2", "colour_seen": "green", "suppression_id": "s2"},   # matched a Notion row instead
            {"tab": "Texas", "block": 1, "row_key": "g3", "colour_seen": "green", "suppression_id": None},
            {"tab": "Texas", "block": 1, "row_key": "r1", "colour_seen": "red", "suppression_id": "s3"},
            {"tab": "Texas", "block": 1, "row_key": "n1", "colour_seen": "none", "suppression_id": None},
        ],
        "suppression": [{"id": "s1", "reason": "sheet-sent", "created_at": "2026-11-18T09:30:00.123+00:00"},
                        {"id": "s2", "reason": "notion-contacted", "created_at": "2026-11-10T09:30:00+00:00"},
                        {"id": "s3", "reason": "sheet-dropped", "created_at": "2026-11-18T09:30:00+00:00"}]})
    assert load_sheet_sent(db) == {("Texas", 1, "g1"): date(2026, 11, 18), ("Texas", 1, "g2"): None, ("Texas", 1, "g3"): None}


def test_plan_backfill_reads_the_sheet_only_when_asked_and_never_writes(monkeypatch):
    csv_in = csv_text(row())
    boom = ReadDB({})  # any table access raises
    rows, skipped = plan_backfill(boom, csv_in)
    assert [r["source"] for r in rows] == ["notion"] and skipped == []

    header = SheetRow("Texas", 1, ["business", "website", "buyer_name", "buyer_role", "email", "maps_url", "city"], [None] * 7)
    data = SheetRow("Texas", 2, ["Sheet Example Spa", "https://sheet-example.test", "Sam Example", "Owner", "owner@example.test", "place_id:ChIJexample1", "Houston"],
                    ["green"] * 7)
    dup = SheetRow("Texas", 3, ["Glow Example Spa", "https://glow-example.test", "Dana Example", "Founder", "dana@example.test", "place_id:ChIJdup", "Austin"],
                   ["green"] * 7)
    asked = []
    monkeypatch.setattr(cb, "read_tab", lambda svc, sid, tab: asked.append((sid, tab)) or ([header, data, dup] if tab == "Texas" else [header]))
    db = ReadDB({"sheet_rows": [{"tab": "Texas", "block": 1, "row_key": "ChIJexample1", "colour_seen": "green", "suppression_id": "s1"},
                                {"tab": "Texas", "block": 1, "row_key": "ChIJdup", "colour_seen": "green", "suppression_id": "s2"}],
                 "suppression": [{"id": "s1", "reason": "sheet-sent", "created_at": "2026-11-18T09:30:00+00:00"},
                                 {"id": "s2", "reason": "sheet-sent", "created_at": "2026-11-18T09:30:00+00:00"}]})
    rows, skipped = plan_backfill(db, csv_in, sheet_id="SHEET", svc=object())
    assert sorted(t for _, t in asked) == ["Newyork", "Texas", "Utah"] and {s for s, _ in asked} == {"SHEET"}
    assert [(r["source"], r["source_ref"], r["email"]) for r in rows] == [("notion", "Batch02", "dana@example.test"), ("sheet", "Texas", "owner@example.test")]
    assert skipped == [("Texas:3", "known")]


# ----- run_backfill -----------------------------------------------------------------------------------------------------

class WriteDB:
    """Stateful fake of contact_history with the unique key; every other table, update, upsert and delete raises."""

    def __init__(self, existing=None, missing=False, forbid_inserts=False):
        self.rows, self.missing, self.forbid_inserts, self.batches = list(existing or []), missing, forbid_inserts, []

    def table(self, name):
        if name not in ("contact_history", "settings"):
            raise AssertionError(f"touched table {name}")
        return WriteTable(self, name)


class WriteTable:
    def __init__(self, db, name):
        self.db, self.name, self.pending, self.lo, self.hi = db, name, None, 0, None

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def order(self, *_):
        return self

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def insert(self, rows):
        assert self.name == "contact_history" and not self.db.forbid_inserts, "unexpected insert"
        self.pending = rows
        return self

    def upsert(self, *_):
        raise AssertionError("upsert")

    update = delete = upsert

    def execute(self):
        if self.name == "settings":
            return type("R", (), {"data": []})()
        if self.db.missing:
            from postgrest.exceptions import APIError
            raise APIError({"code": "PGRST205", "message": "Could not find the table 'public.contact_history' in the schema cache"})
        if self.pending is not None:
            self.db.batches.append(len(self.pending))
            for r in self.pending:
                key = (r["source"], r.get("email") or "", r.get("domain") or "", r["round"])
                assert key not in {(x["source"], x.get("email") or "", x.get("domain") or "", x["round"]) for x in self.db.rows}, "duplicate key"
                assert all(not isinstance(v, date) for v in r.values()), "dates must be serialised"
                self.db.rows.append(r)
            return type("R", (), {"data": self.pending})()
        return type("R", (), {"data": self.db.rows[self.lo:None if self.hi is None else self.hi + 1]})()


def plan(n=3, outcome="no_reply", last=date(2026, 11, 18), source="notion", start=0):
    return [{"email": f"person{i}@example.test", "domain": f"firm{i}.example.test", "business_name": f"Firm {i}", "owner_name": f"Person {i}",
             "owner_title": "Owner", "website": None, "city": None, "state": None, "subject": None, "vector": None, "round": 1,
             "first_sent_on": None, "last_sent_on": last, "date_basis": "upper_bound", "touches_sent": None, "outcome": outcome,
             "source": source, "source_ref": "Batch02"} for i in range(start, start + n)]


@pytest.fixture(autouse=True)
def _sixty_days(monkeypatch):
    monkeypatch.setattr(cb, "setting", lambda key, db=None: 60)


def test_run_backfill_dry_run_writes_nothing():
    db = WriteDB(forbid_inserts=True)
    counts = run_backfill(db, plan(5), confirm=False)
    assert counts["rows"] == 5 and counts["new"] == 5 and counts["inserted"] == 0 and db.rows == []


def test_run_backfill_never_writes_suppression():
    db = WriteDB()
    counts = run_backfill(db, plan(4), confirm=True)  # WriteDB raises on any table but contact_history and settings
    assert counts["inserted"] == 4 and len(db.rows) == 4


def test_run_backfill_chunks_of_200():
    db = WriteDB()
    counts = run_backfill(db, plan(450), confirm=True)
    assert db.batches == [200, 200, 50] and counts["inserted"] == 450 and len(db.rows) == 450


def test_run_backfill_second_run_inserts_nothing():
    db = WriteDB()
    run_backfill(db, plan(3), confirm=True)
    again = run_backfill(db, plan(5), confirm=True)  # 3 already there, 2 new
    assert again["existing"] == 3 and again["new"] == 2 and again["inserted"] == 2 and len(db.rows) == 5
    assert run_backfill(db, plan(5), confirm=True)["inserted"] == 0 and len(db.rows) == 5


def test_run_backfill_a_repeated_key_inside_one_plan_is_inserted_once():
    rows = plan(2) + plan(1)  # person0 twice
    db = WriteDB()
    counts = run_backfill(db, rows, confirm=True)
    assert counts["rows"] == 3 and counts["new"] == 2 and counts["existing"] == 1 and counts["inserted"] == 2


def test_run_backfill_counts_outcomes_and_first_eligible_weeks_with_no_personal_data():
    rows = plan(2, last=date(2026, 11, 18)) + plan(1, outcome="bounce", start=2) + plan(1, outcome="auto_reply", last=date(2026, 9, 1), source="sheet", start=3)
    counts = run_backfill(WriteDB(), rows, confirm=False, today=date(2026, 11, 27), skipped=[("Batch01:row3", "no_send_date"), ("Texas:9", "no_date"),
                                                                                           ("Batch01:row4", "no_send_date")])
    assert counts["outcome:no_reply"] == 2 and counts["outcome:bounce"] == 1 and counts["outcome:auto_reply"] == 1
    assert counts["week:2027-01-11"] == 2  # 2026-11-18 + 60 days = 2027-01-17, a Sunday: the week of Monday 2027-01-11
    assert counts["week:2026-10-26"] == 1  # 2026-09-01 + 60 = 2026-10-31
    assert sum(v for k, v in counts.items() if k.startswith("week:")) == 3  # a bounce never becomes eligible: no week
    assert counts["eligible_now"] == 1 and counts["skipped:no_send_date"] == 2 and counts["skipped:no_date"] == 1
    assert all(isinstance(v, int) for v in counts.values())
    pattern = re.compile(r"^(rows|new|existing|inserted|eligible_now|ledger_table_missing|outcome:[a-z_]+|week:\d{4}-\d{2}-\d{2}|skipped:[a-z_]+)$")
    assert all(pattern.match(k) for k in counts), counts
    text = repr(counts)
    assert "example" not in text and "Person" not in text and "Firm" not in text and "Batch" not in text


def test_run_backfill_reads_recontact_days_and_falls_back_to_sixty(monkeypatch):
    rows = plan(1, last=date(2026, 11, 18))
    monkeypatch.setattr(cb, "setting", lambda key, db=None: 30)
    assert "week:2026-12-14" in run_backfill(WriteDB(), rows, confirm=False)  # 2026-12-18, a Friday
    def broken(key, db=None):
        raise RuntimeError("settings unreadable")
    monkeypatch.setattr(cb, "setting", broken)
    assert "week:2027-01-11" in run_backfill(WriteDB(), rows, confirm=False)


def test_run_backfill_missing_table_dry_run_counts_everything_as_new_and_flags_it():
    counts = run_backfill(WriteDB(missing=True), plan(3), confirm=False)
    assert counts["ledger_table_missing"] == 1 and counts["new"] == 3 and counts["existing"] == 0 and counts["inserted"] == 0


def test_run_backfill_missing_table_with_confirm_raises_a_clear_error():
    db = WriteDB(missing=True)
    with pytest.raises(RuntimeError, match="0018"):
        run_backfill(db, plan(3), confirm=True)
    assert db.rows == []


def test_run_backfill_does_not_swallow_other_read_errors():
    class Down(WriteDB):
        def table(self, name):
            raise ConnectionError("network down")
    with pytest.raises(ConnectionError):
        run_backfill(Down(), plan(1), confirm=False)


@pytest.mark.db
def test_run_backfill_is_idempotent_on_the_unique_key():
    db = get_db()
    try:
        db.table("contact_history").select("id").limit(1).execute()
    except Exception as e:
        if cb._table_missing(e):
            pytest.skip("migration 0018 not applied")
        raise
    tag = uuid.uuid4().hex[:8]
    rows = [{**r, "email": f"rbf-{tag}-{i}@example.invalid", "domain": f"rbf-{tag}-{i}.example.invalid", "source_ref": "TEST"} for i, r in enumerate(plan(3))]
    emails = [r["email"] for r in rows]
    try:
        first = run_backfill(db, rows, confirm=True)
        second = run_backfill(db, rows, confirm=True)
        assert first["inserted"] == 3 and second["inserted"] == 0 and second["existing"] == 3
    finally:
        ids = [x["id"] for x in db.table("contact_history").select("id").in_("email", emails).eq("source_ref", "TEST").execute().data]
        if ids:
            db.table("contact_history").delete().in_("id", ids).execute()

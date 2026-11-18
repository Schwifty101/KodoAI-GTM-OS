import pytest

from gtm.db import get_db
from gtm.sheet import SheetRow
from gtm.sheet_import import run_import_sheet

pytestmark = pytest.mark.db

HDR = "business,maps_category,website,buyer_name,buyer_role,linkedin_url,email,email_person,other_people,maps_url".split(",")
DOM = "test-sheetimp-{}.example"


def _row(no, n, colour=None, email=True):
    cells = [f"TEST_sheetimp {n}", "Med spa", f"https://{DOM.format(n)}", "Dana Fox", "Owner", "",
             f"test_sheetimp_{n}@{DOM.format(n)}" if email else "", "", "", ""]
    return SheetRow("Utah", no, cells, [colour] * len(cells))


def _fake_read(monkeypatch, fail_tab=None):
    def read(svc, sheet_id, tab):
        if tab == fail_tab:
            raise ValueError(f"tab {tab!r} not found in sheet")
        if tab != "Utah":
            return [SheetRow(tab, 1, HDR, [None] * len(HDR))]
        return [SheetRow("Utah", 1, HDR, [None] * len(HDR)), _row(2, 1, "green"), _row(3, 2, "red"), _row(4, 3)]
    monkeypatch.setattr("gtm.sheet_import.read_tab", read)


def _counts(db):
    sup = db.table("suppression").select("id").like("domain", "test-sheetimp-%").execute().data
    sup += db.table("suppression").select("id").like("email", "test_sheetimp_%").execute().data
    leads = db.table("leads").select("id,batch_id").like("name", "TEST_sheetimp%").execute().data
    rows = db.table("sheet_rows").select("id").like("row_key", "domain:test-sheetimp-%").execute().data
    return len(sup), len(leads), len(rows)


def _cleanup(db):
    leads = db.table("leads").select("id,batch_id").like("name", "TEST_sheetimp%").execute().data
    db.table("sheet_rows").delete().like("row_key", "domain:test-sheetimp-%").execute()
    db.table("suppression").delete().like("domain", "test-sheetimp-%").execute()
    db.table("suppression").delete().like("email", "test_sheetimp_%").execute()
    db.table("leads").delete().like("name", "TEST_sheetimp%").execute()
    ids = [x["batch_id"] for x in leads if x["batch_id"]]
    if ids:  # only TEST_-named batches, never a real one
        db.table("batches").delete().in_("id", ids).like("name", "TEST_%").execute()


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("gtm.sheet_import.BATCH_NAME", "TEST_Sheet import")
    d = get_db()
    _cleanup(d)
    yield d
    _cleanup(d)


def test_tab_not_found_error_writes_nothing(db, monkeypatch):
    _fake_read(monkeypatch, fail_tab="Texas")
    with pytest.raises(ValueError, match="Texas"):
        run_import_sheet(db, object(), "sheet", confirm=True)
    assert _counts(db) == (0, 0, 0)


def test_dry_run_writes_nothing_and_confirm_is_idempotent(db, monkeypatch):
    _fake_read(monkeypatch)
    plan = run_import_sheet(db, object(), "sheet")
    assert len(plan.leads) == 1 and _counts(db) == (0, 0, 0)
    run_import_sheet(db, object(), "sheet", confirm=True)
    assert _counts(db) == (4, 1, 3)  # green and red: email + domain each; one lead; three tracked rows
    again = run_import_sheet(db, object(), "sheet", confirm=True)
    assert again.leads == [] and again.suppress == [] and _counts(db) == (4, 1, 3)


def test_leads_land_in_a_test_named_batch(db, monkeypatch):
    _fake_read(monkeypatch)
    run_import_sheet(db, object(), "sheet", confirm=True)
    ids = [x["batch_id"] for x in db.table("leads").select("batch_id").like("name", "TEST_sheetimp%").execute().data]
    names = {b["name"] for b in db.table("batches").select("name").in_("id", ids).execute().data}
    assert names and all(n.startswith("TEST_") for n in names)

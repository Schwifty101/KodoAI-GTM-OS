from types import SimpleNamespace

import pytest

from gtm import sheet_queue
from gtm.db import get_db
from gtm.sheet_queue import pull_sheet_only

pytestmark = pytest.mark.db


def test_pull_sheet_only_inserts_scraped_then_cleans_then_no_buyer(monkeypatch):
    db = get_db()
    monkeypatch.setattr(sheet_queue, "BATCH_NAME", "TEST_Sheet import")
    key = "TEST_domain:queue-pull-glowmed.com"
    row = SimpleNamespace(tab="Texas", block=1, row_no=7, colour=None, emails=[],
                          fields={"name": "TEST_Glowmed", "website": "https://queue-pull-glowmed.com", "category": "Medical spa", "owner_name": "Dana White",
                                  "owner_title": "Owner", "owner_linkedin": "https://li/d", "state": "TX", "city": "Austin"})
    monkeypatch.setattr(sheet_queue, "_mapped", lambda svc, sheet_id: [(row, key)])
    try:
        assert pull_sheet_only(db, object(), "sid") == 1
        lead = db.table("leads").select("id,status,owner_name,owner_linkedin,batch_id").eq("place_id", key).execute().data[0]
        assert (lead["status"], lead["owner_name"], lead["owner_linkedin"]) == ("no_buyer", "Dana White", "https://li/d")
        assert db.table("sheet_rows").select("row_key").eq("lead_id", lead["id"]).execute().data == [{"row_key": key}]
    finally:
        for lead in db.table("leads").select("id,batch_id").eq("place_id", key).execute().data:
            db.table("sheet_rows").delete().eq("lead_id", lead["id"]).execute()
            db.table("leads").delete().eq("id", lead["id"]).execute()
        db.table("batches").delete().like("name", "TEST_Sheet import%").execute()


def test_queue_clean_ignores_the_strict_category_setting(monkeypatch):
    """Owner-curated sheet rows spend no finder credits, so a name-only match is kept even with the strict setting on."""
    import gtm.clean as clean

    db = get_db()
    monkeypatch.setattr(sheet_queue, "BATCH_NAME", "TEST_Sheet import")
    monkeypatch.setattr(clean, "setting", lambda k: True)
    key = "TEST_domain:queue-strict-aesthetic.com"
    row = SimpleNamespace(tab="Texas", block=1, row_no=8, colour=None, emails=[],
                          fields={"name": "TEST_Aesthetic Studio", "website": "https://queue-strict-aesthetic.com", "category": "Skin care clinic",
                                  "owner_name": "Dana White", "owner_title": "Owner", "state": "TX", "city": "Austin"})
    monkeypatch.setattr(sheet_queue, "_mapped", lambda svc, sheet_id: [(row, key)])
    try:
        assert pull_sheet_only(db, object(), "sid") == 1
        assert db.table("leads").select("status").eq("place_id", key).execute().data[0]["status"] == "no_buyer"
    finally:
        for lead in db.table("leads").select("id").eq("place_id", key).execute().data:
            db.table("sheet_rows").delete().eq("lead_id", lead["id"]).execute()
            db.table("leads").delete().eq("id", lead["id"]).execute()
        db.table("batches").delete().like("name", "TEST_Sheet import%").execute()

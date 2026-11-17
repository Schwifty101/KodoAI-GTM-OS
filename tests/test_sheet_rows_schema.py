import pytest

from gtm.db import get_db

pytestmark = pytest.mark.db
db = get_db()


def test_sheet_rows_unique_per_tab_block_key():
    row = {"tab": "TEST_tab", "block": 1, "row_key": "TEST_key"}
    try:
        db.table("sheet_rows").insert(row).execute()
        with pytest.raises(Exception):
            db.table("sheet_rows").insert(row).execute()
    finally:
        db.table("sheet_rows").delete().eq("tab", "TEST_tab").execute()


def test_owner_linkedin_column_exists():
    db.table("leads").select("owner_linkedin").limit(1).execute()

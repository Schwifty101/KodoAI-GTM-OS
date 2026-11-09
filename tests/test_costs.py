import pytest

from gtm.costs import log_cost
from gtm.db import get_db


@pytest.mark.db
def test_log_cost_inserts_row():
    db = get_db()
    note = "pytest-test-log-cost"
    try:
        log_cost("apify", 12, 0.05, note=note)
        rows = db.table("cost_log").select("*").eq("note", note).execute().data
        assert len(rows) == 1
        assert (rows[0]["provider"], float(rows[0]["units"]), float(rows[0]["usd"])) == ("apify", 12.0, 0.05)
    finally:
        db.table("cost_log").delete().eq("note", note).execute()

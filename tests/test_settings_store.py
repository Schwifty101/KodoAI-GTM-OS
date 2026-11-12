import pytest

from gtm.db import get_db
from gtm.settings_store import clear_cache, set_setting, setting

pytestmark = pytest.mark.db
db = get_db()


@pytest.fixture(autouse=True)
def restore():
    saved = db.table("settings").select("*").in_("key", ["monthly_budget_pkr", "weekly_target"]).execute().data
    db.table("settings").delete().in_("key", ["monthly_budget_pkr", "weekly_target"]).execute()
    clear_cache()
    yield
    db.table("settings").delete().in_("key", ["monthly_budget_pkr", "weekly_target"]).execute()
    if saved:
        db.table("settings").upsert(saved).execute()
    clear_cache()


def test_default_when_missing():
    assert setting("weekly_target") == 200


def test_set_then_read_sees_new_value_immediately():
    assert setting("monthly_budget_pkr") == 25000  # primes the cache
    set_setting(db, "monthly_budget_pkr", 30000)
    assert setting("monthly_budget_pkr") == 30000


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        set_setting(db, "nope", 1)


def test_wrong_type_rejected():
    with pytest.raises(ValueError):
        set_setting(db, "weekly_target", "lots")


def test_bool_not_accepted_for_int():
    with pytest.raises(ValueError):
        set_setting(db, "weekly_target", True)


def test_bad_stored_value_falls_back_to_default():
    db.table("settings").upsert({"key": "weekly_target", "value": "x"}).execute()
    clear_cache()
    assert setting("weekly_target") == 200

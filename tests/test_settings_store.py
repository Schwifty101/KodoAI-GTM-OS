import pytest

from gtm.db import get_db
from gtm.settings_store import clear_cache, set_setting, setting

pytestmark = pytest.mark.db
KEYS = ["monthly_budget_pkr", "weekly_target", "paid_gemini_monthly_cap_usd", "credit_balance_usd", "credit_end_date",
        "autopilot_on", "autopilot_limit_usd", "autopilot_started_at", "autopilot_state", "autopilot_target", "batch_base",
        "walk_yield_order", "clean_category_strict"]
db = get_db()


@pytest.fixture(autouse=True)
def restore():
    saved = db.table("settings").select("*").in_("key", KEYS).execute().data
    db.table("settings").delete().in_("key", KEYS).execute()
    clear_cache()
    yield
    db.table("settings").delete().in_("key", KEYS).execute()
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


def test_float_settings_accept_fractions_and_malformed_dates_fall_back():
    set_setting(db, "paid_gemini_monthly_cap_usd", 2.5)
    set_setting(db, "credit_balance_usd", 297.43)
    assert setting("paid_gemini_monthly_cap_usd") == 2.5 and setting("credit_balance_usd") == 297.43
    db.table("settings").upsert({"key": "credit_end_date", "value": "soon"}).execute()
    clear_cache()
    assert setting("credit_end_date") == "2027-02-09"


def test_walk_and_fallback_defaults():
    from gtm.settings_store import DEFAULTS
    want = {"walk_schedule_enabled": False, "walk_hour_utc": 13, "walk_tiles_per_run": 3,
            "walk_queries": "med spa,aesthetics clinic", "walk_max_places": 40,
            "walk_escalate_at": 0.8, "fetch_fallback": True}
    for k, v in want.items():
        assert DEFAULTS[k] == v and type(DEFAULTS[k]) is type(v)
    with pytest.raises(ValueError):
        set_setting(db, "walk_hour_utc", True)


def test_yield_settings_defaults_and_types():
    from gtm.settings_store import DEFAULTS
    for k in ("walk_yield_order", "clean_category_strict"):
        assert DEFAULTS[k] is True and setting(k) is True


def test_gemini_lite_price_defaults_are_floats():
    from gtm.settings_store import DEFAULTS
    for k in ("gemini_lite_input_usd_per_m", "gemini_lite_output_usd_per_m"):
        assert isinstance(DEFAULTS[k], float)


def test_sending_on_defaults_false_and_is_a_bool():
    from gtm.settings_store import DEFAULTS

    assert DEFAULTS["sending_on"] is False
    assert setting("sending_on") is False


def test_sheet_defaults():
    want = {"sheet_id": "", "sheet_queue_size": 5, "sheet_queue_on": False, "sheet_queue_hour_utc": 13,
            "sheet_writeback_on": False, "import_hunter_allowance_credits": 0.0}
    from gtm.settings_store import DEFAULTS

    for k, v in want.items():
        assert DEFAULTS[k] == v and type(DEFAULTS[k]) is type(v)


def test_autopilot_defaults_and_types():
    assert (setting("autopilot_on"), setting("autopilot_limit_usd"), setting("autopilot_started_at"),
            setting("autopilot_state"), setting("autopilot_target"), setting("batch_base")) == (False, 2.0, "", "off", 100, {"3": 32})
    set_setting(db, "autopilot_limit_usd", 0)  # 0 = no limit
    assert setting("autopilot_limit_usd") == 0
    for bad in ("x", -1):
        with pytest.raises(ValueError):
            set_setting(db, "autopilot_limit_usd", bad)
    db.table("settings").upsert({"key": "batch_base", "value": "x"}).execute()
    clear_cache()
    assert setting("batch_base") == {"3": 32}


class _FakeDb:
    """Canned settings rows, records upserts: no real row is read or written."""

    def __init__(self, rows):
        self.rows, self.upserts = rows, []

    def table(self, name):
        return self

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def upsert(self, row):
        self.upserts.append(row)
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})


class TestCreditPrices:
    PRICES = ("price_hunter_usd_per_credit", "price_prospeo_usd_per_credit", "price_serper_usd_per_credit")

    @pytest.fixture(autouse=True)
    def restore(self):  # overrides the module fixture, which deletes real settings rows
        clear_cache()
        yield
        clear_cache()

    def test_credit_price_defaults_are_zero_floats_meaning_unpriced(self):
        from gtm.settings_store import DEFAULTS
        for k in self.PRICES:
            assert k in DEFAULTS and DEFAULTS[k] == 0.0 and type(DEFAULTS[k]) is float, k

    def test_negative_credit_price_falls_back_to_default(self):
        fake = _FakeDb([{"value": -1}])
        assert setting("price_hunter_usd_per_credit", fake) == 0.0
        with pytest.raises(ValueError):
            set_setting(fake, "price_hunter_usd_per_credit", -1)
        assert fake.upserts == []

class _FakeSettings:
    """settings table stub: setting(key, db=fake) reads it, nothing touches the real database."""
    def __init__(self, stored):
        self.stored, self.key = stored, None

    def table(self, _):
        return self

    def select(self, _):
        return self

    def eq(self, _, key):
        self.key = key
        return self

    def execute(self):
        self.data = [{"value": self.stored[self.key]}] if self.key in self.stored else []
        return self


def test_recontact_defaults_and_types():
    from gtm.settings_store import DEFAULTS

    want = {"recontact_on": False, "recontact_days": 60, "recontact_max_rounds": 3, "recontact_hunter_allowance_credits": 0.0}
    for k, v in want.items():
        assert DEFAULTS[k] == v and type(DEFAULTS[k]) is type(v)
    for k in ("recontact_days", "recontact_max_rounds"):
        with pytest.raises(ValueError):
            set_setting(None, k, True)  # bool is not an int; a rejected value never reaches the db (None would raise AttributeError)


@pytest.mark.parametrize("key,default", [("recontact_days", 60), ("recontact_max_rounds", 3)])
@pytest.mark.parametrize("bad", [0, -5])
def test_recontact_days_or_rounds_below_one_fall_back_to_default(key, default, bad):
    clear_cache()
    try:
        assert setting(key, _FakeSettings({key: bad})) == default  # a stored 0 or negative must never lift everything
        clear_cache()
        assert setting(key, _FakeSettings({key: 7})) == 7
        with pytest.raises(ValueError):
            set_setting(None, key, bad)
    finally:
        clear_cache()

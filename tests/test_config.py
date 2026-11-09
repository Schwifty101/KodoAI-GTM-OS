from gtm.config import Settings


def test_empty_footer_values_default_blank():
    s = Settings.from_env({})
    assert (s.postal_address, s.ad_disclosure, s.opt_out_line) == ("", "", "")


def test_hunter_keys_collects_numbered_vars():
    s = Settings.from_env({"HUNTER_API_KEY": "a", "HUNTER_API_KEY_2": "b", "HUNTER_API_KEY_4": "d"})
    assert s.hunter_keys == ["a", "b", "d"]


def test_blank_keys_are_ignored():
    assert Settings.from_env({"APIFY_API_KEY": "x", "APIFY_API_KEY_2": ""}).apify_keys == ["x"]


def test_pause_thresholds_have_defaults():
    s = Settings.from_env({})
    assert (s.pause_bounce_rate, s.pause_min_sends) == (0.03, 20)

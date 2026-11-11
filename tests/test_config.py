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


def test_harvest_key_is_read_from_harvest_api_key():
    assert Settings.from_env({"HARVEST_API_KEY": "h"}).harvest_api_key == "h"


def test_vertex_key_is_read_from_the_agent_platform_var():
    assert Settings.from_env({"GEMINI_AGENT_PLATFORM_API_KEY": "v"}).vertex_api_key == "v"


def test_prospeo_key_is_read_from_prospeo_api_key():
    assert Settings.from_env({"PROSPEO_API_KEY": "p"}).prospeo_api_key == "p"


def test_serper_key_is_read_from_serp_api_key():
    assert Settings.from_env({"SERP_API_KEY": "s"}).serper_api_key == "s"

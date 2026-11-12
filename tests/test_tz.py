import pytest

from gtm.tz import lead_tz


@pytest.mark.parametrize("state,city,zone", [
    ("TX", "Houston", "America/Chicago"), ("TX", "El Paso", "America/Denver"),
    ("FL", "Miami", "America/New_York"), ("FL", "Pensacola", "America/Chicago"),
    ("TN", "Knoxville", "America/New_York"), ("TN", "Nashville", "America/Chicago"),
    ("IN", "Gary", "America/Chicago"), ("AZ", "Scottsdale", "America/Phoenix"),
    (None, "Houston", None), ("ZZ", "x", None), ("tx", " HOUSTON ", "America/Chicago"),
    ("Texas", "El Paso", "America/Denver"),  # Apify returns full state names
])
def test_lead_tz(state, city, zone):
    assert lead_tz(state, city) == zone

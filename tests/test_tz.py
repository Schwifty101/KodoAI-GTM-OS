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


E_, C_, M_, P_ = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"


@pytest.mark.parametrize("state,cities,zone", [
    ("TN", ["Farragut", "Maryville", "Oak Ridge", "Powell", "Alcoa", "Hixson", "Ooltewah", "Signal Mountain", "Bristol", "Church Hill"], E_),
    ("FL", ["Gulf Breeze", "Pace", "Milton", "Crestview", "Niceville", "Destin", "Navarre", "Panama City Beach"], C_),
    ("IN", ["Munster", "Hammond", "Gary", "Merrillville", "Valparaiso", "Portage", "Crown Point", "Newburgh", "Evansville"], C_),
    ("KY", ["Henderson", "Oak Grove", "Hopkinsville", "Paducah", "Owensboro", "Bowling Green"], C_),
    ("TX", ["Horizon City", "Socorro", "Canutillo", "Anthony"], M_),
    ("SD", ["Rapid City"], M_),
    ("ID", ["Post Falls", "Hayden", "Coeur d'Alene", "Coeur d’Alene"], P_),
])
def test_split_zone_suburbs(state, cities, zone):
    for c in cities:
        assert lead_tz(state, c) == zone, (state, c)


def test_every_seeded_tile_has_a_zone():
    import csv
    from pathlib import Path
    rows = list(csv.DictReader(open(Path(__file__).parent.parent / "gtm/data/metros.csv")))
    assert rows and all(lead_tz(r["state"], r["tile"]) for r in rows)

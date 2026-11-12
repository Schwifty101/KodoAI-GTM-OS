"""Lead time zone: the state's majority IANA zone, with a small city override table for split states."""

from __future__ import annotations

E, C, M, P = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"
# state -> (majority zone, full name)
_STATES = {
    "AL": (C, "alabama"), "AK": ("America/Anchorage", "alaska"), "AZ": ("America/Phoenix", "arizona"),
    "AR": (C, "arkansas"), "CA": (P, "california"), "CO": (M, "colorado"), "CT": (E, "connecticut"),
    "DE": (E, "delaware"), "DC": (E, "district of columbia"), "FL": (E, "florida"), "GA": (E, "georgia"),
    "HI": ("Pacific/Honolulu", "hawaii"), "ID": (M, "idaho"), "IL": (C, "illinois"), "IN": (E, "indiana"),
    "IA": (C, "iowa"), "KS": (C, "kansas"), "KY": (E, "kentucky"), "LA": (C, "louisiana"), "ME": (E, "maine"),
    "MD": (E, "maryland"), "MA": (E, "massachusetts"), "MI": (E, "michigan"), "MN": (C, "minnesota"),
    "MS": (C, "mississippi"), "MO": (C, "missouri"), "MT": (M, "montana"), "NE": (C, "nebraska"),
    "NV": (P, "nevada"), "NH": (E, "new hampshire"), "NJ": (E, "new jersey"), "NM": (M, "new mexico"),
    "NY": (E, "new york"), "NC": (E, "north carolina"), "ND": (C, "north dakota"), "OH": (E, "ohio"),
    "OK": (C, "oklahoma"), "OR": (P, "oregon"), "PA": (E, "pennsylvania"), "RI": (E, "rhode island"),
    "SC": (E, "south carolina"), "SD": (C, "south dakota"), "TN": (C, "tennessee"), "TX": (C, "texas"),
    "UT": (M, "utah"), "VT": (E, "vermont"), "VA": (E, "virginia"), "WA": (P, "washington"),
    "WV": (E, "west virginia"), "WI": (C, "wisconsin"), "WY": (M, "wyoming"),
}
_BY_NAME = {name: code for code, (_, name) in _STATES.items()}  # Apify returns "Texas", not "TX"
def _z(state: str, zone: str, cities: str) -> dict:
    return {(state, c.strip()): zone for c in cities.split(",")}


# Apify returns the suburb as city, so each split area lists its suburbs, not just the principal city.
_OVERRIDES = {
    **_z("TX", M, "el paso, horizon city, socorro, canutillo, anthony, clint, san elizario, fabens"),
    **_z("FL", C, "pensacola, pensacola beach, gulf breeze, pace, milton, cantonment, navarre, fort walton beach, "
                  "mary esther, shalimar, destin, miramar beach, santa rosa beach, crestview, niceville, "
                  "panama city, panama city beach, lynn haven, callaway, defuniak springs"),
    **_z("TN", E, "knoxville, farragut, maryville, oak ridge, powell, alcoa, lenoir city, sevierville, "
                  "pigeon forge, gatlinburg, morristown, greeneville, cleveland, chattanooga, hixson, ooltewah, "
                  "signal mountain, east ridge, collegedale, soddy-daisy, johnson city, kingsport, bristol, "
                  "church hill, elizabethton"),
    **_z("KY", C, "bowling green, owensboro, paducah, henderson, hopkinsville, oak grove, madisonville, murray, "
                  "glasgow, russellville"),
    **_z("IN", C, "gary, hammond, valparaiso, munster, merrillville, portage, crown point, schererville, highland, "
                  "dyer, east chicago, whiting, griffith, hobart, lake station, michigan city, la porte, chesterton, "
                  "evansville, newburgh, boonville, mount vernon"),
    **_z("ID", P, "coeur d'alene, post falls, hayden, rathdrum, dalton gardens, sandpoint, lewiston, moscow"),
    **_z("SD", M, "rapid city, spearfish, box elder, black hawk, sturgis"),
    **_z("ND", M, "dickinson"),
    **_z("NE", M, "scottsbluff, gering, alliance, chadron, sidney"),
    **_z("KS", M, "goodland"),
    **_z("OR", M, "ontario"),
    **_z("MI", C, "iron mountain, kingsford, iron river, ironwood, menominee, bessemer, wakefield"),
}


def lead_tz(state: str | None, city: str | None) -> str | None:
    s = (state or "").strip().lower()
    code = _BY_NAME.get(s) or s.upper()
    if code not in _STATES:
        return None
    return _OVERRIDES.get((code, (city or "").replace("\u2019", "'").strip().lower()), _STATES[code][0])

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
_OVERRIDES = {
    ("TX", "el paso"): M,
    **{("FL", c): C for c in ("pensacola", "destin", "panama city", "fort walton beach")},
    **{("TN", c): E for c in ("knoxville", "chattanooga", "johnson city", "kingsport")},
    **{("KY", c): C for c in ("bowling green", "owensboro")},
    **{("IN", c): C for c in ("gary", "hammond", "valparaiso", "evansville")},
    ("ID", "coeur d'alene"): P,
}


def lead_tz(state: str | None, city: str | None) -> str | None:
    s = (state or "").strip().lower()
    code = _BY_NAME.get(s) or s.upper()
    if code not in _STATES:
        return None
    return _OVERRIDES.get((code, (city or "").strip().lower()), _STATES[code][0])

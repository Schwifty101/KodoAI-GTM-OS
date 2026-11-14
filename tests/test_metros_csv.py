import csv
from pathlib import Path

STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())


def test_metros_csv():
    path = Path(__file__).parent.parent / "gtm" / "data" / "metros.csv"
    with path.open(newline="") as f:
        assert f.readline().strip() == "metro_rank,metro,state,tile"
        f.seek(0)
        rows = list(csv.DictReader(f))
    assert {r["state"] for r in rows} <= STATES
    keys = [(r["metro"], r["state"], r["tile"]) for r in rows]
    assert len(keys) == len(set(keys))
    ranks, closed, prev = {}, set(), None
    for r in rows:
        m = r["metro"]
        assert ranks.setdefault(m, r["metro_rank"]) == r["metro_rank"], m
        if m != prev:
            assert m not in closed, f"{m} rows not contiguous"
            closed.add(prev)
        prev = m
    assert len(ranks) >= 150

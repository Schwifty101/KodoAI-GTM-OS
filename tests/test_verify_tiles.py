import httpx
import pytest

from scripts import verify_tiles as v


def resp(state="NY", types=("locality", "political"), lat=40.7, lng=-74.0, status="OK", partial=False):
    r = {"status": status, "results": []}
    if status == "OK":
        r["results"] = [{"types": list(types), "formatted_address": "X", "partial_match": partial,
                         "geometry": {"location": {"lat": lat, "lng": lng}},
                         "address_components": [{"short_name": state, "types": ["administrative_area_level_1"]}]}]
    return r


PC = (40.7, -74.0)


def test_haversine_known_pair():
    assert v.haversine(40.7128, -74.0060, 34.0522, -118.2437) == pytest.approx(2445, abs=15)


def test_clean_pass():
    assert v.classify(resp(), "NY", PC, 60)["flags"] == []


@pytest.mark.parametrize("kw,state,flag", [
    (dict(status="ZERO_RESULTS"), "NY", "status"),
    (dict(state="NJ"), "NY", "state_mismatch"),
    (dict(partial=True), "NY", "partial_match"),
    (dict(types=("route",)), "NY", "bad_type"),
    (dict(lat=42.7), "NY", "too_far"),
])
def test_flags(kw, state, flag):
    assert flag in v.classify(resp(**kw), state, PC, 60)["flags"]


def test_dry_run_makes_no_request(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise AssertionError("network call")
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx.Client, "get", boom)
    v.main(["--dry-run", "--limit", "5", "--out", str(tmp_path / "o.csv")])
    out = capsys.readouterr().out
    assert "5 requests" in out and not (tmp_path / "o.csv").exists()

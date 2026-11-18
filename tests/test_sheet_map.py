import pytest

from gtm.sheet import SheetRow
from gtm.sheet_map import blocks, header_map, map_tab

H1 = "business,maps_category,website,buyer_name,buyer_role,linkedin_url,email,email_person,other_people,maps_url".split(",")
HTX = H1 + ["metro", "email_verification", "buyer_verdict"]
H2 = ["Company", "City", "Website", "Fit", "Buyer", "Role", "Role check", "Role evidence (quote)", "Role evidence URL",
      "LinkedIn (confirmed)", "LinkedIn (to check)", "Email", "Email type", "Email status", "Email source", "Notes"]


def row(tab, no, cells, colours=None):
    return SheetRow(tab, no, cells, colours or [None] * len(cells))


def data(**kw):
    c = {k: "" for k in H1}
    c.update(business="Glow Lab", website="https://glowlab.example", buyer_name="Dana Fox", buyer_role="Owner",
             email="dana@glowlab.example", maps_url="https://maps.google.com/?cid=1")
    c.update(kw)
    return [c[k] for k in H1]


def b2row(confirmed="", check=""):
    return ["Sun Spa", "Provo", "sun.example", "", "Kim Roe", "Founder", "", "", "", confirmed, check, "kim@sun.example"]


def test_utah_two_blocks_have_separate_headers():
    rows = [row("Utah", 1, H1), row("Utah", 2, data()), row("Utah", 20, H2), row("Utah", 21, b2row())]
    out = blocks(rows)
    assert len(out) == 2 and out[0][0]["website"] == 2 and out[1][0]["website"] == 2 and out[1][0]["city"] == 1
    assert [r.row_no for r in out[0][1]] == [2] and [r.row_no for r in out[1][1]] == [21]
    m = map_tab("Utah", rows)
    assert [(x.block, x.row_no) for x in m] == [(1, 2), (2, 21)]


def test_utah_block2_columns_map_by_header_text():
    h = header_map(H2)
    assert h["name"] == 0 and h["city"] == 1 and h["website"] == 2 and h["owner_name"] == 4 and h["owner_title"] == 5
    assert h["owner_linkedin"] == 9 and h["owner_linkedin_check"] == 10 and h["owner_email"] == 11
    assert len(set(h.values())) == len(h) and 3 not in h.values()


def test_texas_metro_maps_to_city_and_extra_columns_ignored():
    h = header_map(HTX)
    assert h["city"] == 10 and h["maps_url"] == 9 and h["category"] == 1
    assert 11 not in h.values() and 12 not in h.values()


def test_two_emails_in_one_cell_are_split_and_lowercased():
    m = map_tab("Texas", [row("Texas", 1, H1), row("Texas", 2, data(email="A@x.com; b@Y.com, n/a  c@z.com"))])
    assert m[0].emails == ["a@x.com", "b@y.com", "c@z.com"]


def test_red_wins_over_green():
    cols = ["green", None, "red"] + [None] * 7
    m = map_tab("Texas", [row("Texas", 1, H1), row("Texas", 2, data(), cols)])
    assert m[0].colour == "red"


def test_colour_in_any_cell_marks_the_row():
    cols = [None] * 9 + ["green"]
    m = map_tab("Texas", [row("Texas", 1, H1), row("Texas", 2, data(), cols), row("Texas", 3, data())])
    assert [x.colour for x in m] == ["green", None]


def test_state_comes_from_tab_name():
    for tab, st in [("Utah", "UT"), ("Newyork", "NY"), ("Texas", "TX")]:
        assert map_tab(tab, [row(tab, 1, H1), row(tab, 2, data())])[0].fields["state"] == st


def test_missing_header_raises_value_error_naming_tab():
    with pytest.raises(ValueError, match="Newyork"):
        blocks([row("Newyork", 1, data())])
    with pytest.raises(ValueError, match="Newyork"):
        blocks([], "Newyork")


def test_linkedin_falls_back_to_to_check_column():
    rows = [row("Utah", 20, H2), row("Utah", 21, b2row(check="https://linkedin.com/in/maybe")),
            row("Utah", 22, b2row(confirmed="https://linkedin.com/in/sure", check="https://linkedin.com/in/maybe"))]
    m = map_tab("Utah", rows)
    assert [x.fields["owner_linkedin"] for x in m] == ["https://linkedin.com/in/maybe", "https://linkedin.com/in/sure"]


def test_width_is_header_length():
    assert map_tab("Texas", [row("Texas", 1, HTX), row("Texas", 2, data())])[0].width == len(HTX)


def test_unified_utah_header_and_old_block_two_names_both_read():
    from gtm.sheet_map import MERGE_TARGET
    h = header_map(MERGE_TARGET["Utah"])
    assert h["city"] == 10 and h["owner_linkedin_check"] == 15 and h["owner_email"] == 6 and h["owner_name"] == 3
    old = header_map(H2)
    assert old["city"] == 1 and old["owner_linkedin_check"] == 10

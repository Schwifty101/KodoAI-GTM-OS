from gtm.sitescrape import find_owner_candidates, owner_names_from_html


def names(html):
    return [(n["first_name"], n["last_name"], n["position"]) for n in owner_names_from_html(html)]


def test_name_and_title_on_separate_lines():
    assert names("<div><h3>Dana Whitfield</h3><p>Founder &amp; CEO</p></div>") == [("Dana", "Whitfield", "Founder & CEO")]


def test_title_colon_name():
    assert names("<p>Owner: Dana Whitfield</p>") == [("Dana", "Whitfield", "Owner")]


def test_name_comma_title_and_credentials_are_stripped():
    assert names("<p>Dr. Dana Whitfield, MD - Owner</p>") == [("Dana", "Whitfield", "Owner")]


def test_managers_and_medical_directors_are_ignored():
    html = "<h3>Priya Nair</h3><p>Practice Manager</p><h3>Sam Ortiz</h3><p>Medical Director</p>"
    assert names(html) == []


def test_same_person_listed_twice_is_returned_once():
    assert len(names("<h3>Dana Whitfield</h3><p>Owner</p><p>Dana Whitfield, Owner</p>")) == 1


def test_jsonld_person_with_job_title():
    html = '<script type="application/ld+json">{"@type":"Person","name":"Dana Whitfield","jobTitle":"Founder"}</script>'
    assert names(html) == [("Dana", "Whitfield", "Founder")]


def test_non_names_are_not_returned():
    assert names("<h2>Meet Founder</h2><p>Owner</p><p>Our Team</p><p>CEO</p>") == []


def test_find_owner_candidates_stops_at_first_page_with_a_match():
    pages = {"https://glow.com/about": "<h3>Dana Whitfield</h3><p>Owner</p>"}
    asked = []

    def fetch(url):
        asked.append(url)
        return pages.get(url)

    out = find_owner_candidates("glow.com", fetch)
    assert [(n["first_name"], n["last_name"]) for n in out] == [("Dana", "Whitfield")]
    assert asked == ["https://glow.com/", "https://glow.com/about"]  # nothing fetched after the match

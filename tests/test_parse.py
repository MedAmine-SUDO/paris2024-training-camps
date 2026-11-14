from pathlib import Path

import pytest

from camps.parse import ParseError, parse_camp, parse_search_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def camp():
    html = (FIXTURES / "camp_page.html").read_text(encoding="utf-8")
    return parse_camp(html, "https://prepare.paris2024.org/fr/training-camp/centre-sportif-des-tests/")


def test_identity_and_address(camp):
    assert camp["title"] == "Centre Sportif des Tests"
    assert camp["subtitle"] == "Communauté de Communes Fictive"
    assert camp["address"] == {
        "location": "Villetest, Bretagne",
        "altitude": "Altitude : 120m",  # the non-breaking space is normalized
        "lat": "47.123456789",
        "long": "-2.987654321",
    }


def test_sections_lists_and_spans(camp):
    assert camp["details"]["Disciplines du centre"] == ["Judo", "Para judo", "Judo"]
    assert camp["details"]["Options dans ce centre"] == ["Sauna", "Salle de musculation"]


def test_facility_counts(camp):
    assert camp["summary"] == {"Dojo": 2, "Gymnases multisport": 1}


def test_facilities_are_deduplicated_and_geolocated(camp):
    assert [f["name"] for f in camp["facilities"]] == ["Dojo Principal", "Gymnase Est"]
    assert camp["facilities"][0]["lat"] == "47.12"


def test_script_variables_are_read_as_json(camp):
    assert camp["meteo"]["temp_max"][6] == "24"
    assert camp["gallery"] == ["https://example.org/a.jpg"]


def test_missing_title_raises():
    with pytest.raises(ParseError):
        parse_camp("<html><body><p>not a camp</p></body></html>")


def test_search_page():
    links, count = parse_search_page((FIXTURES / "search_page.html").read_text(encoding="utf-8"))
    assert count == 1000
    assert links == [
        "https://prepare.paris2024.org/fr/training-camp/centre-a/",
        "https://prepare.paris2024.org/fr/training-camp/centre-b/",
    ]

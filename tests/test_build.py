import json
from pathlib import Path

import pandas as pd
import pytest

from camps.build import assert_no_contacts, build, split_location, to_frames
from camps.parse import parse_camp

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def built():
    raw = parse_camp((FIXTURES / "camp_page.html").read_text(encoding="utf-8"),
                     "https://prepare.paris2024.org/fr/training-camp/centre-sportif-des-tests/")
    return build([raw, dict(raw)])  # the same camp twice


def test_duplicates_are_dropped_and_ids_come_from_the_url(built):
    camps, facilities = built
    assert len(camps) == 1
    assert camps[0].camp_id == "centre-sportif-des-tests"
    assert len(facilities) == 2


def test_facts_are_typed_and_normalized(built):
    camp = built[0][0]
    assert (camp.city, camp.region, camp.altitude_m) == ("Villetest", "Bretagne", 120)
    assert camp.lat == pytest.approx(47.123456789)
    assert camp.disciplines == ["Judo", "Para judo"]
    assert camp.para_disciplines == ["Para judo"]
    assert camp.facility_counts == {"Dojo": 2, "Gymnase multisport": 1}  # plural merged
    assert camp.n_facilities == 3
    assert camp.temp_max_c[6] == 24.0


def test_free_text_and_contacts_are_not_kept(built):
    camp, facilities = built[0][0], built[1]
    dumped = json.dumps([camp.model_dump()] + [f.model_dump() for f in facilities], ensure_ascii=False)
    assert "Description" not in dumped and "example.org" not in dumped
    assert_no_contacts(dumped)


@pytest.mark.parametrize("text", ["contact@club.example", "appelez le 01 23 45 67 89", "+33 6 12 34 56 78"])
def test_contact_guard_catches_contacts(text):
    with pytest.raises(ValueError):
        assert_no_contacts(text)


def test_contact_guard_ignores_coordinates():
    assert_no_contacts('{"lat": 48.34560117093884, "lon": -1.0123456789}')


def test_all_zero_climate_means_missing():
    raw = {"title": "X", "address": {}, "meteo": {"temp_max": ["0"] * 12}}
    camp = build([raw])[0][0]
    assert camp.temp_max_c is None


@pytest.mark.parametrize("location, expected", [
    ("Fontainebleau, Île-de-France", ("Fontainebleau", "Île-de-France")),
    ("Metz, Grand-Est", ("Metz", "Grand Est")),
    ("Marseille", ("Marseille", None)),
    (None, (None, None)),
])
def test_split_location(location, expected):
    assert split_location(location) == expected


def test_city_table_fills_missing_region():
    camp = build([{"title": "Y", "address": {"location": "Fort-de-France"}}])[0][0]
    assert (camp.region, camp.region_inferred) == ("Martinique", True)


def test_committed_dataset_is_consistent_and_contact_free():
    camps = pd.read_csv(ROOT / "data/processed/camps.csv")
    facilities = pd.read_csv(ROOT / "data/processed/facilities.csv")
    assert len(camps) == 999 and camps.camp_id.is_unique
    assert set(facilities.camp_id) <= set(camps.camp_id)
    assert camps.region.notna().all()
    for path in ("camps.csv", "facilities.csv", "camps.json"):
        assert_no_contacts((ROOT / "data/processed" / path).read_text(encoding="utf-8"))


def test_frames_flatten_lists(built):
    camps_df, _ = to_frames(*built)
    assert camps_df.loc[0, "disciplines"] == "Judo | Para judo"
    assert camps_df.loc[0, "annual_rainfall_mm"] == 780

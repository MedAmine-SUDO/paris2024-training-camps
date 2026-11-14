"""Turn the raw scrape into a clean, facts-only dataset.

Kept: names, host organisation, location, altitude, coordinates, disciplines,
options, facility counts and positions, and monthly climate normals.

Dropped on purpose: free-text descriptions, photos and anything that could
hold contact details (emails, phone numbers). Those belong to the original
site, not to this dataset. `assert_no_contacts` enforces it on the output.
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Not preceded by a digit or dot, so long coordinate decimals (48.3456011709...) don't match
PHONE = re.compile(r"(?<![\d.])(?:\+33\s?|0)[1-9](?:[ .-]?\d{2}){4}(?!\d)")
REGION_ALIASES = {"Grand-Est": "Grand Est"}
FACILITY_ALIASES = {"Gymnases multisport": "Gymnase multisport"}
# The source gave only a city for these camps; their region is filled in from this table
CITY_REGIONS = {
    "Méjannes-le-Clap": "Occitanie",
    "Baillargues": "Occitanie",
    "Marseille": "Provence-Alpes-Côte d'Azur",
    "Aix-en-Provence": "Provence-Alpes-Côte d'Azur",
    "Saint-Laurent-du-Var": "Provence-Alpes-Côte d'Azur",
    "Ploërmel": "Bretagne",
    "Sarralbe": "Grand Est",
    "Saint-Rémy-les-Chevreuse": "Île-de-France",
    "Gif-sur-Yvette": "Île-de-France",
    "Saint-Martin-d'Uriage": "Auvergne-Rhône-Alpes",
    "Chantonnay": "Pays de la Loire",
    "Saint-Paul-lès-Dax": "Nouvelle-Aquitaine",
    "Nouméa": "Nouvelle-Calédonie",
    "Fort-de-France": "Martinique",
    "Le Lamentin": "Martinique",
}
PARA_MARKERS = ("para", "fauteuil", "cécifoot", "goalball", "boccia", "assis", "torball")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


class Facility(BaseModel):
    camp_id: str
    name: str
    type: str | None
    lat: float | None
    lon: float | None


class Camp(BaseModel):
    camp_id: str
    name: str
    host: str | None
    city: str | None
    region: str | None
    region_inferred: bool = False
    altitude_m: int | None
    lat: float | None
    lon: float | None
    disciplines: list[str]
    para_disciplines: list[str]
    options: list[str]
    facility_counts: dict[str, int]
    n_facilities: int
    temp_min_c: list[float] | None
    temp_max_c: list[float] | None
    rainfall_mm: list[float] | None


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series(meteo: dict, key: str) -> list[float] | None:
    values = [_float(v) for v in meteo.get(key, [])]
    if len(values) != 12 or None in values or not any(values):
        return None  # the source fills missing climate data with twelve zeros
    return values


def split_location(location: str | None) -> tuple[str | None, str | None]:
    if not location:
        return None, None
    city, _, region = location.rpartition(",")
    if not city:  # no comma: only one part given
        return location.strip() or None, None
    region = region.strip()
    return city.strip() or None, REGION_ALIASES.get(region, region) or None


def is_para(discipline: str) -> bool:
    return any(marker in discipline.lower() for marker in PARA_MARKERS)


def clean_camp(raw: dict, camp_id: str) -> tuple[Camp, list[Facility]]:
    address = raw.get("address", {})
    city, region = split_location(address.get("location"))
    altitude = re.search(r"(-?\d[\d\s]*)\s*m", address.get("altitude") or "")
    meteo = raw.get("meteo") or {}
    if isinstance(meteo, str):  # the first scraper stored it as a JSON string
        meteo = json.loads(meteo) if meteo.strip() else {}

    counts: dict[str, int] = {}
    for facility_type, n in (raw.get("summary") or {}).items():
        key = FACILITY_ALIASES.get(facility_type, facility_type)
        counts[key] = counts.get(key, 0) + int(n)

    details = raw.get("details") or {}
    disciplines = sorted(set(details.get("Disciplines du centre", [])))
    raw_facilities = raw.get("facilities", raw.get("fascilities", []))  # old key was misspelled
    facilities = [
        Facility(
            camp_id=camp_id,
            name=f["name"],
            type=FACILITY_ALIASES.get(f.get("type"), f.get("type")),
            lat=_float(f.get("lat")),
            lon=_float(f.get("long", f.get("lng"))),
        )
        for f in raw_facilities
        if f.get("name")
    ]
    camp = Camp(
        camp_id=camp_id,
        name=raw["title"],
        host=raw.get("subtitle"),
        city=city,
        region=region,
        altitude_m=int(altitude.group(1).replace(" ", "")) if altitude else None,
        lat=_float(address.get("lat")),
        lon=_float(address.get("long")),
        disciplines=disciplines,
        para_disciplines=[d for d in disciplines if is_para(d)],
        options=sorted(set(details.get("Options dans ce centre", []))),
        facility_counts=counts,
        n_facilities=sum(counts.values()),
        temp_min_c=_series(meteo, "temp_min"),
        temp_max_c=_series(meteo, "temp_max"),
        rainfall_mm=_series(meteo, "rainfall"),
    )
    return camp, facilities


def build(raw_records: list[dict]) -> tuple[list[Camp], list[Facility]]:
    camps, facilities, used_ids = [], [], set()
    seen_names: set[tuple] = set()
    for raw in raw_records:
        identity = (raw.get("title"), (raw.get("address") or {}).get("lat"), (raw.get("address") or {}).get("long"))
        if identity in seen_names:  # the same camp listed twice
            continue
        seen_names.add(identity)
        base = slugify(raw["url"].rstrip("/").rsplit("/", 1)[-1]) if raw.get("url") else slugify(raw["title"])
        camp_id, n = base, 2
        while camp_id in used_ids:
            camp_id, n = f"{base}-{n}", n + 1
        used_ids.add(camp_id)
        camp, camp_facilities = clean_camp(raw, camp_id)
        camps.append(camp)
        facilities.extend(camp_facilities)
    for camp in camps:
        if not camp.region and camp.city in CITY_REGIONS:
            camp.region, camp.region_inferred = CITY_REGIONS[camp.city], True
    return camps, facilities


def assert_no_contacts(text: str) -> None:
    emails, phones = EMAIL.findall(text), PHONE.findall(text)
    if emails or phones:
        raise ValueError(f"contact details leaked into the dataset: {len(emails)} emails, {len(phones)} phones")


def to_frames(camps: list[Camp], facilities: list[Facility]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for c in camps:
        row = c.model_dump(exclude={"disciplines", "para_disciplines", "options", "facility_counts",
                                    "temp_min_c", "temp_max_c", "rainfall_mm"})
        row["disciplines"] = " | ".join(c.disciplines)
        row["para_disciplines"] = " | ".join(c.para_disciplines)
        row["options"] = " | ".join(c.options)
        row["n_disciplines"] = len(c.disciplines)
        row["temp_min_jan_c"] = c.temp_min_c[0] if c.temp_min_c else None
        row["temp_max_jul_c"] = c.temp_max_c[6] if c.temp_max_c else None
        row["annual_rainfall_mm"] = round(sum(c.rainfall_mm)) if c.rainfall_mm else None
        rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame([f.model_dump() for f in facilities])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the facts-only dataset from the raw scrape.")
    parser.add_argument("--raw", type=Path, default=Path("data/raw/trainingcamps.json"))
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    camps, facilities = build(json.loads(args.raw.read_text(encoding="utf-8")))
    camps_df, facilities_df = to_frames(camps, facilities)
    nested = json.dumps([c.model_dump() for c in camps], ensure_ascii=False, indent=1)
    for text in (nested, camps_df.to_csv(index=False), facilities_df.to_csv(index=False)):
        assert_no_contacts(text)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "camps.json").write_text(nested, encoding="utf-8")
    camps_df.to_csv(args.out / "camps.csv", index=False)
    facilities_df.to_csv(args.out / "facilities.csv", index=False)
    print(f"{len(camps)} camps, {len(facilities)} facilities -> {args.out}/")


if __name__ == "__main__":
    main()

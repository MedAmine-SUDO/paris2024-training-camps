"""Parse one training-camp page from the Paris 2024 "Prepare" directory into a raw record.

The raw record mirrors the page: it keeps everything, including free text and
photos. `camps.build` later reduces it to a facts-only dataset.
"""

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

_NBSP = re.compile(r"\xa0")
_METEO = re.compile(r"var meteo = (\{.*?\});", re.DOTALL)
_MARKERS = re.compile(r"var markers = (\[.*?\]);", re.DOTALL)


class ParseError(ValueError):
    """The page is missing an element every camp page has."""


def _text(node: Tag | None) -> str | None:
    return _NBSP.sub(" ", node.get_text(strip=True)) if node else None


def _required(soup: BeautifulSoup, tag: str, cls: str) -> str:
    value = _text(soup.find(tag, class_=cls))
    if not value:
        raise ParseError(f"missing <{tag} class={cls}>")
    return value


def parse_address(soup: BeautifulSoup) -> dict[str, Any]:
    address: dict[str, Any] = {}
    node = soup.find("address", class_="training-camp__address")
    if node:
        spans = node.find_all("span")
        if spans:
            address["location"] = _text(spans[0])
        if len(spans) > 1:
            address["altitude"] = _text(spans[1])
    map_div = soup.find("div", class_="block-presentation__map")
    if map_div and map_div.get("data-center"):
        center = json.loads(map_div["data-center"])
        address["lat"], address["long"] = center.get("lat"), center.get("lng")
    return address


def parse_summary(soup: BeautifulSoup) -> dict[str, int]:
    """Facility counts, e.g. {"Stade": 2, "Dojo": 1}."""
    summary: dict[str, int] = {}
    node = soup.find("div", class_="block-facilities__summary")
    for figure in node.find_all("div", class_="block-facilities__figure") if node else []:
        if figure.strong and figure.span:
            summary[_text(figure.span)] = int(_text(figure.strong))
    return summary


def parse_details(soup: BeautifulSoup) -> dict[str, list[str]]:
    """Titled sections (disciplines, options, description...) -> list of text values."""
    details: dict[str, list[str]] = {}
    node = soup.find("div", class_="block-presentation__details")
    if not node:
        return details
    for heading in node.find_all(["h2", "h3"], class_="block-presentation__title"):
        values: list[str] = []
        sibling = heading.find_next_sibling()
        while sibling is not None and sibling.name not in ("h2", "h3"):
            if sibling.name == "ul":
                values.extend(_text(li) for li in sibling.find_all("li") if _text(li))
            elif sibling.name == "p" and sibling.find_all("span"):
                values.extend(_text(s) for s in sibling.find_all("span") if _text(s))
            elif _text(sibling):
                values.append(_text(sibling))
            sibling = sibling.find_next_sibling()
        details[_text(heading)] = values
    return details


def parse_script_data(soup: BeautifulSoup) -> tuple[dict, list[dict]]:
    """Climate normals and facility map markers, embedded as JS variables.

    They are JSON literals, so they're read with json.loads (never eval).
    """
    script = soup.find("script", id="sage/main.js-js-extra")
    content = (script.string or "") if script else ""
    meteo_match, markers_match = _METEO.search(content), _MARKERS.search(content)
    meteo = json.loads(meteo_match.group(1)) if meteo_match else {}
    markers = json.loads(markers_match.group(1)) if markers_match else []
    return meteo, markers


def parse_facilities(soup: BeautifulSoup, markers: list[dict]) -> list[dict]:
    by_name = {m.get("name"): m for m in markers}
    facilities, seen = [], set()
    slider = soup.find("div", class_=lambda c: c and "block-facilities__slider" in c)
    for item in slider.select("ul.glide__slides > li") if slider else []:
        name = _text(item.find("div", class_="block-facilities__slider__name"))
        if not name or name in seen:
            continue
        seen.add(name)
        marker = by_name.get(name, {})
        img = item.find("img")
        facilities.append({
            "name": name,
            "type": _text(item.find("div", class_="block-facilities__slider__type")),
            "lat": marker.get("lat"),
            "long": marker.get("lng"),
            "src": img.get("src") if img else None,
        })
    return facilities


def parse_gallery(soup: BeautifulSoup) -> list[str]:
    gallery = soup.find("div", class_=lambda c: c and "block-gallery__slider" in c)
    srcs = [img.get("src") for img in gallery.select("ul.glide__slides img")] if gallery else []
    return list(dict.fromkeys(s for s in srcs if s))


def parse_camp(html: str, url: str | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    meteo, markers = parse_script_data(soup)
    return {
        "url": url,
        "title": _required(soup, "h1", "training-camp__title"),
        "subtitle": _text(soup.find("p", class_="training-camp__subtitle")),
        "address": parse_address(soup),
        "summary": parse_summary(soup),
        "details": parse_details(soup),
        "facilities": parse_facilities(soup, markers),
        "gallery": parse_gallery(soup),
        "meteo": meteo,
    }


def parse_search_page(html: str) -> tuple[list[str], int]:
    """Return (camp detail links, result count shown on the page)."""
    soup = BeautifulSoup(html, "html.parser")
    counter = _text(soup.find("div", class_="resultsCounter")) or "0"
    links = [a["href"] for a in soup.find_all("a", class_="btn hidden") if a.get("href")]
    return links, int("".join(ch for ch in counter if ch.isdigit()) or 0)

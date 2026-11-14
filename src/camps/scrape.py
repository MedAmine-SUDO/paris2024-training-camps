"""Crawl the camp directory: search pages -> detail links -> parsed raw records.

The original site (prepare.paris2024.org) went offline after the Games, so this
step can no longer run live. It is kept as the documented, tested ingestion
step that produced `data/raw/trainingcamps.json`.

Compared with the first version (Selenium, a new browser per page, fixed
5-second sleeps), it fetches over plain HTTP with a shared connection pool,
bounded concurrency, polite rate limiting and retries.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

import httpx

from .parse import ParseError, parse_camp, parse_search_page

BASE_URL = "https://prepare.paris2024.org"
SEARCH_PATH = "/fr/search/"
log = logging.getLogger("camps.scrape")


async def fetch(client: httpx.AsyncClient, url: str, retries: int = 3) -> str:
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code not in (429, 500, 502, 503, 504):
                resp.raise_for_status()
        except httpx.TransportError:
            if attempt == retries:
                raise
        await asyncio.sleep(2**attempt)
    raise httpx.HTTPError(f"giving up on {url}")


async def collect_links(client: httpx.AsyncClient, max_pages: int = 200) -> list[str]:
    links: list[str] = []
    for page in range(1, max_pages + 1):
        page_links, count = parse_search_page(await fetch(client, f"{SEARCH_PATH}?page={page}"))
        if count == 0 or not page_links:
            break
        links.extend(page_links)
        log.info("search page %d: %d links (%d total)", page, len(page_links), len(links))
    return list(dict.fromkeys(links))


async def scrape(out: Path, concurrency: int = 4, delay: float = 0.5) -> int:
    async with httpx.AsyncClient(
        base_url=BASE_URL, timeout=30, follow_redirects=True,
        headers={"User-Agent": "paris2024-training-camps (portfolio project)"},
    ) as client:
        links = await collect_links(client)
        semaphore = asyncio.Semaphore(concurrency)
        records, failures = [], 0

        async def one(url: str) -> None:
            nonlocal failures
            async with semaphore:
                try:
                    records.append(parse_camp(await fetch(client, url), url))
                except (httpx.HTTPError, ParseError) as exc:
                    failures += 1
                    log.warning("skipped %s: %s", url, exc)
                await asyncio.sleep(delay)

        await asyncio.gather(*(one(url) for url in links))

    out.parent.mkdir(parents=True, exist_ok=True)
    # Written once, as a single JSON array (the first version appended per run)
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("saved %d camps to %s (%d failed)", len(records), out, failures)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("data/raw/trainingcamps.json"))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests per worker")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(scrape(args.out, args.concurrency, args.delay))


if __name__ == "__main__":
    main()

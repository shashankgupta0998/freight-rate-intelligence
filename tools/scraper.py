"""Multi-source rate scraper — three parsers, one aggregator.

v1 reads HTML from tests/fixtures/ (LIVE_SCRAPING=false, both default and
production). Parses three structurally distinct fixtures and normalises
everything into a flat list of ScrapedRate dicts.

Live HTTP is not wired in v1: LIVE_SCRAPING=true raises NotImplementedError.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup

logger = logging.getLogger("scraper")

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


# ---- Types ----

@dataclass(frozen=True)
class Query:
    origin: str
    destination: str
    chargeable_weight_kg: float
    mode: str | None = None


@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str
    fixture: str
    parser: Callable[[str], list[dict]]


# ---- Shared helpers ----

_PRICE_RE = re.compile(r"[0-9][0-9,]*\.?[0-9]*")
_ISO_DURATION_RE = re.compile(r"P(\d+)D")

_COURIER_TOKENS = ("courier", "express", "door")
_ROAD_TOKENS = ("road", "truck", "trucking")
_SEA_TOKENS = ("sea", "ocean", "lcl", "fcl")
_AIR_TOKENS = ("air",)


def _normalise_mode(text: str | None) -> str:
    """Map a free-text mode label to one of the four ScrapedRate-approved values."""
    if not text:
        return "air_freight"
    t = text.lower()
    if any(k in t for k in _COURIER_TOKENS):
        return "courier"
    if any(k in t for k in _ROAD_TOKENS):
        return "road_freight"
    if any(k in t for k in _SEA_TOKENS):
        return "sea_freight"
    if any(k in t for k in _AIR_TOKENS):
        return "air_freight"
    return "air_freight"


def _parse_usd(text: str) -> float:
    """Parse '$1,245.50' or '1,245.50' or '1245.50' -> 1245.50."""
    cleaned = text.replace(",", "").replace("$", "").strip()
    match = _PRICE_RE.search(cleaned)
    if not match:
        raise ValueError(f"no numeric value in {text!r}")
    return float(match.group())


def _parse_duration_days(datetime_attr: str) -> int:
    """Parse ISO 8601 duration 'P7D' -> 7."""
    m = _ISO_DURATION_RE.match(datetime_attr)
    if not m:
        raise ValueError(f"not a P<N>D duration: {datetime_attr!r}")
    return int(m.group(1))


def _parse_days_from_text(text: str) -> int:
    """Extract an integer day count from free text like '32 days'."""
    m = _PRICE_RE.search(text)
    if not m:
        raise ValueError(f"no day count in {text!r}")
    return int(float(m.group()))


# ---- Per-site parsers ----

def parse_freightos(html: str) -> list[dict]:
    """List-of-cards DOM: <ul class="quote-results"><li class="quote-card">..."""
    soup = BeautifulSoup(html, "lxml")
    rates: list[dict] = []
    for card in soup.select("ul.quote-results li.quote-card"):
        try:
            carrier = card.select_one(".carrier-name").text.strip()
            price = _parse_usd(card.select_one(".price-usd").text)
            transit_el = card.select_one("time.transit")
            transit = _parse_duration_days(transit_el["datetime"])
            booking_url = card.select_one("a.book-link")["href"]
            mode = _normalise_mode(card.select_one(".mode-label").text)
            rates.append({
                "carrier": carrier,
                "base_price_usd": price,
                "transit_days": transit,
                "booking_url": booking_url,
                "mode": mode,
            })
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.debug("freightos: skipped malformed card: %s", e)
    return rates


def parse_icontainers(html: str) -> list[dict]:
    """Table DOM: <table class="rates-table"><tbody><tr class="rate-row">..."""
    soup = BeautifulSoup(html, "lxml")
    rates: list[dict] = []
    table = soup.find("table", class_="rates-table")
    if table is None:
        return rates
    tbody = table.find("tbody")
    if tbody is None:
        return rates
    for row in tbody.find_all("tr", class_="rate-row"):
        try:
            carrier = row.find("td", class_="carrier").text.strip()
            price_td = row.find("td", class_="price")
            data_usd = price_td.get("data-usd")
            price = float(data_usd) if data_usd else _parse_usd(price_td.text)
            transit_td = row.find("td", class_="transit")
            data_days = transit_td.get("data-days")
            transit = int(data_days) if data_days else _parse_days_from_text(transit_td.text)
            booking_url = row.find("a", class_="book")["href"]
            mode = _normalise_mode(row.find("td", class_="mode").text)
            rates.append({
                "carrier": carrier,
                "base_price_usd": price,
                "transit_days": transit,
                "booking_url": booking_url,
                "mode": mode,
            })
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.debug("icontainers: skipped malformed row: %s", e)
    return rates


def parse_searates(html: str) -> list[dict]:
    """Semantic HTML5: <article class="rate" data-carrier data-mode>..."""
    soup = BeautifulSoup(html, "lxml")
    rates: list[dict] = []
    for article in soup.find_all("article", class_="rate"):
        try:
            carrier = (article.get("data-carrier") or "").strip()
            if not carrier:
                continue
            price_data = article.find("data", class_="price")
            price = float(price_data["value"])
            transit_el = article.find("time", class_="transit")
            transit = _parse_duration_days(transit_el["datetime"])
            booking_url = article.find("a", class_="book")["href"]
            mode = _normalise_mode(article.get("data-mode"))
            rates.append({
                "carrier": carrier,
                "base_price_usd": price,
                "transit_days": transit,
                "booking_url": booking_url,
                "mode": mode,
            })
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.debug("searates: skipped malformed article: %s", e)
    return rates


# ---- Site registry ----

SITES: dict[str, SiteConfig] = {
    "freightos": SiteConfig(
        name="freightos",
        url="https://ship.freightos.com/",
        fixture="freightos_delhi_rotterdam.html",
        parser=parse_freightos,
    ),
    "icontainers": SiteConfig(
        name="icontainers",
        url="https://www.icontainers.com/",
        fixture="icontainers_delhi_rotterdam.html",
        parser=parse_icontainers,
    ),
    "searates": SiteConfig(
        name="searates",
        url="https://www.searates.com/",
        fixture="searates_delhi_rotterdam.html",
        parser=parse_searates,
    ),
}


# ---- Fetcher (fixture vs live dispatch) ----

def fetch_site(site_name: str, query: Query) -> str:
    """Return raw HTML for a site. v1 reads from tests/fixtures/."""
    cfg = SITES[site_name]
    if os.getenv("LIVE_SCRAPING", "false").lower() == "true":
        raise NotImplementedError(
            "live scraping not wired in v1 -- set LIVE_SCRAPING=false "
            "and use fixtures"
        )
    fixture_path = FIXTURE_DIR / cfg.fixture
    return fixture_path.read_text(encoding="utf-8")


# ---- Aggregator ----

def scrape_all(query: Query) -> list[dict]:
    """Run every configured site, concatenating parsed ScrapedRate dicts.

    Per-site failures are logged at WARNING and skipped; other sites continue.
    Returns [] only if every site fails.
    """
    results: list[dict] = []
    successes = 0
    for site_name, cfg in SITES.items():
        try:
            html = fetch_site(site_name, query)
            site_rates = cfg.parser(html)
            now = datetime.now(timezone.utc).isoformat()
            for r in site_rates:
                r["source_site"] = site_name
                r["chargeable_weight_kg"] = query.chargeable_weight_kg
                r["scraped_at"] = now
            results.extend(site_rates)
            successes += 1
            logger.info("%s -> %d rates", site_name, len(site_rates))
        except Exception as e:
            logger.warning("%s failed (%s), skipping", site_name, e)
            logger.debug("%s traceback", site_name, exc_info=True)
    logger.info(
        "scrape_all -> %d rates from %d/%d sites",
        len(results),
        successes,
        len(SITES),
    )
    return results

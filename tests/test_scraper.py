"""Unit tests for tools/scraper.py — three parsers + helpers + aggregator + fetcher."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.scraper import (
    FIXTURE_DIR,
    Query,
    _ISO_DURATION_RE,
    _normalise_mode,
    _parse_duration_days,
    _parse_usd,
    fetch_site,
    parse_freightos,
    parse_icontainers,
    parse_searates,
    scrape_all,
)


def _fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ---- Parsers ----

def test_parse_freightos_returns_four_rates():
    rates = parse_freightos(_fixture_text("freightos_delhi_rotterdam.html"))
    assert len(rates) == 4
    assert {r["carrier"] for r in rates} == {
        "Lufthansa Cargo",
        "Emirates SkyCargo",
        "Qatar Airways Cargo",
        "KLM Cargo",
    }
    assert all(r["mode"] == "air_freight" for r in rates)


def test_parse_freightos_includes_card_html():
    rates = parse_freightos(_fixture_text("freightos_delhi_rotterdam.html"))
    for r in rates:
        assert "_card_html" in r
        assert len(r["_card_html"]) > 50


def test_parse_icontainers_data_usd_and_text_fallback():
    rates = parse_icontainers(_fixture_text("icontainers_delhi_rotterdam.html"))
    by_carrier = {r["carrier"]: r for r in rates}
    # Maersk row has data-usd=1245.50 (attribute path)
    assert by_carrier["Maersk"]["base_price_usd"] == 1245.50
    # MSC row has no data-usd, must fall back to text parsing
    assert by_carrier["MSC"]["base_price_usd"] == 1180.00


def test_parse_searates_uses_data_attributes():
    rates = parse_searates(_fixture_text("searates_delhi_rotterdam.html"))
    assert {r["carrier"] for r in rates} == {"Hapag-Lloyd", "ONE", "Evergreen"}
    assert all(r["mode"] == "sea_freight" for r in rates)


def test_parsers_handle_empty_html():
    assert parse_freightos("") == []
    assert parse_icontainers("") == []
    assert parse_searates("") == []


def test_parse_freightos_skips_malformed_card(caplog):
    # Missing .carrier-name span in the first card
    html = """
    <ul class="quote-results">
      <li class="quote-card">
        <span class="mode-label">Air Freight</span>
        <span class="price-usd">$500.00</span>
        <time class="transit" datetime="P7D">7</time>
        <a class="book-link" href="https://x.com/b">Book</a>
      </li>
      <li class="quote-card">
        <span class="carrier-name">Good Carrier</span>
        <span class="mode-label">Air Freight</span>
        <span class="price-usd">$600.00</span>
        <time class="transit" datetime="P8D">8</time>
        <a class="book-link" href="https://x.com/c">Book</a>
      </li>
    </ul>
    """
    rates = parse_freightos(html)
    assert len(rates) == 1
    assert rates[0]["carrier"] == "Good Carrier"


# ---- Helpers ----

def test_normalise_mode_air():
    assert _normalise_mode("Air Freight") == "air_freight"
    assert _normalise_mode("AIR") == "air_freight"


def test_normalise_mode_sea_variants():
    assert _normalise_mode("LCL Sea") == "sea_freight"
    assert _normalise_mode("FCL Ocean") == "sea_freight"
    assert _normalise_mode("sea_freight") == "sea_freight"


def test_normalise_mode_courier():
    assert _normalise_mode("Courier Express") == "courier"
    assert _normalise_mode("express door-to-door") == "courier"


def test_normalise_mode_none_defaults_to_air():
    assert _normalise_mode(None) == "air_freight"
    assert _normalise_mode("") == "air_freight"


def test_parse_usd_variants():
    assert _parse_usd("$1,245.50") == 1245.50
    assert _parse_usd("1245.50") == 1245.50
    assert _parse_usd("$800") == 800.0


def test_parse_usd_raises_on_non_numeric():
    with pytest.raises(ValueError):
        _parse_usd("not a price")


def test_parse_duration_days_valid_and_invalid():
    assert _parse_duration_days("P7D") == 7
    assert _parse_duration_days("P35D") == 35
    with pytest.raises(ValueError):
        _parse_duration_days("7 days")


# ---- Aggregator + Fetcher ----

def test_scrape_all_returns_ten_rates():
    rates = scrape_all(Query("Delhi", "Rotterdam", 200.0))
    assert len(rates) == 10
    required = {
        "carrier",
        "base_price_usd",
        "chargeable_weight_kg",
        "transit_days",
        "booking_url",
        "source_site",
        "scraped_at",
        "mode",
    }
    for r in rates:
        assert required <= r.keys()


def test_scrape_all_continue_on_error(monkeypatch, caplog):
    # Patch icontainers parser to raise — other sites must still return
    def boom(html):
        raise RuntimeError("simulated parser failure")

    from tools import scraper

    # Dataclass fields are frozen — so monkeypatch the whole SiteConfig
    from dataclasses import replace

    patched_site = replace(scraper.SITES["icontainers"], parser=boom)
    monkeypatch.setitem(scraper.SITES, "icontainers", patched_site)

    rates = scrape_all(Query("Delhi", "Rotterdam", 200.0))
    # freightos (4) + searates (3) = 7
    assert len(rates) == 7
    assert not any(r["source_site"] == "icontainers" for r in rates)


def test_fetch_site_live_scraping_raises(monkeypatch):
    monkeypatch.setenv("LIVE_SCRAPING", "true")
    with pytest.raises(NotImplementedError, match="live scraping not wired"):
        fetch_site("freightos", Query("Delhi", "Rotterdam", 200.0))

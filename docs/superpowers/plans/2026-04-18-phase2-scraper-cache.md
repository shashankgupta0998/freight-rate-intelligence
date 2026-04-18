# Phase 2 — Scraper + Cache + Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-source rate scraper (pure-function parsers against hand-crafted HTML fixtures) and a SQLite rate cache with 6h TTL, both production-shaped and test-ready.

**Architecture:** `tools/scraper.py` has three distinct parsers (list-of-cards for freightos, table for icontainers, semantic-HTML5 for searates) feeding a continue-on-error aggregator. `tools/cache.py` wraps SQLite with a `(origin, destination, query_date)` key and a 6h read-time TTL. Neither module imports the other — the Phase 3 orchestrator will compose them. Live HTTP is deliberately not wired in v1 (`LIVE_SCRAPING=true` raises `NotImplementedError`).

**Tech Stack:** Python 3.11+, `beautifulsoup4` (+ `lxml` backend), stdlib `sqlite3` / `json` / `logging` / `argparse` / `dataclasses`. Managed via `uv` + `pyproject.toml`.

**Source spec:** `docs/superpowers/specs/2026-04-18-phase2-scraper-cache-design.md`

**Tests:** Deferred to Phase 5 per the approved spec. Each task uses manual verification commands instead of pytest. Code is factored so every parser is a pure `html → list[dict]` function and cache I/O is isolated to four public functions — all trivially unit-testable when Phase 5 lands.

---

## Task 1: Add beautifulsoup4 + lxml to dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

Replace the `dependencies` list to add `beautifulsoup4` and `lxml`. Final block:

```toml
dependencies = [
  "requests>=2.31",
  "python-dotenv>=1.0",
  "beautifulsoup4>=4.12",
  "lxml>=5.2",
]
```

(Leave `[tool.uv]`, `[tool.hatch.build.targets.wheel]`, `[build-system]` and every other section untouched.)

- [ ] **Step 2: Sync**

```bash
uv sync
```
Expected: resolves to ~9 packages total (previously 7 + bs4 + lxml + soupsieve). No errors.

- [ ] **Step 3: Verify imports**

```bash
uv run python -c "import bs4, lxml; print('bs4:', bs4.__version__, '| lxml:', lxml.__version__)"
```
Expected: prints both version strings; exit 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add beautifulsoup4 + lxml for Phase 2 scraper"
```

---

## Task 2: Create package scaffolding for tools/ and tests/

**Files:**
- Create: `tools/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/fixtures/__init__.py` (empty)

- [ ] **Step 1: Create directories and empty files**

```bash
mkdir -p tools tests/fixtures
touch tools/__init__.py tests/__init__.py tests/fixtures/__init__.py
```

- [ ] **Step 2: Verify**

```bash
ls -la tools/ tests/ tests/fixtures/
```
Expected: each directory contains an `__init__.py` (0 bytes).

- [ ] **Step 3: Commit**

```bash
git add tools/__init__.py tests/__init__.py tests/fixtures/__init__.py
git commit -m "feat: scaffold tools/ and tests/fixtures/ packages for Phase 2"
```

---

## Task 3: Create freightos fixture (list-of-cards DOM)

**Files:**
- Create: `tests/fixtures/freightos_delhi_rotterdam.html`

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/freightos_delhi_rotterdam.html` with EXACTLY this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Freightos — Quote results: Delhi → Rotterdam</title>
</head>
<body>
<main>
  <h1>Quote results for Delhi (DEL) → Rotterdam (RTM), 200 kg</h1>
  <ul class="quote-results">
    <li class="quote-card" data-carrier="lufthansa-cargo">
      <span class="carrier-name">Lufthansa Cargo</span>
      <span class="mode-label">Air Freight</span>
      <span class="price-usd">$892.00</span>
      <time class="transit" datetime="P7D">7 days</time>
      <ul class="surcharges">
        <li><span class="fee-name">Fuel surcharge</span><span class="fee-amount">$78</span></li>
        <li><span class="fee-name">Security fee</span><span class="fee-amount">$25</span></li>
      </ul>
      <a class="book-link" href="https://ship.freightos.com/book/LH-ABC123">Book</a>
    </li>
    <li class="quote-card" data-carrier="emirates-skycargo">
      <span class="carrier-name">Emirates SkyCargo</span>
      <span class="mode-label">Air Freight</span>
      <span class="price-usd">$845.00</span>
      <time class="transit" datetime="P8D">8 days</time>
      <ul class="surcharges">
        <li><span class="fee-name">Fuel surcharge</span><span class="fee-amount">$72</span></li>
        <li><span class="fee-name">Peak season surcharge</span><span class="fee-amount">$40</span></li>
      </ul>
      <a class="book-link" href="https://ship.freightos.com/book/EK-DEF456">Book</a>
    </li>
    <li class="quote-card" data-carrier="qatar-airways-cargo">
      <span class="carrier-name">Qatar Airways Cargo</span>
      <span class="mode-label">Air Freight</span>
      <span class="price-usd">$910.00</span>
      <time class="transit" datetime="P6D">6 days</time>
      <!-- No surcharges block — Phase 3 hidden-charge detector should flag this -->
      <a class="book-link" href="https://ship.freightos.com/book/QR-GHI789">Book</a>
    </li>
    <li class="quote-card" data-carrier="klm-cargo">
      <span class="carrier-name">KLM Cargo</span>
      <span class="mode-label">Air Freight</span>
      <span class="price-usd">$1,024.00</span>
      <time class="transit" datetime="P9D">9 days</time>
      <ul class="surcharges">
        <li><span class="fee-name">Fuel surcharge</span><span class="fee-amount">$88</span></li>
        <li><span class="fee-name">Security fee</span><span class="fee-amount">$28</span></li>
      </ul>
      <a class="book-link" href="https://ship.freightos.com/book/KL-JKL012">Book</a>
    </li>
  </ul>
</main>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/freightos_delhi_rotterdam.html
git commit -m "feat(fixtures): add freightos Delhi→Rotterdam fixture (4 air cards, 1 no-surcharge)"
```

---

## Task 4: Create icontainers fixture (table DOM)

**Files:**
- Create: `tests/fixtures/icontainers_delhi_rotterdam.html`

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/icontainers_delhi_rotterdam.html` with EXACTLY this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>iContainers — Rates: Delhi → Rotterdam</title>
</head>
<body>
<main>
  <h1>LCL rates Delhi → Rotterdam (200 kg)</h1>
  <table class="rates-table">
    <thead>
      <tr><th>Carrier</th><th>Mode</th><th>Total USD</th><th>Transit</th><th>Book</th></tr>
    </thead>
    <tbody>
      <tr class="rate-row" data-rate-id="R1">
        <td class="carrier">Maersk</td>
        <td class="mode">LCL Sea</td>
        <td class="price" data-usd="1245.50">$1,245.50</td>
        <td class="transit" data-days="32">32 days</td>
        <td><a class="book" href="https://www.icontainers.com/book/R1">Book</a></td>
      </tr>
      <tr class="rate-row" data-rate-id="R2">
        <td class="carrier">MSC</td>
        <td class="mode">LCL Sea</td>
        <td class="price">$1,180.00</td>
        <td class="transit" data-days="35">35 days</td>
        <td><a class="book" href="https://www.icontainers.com/book/R2">Book</a></td>
      </tr>
      <tr class="rate-row" data-rate-id="R3">
        <td class="carrier">CMA CGM</td>
        <td class="mode">LCL Sea</td>
        <td class="price" data-usd="1320.00">$1,320.00</td>
        <td class="transit" data-days="30">30 days</td>
        <td><a class="book" href="https://www.icontainers.com/book/R3">Book</a></td>
      </tr>
    </tbody>
  </table>
</main>
</body>
</html>
```

Note: the MSC row (R2) deliberately omits the `data-usd` attribute on `<td class="price">` so the parser must fall back to text parsing — this exercises the `data_usd or _parse_usd(td.text)` branch.

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/icontainers_delhi_rotterdam.html
git commit -m "feat(fixtures): add icontainers Delhi→Rotterdam fixture (3 sea rows, 1 text-fallback price)"
```

---

## Task 5: Create searates fixture (semantic HTML5 DOM)

**Files:**
- Create: `tests/fixtures/searates_delhi_rotterdam.html`

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/searates_delhi_rotterdam.html` with EXACTLY this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SeaRates — Delhi → Rotterdam</title>
</head>
<body>
<main>
  <section class="search-results">
    <h1>Rates Delhi → Rotterdam (200 kg)</h1>
    <article class="rate" data-carrier="Hapag-Lloyd" data-mode="sea_freight">
      <h3 class="rate-title">Hapag-Lloyd — LCL Sea</h3>
      <data class="price" value="1180.00">$1,180 USD</data>
      <time class="transit" datetime="P35D">35 days</time>
      <a class="book" href="https://www.searates.com/book/hl-xyz">Reserve</a>
      <details class="fees">
        <summary>Additional fees</summary>
        <ul>
          <li data-fee="BAF">Bunker adjustment: $45</li>
          <li data-fee="THC">Terminal handling: $120</li>
        </ul>
      </details>
    </article>
    <article class="rate" data-carrier="ONE" data-mode="sea_freight">
      <h3 class="rate-title">ONE (Ocean Network Express) — LCL Sea</h3>
      <data class="price" value="1095.00">$1,095 USD</data>
      <time class="transit" datetime="P38D">38 days</time>
      <a class="book" href="https://www.searates.com/book/one-abc">Reserve</a>
      <!-- No <details class="fees"> — Phase 3 hidden-charge detector will flag -->
    </article>
    <article class="rate" data-carrier="Evergreen" data-mode="sea_freight">
      <h3 class="rate-title">Evergreen Marine — LCL Sea</h3>
      <data class="price" value="1230.00">$1,230 USD</data>
      <time class="transit" datetime="P33D">33 days</time>
      <a class="book" href="https://www.searates.com/book/evg-pqr">Reserve</a>
      <details class="fees">
        <summary>Additional fees</summary>
        <ul>
          <li data-fee="BAF">Bunker adjustment: $50</li>
          <li data-fee="THC">Terminal handling: $115</li>
          <li data-fee="DOC">Documentation: $30</li>
        </ul>
      </details>
    </article>
  </section>
</main>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/searates_delhi_rotterdam.html
git commit -m "feat(fixtures): add searates Delhi→Rotterdam fixture (3 sea articles, 1 no-fees)"
```

---

## Task 6: Implement tools/cache.py

**Files:**
- Create: `tools/cache.py`

- [ ] **Step 1: Write cache.py**

Create `tools/cache.py` with EXACTLY this content:

```python
"""SQLite-backed rate cache with 6h TTL.

Key: (origin, destination, query_date). Value: JSON-serialised list[ScrapedRate].
Expiry is read-time (no background eviction). Upsert semantics on writes.

Override the DB path with the CACHE_DB_PATH env var (default:
knowledge_base/rate_cache.db — covered by the existing *.db gitignore rule).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger("cache")

TTL_SECONDS = 6 * 60 * 60  # 6h per CLAUDE.md


def _db_path() -> Path:
    """Resolve the cache DB path from env or fall back to the default."""
    env_path = os.getenv("CACHE_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path("knowledge_base/rate_cache.db")


def _connect() -> sqlite3.Connection:
    """Open a connection, ensuring the parent dir and table both exist."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_cache (
            origin       TEXT NOT NULL,
            destination  TEXT NOT NULL,
            query_date   TEXT NOT NULL,
            rates_json   TEXT NOT NULL,
            cached_at    TEXT NOT NULL,
            PRIMARY KEY (origin, destination, query_date)
        )
        """
    )
    conn.commit()
    return conn


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_cached(
    origin: str, destination: str, query_date: date
) -> list[dict] | None:
    """Return cached rates or None on miss/expiry/corruption.

    Miss conditions:
      - no matching row
      - row exists but age > TTL_SECONDS
      - cached_at or rates_json is unparseable
    """
    key = (origin, destination, query_date.isoformat())
    try:
        conn = _connect()
    except sqlite3.DatabaseError as e:
        logger.error("DB connect failed: %s", e)
        return None
    try:
        row = conn.execute(
            "SELECT rates_json, cached_at FROM rate_cache "
            "WHERE origin = ? AND destination = ? AND query_date = ?",
            key,
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        logger.info("MISS %s->%s %s (not cached)", origin, destination, key[2])
        return None
    rates_json, cached_at_str = row
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
    except ValueError:
        logger.error(
            "cached_at unparseable: %r -- treating as miss", cached_at_str
        )
        return None
    age = _now_utc() - cached_at
    if age.total_seconds() > TTL_SECONDS:
        logger.info(
            "EXPIRED %s->%s %s (aged %s)",
            origin,
            destination,
            key[2],
            age,
        )
        return None
    try:
        rates = json.loads(rates_json)
    except json.JSONDecodeError as e:
        logger.error("rates_json unparseable: %s -- treating as miss", e)
        return None
    logger.info(
        "HIT %s->%s %s (aged %s)", origin, destination, key[2], age
    )
    return rates


def put_cache(
    origin: str, destination: str, query_date: date, rates: list[dict]
) -> None:
    """Upsert the rates list for the given key."""
    key = (origin, destination, query_date.isoformat())
    rates_json = json.dumps(rates, sort_keys=True)
    cached_at = _now_utc().isoformat()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO rate_cache "
            "(origin, destination, query_date, rates_json, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (*key, rates_json, cached_at),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info(
        "PUT %s->%s %s (%d rates)",
        origin,
        destination,
        key[2],
        len(rates),
    )


def clear_cache() -> None:
    """Drop and recreate the rate_cache table. For dev + future tests."""
    conn = _connect()
    try:
        conn.execute("DROP TABLE IF EXISTS rate_cache")
        conn.commit()
    finally:
        conn.close()
    # Re-create the table via a fresh connection
    _connect().close()
    logger.info("CLEAR rate_cache dropped and recreated")
```

- [ ] **Step 2: Manual verification — round-trip**

```bash
uv run python -c "
import logging
from datetime import date
from tools.cache import get_cached, put_cache, clear_cache

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

clear_cache()
assert get_cached('Delhi', 'Rotterdam', date.today()) is None, 'expected miss after clear'
put_cache('Delhi', 'Rotterdam', date.today(), [{'carrier': 'Test', 'base_price_usd': 100.0}])
got = get_cached('Delhi', 'Rotterdam', date.today())
assert got == [{'carrier': 'Test', 'base_price_usd': 100.0}], f'roundtrip mismatch: {got}'
print('cache round-trip OK')
"
```
Expected output ends with:
```
INFO cache: CLEAR rate_cache dropped and recreated
INFO cache: MISS Delhi->Rotterdam 2026-04-18 (not cached)
INFO cache: PUT Delhi->Rotterdam 2026-04-18 (1 rates)
INFO cache: HIT Delhi->Rotterdam 2026-04-18 (aged ...)
cache round-trip OK
```

- [ ] **Step 3: Manual verification — TTL expiry**

```bash
uv run python -c "
import logging, sqlite3
from datetime import date, datetime, timedelta, timezone
from tools.cache import get_cached, put_cache, clear_cache, _db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

clear_cache()
put_cache('Delhi', 'Rotterdam', date.today(), [{'stale': True}])

# Manually age the row by 7 hours (> 6h TTL)
seven_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
conn = sqlite3.connect(_db_path())
conn.execute('UPDATE rate_cache SET cached_at = ? WHERE origin = ?', (seven_hours_ago, 'Delhi'))
conn.commit()
conn.close()

got = get_cached('Delhi', 'Rotterdam', date.today())
assert got is None, f'expected EXPIRED, got {got!r}'
print('TTL expiry OK')
"
```
Expected: ends with `INFO cache: EXPIRED Delhi->Rotterdam ... (aged 7:00:...)` and `TTL expiry OK`.

- [ ] **Step 4: Cleanup (remove the test DB so it doesn't pollute real runs)**

```bash
rm -f knowledge_base/rate_cache.db
```

- [ ] **Step 5: Commit**

```bash
git add tools/cache.py
git commit -m "feat(cache): add SQLite rate cache with 6h TTL and upsert semantics"
```

---

## Task 7: Implement tools/scraper.py

**Files:**
- Create: `tools/scraper.py`

- [ ] **Step 1: Write scraper.py**

Create `tools/scraper.py` with EXACTLY this content:

```python
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
```

- [ ] **Step 2: Manual verification — full scrape_all against all three fixtures**

```bash
uv run python -c "
import logging, json
from tools.scraper import scrape_all, Query

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

q = Query(origin='Delhi', destination='Rotterdam', chargeable_weight_kg=200.0)
rates = scrape_all(q)

print()
print(f'TOTAL RATES: {len(rates)}')
for r in rates:
    print(f'  {r[\"source_site\"]:12} {r[\"carrier\"]:24} {r[\"mode\"]:12} \${r[\"base_price_usd\"]:8.2f} {r[\"transit_days\"]}d')

# Sanity assertions
assert len(rates) == 10, f'expected 10 rates, got {len(rates)}'
by_site = {r['source_site'] for r in rates}
assert by_site == {'freightos', 'icontainers', 'searates'}, f'sites: {by_site}'

counts = {s: sum(1 for r in rates if r['source_site'] == s) for s in by_site}
assert counts == {'freightos': 4, 'icontainers': 3, 'searates': 3}, f'counts: {counts}'

modes = {r['mode'] for r in rates}
assert modes == {'air_freight', 'sea_freight'}, f'modes: {modes}'

required = {'carrier', 'base_price_usd', 'chargeable_weight_kg', 'transit_days',
            'booking_url', 'source_site', 'scraped_at', 'mode'}
for r in rates:
    missing = required - r.keys()
    assert not missing, f'rate missing keys {missing}: {r}'

print()
print('sanity checks PASS')
"
```
Expected log output ends with:
```
INFO scraper: freightos -> 4 rates
INFO scraper: icontainers -> 3 rates
INFO scraper: searates -> 3 rates
INFO scraper: scrape_all -> 10 rates from 3/3 sites

TOTAL RATES: 10
  freightos    Lufthansa Cargo          air_freight  $ 892.00 7d
  freightos    Emirates SkyCargo        air_freight  $ 845.00 8d
  freightos    Qatar Airways Cargo      air_freight  $ 910.00 6d
  freightos    KLM Cargo                air_freight  $1024.00 9d
  icontainers  Maersk                   sea_freight  $1245.50 32d
  icontainers  MSC                      sea_freight  $1180.00 35d
  icontainers  CMA CGM                  sea_freight  $1320.00 30d
  searates     Hapag-Lloyd              sea_freight  $1180.00 35d
  searates     ONE                      sea_freight  $1095.00 38d
  searates     Evergreen                sea_freight  $1230.00 33d

sanity checks PASS
```

- [ ] **Step 3: Manual verification — continue-on-error (temporarily rename one fixture)**

```bash
mv tests/fixtures/icontainers_delhi_rotterdam.html tests/fixtures/icontainers_delhi_rotterdam.html.bak
uv run python -c "
import logging
from tools.scraper import scrape_all, Query
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
q = Query(origin='Delhi', destination='Rotterdam', chargeable_weight_kg=200.0)
rates = scrape_all(q)
assert len(rates) == 7, f'expected 7 rates (freightos 4 + searates 3), got {len(rates)}'
assert not any(r['source_site'] == 'icontainers' for r in rates)
print('continue-on-error PASS')
"
mv tests/fixtures/icontainers_delhi_rotterdam.html.bak tests/fixtures/icontainers_delhi_rotterdam.html
```
Expected log includes `WARNING scraper: icontainers failed (...)` and the final assertion prints `continue-on-error PASS`.

- [ ] **Step 4: Manual verification — LIVE_SCRAPING guard**

```bash
LIVE_SCRAPING=true uv run python -c "
from tools.scraper import fetch_site, Query
try:
    fetch_site('freightos', Query('Delhi', 'Rotterdam', 200.0))
except NotImplementedError as e:
    print(f'NotImplementedError raised: {e}')
"
```
Expected: `NotImplementedError raised: live scraping not wired in v1 -- set LIVE_SCRAPING=false and use fixtures`.

- [ ] **Step 5: Commit**

```bash
git add tools/scraper.py
git commit -m "feat(scraper): add three-parser rate scraper with fixture-first dispatch"
```

---

## Task 8: Integration sanity check — scraper + cache together

**Files:** none modified — verification only.

- [ ] **Step 1: Verify scraper + cache compose cleanly**

```bash
uv run python -c "
import logging
from datetime import date
from tools.scraper import scrape_all, Query
from tools.cache import get_cached, put_cache, clear_cache

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

clear_cache()
today = date.today()
q = Query('Delhi', 'Rotterdam', 200.0)

# First call: cache miss, scrape, then cache
cached = get_cached(q.origin, q.destination, today)
assert cached is None
rates = scrape_all(q)
put_cache(q.origin, q.destination, today, rates)
print(f'first call: {len(rates)} rates scraped and cached')

# Second call: cache hit, no scrape
cached = get_cached(q.origin, q.destination, today)
assert cached is not None, 'expected cache hit on second call'
assert len(cached) == len(rates), f'count mismatch: {len(cached)} vs {len(rates)}'
# JSON round-trip preserves data
assert cached[0]['carrier'] == rates[0]['carrier']
print(f'second call: cache hit, {len(cached)} rates returned')
print('scraper+cache integration PASS')
"
```
Expected: both calls succeed, log shows MISS then HIT, final assertion prints `scraper+cache integration PASS`.

- [ ] **Step 2: Cleanup**

```bash
rm -f knowledge_base/rate_cache.db
```

No commit — this is verification only.

---

## Task 9: Update CLAUDE.md for Phase 2 shipped state

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Current state section**

Find:
```markdown
## Current state (2026-04-17)
Phase 1 complete: repo is git-initialised, `uv` manages deps (hatchling backend), `.env.example` / `.gitignore` / `.mcp.json` in place, and `knowledge_base/ingest.py` has uploaded the three seed PDFs to PageIndex (registry `knowledge_base/doc_registry.json` has 3 entries with `doc_id` + `sha256`, idempotency verified). Phases 2–6 (scraper, agents, UI, tests, deploy) remain. Follow the **Build order** section.
```

Replace with:
```markdown
## Current state (2026-04-18)
Phase 2 complete: `tools/scraper.py` normalises three hand-crafted HTML fixtures (freightos / icontainers / searates, Delhi→Rotterdam 200 kg) into 10 `ScrapedRate` dicts via three distinct parsers; `tools/cache.py` provides a SQLite rate cache with 6 h read-time TTL. Phase 1 deliverables remain in place (ingest.py, PageIndex MCP). Phases 3–6 (agents, UI, tests, deploy) remain. Follow the **Build order** section.

**Phase 2 notes:**
- `LIVE_SCRAPING=false` is both default and production in v1. `LIVE_SCRAPING=true` raises `NotImplementedError`.
- Cache key is `(origin, destination, query_date)` per CLAUDE.md — known to be too coarse (ignores weight + mode); acceptable for the single-route demo, tighten to `(origin, destination, date, mode, weight_bucket)` when multi-route support lands.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): Phase 2 complete -- update Current state section"
```

---

## Task 10: Push to GitHub

**Files:** none modified — push only.

- [ ] **Step 1: Push all Phase 2 commits**

```bash
git push origin main
```
Expected: lists 8–10 new objects, updates `origin/main` to the Task 9 commit SHA.

- [ ] **Step 2: Verify remote**

```bash
git log --oneline origin/main | head -10
```
Expected: matches local `git log --oneline | head -10` exactly.

No commit on this task.

---

## Self-review notes

Checked against the spec before finalising:

**Spec coverage:**
- Spec §2 In scope (all 6 deliverables): pyproject deps (Task 1), package scaffolding (Task 2), three fixtures (Tasks 3–5), cache.py (Task 6), scraper.py (Task 7). All covered.
- Spec §3 decisions D1–D12 all implemented verbatim: fixture-first production (D1), hand-crafted fixtures (D2), three distinct DOM conventions (D3), pure-function parsers (D4), `LIVE_SCRAPING` at fetch boundary (D5), continue-on-error (D6), `NotImplementedError` on live (D7), opaque JSON cache (D8), read-time expiry (D9), DB path (D10), no cross-module import (D11), bs4+lxml deps (D12).
- Spec §4 architecture (Query, SiteConfig, SITES dict, three parsers, fetch_site, scrape_all): Task 7 implements every function.
- Spec §5 cache interface (`get_cached`, `put_cache`, `clear_cache`, TTL_SECONDS): Task 6 implements all four.
- Spec §6 fixture design (4 freightos cards / 3 icontainers rows / 3 searates articles, one "missing surcharge" per fixture): Tasks 3–5.
- Spec §8 implementation sequence (11 steps) maps to Tasks 1–9; Task 8 is the integration sanity check.
- Spec §9 acceptance criteria (6 items): `uv sync` clean (Task 1); 10 rates with all keys (Task 7 Step 2); continue-on-error 6–7 rates (Task 7 Step 3); cache round-trip + TTL expiry (Task 6 Steps 2–3); `NotImplementedError` on LIVE_SCRAPING=true (Task 7 Step 4); CLAUDE.md updated (Task 9).

**Placeholder scan:** no TBDs, TODOs, "similar to Task N", "add appropriate error handling", or "similar pattern." All helpers, parsers, fixtures, and verifications have complete code / exact text / exact commands with expected output.

**Type consistency:**
- `Query` dataclass: `origin, destination, chargeable_weight_kg, mode` — used consistently in Task 7, Task 8.
- `SiteConfig` fields: `name, url, fixture, parser` — consistent throughout.
- `ScrapedRate` dict keys: `carrier, base_price_usd, transit_days, booking_url, mode` returned by parsers + `source_site, chargeable_weight_kg, scraped_at` added by aggregator = 8 required keys. Task 7 Step 2 sanity check asserts all 8.
- Mode values: `air_freight`, `sea_freight`, `courier`, `road_freight` — only these four. `_normalise_mode` maps to these; fixtures only produce `air_freight` and `sea_freight`; Task 7 Step 2 asserts `modes == {'air_freight', 'sea_freight'}`.
- Cache signatures: `get_cached(origin, destination, query_date) -> list[dict] | None`, `put_cache(origin, destination, query_date, rates) -> None`, `clear_cache() -> None` — consistent between Task 6 and Task 8.
- Fixture filenames identical in Tasks 3–5 file creation and Task 7 SITES dict.

No drift found. Ready for execution.

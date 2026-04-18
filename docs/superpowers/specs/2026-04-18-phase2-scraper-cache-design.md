# Phase 2 — Scraper + Cache + Fixtures: Design

**Date:** 2026-04-18
**Author:** Shashank Gupta (with Claude)
**Status:** Approved for implementation planning
**Related:** `CLAUDE.md` (Build order §Phase 2), `freight-rate-intelligence-PRD.md` (§F3), `docs/superpowers/specs/2026-04-17-phase1-scaffold-design.md` (prior phase)

---

## 1. Purpose

Build the data-acquisition layer: a scraper module that normalises rate quotes from three hand-crafted HTML fixtures into a uniform `ScrapedRate` list, plus a SQLite-backed rate cache with 6h TTL. Production mode for v1 uses fixtures exclusively (`LIVE_SCRAPING=false`); live HTTP is a future experiment.

The portfolio story: three parsers against three structurally distinct sources, all normalised to one output shape, backed by a TTL cache. The architecture is production-shaped; the data source is local fixtures by design.

## 2. Scope

### In scope

1. `tools/scraper.py` — three site-specific pure-function parsers, per-site fetchers with `LIVE_SCRAPING` dispatch, top-level `scrape_all` aggregator, site config dict (no hardcoded URLs in logic).
2. `tools/cache.py` — SQLite rate cache, TTL 6h, key `(origin, destination, query_date)`, `get_cached` / `put_cache` / `clear_cache` public interface.
3. `tests/fixtures/freightos_delhi_rotterdam.html` — list-of-cards DOM (`<ul><li>`), class selectors.
4. `tests/fixtures/icontainers_delhi_rotterdam.html` — table DOM, `<td data-usd>` attributes.
5. `tests/fixtures/searates_delhi_rotterdam.html` — semantic HTML5 (`<article>`, `<data>`, `<time>`, `<details>`).
6. Supporting: `tools/__init__.py`, `tests/__init__.py`, `tests/fixtures/__init__.py` (all empty; for package discovery and path resolution).

### Out of scope

- Real HTTP scraping (code path exists; raises `NotImplementedError` in v1)
- Playwright / JS rendering (YAGNI — add if live scraping ever wired)
- Hidden-charge detection (Phase 3; reads the same fixture files independently)
- PageIndex-tariff fallback when `scrape_all` returns `[]` (Phase 3 orchestrator's job)
- pytest tests (Phase 5)

### Cache key caveat

CLAUDE.md's spec is `(origin, destination, date)`. This ignores chargeable weight and mode, which in reality produce materially different rates. Accepted as-is for v1 because the demo has one route and one fixture per site; documented as a known limitation to tighten to `(origin, destination, date, mode, weight_bucket)` when multiple routes / modes exist.

## 3. Decisions locked in during brainstorm

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Fixture-first production.** `LIVE_SCRAPING=false` is both default and production in v1. | Target aggregators (Freightos / iContainers / SeaRates) gate rates behind signup/RFQ flows; anonymous scraping is infeasible. Fixture-first lets parsers be real code without fighting Cloudflare. |
| D2 | **Hand-crafted fixtures** (not real captures). | Anonymous capture impossible (D1); authenticated capture bit-rots quickly. Synthetic fixtures with realistic DOM structure give stable, portfolio-clean demos with zero legal/ToS footprint. |
| D3 | **Three distinct DOM conventions** — list-of-cards (Freightos), table (iContainers), semantic-HTML5 (SeaRates). | Real aggregators never share conventions. Three patterns exercise different BS4 strategies (`.select`, `.find_all`, attribute reads) and make parser code visibly non-trivial. |
| D4 | **Parsers as pure functions** (`parse_freightos(html) -> list[ScrapedRate]`), not classes. | Single-method behaviour; classes are premature abstraction. Pure functions are trivial to unit-test (`open → parse → assert`). |
| D5 | **`LIVE_SCRAPING` dispatch at fetch boundary only.** Parsers never see the toggle. | Single responsibility: parsers parse HTML, fetchers source HTML. |
| D6 | **Continue-on-error per site.** One site fails → log, skip, return partial. All fail → return `[]`. | Mirrors Phase 1 ingest pattern. Partial rates are more useful than no rates. |
| D7 | **`NotImplementedError` on `LIVE_SCRAPING=true`** in v1. | Honest about what ships. No half-working HTTP code that looks real but isn't exercised. |
| D8 | **Cache stores rates as opaque JSON blob** keyed by `(origin, destination, query_date)`. | Simpler than normalised rate table; matches short-TTL query-cache pattern. Cache doesn't know or care about `ScrapedRate` internals. |
| D9 | **Read-time expiry** (no background eviction). | `get_cached` checks age on read. Expired rows are overwritten on next `put_cache`. No threads, no cron. |
| D10 | **DB path `knowledge_base/rate_cache.db`** (gitignored via existing `*.db` rule). Override via `CACHE_DB_PATH`. | Co-located with `doc_registry.json`; no new gitignore entries needed. |
| D11 | **No cross-module import between `scraper.py` and `cache.py`.** Orchestrator (Phase 3+) composes them. | Keeps both files focused and testable in isolation. |
| D12 | **Dependencies: add `beautifulsoup4` + `lxml`** to `pyproject.toml`. No Playwright, no `requests-html`, no Scrapy. | Minimum viable parsing. `lxml` as BS4 backend for speed + correctness on malformed HTML. |

## 4. `tools/scraper.py` architecture

### Data flow

```
ShipmentInput (from caller)
       ↓
Query(origin, destination, chargeable_weight_kg, mode)   ← small adapter dataclass
       ↓
scrape_all(query)  ←─ env LIVE_SCRAPING=false (v1): read fixtures; =true: NotImplementedError
       │
       ├── fetch_site("freightos", query)    → HTML string
       │       └── parse_freightos(html)     → list[ScrapedRate]
       ├── fetch_site("icontainers", query)  → HTML string
       │       └── parse_icontainers(html)   → list[ScrapedRate]
       └── fetch_site("searates", query)     → HTML string
               └── parse_searates(html)      → list[ScrapedRate]
       ↓
   list[ScrapedRate]   (flat concatenation, per-site failures logged + skipped)
```

### Module shape

```python
# Types
@dataclass(frozen=True)
class Query:
    origin: str
    destination: str
    chargeable_weight_kg: float
    mode: str | None = None  # optional hint from Router agent

# Site registry — one source of truth for URLs + fixtures + parsers
@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str               # live URL (not exercised in v1)
    fixture: str           # filename within tests/fixtures/
    parser: Callable[[str], list[dict]]

SITES: dict[str, SiteConfig] = { ... }  # freightos, icontainers, searates

# Per-site parsers (pure)
def parse_freightos(html: str) -> list[dict]: ...
def parse_icontainers(html: str) -> list[dict]: ...
def parse_searates(html: str) -> list[dict]: ...

# Fetcher (fixture vs live dispatch)
def fetch_site(site_name: str, query: Query) -> str: ...

# Aggregator
def scrape_all(query: Query) -> list[dict]: ...
```

### ScrapedRate shape (returned as plain dict)

```python
{
  "carrier": str,                  # e.g. "Lufthansa Cargo"
  "base_price_usd": float,         # parsed from price field
  "chargeable_weight_kg": float,   # passed through from Query
  "transit_days": int,             # parsed from <time datetime="P7D"> or "32 days" text
  "booking_url": str,              # per-card href
  "source_site": str,              # "freightos" | "icontainers" | "searates"
  "scraped_at": str,               # ISO 8601 UTC timestamp at parse time
  "mode": str,                     # "air_freight" | "sea_freight" | ...
}
```

Matches CLAUDE.md data contract exactly. Returned as dict (not dataclass) so `json.dumps` in cache is trivial.

### Fixture path resolution

```python
FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
```

Relative to `tools/scraper.py`. Works from any CWD. Overridable via `SCRAPER_FIXTURE_DIR` env var if ever needed.

### Dispatch logic in `fetch_site`

```python
def fetch_site(site_name: str, query: Query) -> str:
    cfg = SITES[site_name]
    if os.getenv("LIVE_SCRAPING", "false").lower() == "true":
        raise NotImplementedError(
            "live scraping not wired in v1 — set LIVE_SCRAPING=false and use fixtures"
        )
    fixture_path = FIXTURE_DIR / cfg.fixture
    return fixture_path.read_text(encoding="utf-8")
```

### Aggregator

```python
def scrape_all(query: Query) -> list[dict]:
    results: list[dict] = []
    successes = 0
    for site_name, cfg in SITES.items():
        try:
            html = fetch_site(site_name, query)
            site_rates = cfg.parser(html)
            # Fill in fields the parser doesn't derive from HTML
            now = datetime.now(UTC).isoformat()
            for r in site_rates:
                r["source_site"] = site_name
                r["chargeable_weight_kg"] = query.chargeable_weight_kg
                r["scraped_at"] = now
            results.extend(site_rates)
            successes += 1
            logger.info("%s → %d rates", site_name, len(site_rates))
        except Exception as e:
            logger.warning("%s failed (%s), skipping", site_name, e)
            logger.debug("%s traceback", site_name, exc_info=True)
    logger.info(
        "scrape_all → %d rates from %d/%d sites",
        len(results),
        successes,
        len(SITES),
    )
    return results
```

**Field ownership convention:** parsers return dicts with the fields they can derive from HTML (`carrier`, `base_price_usd`, `transit_days`, `booking_url`, `mode`). `scrape_all` then fills in the three fields that are context, not content: `source_site`, `chargeable_weight_kg`, `scraped_at`. Parsers never import `datetime` or know their own site name.

### Parser responsibilities per site

All three parsers normalise `mode` to one of the four CLAUDE.md-approved values: `"air_freight"`, `"sea_freight"`, `"courier"`, `"road_freight"`. Free-text mode labels in the HTML get mapped through a small `_normalise_mode(text)` helper shared across parsers.

**`parse_freightos`** — list-of-cards DOM:
- Selector: `soup.select("ul.quote-results li.quote-card")`
- Per card: `.select_one(".carrier-name").text`, `.select_one(".price-usd").text` (strip `$` / `,` → float), `.select_one("time.transit")["datetime"]` (parse ISO 8601 duration `P7D` → `7`), `.select_one("a.book-link")["href"]`, `.select_one(".mode-label").text` → `_normalise_mode(...)` → `"air_freight"`
- Returns 3–4 rates; skips cards with missing required fields (malformed tolerance)

**`parse_icontainers`** — table DOM:
- Selector: `soup.find("table", class_="rates-table").find("tbody").find_all("tr", class_="rate-row")`
- Per row: `.find("td", class_="carrier").text`, `.find("td", class_="price").get("data-usd")` (fallback: parse text with `$` / `,` stripped), `.find("td", class_="transit").get("data-days")` → int, `.find("a", class_="book")["href"]`, `_normalise_mode(.find("td", class_="mode").text)` → `"sea_freight"`
- Demonstrates structured (`data-*` attribute) + text fallback

**`parse_searates`** — semantic HTML5:
- Selector: `soup.find_all("article", class_="rate")`
- Per article: `article["data-carrier"]`, `.find("data", class_="price")["value"]` (numeric attribute → float), `.find("time", class_="transit")["datetime"]` (parse `P35D` → `35`), `.find("a", class_="book")["href"]`, `_normalise_mode(article["data-mode"])` → `"sea_freight"`
- Demonstrates attribute-first parsing (no text wrangling)

### Error handling (scraper)

| Failure | Behaviour | Exit |
|---|---|---|
| Fixture file missing | `FileNotFoundError` caught per site; logged with path; site skipped | partial |
| Parser throws on one site | Logged at WARNING with site + exception class; traceback at DEBUG; site skipped | partial |
| All three fail | Return `[]`, log error | empty list (orchestrator handles) |
| `LIVE_SCRAPING=true` | `NotImplementedError` raised from `fetch_site`, propagates up | fail-fast |
| Malformed HTML (empty file, wrong structure) | Parser's `find_all` returns empty; returns `[]`; no error | silent |

## 5. `tools/cache.py`

### Schema

```sql
CREATE TABLE IF NOT EXISTS rate_cache (
    origin       TEXT    NOT NULL,
    destination  TEXT    NOT NULL,
    query_date   TEXT    NOT NULL,     -- YYYY-MM-DD
    rates_json   TEXT    NOT NULL,     -- json.dumps(list[dict])
    cached_at    TEXT    NOT NULL,     -- ISO 8601 UTC
    PRIMARY KEY (origin, destination, query_date)
);
```

### Public interface

```python
TTL_SECONDS = 6 * 60 * 60  # 6h per CLAUDE.md

def _db_path() -> Path:
    """Return CACHE_DB_PATH env var if set, else knowledge_base/rate_cache.db."""

def _connect() -> sqlite3.Connection: ...  # ensures table exists via CREATE IF NOT EXISTS

def get_cached(origin: str, destination: str, query_date: date) -> list[dict] | None:
    """Return cached rates or None on miss/expiry.

    Miss conditions:
    - row absent
    - row present but (now_utc - cached_at) > TTL_SECONDS
    - row present but rates_json fails to parse (logged, treated as miss)
    """

def put_cache(origin: str, destination: str, query_date: date, rates: list[dict]) -> None:
    """Upsert via INSERT OR REPLACE. Writes cached_at = now_utc()."""

def clear_cache() -> None:
    """Drop and recreate the rate_cache table. For dev + future tests."""
```

### Integration pattern (orchestrator-side, not in this module)

```python
cached = get_cached(origin, destination, today)
if cached is not None:
    rates = cached
else:
    rates = scrape_all(Query(origin, destination, chargeable_weight_kg, mode))
    if rates:
        put_cache(origin, destination, today, rates)
```

Single caller composes scraper + cache. Neither module imports the other.

### Error handling (cache)

| Failure | Behaviour |
|---|---|
| DB file corrupt | `sqlite3.DatabaseError` → `get_cached` logs and returns `None`; `put_cache` logs and re-raises |
| `rates_json` unparseable on read | Logged, return `None` (treat as miss) |
| Disk full on write | `sqlite3.OperationalError` → logged and re-raised (caller decides) |
| DB absent on first use | `CREATE TABLE IF NOT EXISTS` handles it silently |

### Log lines

- `INFO cache: HIT delhi→rotterdam 2026-04-18 (aged 00:12:33)`
- `INFO cache: MISS delhi→rotterdam 2026-04-18 (not cached)`
- `INFO cache: EXPIRED delhi→rotterdam 2026-04-18 (aged 07:22:15)`

## 6. Fixture design detail

Each fixture has 3–4 rate cards. **One card per fixture deliberately omits the surcharges/fees section** (Phase 3's hidden-charge agent will flag these later; Phase 2 scraper ignores surcharges — they aren't in `ScrapedRate`).

### `tests/fixtures/freightos_delhi_rotterdam.html`

- 4 cards in `<ul class="quote-results">`
- Carriers: Lufthansa Cargo, Emirates SkyCargo, Qatar Airways Cargo, KLM Cargo
- Prices: $892, $845, $910, $1,024
- Transit: 7, 8, 6, 9 days (all air)
- Mode: all "Air Freight"
- 1 card missing `<ul class="surcharges">`

### `tests/fixtures/icontainers_delhi_rotterdam.html`

- 3 rows in `<table class="rates-table">`
- Carriers: Maersk, MSC, CMA CGM
- Prices: $1,245.50, $1,180, $1,320
- Transit: 32, 35, 30 days (all sea, LCL)
- Mode: all "LCL Sea"
- 1 row has no `data-usd` attribute on `<td class="price">` (text-only fallback required)

### `tests/fixtures/searates_delhi_rotterdam.html`

- 3 articles in `<section class="search-results">`
- Carriers: Hapag-Lloyd, ONE, Evergreen
- Prices: $1,180, $1,095, $1,230
- Transit: 35, 38, 33 days (all sea)
- Mode: all "sea_freight" (via `data-mode`)
- 1 article without `<details class="fees">` element

### Total across three fixtures

- 10 rate cards, carriers all distinct (one exception: Maersk appears in iContainers; CMA CGM only there)
- Air and sea modes both represented
- Prices span $845–$1,320 (plausible DEL→RTM range for 200kg)
- Normalised into 10 `ScrapedRate` dicts after `scrape_all`

## 7. `pyproject.toml` additions

```toml
dependencies = [
  "requests>=2.31",          # already present from Phase 1
  "python-dotenv>=1.0",      # already present
  "beautifulsoup4>=4.12",    # NEW — HTML parsing
  "lxml>=5.2",               # NEW — BS4 backend (fast + malformed-tolerant)
]
```

No dev deps added in this phase (Phase 5 adds pytest stack).

## 8. Implementation sequence

Each step independently verifiable:

```
 1. pyproject.toml: add beautifulsoup4 + lxml → uv sync       → deps resolve
 2. tests/__init__.py + tests/fixtures/__init__.py (empty)    → package discovery
 3. tests/fixtures/freightos_delhi_rotterdam.html             → realistic list-of-cards HTML
 4. tests/fixtures/icontainers_delhi_rotterdam.html           → realistic table HTML
 5. tests/fixtures/searates_delhi_rotterdam.html              → realistic semantic-HTML5
 6. tools/__init__.py (empty)
 7. tools/cache.py                                            → SQLite + TTL (simplest of the two)
 8. tools/scraper.py                                          → Query/SiteConfig/parsers/fetcher/scrape_all
 9. Manual sanity: `uv run python -c "from tools.scraper import scrape_all; from tools.scraper import Query; print(scrape_all(Query('Delhi','Rotterdam',200.0)))"` → list of ~10 dicts
10. Manual sanity: round-trip cache.put → cache.get, then clear, verify gone
11. CLAUDE.md touch-ups: update Current state date, note Phase 2 shipped, document cache key limitation
```

## 9. Acceptance criteria

Phase 2 is complete when all of these hold:

- `uv sync` resolves with `beautifulsoup4` + `lxml` installed
- `scrape_all(Query("Delhi", "Rotterdam", 200.0))` returns a list of 10 `ScrapedRate` dicts (4 from freightos, 3 from icontainers, 3 from searates)
- Every returned dict has all 8 `ScrapedRate` keys populated correctly (carrier names, prices parsed as floats, transit days parsed as ints, etc.)
- Deleting one fixture and re-running `scrape_all` returns the rate count of the other two sites (6 if freightos deleted, 7 if either icontainers or searates deleted), with a WARNING log for the skipped site
- `put_cache(...)` then `get_cached(...)` within 6h returns the same list; after mocking `cached_at` to 7h ago, `get_cached` returns `None`
- Setting `LIVE_SCRAPING=true` and calling `fetch_site(...)` raises `NotImplementedError` with an actionable message
- CLAUDE.md's "Current state" section mentions Phase 2 complete; known cache-key limitation is documented

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Hand-crafted fixtures diverge from any real site's DOM | Acknowledged: parsers exercise realistic patterns, not site-specific quirks. Portfolio story is accurate. |
| `lxml` wheel install issues on some platforms (rare with uv) | Code calls `BeautifulSoup(html, "lxml")`. If install fails on a contributor's machine, they can edit the call to `"html.parser"` (stdlib, no install). No env-var indirection — one-line source edit is cleaner. |
| Cache key too coarse (see §2 caveat) | Documented limitation. Concrete users (Phase 3+ agents) will hit it; schema migration is the fix path. |
| Scraper returning zero rates on total failure leaves orchestrator with no fallback in Phase 2 | Accepted. Phase 3 orchestrator is where PageIndex tariff fallback lives. Scraper stays focused. |
| `NotImplementedError` on `LIVE_SCRAPING=true` might surprise someone reading the code later | The exception message explicitly says "not wired in v1"; the README (Phase 5) can call this out too. |

## 11. Non-goals for Phase 2

- No retries or backoff (no HTTP to retry)
- No parallel fetches (fixtures are local reads; serial is fine)
- No progress bars, colour output, or CLI (internal module)
- No caching of the fixture HTML (OS page cache handles repeated reads)
- No charset detection heuristics (fixtures are UTF-8)
- No tests (Phase 5)
- No README updates beyond the CLAUDE.md "Current state" bullet

# CCA-F Architecture Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply CCA-F architecture principles across 5 phases — structured errors, pipeline compliance, anti-fabrication prompts, Claude Code config, and UI updates.

**Architecture:** Bottom-up layering. Phase 1 builds shared error types consumed by all tools. Phase 2 propagates them through the pipeline and adds compliance enforcement. Phase 3 improves prompt quality and schema safety. Phase 4 trims CLAUDE.md and adds Claude Code primitives. Phase 5 updates the Streamlit UI to reflect confidence and structured errors.

**Tech Stack:** Python 3.11+, Pydantic v2, LangChain 1.x, Streamlit, pytest, SQLite

---

## Phase 1 — Structured Error Types + Tool Refactor

### Task 1: Create `tools/errors.py` with shared error models

**Files:**
- Create: `tools/errors.py`
- Test: `tests/test_errors.py`

- [ ] **Step 1: Write tests for error models**

Create `tests/test_errors.py`:

```python
"""Unit tests for tools/errors.py — shared error contract."""
from __future__ import annotations

from tools.errors import ErrorCategory, PipelineError, ScraperResult, SiteResult, ToolResult


def test_tool_result_ok():
    r = ToolResult(status="ok", data=[1, 2, 3])
    assert r.is_error is False
    assert r.error_category is None
    assert r.data == [1, 2, 3]


def test_tool_result_error():
    r = ToolResult(
        status="error",
        is_error=True,
        error_category=ErrorCategory.TRANSIENT,
        is_retryable=True,
        detail="connection timeout",
    )
    assert r.is_error is True
    assert r.error_category == ErrorCategory.TRANSIENT
    assert r.is_retryable is True


def test_pipeline_error_model_dump():
    e = PipelineError(
        stage="scraper",
        error_category=ErrorCategory.TRANSIENT,
        is_retryable=True,
        detail="site down",
    )
    d = e.model_dump()
    assert d["stage"] == "scraper"
    assert d["error_category"] == "transient"
    assert d["is_retryable"] is True


def test_site_result_defaults():
    s = SiteResult(site="freightos")
    assert s.status == "ok"
    assert s.error_category is None
    assert s.rate_count == 0


def test_scraper_result_inherits_tool_result():
    r = ScraperResult(status="ok", data=[{"carrier": "X"}], site_results=[])
    assert isinstance(r, ToolResult)
    assert r.site_results == []


def test_error_category_values():
    assert ErrorCategory.TRANSIENT == "transient"
    assert ErrorCategory.VALIDATION == "validation"
    assert ErrorCategory.PERMISSION == "permission"
    assert ErrorCategory.BUSINESS == "business"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.errors'`

- [ ] **Step 3: Implement `tools/errors.py`**

Create `tools/errors.py`:

```python
"""Shared error contract for all tools and the pipeline.

Every tool returns a ToolResult (or subclass) instead of bare values/None.
The pipeline collects PipelineError dicts for structured error reporting.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"
    VALIDATION = "validation"
    PERMISSION = "permission"
    BUSINESS = "business"


class ToolResult(BaseModel):
    status: str
    data: Any = None
    is_error: bool = False
    error_category: ErrorCategory | None = None
    is_retryable: bool = False
    detail: str = ""


class SiteResult(BaseModel):
    site: str
    status: str = "ok"
    error_category: ErrorCategory | None = None
    is_retryable: bool = False
    detail: str = ""
    rate_count: int = 0


class ScraperResult(ToolResult):
    site_results: list[SiteResult] = []


class PipelineError(BaseModel):
    stage: str
    error_category: ErrorCategory
    is_retryable: bool
    detail: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/errors.py tests/test_errors.py
git commit -m "feat: add shared error types (ToolResult, PipelineError, ScraperResult)"
```

---

### Task 2: Refactor `tools/cache.py` to return `ToolResult`

**Files:**
- Modify: `tools/cache.py`
- Modify: `tests/test_cache.py`

- [ ] **Step 1: Update cache tests to assert on ToolResult**

Replace the full contents of `tests/test_cache.py`:

```python
"""Unit tests for tools/cache.py — SQLite cache with 6h TTL, returns ToolResult."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from tools.cache import TTL_SECONDS, clear_cache, get_cached, put_cache
from tools.errors import ErrorCategory


def test_put_then_get_roundtrip(isolated_cache_db):
    put_cache("Delhi", "Rotterdam", date.today(), [{"carrier": "X"}])
    result = get_cached("Delhi", "Rotterdam", date.today())
    assert result.status == "hit"
    assert result.data == [{"carrier": "X"}]
    assert result.is_error is False


def test_get_cached_miss(isolated_cache_db):
    result = get_cached("Tokyo", "Paris", date.today())
    assert result.status == "miss"
    assert result.data is None
    assert result.is_error is False


def test_get_cached_expires_after_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    seven_h_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (seven_h_ago,))
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "expired"
    assert result.data is None


def test_get_cached_fresh_within_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    fresh = (datetime.now(timezone.utc) - timedelta(hours=5, minutes=59)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (fresh,))
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "hit"
    assert result.data == [{"v": 1}]


def test_get_cached_corrupt_json(isolated_cache_db, caplog):
    put_cache("A", "B", date.today(), [{"v": 1}])
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET rates_json = 'not{valid-json'")
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "error"
    assert result.is_error is True
    assert result.error_category == ErrorCategory.VALIDATION


def test_get_cached_unparseable_cached_at(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = 'definitely-not-a-datetime'")
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "error"
    assert result.error_category == ErrorCategory.VALIDATION


def test_put_cache_upsert_overwrites(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    put_cache("A", "B", date.today(), [{"v": 2}])
    result = get_cached("A", "B", date.today())
    assert result.data == [{"v": 2}]


def test_clear_cache_drops_rows(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    clear_cache()
    result = get_cached("A", "B", date.today())
    assert result.status == "miss"


def test_cache_db_path_env_override(tmp_path, monkeypatch):
    alt = tmp_path / "alt.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(alt))
    put_cache("A", "B", date.today(), [{"v": 1}])
    assert alt.exists()


def test_connect_creates_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "c.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(nested))
    put_cache("X", "Y", date.today(), [])
    assert nested.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cache.py -v`
Expected: FAIL — `get_cached` returns `None`/`list`, not `ToolResult`

- [ ] **Step 3: Rewrite `tools/cache.py` to return ToolResult**

Replace `tools/cache.py` with:

```python
"""SQLite-backed rate cache with 6h TTL, returning structured ToolResult.

Key: (origin, destination, query_date). Value: JSON-serialised list[ScrapedRate].
Expiry is read-time (no background eviction). Upsert semantics on writes.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from tools.errors import ErrorCategory, ToolResult

logger = logging.getLogger("cache")

TTL_SECONDS = 6 * 60 * 60


def _db_path() -> Path:
    env_path = os.getenv("CACHE_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path("knowledge_base/rate_cache.db")


def _connect() -> sqlite3.Connection:
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


def get_cached(origin: str, destination: str, query_date: date) -> ToolResult:
    key = (origin, destination, query_date.isoformat())
    try:
        conn = _connect()
    except sqlite3.DatabaseError as e:
        logger.error("DB connect failed for %s->%s: %s", origin, destination, e)
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.TRANSIENT,
            is_retryable=True, detail=str(e),
        )
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
        return ToolResult(status="miss")
    rates_json, cached_at_str = row
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
    except ValueError:
        logger.error(
            "cached_at unparseable for %s->%s: %r -- treating as error",
            origin, destination, cached_at_str,
        )
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.VALIDATION,
            detail=f"unparseable cached_at: {cached_at_str!r}",
        )
    age = _now_utc() - cached_at
    if age.total_seconds() > TTL_SECONDS:
        logger.info("EXPIRED %s->%s %s (aged %s)", origin, destination, key[2], age)
        return ToolResult(status="expired")
    try:
        rates = json.loads(rates_json)
    except json.JSONDecodeError as e:
        logger.error(
            "rates_json unparseable for %s->%s: %s -- treating as error",
            origin, destination, e,
        )
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.VALIDATION,
            detail=f"unparseable rates_json: {e}",
        )
    logger.info("HIT %s->%s %s (aged %s)", origin, destination, key[2], age)
    return ToolResult(status="hit", data=rates)


def put_cache(
    origin: str, destination: str, query_date: date, rates: list[dict]
) -> None:
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
    logger.info("PUT %s->%s %s (%d rates)", origin, destination, key[2], len(rates))


def clear_cache() -> None:
    conn = _connect()
    try:
        conn.execute("DROP TABLE IF EXISTS rate_cache")
        conn.commit()
    finally:
        conn.close()
    conn2 = _connect()
    conn2.close()
    logger.info("CLEAR rate_cache dropped and recreated")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cache.py -v`
Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cache.py tests/test_cache.py
git commit -m "refactor: cache returns ToolResult with structured error categories"
```

---

### Task 3: Refactor `tools/pageindex_client.py` to return `ToolResult`

**Files:**
- Modify: `tools/pageindex_client.py`
- Modify: `tests/test_pageindex_client.py`

- [ ] **Step 1: Update pageindex tests to assert on ToolResult**

Replace `tests/test_pageindex_client.py`:

```python
"""Unit tests for tools/pageindex_client.py with fully mocked requests.post."""
from __future__ import annotations

import requests

from tools.errors import ErrorCategory


def test_is_enabled_default_false(monkeypatch):
    monkeypatch.delenv("USE_PAGEINDEX_RUNTIME", raising=False)
    from tools.pageindex_client import is_enabled
    assert is_enabled() is False


def test_is_enabled_case_insensitive_true(monkeypatch):
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "TRUE")
    from tools.pageindex_client import is_enabled
    assert is_enabled() is True


def test_doc_id_for_known_and_unknown_filenames(monkeypatch):
    from tools import pageindex_client
    fake_registry = {
        "surcharge_bulletin.pdf": {"doc_id": "pi-known", "sha256": "abc"},
    }
    monkeypatch.setattr(pageindex_client, "_registry", lambda: fake_registry)
    assert pageindex_client.doc_id_for("surcharge_bulletin.pdf") == "pi-known"
    assert pageindex_client.doc_id_for("missing.pdf") is None


def test_query_pageindex_success(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": "fuel surcharge 18-32%"}}]}

    monkeypatch.setattr(pageindex_client.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key-abc")
    result = pageindex_client.query_pageindex("pi-any", "What are surcharges?")
    assert result.status == "ok"
    assert result.data == "fuel surcharge 18-32%"


def test_query_pageindex_missing_api_key(monkeypatch):
    monkeypatch.delenv("PAGEINDEX_API_KEY", raising=False)
    from tools.pageindex_client import query_pageindex
    result = query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.PERMISSION


def test_query_pageindex_non_2xx(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = False
        status_code = 500
        text = "internal error"

    monkeypatch.setattr(pageindex_client.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    result = pageindex_client.query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.TRANSIENT
    assert result.is_retryable is True


def test_query_pageindex_network_error(monkeypatch):
    from tools import pageindex_client

    def boom(*args, **kwargs):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(pageindex_client.requests, "post", boom)
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    result = pageindex_client.query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.TRANSIENT


def test_query_pageindex_malformed_body(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = "{}"
        def json(self):
            return {}

    monkeypatch.setattr(pageindex_client.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    result = pageindex_client.query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.BUSINESS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pageindex_client.py -v`
Expected: FAIL — `query_pageindex` returns `str | None`, not `ToolResult`

- [ ] **Step 3: Rewrite `tools/pageindex_client.py`**

Replace `tools/pageindex_client.py`:

```python
"""PageIndex runtime retrieval — returns ToolResult instead of bare str|None.

Used only when USE_PAGEINDEX_RUNTIME=true. Wraps POST /chat/completions
scoped to a doc_id.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

from tools.errors import ErrorCategory, ToolResult

load_dotenv()
logger = logging.getLogger("pageindex_client")

PAGEINDEX_CHAT_URL = "https://api.pageindex.ai/chat/completions"
REGISTRY_PATH = Path(__file__).parent.parent / "knowledge_base" / "doc_registry.json"


def is_enabled() -> bool:
    return os.getenv("USE_PAGEINDEX_RUNTIME", "false").lower() == "true"


@lru_cache(maxsize=1)
def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def doc_id_for(filename: str) -> str | None:
    entry = _registry().get(filename)
    return entry["doc_id"] if entry else None


def query_pageindex(doc_id: str, question: str, timeout: float = 10.0) -> ToolResult:
    api_key = os.getenv("PAGEINDEX_API_KEY")
    if not api_key:
        logger.warning("PAGEINDEX_API_KEY not set -- skipping runtime retrieval")
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.PERMISSION,
            detail="PAGEINDEX_API_KEY not set",
        )
    try:
        response = requests.post(
            PAGEINDEX_CHAT_URL,
            headers={"api_key": api_key, "Content-Type": "application/json"},
            json={
                "messages": [{"role": "user", "content": question}],
                "doc_id": doc_id,
                "stream": False,
            },
            timeout=timeout,
        )
        if not response.ok:
            logger.warning(
                "PageIndex query failed: HTTP %d -- %s",
                response.status_code, response.text[:200],
            )
            return ToolResult(
                status="error", is_error=True,
                error_category=ErrorCategory.TRANSIENT,
                is_retryable=True,
                detail=f"HTTP {response.status_code}",
            )
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logger.warning("PageIndex returned empty content: %s", body)
            return ToolResult(
                status="error", is_error=True,
                error_category=ErrorCategory.BUSINESS,
                detail="empty content in response",
            )
        return ToolResult(status="ok", data=content.strip())
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("PageIndex query raised: %s", e)
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.TRANSIENT,
            is_retryable=True, detail=str(e),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pageindex_client.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Update hidden_charge.py to consume ToolResult from pageindex**

In `agents/hidden_charge.py`, update `_gather_rag_context` (lines 100-125). Change the `query_pageindex` return handling:

```python
def _gather_rag_context(mode: str, origin: str, destination: str) -> str:
    if not is_enabled():
        return ""
    doc_id = doc_id_for("surcharge_bulletin.pdf")
    if not doc_id:
        logger.warning(
            "surcharge_bulletin.pdf not in doc_registry -- run ingest first"
        )
        return ""
    question = (
        f"What typical surcharges apply to a {mode.replace('_', ' ')} "
        f"shipment from {origin} to {destination}? "
        "List each fee name and typical amount."
    )
    result = query_pageindex(doc_id, question)
    if result.is_error or not result.data:
        return ""
    return (
        "Additional context from surcharge bulletin:\n"
        f"```\n{result.data}\n```\n\n"
    )
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS (hidden_charge tests already mock `query_pageindex`)

- [ ] **Step 7: Commit**

```bash
git add tools/pageindex_client.py tests/test_pageindex_client.py agents/hidden_charge.py
git commit -m "refactor: pageindex_client returns ToolResult with error categories"
```

---

### Task 4: Refactor `tools/scraper.py` to return `ScraperResult`

**Files:**
- Modify: `tools/scraper.py`
- Modify: `tests/test_scraper.py`

- [ ] **Step 1: Update scraper tests**

In `tests/test_scraper.py`, update imports and the two aggregator tests. Add import at top:

```python
from tools.errors import ErrorCategory, ScraperResult
```

Replace `test_scrape_all_returns_ten_rates`:

```python
def test_scrape_all_returns_ten_rates():
    result = scrape_all(Query("Delhi", "Rotterdam", 200.0))
    assert isinstance(result, ScraperResult)
    assert result.status == "ok"
    assert len(result.data) == 10
    assert len(result.site_results) == 3
    assert all(sr.status == "ok" for sr in result.site_results)
    required = {
        "carrier", "base_price_usd", "chargeable_weight_kg",
        "transit_days", "booking_url", "source_site", "scraped_at", "mode",
    }
    for r in result.data:
        assert required <= r.keys()
```

Replace `test_scrape_all_continue_on_error`:

```python
def test_scrape_all_continue_on_error(monkeypatch, caplog):
    def boom(html):
        raise RuntimeError("simulated parser failure")

    from tools import scraper
    from dataclasses import replace

    patched_site = replace(scraper.SITES["icontainers"], parser=boom)
    monkeypatch.setitem(scraper.SITES, "icontainers", patched_site)

    result = scrape_all(Query("Delhi", "Rotterdam", 200.0))
    assert result.status == "ok"
    assert len(result.data) == 7
    assert not any(r["source_site"] == "icontainers" for r in result.data)
    failed = [sr for sr in result.site_results if sr.status == "error"]
    assert len(failed) == 1
    assert failed[0].site == "icontainers"
    assert failed[0].error_category == ErrorCategory.TRANSIENT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scraper.py::test_scrape_all_returns_ten_rates tests/test_scraper.py::test_scrape_all_continue_on_error -v`
Expected: FAIL — `scrape_all` returns `list`, not `ScraperResult`

- [ ] **Step 3: Update `tools/scraper.py` to return `ScraperResult`**

Add import at the top of `tools/scraper.py`:

```python
from tools.errors import ErrorCategory, ScraperResult, SiteResult
```

Replace the `scrape_all` function (lines 225-254):

```python
def scrape_all(query: Query) -> ScraperResult:
    results: list[dict] = []
    site_results: list[SiteResult] = []
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
            site_results.append(SiteResult(
                site=site_name, status="ok", rate_count=len(site_rates),
            ))
            logger.info("%s -> %d rates", site_name, len(site_rates))
        except Exception as e:
            logger.warning("%s failed (%s), skipping", site_name, e)
            logger.debug("%s traceback", site_name, exc_info=True)
            site_results.append(SiteResult(
                site=site_name, status="error",
                error_category=ErrorCategory.TRANSIENT,
                is_retryable=True, detail=str(e),
            ))
    logger.info(
        "scrape_all -> %d rates from %d/%d sites",
        len(results), successes, len(SITES),
    )
    return ScraperResult(
        status="ok" if successes > 0 else "error",
        data=results,
        is_error=successes == 0,
        error_category=ErrorCategory.TRANSIENT if successes == 0 else None,
        detail="" if successes > 0 else "all sites failed",
        site_results=site_results,
    )
```

- [ ] **Step 4: Run scraper tests**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: all tests PASS

- [ ] **Step 5: Update `pipeline.py` to consume ScraperResult and cache ToolResult**

In `pipeline.py`, update the imports and Steps 2-3 (cache + scrape). Change import:

```python
from tools.cache import get_cached, put_cache
from tools.scraper import Query, scrape_all
```

Replace lines 76-97 (Steps 2 & 3):

```python
    # Steps 2 & 3: Cache then scrape
    notify("scraping")
    today = date.today()
    cache_result = get_cached(
        shipment_input["origin"], shipment_input["destination"], today
    )
    cache_hit = cache_result.status == "hit"
    if cache_hit:
        scraped = cache_result.data
    else:
        scraper_result = scrape_all(Query(
            origin=shipment_input["origin"],
            destination=shipment_input["destination"],
            chargeable_weight_kg=shipment_input["chargeable_weight_kg"],
            mode=route["mode"],
        ))
        scraped = scraper_result.data or []
        if scraped:
            put_cache(
                shipment_input["origin"],
                shipment_input["destination"],
                today, scraped,
            )
    sites_succeeded = len({r["source_site"] for r in scraped})
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add tools/scraper.py tests/test_scraper.py pipeline.py
git commit -m "refactor: scraper returns ScraperResult, pipeline consumes ToolResult"
```

---

## Phase 2 — Pipeline Structured Errors + Compliance

### Task 5: Pipeline structured errors + shipment echo + compliance URL stripping

**Files:**
- Modify: `pipeline.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Add new pipeline tests**

Add these tests to the end of `tests/test_pipeline.py`:

```python
def test_run_pipeline_errors_are_structured_dicts(
    install_fake_llm, isolated_cache_db, monkeypatch
):
    install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(recommendation="ok"),
    })

    class BrittleAgent:
        def invoke(self, payload):
            raise RuntimeError("brittle batch failure")

    monkeypatch.setattr(
        "pipeline.build_hidden_charge_agent", lambda: BrittleAgent(),
    )
    result = run_pipeline(SHIPMENT_200KG)
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["stage"] == "hidden_charge"
    assert err["error_category"] == "transient"
    assert err["is_retryable"] is True


def test_run_pipeline_echoes_shipment_input(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    result = run_pipeline(SHIPMENT_200KG)
    assert result["shipment_input"] == SHIPMENT_200KG


def test_run_pipeline_strips_booking_url_for_low_trust(
    install_fake_llm, isolated_cache_db
):
    install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
    install_fake_llm("hidden_charge", {
        BatchHiddenChargeOutput: batch_hc_stub(trust_score=30, flags=["sketchy"]),
    })
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(recommendation="caution"),
    })
    result = run_pipeline(SHIPMENT_200KG)
    for rate in result["rates"]:
        assert rate["booking_url"] == "", f"booking_url not stripped for trust={rate['trust_score']}"
```

- [ ] **Step 2: Update existing pipeline tests for structured errors**

In `tests/test_pipeline.py`, update `test_run_pipeline_batch_failure_captured` — change the assertion on errors:

```python
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "hidden_charge"
```

Update `test_run_pipeline_summarizer_failure_degrades` — change the assertion:

```python
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "summarizer"
```

- [ ] **Step 3: Run tests to verify new ones fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: new tests FAIL, some existing tests FAIL (structured error shape mismatch)

- [ ] **Step 4: Update `pipeline.py` with structured errors, shipment echo, compliance**

In `pipeline.py`, add import:

```python
from tools.errors import ErrorCategory, PipelineError
```

Update `RecommendationResult` TypedDict:

```python
class RecommendationResult(TypedDict):
    mode: str
    router_reason: str
    rates: list[dict]
    recommendation: str
    cache_hit: bool
    sites_succeeded: int
    errors: list[dict]
    shipment_input: dict
```

Replace the hidden-charge error handling (around line 122-124):

```python
        except Exception as e:
            logger.error("hidden-charge batch failed: %s", e)
            errors.append(PipelineError(
                stage="hidden_charge",
                error_category=ErrorCategory.TRANSIENT,
                is_retryable=True,
                detail=str(e),
            ).model_dump())
```

Add compliance enforcement after ranking (after line 129, before the `if not ranked:` check):

```python
    for rate in ranked:
        if rate.get("trust_score", 0) < 50:
            rate["booking_url"] = ""
```

Replace the summarizer error handling (around line 156-159):

```python
    except Exception as e:
        logger.error("summarizer failed: %s", e)
        errors.append(PipelineError(
            stage="summarizer",
            error_category=ErrorCategory.TRANSIENT,
            is_retryable=True,
            detail=str(e),
        ).model_dump())
        recommendation = ""
```

Add `shipment_input` to both return statements (the empty-rates return and the normal return):

```python
        "shipment_input": shipment_input,
```

- [ ] **Step 5: Update smoke test for new keys**

In `tests/test_smoke.py`, add `"confidence"` is not yet required (Phase 3), but `"shipment_input"` is. Update `test_smoke_delhi_rotterdam_12kg_completes_end_to_end`:

Add after `assert result["errors"] == []`:

```python
    assert result["shipment_input"] == CLAUDE_MD_SMOKE_SHIPMENT
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline.py tests/test_pipeline.py tests/test_smoke.py
git commit -m "feat: structured pipeline errors, shipment echo, compliance URL stripping"
```

---

### Task 6: Hidden-charge error differentiation (split default paths)

**Files:**
- Modify: `agents/hidden_charge.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Update the LLM failure test**

In `tests/test_agents.py`, update `test_hidden_charge_llm_failure_falls_back_to_defaults` (line 309-346). Change the assertion:

```python
    for entry in out:
        assert entry["trust_score"] == 50
        assert entry["flags"] == ["Automated scoring unavailable — LLM error"]
        assert entry["verified_site"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agents.py::test_hidden_charge_llm_failure_falls_back_to_defaults -v`
Expected: FAIL — flags still say "Automated scoring unavailable"

- [ ] **Step 3: Split `_default_score` in `agents/hidden_charge.py`**

Replace `_DEFAULT_UNAVAILABLE_FLAG` and `_default_score` (lines 41, 128-129):

```python
def _default_score_llm_failed() -> dict[str, Any]:
    return {"trust_score": 50, "flags": ["Automated scoring unavailable — LLM error"]}


def _default_score_incomplete() -> dict[str, Any]:
    return {"trust_score": 50, "flags": ["Automated scoring unavailable — incomplete batch"]}
```

In the `invoke` method, update line 192 (the `llm_failed = True` path) to use `_default_score_llm_failed`. In lines 195-210, when `local_idx >= len(llm_results)` and `not llm_failed`, use `_default_score_incomplete` instead. When `llm_failed`, use `_default_score_llm_failed`:

```python
        for local_idx, (global_idx, rate) in enumerate(to_score):
            if local_idx < len(llm_results):
                r = llm_results[local_idx]
                score = {
                    "trust_score": int(r.trust_score),
                    "flags": list(r.flags),
                }
            else:
                if llm_failed:
                    score = _default_score_llm_failed()
                else:
                    logger.warning(
                        "hidden-charge: no LLM result for rate %d (%s/%s), using default",
                        global_idx,
                        rate.get("source_site", "?"),
                        rate.get("carrier", "?"),
                    )
                    score = _default_score_incomplete()
            outputs[global_idx] = {
                **score,
                "verified_site": is_verified_site(rate.get("booking_url", "")),
            }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_agents.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hidden_charge.py tests/test_agents.py
git commit -m "refactor: differentiate LLM failure vs incomplete batch defaults"
```

---

## Phase 3 — Anti-Fabrication + Few-Shot + Retry

### Task 7: Add confidence field to HiddenChargeOutput + pipeline compliance

**Files:**
- Modify: `agents/hidden_charge.py`
- Modify: `pipeline.py`
- Modify: `tests/test_agents.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Add confidence test**

Add to `tests/test_agents.py` after the existing hidden-charge tests:

```python
def test_hidden_charge_output_includes_confidence(install_fake_llm):
    from agents.hidden_charge import BatchHiddenChargeOutput, HiddenChargeOutput

    def _stub_with_confidence(prompt_value):
        text = str(prompt_value)
        n = text.count("=== Rate ")
        return BatchHiddenChargeOutput(
            results=[
                HiddenChargeOutput(trust_score=40, flags=[], confidence="unclear")
                for _ in range(max(n, 1))
            ],
        )

    install_fake_llm("hidden_charge", {BatchHiddenChargeOutput: _stub_with_confidence})
    out = build_hidden_charge_agent().invoke(_batch_input())
    assert out[0]["confidence"] == "unclear"


def test_hidden_charge_confidence_defaults_to_high(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=85, flags=[])},
    )
    out = build_hidden_charge_agent().invoke(_batch_input())
    assert out[0]["confidence"] == "high"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agents.py::test_hidden_charge_output_includes_confidence -v`
Expected: FAIL — `confidence` key not in output dict

- [ ] **Step 3: Add confidence field to HiddenChargeOutput**

In `agents/hidden_charge.py`, add import:

```python
from typing import Any, Literal
```

Update `HiddenChargeOutput` class:

```python
class HiddenChargeOutput(BaseModel):
    trust_score: int = Field(
        ge=0, le=100,
        description="Transparency score 0-100. Higher = more surcharges itemised upfront.",
    )
    flags: list[str] = Field(
        description=(
            "Plain-English warnings drawn from the provided red-flag patterns "
            "that this quote exhibits. Empty list if none apply."
        ),
    )
    confidence: Literal["high", "low", "unclear"] = Field(
        default="high",
        description=(
            "How confident the assessment is. 'unclear' when the rate card "
            "lacks enough detail to meaningfully score — e.g., only a base "
            "price with no line items at all. Do NOT guess when data is "
            "insufficient."
        ),
    )
```

Update the `invoke` method to include `confidence` in the score dict (in the `local_idx < len(llm_results)` branch):

```python
                score = {
                    "trust_score": int(r.trust_score),
                    "flags": list(r.flags),
                    "confidence": r.confidence,
                }
```

Update both `_default_score_llm_failed` and `_default_score_incomplete` to include `confidence`:

```python
def _default_score_llm_failed() -> dict[str, Any]:
    return {"trust_score": 50, "flags": ["Automated scoring unavailable — LLM error"], "confidence": "low"}


def _default_score_incomplete() -> dict[str, Any]:
    return {"trust_score": 50, "flags": ["Automated scoring unavailable — incomplete batch"], "confidence": "low"}
```

Update the flagged-site short-circuit to include `confidence`:

```python
                outputs[i] = {
                    "trust_score": 0,
                    "flags": ["Site is flagged as deceptive"],
                    "verified_site": False,
                    "confidence": "high",
                }
```

- [ ] **Step 4: Extend pipeline compliance for unclear confidence**

In `pipeline.py`, update the compliance enforcement block:

```python
    for rate in ranked:
        if rate.get("trust_score", 0) < 50 or rate.get("confidence") == "unclear":
            rate["booking_url"] = ""
```

- [ ] **Step 5: Update conftest batch_hc_stub to include confidence**

In `tests/conftest.py`, update `batch_hc_stub` to include `confidence` in each `HiddenChargeOutput`:

```python
    def _stub(prompt_value: Any) -> BatchHiddenChargeOutput:
        text = str(prompt_value)
        n = text.count("=== Rate ")
        return BatchHiddenChargeOutput(
            results=[
                HiddenChargeOutput(trust_score=trust_score, flags=list(_flags), confidence="high")
                for _ in range(max(n, 1))
            ],
        )
```

- [ ] **Step 6: Update smoke test to check confidence key**

In `tests/test_smoke.py`, add `"confidence"` to `SCORED_RATE_KEYS`:

```python
SCORED_RATE_KEYS = {
    "carrier", "base_price_usd", "chargeable_weight_kg",
    "transit_days", "booking_url", "source_site", "scraped_at",
    "mode", "trust_score", "flags", "estimated_total_usd",
    "verified_site", "confidence",
}
```

- [ ] **Step 7: Update flagged-site test assertion**

In `tests/test_agents.py`, update `test_hidden_charge_short_circuits_flagged_site` assertion:

```python
    assert out == [{
        "trust_score": 0,
        "flags": ["Site is flagged as deceptive"],
        "verified_site": False,
        "confidence": "high",
    }]
```

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 9: Commit**

```bash
git add agents/hidden_charge.py pipeline.py tests/test_agents.py tests/conftest.py tests/test_smoke.py
git commit -m "feat: add confidence field to HiddenChargeOutput (anti-fabrication)"
```

---

### Task 8: Few-shot examples in hidden-charge prompt

**Files:**
- Modify: `agents/hidden_charge.py`

- [ ] **Step 1: Update `_PROMPT` in `agents/hidden_charge.py`**

Replace the `_PROMPT` definition (lines 71-87):

```python
_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a freight auditing expert. You review freight quote HTML "
     "against known red-flag patterns and score transparency."),
    ("human",
     "Route: {origin} -> {destination}, mode={mode}\n\n"
     "Red-flag patterns to check for ({mode}):\n{red_flags}\n\n"
     "{rag_context}"
     "Score each of the following {n} rate cards for transparency. "
     "Return a list of results in the SAME ORDER as the input cards.\n\n"
     "{rate_blocks}\n\n"
     "For each card, return a trust_score (0-100), the list of red-flag "
     "patterns (from the list above, verbatim) that this quote exhibits, "
     "and a confidence level (high/low/unclear).\n\n"
     "A quote with all surcharges itemised should score 85-100; a quote "
     "with only a base price and no fee breakdown should score 30-50; a "
     "quote missing standard fees for its mode should score below 30.\n\n"
     "If a rate card lacks enough detail to meaningfully score, set "
     "confidence to 'unclear'. Do NOT fabricate a precise score when "
     "the data is insufficient.\n\n"
     "--- EXAMPLES ---\n"
     "Example 1 (partial disclosure):\n"
     "Rate card shows: base price $1,200, fuel surcharge $180. "
     "Missing: THC, documentation fee.\n"
     "Result: trust_score=60, flags=[\"destination handling charge "
     "(DHC / THC) not itemised\", \"documentation fee above $75 without "
     "justification\"], confidence=\"high\"\n"
     "Reasoning: Two of four expected surcharges itemised. FSC shown but "
     "THC and doc fee absent.\n\n"
     "Example 2 (opaque quote):\n"
     "Rate card shows: total price $950, no breakdown.\n"
     "Result: trust_score=35, flags=[\"base price shown without itemised "
     "surcharges\"], confidence=\"low\"\n"
     "Reasoning: No fee breakdown at all. Unable to verify if surcharges "
     "are included or hidden.\n"
     "--- END EXAMPLES ---"),
])
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_agents.py -v`
Expected: all tests PASS (FakeChatModel doesn't parse prompts)

- [ ] **Step 3: Commit**

```bash
git add agents/hidden_charge.py
git commit -m "feat: add few-shot borderline examples to hidden-charge prompt"
```

---

### Task 9: Retry-with-feedback on structured output failure

**Files:**
- Modify: `agents/hidden_charge.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Add retry test**

Add to `tests/test_agents.py`:

```python
def test_hidden_charge_retries_on_validation_error(monkeypatch):
    """First LLM call returns bad output, second succeeds."""
    from langchain_core.runnables import Runnable

    call_count = {"n": 0}

    class RetryStructured(Runnable):
        def invoke(self, input, config=None, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ValueError("Invalid output: missing trust_score")
            return BatchHiddenChargeOutput(
                results=[HiddenChargeOutput(trust_score=70, flags=[], confidence="high")],
            )

    class RetryFake:
        def with_structured_output(self, schema):
            return RetryStructured()

    monkeypatch.setattr(
        "agents.hidden_charge.get_llm",
        lambda temperature=0.2: RetryFake(),
    )

    out = build_hidden_charge_agent().invoke(_batch_input())
    assert call_count["n"] == 2
    assert out[0]["trust_score"] == 70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agents.py::test_hidden_charge_retries_on_validation_error -v`
Expected: FAIL — no retry logic, first error propagates

- [ ] **Step 3: Add retry logic to hidden_charge.py**

In `agents/hidden_charge.py`, in the `invoke` method, replace the single `chain.invoke` try/except block (around lines 179-192) with a retry loop:

```python
            llm = get_llm(temperature=0.2)
            structured = llm.with_structured_output(BatchHiddenChargeOutput)
            chain = _PROMPT | structured
            prompt_vars = {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "red_flags": "\n".join(f"- {f}" for f in red_flags),
                "rag_context": rag_context,
                "n": len(to_score),
                "rate_blocks": rate_blocks,
            }
            for attempt in range(3):
                try:
                    batch = chain.invoke(prompt_vars)
                    llm_results = list(batch.results)
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error("hidden-charge batch LLM failed after 3 attempts: %s", e)
                        llm_failed = True
                        break
                    logger.warning(
                        "hidden-charge parse failed (attempt %d): %s", attempt + 1, e,
                    )
                    prompt_vars["rate_blocks"] += (
                        f"\n\n[RETRY: Previous response failed validation: {e}. "
                        f"Ensure output matches the schema exactly.]"
                    )
```

Remove the old `try/except` that set `llm_results` directly.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_agents.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hidden_charge.py tests/test_agents.py
git commit -m "feat: retry-with-feedback on hidden-charge structured output failure"
```

---

### Task 10: SummarizerOutput length guards + router prompt tightening

**Files:**
- Modify: `agents/summarizer.py`
- Modify: `agents/router.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Add summarizer validation tests**

Add to `tests/test_agents.py`:

```python
def test_summarizer_output_rejects_empty_string():
    with pytest.raises(ValidationError):
        SummarizerOutput(recommendation="")


def test_summarizer_output_rejects_overlong_string():
    with pytest.raises(ValidationError):
        SummarizerOutput(recommendation="x" * 2001)


def test_summarizer_output_accepts_valid_length():
    out = SummarizerOutput(recommendation="Book the cheapest option.")
    assert out.recommendation == "Book the cheapest option."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agents.py::test_summarizer_output_rejects_empty_string tests/test_agents.py::test_summarizer_output_rejects_overlong_string -v`
Expected: FAIL — empty string and overlong string currently accepted

- [ ] **Step 3: Update SummarizerOutput with length guards**

In `agents/summarizer.py`, replace the `recommendation` field:

```python
class SummarizerOutput(BaseModel):
    recommendation: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "3-4 sentence plain-English recommendation for a small business "
            "owner: which quote to book, why it is the best value, and one "
            "key thing to watch out for."
        )
    )
```

- [ ] **Step 4: Tighten router prompt**

In `agents/router.py`, replace the system message in `_PROMPT` (line 43-46):

```python
_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You advise small business owners on freight logistics. Write exactly "
     "one sentence. State the freight mode, the chargeable weight, and why "
     "it crossed the threshold."),
    ("human",
     "Shipment: product={product}, chargeable_weight={weight} kg, "
     "origin={origin}, destination={destination}.\n"
     "Mode already classified as '{mode}' based on weight thresholds "
     "(<68kg courier, <500kg air, >=500kg sea).\n"
     "Write ONE sentence explaining why this mode fits this shipment."),
])
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add agents/summarizer.py agents/router.py tests/test_agents.py
git commit -m "feat: summarizer length guards + router prompt tightening (CCA-F D4)"
```

---

## Phase 4 — CLAUDE.md Trim + Skills/Rules/Commands

### Task 11: Move Phase 5 backlog to skill, add rules and commands

**Files:**
- Modify: `CLAUDE.md` (lines 22-36)
- Create: `.claude/skills/freight-backlog/SKILL.md`
- Create: `.claude/rules/agents.md`
- Create: `.claude/commands/fix-tests.md`
- Create: `.claude/commands/validate-schema.md`
- Create: `.claude/commands/run-smoke.md`

- [ ] **Step 1: Create the skill file**

Create `.claude/skills/freight-backlog/SKILL.md`:

```markdown
---
name: freight-backlog
description: Phase 5 backlog — known bugs, polish items, and non-blocking improvements surfaced by reviewers
context: fork
---

# Phase 5 Backlog (non-blocking)

> **Status note (2026-04-22):** the Phase 5 test suite LOCKS current behaviour in. Items below describe bugs/polish to fix in a future commit — tests will need updating alongside each fix.

- `tools/cache.py`: `clear_cache` has a redundant `_connect().close()` line that leaks on a failing reconnect — drop it; table is recreated lazily on next call.
- `tools/cache.py`: error logs for unparseable `cached_at` / `rates_json` should include origin/destination in the `%s->%s` format used elsewhere.
- `tools/scraper.py`: `_parse_days_from_text` reuses `_PRICE_RE` but doesn't strip commas; `"2,000 days"` raises `ValueError` (silently drops the row via the per-parser except). Use a dedicated `r"\d+"` or strip commas.
- `tools/scraper.py`: `Query.origin` / `destination` / `mode` are unused in v1 (reserved for live mode) — document with a one-line note or defer trimming until live mode is wired.
- ~~`pipeline.py`: hidden-charge LLM calls are serial (~0.5s × N rates). Parallelise via `ThreadPoolExecutor` or batch all N cards into one LLM call for ~3× latency reduction.~~ **Done (Phase 5.5):** batched into single LLM call.
- `agents/rate_comparator.py`: no LLM call; the `Runnable` wrapper is pure A2A ceremony. If A2A never ships, collapse to a plain function.
- `agents/summarizer.py`: `payload["shipment"]` is an unguarded `[]` access while `router_reason` / `ranked_rates` use `.get(default)` — inconsistent. Either make all three defaults-based or raise a typed error.
- `agents/summarizer.py`: output isn't streamed; Phase 4 Streamlit can add streaming if UX demands.
- `agents/summarizer.py`: optional `query_pageindex(incoterms_doc_id, ...)` call for Incoterms-aware advice — hook exists in design, not wired.
```

- [ ] **Step 2: Create the rules file**

Create `.claude/rules/agents.md`:

```markdown
---
paths:
  - "agents/**"
---

- Always import `get_llm()` from `tools.llm_router` — never instantiate ChatGroq, ChatOpenAI, or ChatGoogleGenerativeAI directly
- All agents receive `chargeable_weight_kg`, never `gross_weight_kg`
- All agents return via Pydantic BaseModel + `with_structured_output`
- Use temperature 0.2 for classification/scoring, 0.5 for prose generation
- Hidden-charge agent includes `confidence` field (high/low/unclear) in all output paths
```

- [ ] **Step 3: Create slash commands**

Create `.claude/commands/fix-tests.md`:

```markdown
Run the test suite, identify failures, and fix them one by one.

1. Run `uv run pytest -v` and capture output
2. For each failing test, read the test file and the source file it tests
3. Fix the minimal code change to make the test pass
4. Re-run the single test to confirm it passes
5. After all fixes, run the full suite to check for regressions
6. Commit with message: "fix: resolve test failures"
```

Create `.claude/commands/validate-schema.md`:

```markdown
Validate that all agent outputs conform to their Pydantic schemas.

1. Import all agent builders: `build_router_agent`, `build_hidden_charge_agent`, `build_rate_comparator_agent`, `build_summarizer_agent`
2. Use FakeChatModel from `tests/conftest.py` to mock LLM calls
3. Invoke each agent with the SHIPMENT_200KG fixture
4. Assert output dicts contain all required keys per CLAUDE.md data contracts:
   - Router: `{mode, reason}`
   - Hidden-charge: `{trust_score, flags, verified_site, confidence}`
   - Rate-comparator: `{estimated_total_usd}` added to input rates
   - Summarizer: `{recommendation}` (1-2000 chars)
5. Report pass/fail per agent
```

Create `.claude/commands/run-smoke.md`:

```markdown
Run the CLAUDE.md-mandated Delhi→Rotterdam smoke test.

```
uv run pytest tests/test_smoke.py::test_smoke_delhi_rotterdam_12kg_completes_end_to_end -v
```

Expected: PASS with courier mode, 10 rates, no errors, non-empty recommendation.
```

- [ ] **Step 4: Trim CLAUDE.md**

In `CLAUDE.md`, replace lines 22-35 (the entire Phase 5 backlog section) with:

```markdown
**Phase 5 backlog:** see `.claude/skills/freight-backlog/SKILL.md` for known bugs and polish items.
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS (no code changes in this task)

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md .claude/skills/freight-backlog/SKILL.md .claude/rules/agents.md .claude/commands/fix-tests.md .claude/commands/validate-schema.md .claude/commands/run-smoke.md
git commit -m "chore: trim CLAUDE.md, add skills/rules/commands (CCA-F D3)"
```

---

## Phase 5 — UI Updates

### Task 12: Confidence badge + structured error display + shipment echo in UI

**Files:**
- Modify: `app.py`
- Modify: `tests/test_ui_smoke.py`

- [ ] **Step 1: Update `_render_rate_card` in app.py for confidence**

In `app.py`, in `_render_rate_card` (starting around line 796), add confidence handling after the `trust` variable:

```python
    confidence = rate.get("confidence", "high")
```

Replace the trust bar HTML block (lines 896-903) with a confidence-aware version:

```python
    if confidence == "unclear":
        trust_bar_html = f"""
          <div style="background:var(--surface-2); border:1px solid var(--border);
                      border-radius:8px; padding:8px 12px; text-align:center;">
            <span style="color:var(--text-3); font-size:12px; font-weight:600;">
              Insufficient data — score is estimated
            </span>
            <div style="color:var(--text-4); font-size:10px; margin-top:2px;">
              Trust score: {trust}/100
            </div>
          </div>
        """
    else:
        low_conf_note = (
            ' <span style="color:var(--text-4); font-size:10px;">(low confidence)</span>'
            if confidence == "low" else ""
        )
        trust_bar_html = f"""
          <div>
            <div class="fiq-trustbar-track">
              <div class="fiq-trustbar-fill" style="width:{max(0, min(100, trust))}%; background:{band_colour};"></div>
            </div>
            <div style="display:flex; justify-content:space-between; color:var(--text-3); font-size:11px; margin-top:4px;">
              <span>Trust score</span>
              <span><strong style="color:{band_colour};">{trust}</strong> / 100 · {band_label}{low_conf_note}</span>
            </div>
          </div>
        """
```

Then in the card HTML template, replace the inline trust bar div with `{trust_bar_html}`.

Update the book button logic to also check confidence:

```python
    book_button_html = ""
    if confidence == "unclear":
        book_button_html = (
            '<span style="color:var(--text-4); font-size:13px;">Insufficient data</span>'
        )
    elif trust >= 80:
        book_button_html = (
            f'<a href="{_html_escape(rate.get("booking_url", "#"))}" target="_blank" '
            f'style="background:var(--accent); color:#06070a; font-weight:700; '
            f'padding:7px 14px; border-radius:8px; text-decoration:none; '
            f'font-size:13px; letter-spacing:-0.01em;">Book now →</a>'
        )
    elif trust >= 50:
        book_button_html = (
            f'<a href="{_html_escape(rate.get("booking_url", "#"))}" target="_blank" '
            f'style="color:var(--amber); border:1px solid var(--amber); '
            f'padding:6px 13px; border-radius:8px; text-decoration:none; '
            f'font-size:13px;">Book with caution</a>'
        )
    else:
        book_button_html = (
            '<span style="color:var(--text-4); font-size:13px;">Do not book</span>'
        )
```

- [ ] **Step 2: Update `_render_results` for structured error display**

In `app.py`, replace the error display block in `_render_results` (lines 988-994):

```python
    if result.get("errors"):
        error_stages = [e.get("stage", "unknown") for e in result["errors"] if isinstance(e, dict)]
        has_transient = any(
            isinstance(e, dict) and e.get("error_category") == "transient"
            for e in result["errors"]
        )
        if has_transient:
            st.warning("Some rate sources were temporarily unavailable. Results may be incomplete.")
        elif "hidden_charge" in error_stages:
            st.warning("Automated trust scoring was unavailable for some rates. Flagged rates are marked.")
        else:
            st.warning(f"{len(result['errors'])} warning(s) during analysis.")

        with st.expander("Technical details"):
            for err in result["errors"]:
                if isinstance(err, dict):
                    st.text(f"Stage: {err.get('stage', '?')} | Category: {err.get('error_category', '?')} | Retryable: {err.get('is_retryable', '?')}")
                else:
                    st.text(str(err))
```

- [ ] **Step 3: Update `_render_how_calculated` for shipment echo**

In `app.py`, update `_render_how_calculated` (around line 923). Add a shipment echo section before the existing content:

```python
def _render_how_calculated(result: RecommendationResult) -> None:
    with st.expander("How this analysis was calculated"):
        shipment = result.get("shipment_input")
        if shipment:
            st.markdown(
                f"""**Your inputs**
- Product: {shipment.get("product", "?")}
- Gross weight: {shipment.get("gross_weight_kg", 0):.1f} kg
- Volume weight: {shipment.get("volume_weight_kg", 0):.1f} kg
- Chargeable weight: {shipment.get("chargeable_weight_kg", 0):.1f} kg ({shipment.get("weight_basis", "?")})
- Route: {shipment.get("origin", "?")} → {shipment.get("destination", "?")}
- Urgency: {shipment.get("urgency", "standard")}
"""
            )
        st.markdown(
            f"""
**1. Chargeable weight**
```
volume_weight_kg    = (L × W × H) / 5000
chargeable_weight_kg = max(gross_weight_kg, volume_weight_kg)
```

**2. Mode classification** (deterministic thresholds)
```
< 68 kg   → courier
< 500 kg  → air_freight
≥ 500 kg  → sea_freight
```
Your shipment: **{result.get("mode", "?")}** — *{result.get("router_reason", "")}*

**3. Trust-adjusted total** (per rate)
```
factor              = (100 - trust_score) / 100 × 0.5
estimated_total_usd = base_price × (1 + factor)
```
trust 100 → +0%, trust 50 → +25%, trust 0 → +50%

**4. Ranking**
All rates sorted ascending by `estimated_total_usd`.
Source sites: {result.get("sites_succeeded", 0)} of 3 returned quotes.
Cache hit: {result.get("cache_hit", False)}.

**5. LLM pipeline**
- Groq `llama-3.3-70b-versatile` (primary) with OpenAI → Gemini fallback
- 3 LLM calls per search (1 router + 1 batched hidden-charge + 1 summarizer)
- Structured output enforced via Pydantic schemas per agent
"""
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_ui_smoke.py -v`
Expected: all tests PASS (UI smoke tests only check imports and helper functions)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: confidence badge, structured error display, shipment echo in UI"
```

---

## Final Verification

### Task 13: Full suite green + coverage check

- [ ] **Step 1: Run full test suite with coverage**

Run: `uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term-missing -v`
Expected: all tests PASS, coverage ≥80% on all modules

- [ ] **Step 2: Run smoke test explicitly**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: all 3 smoke tests PASS

- [ ] **Step 3: Verify no regressions in existing test count**

Run: `uv run pytest --co -q | tail -1`
Expected: test count ≥ 96 (original) + new tests added

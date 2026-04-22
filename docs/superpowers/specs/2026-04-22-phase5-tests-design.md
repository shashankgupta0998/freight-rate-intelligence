# Phase 5 — Tests: Design

**Date:** 2026-04-22
**Author:** Shashank Gupta (with Claude)
**Status:** Approved for implementation planning
**Related:** `CLAUDE.md` (Build order §Phase 5, §Testing requirements), prior phase specs 2026-04-17 (P1), 2026-04-18 (P2, P3), 2026-04-20 (Phase 4 UI)

---

## 1. Purpose

Ship the test suite. Achieve ≥80% line coverage on `agents/`, `tools/`, and `pipeline.py` with fast, deterministic, zero-network tests. Every agent runs against a `FakeChatModel` fake; every PageIndex / HTTP seam is mocked. The CLAUDE.md-mandated `test_smoke.py` with query `(electronics, 12kg, 40×30×20cm, Delhi, Rotterdam)` passes end-to-end in the suite.

Portfolio story: production-shaped test suite — runnable in <5s with zero external dependencies; coverage reports exceed the CLAUDE.md target; shared fixtures (`FakeChatModel`, `install_fake_llm`, `isolated_cache_db`) make each test read like a single focused assertion.

## 2. Scope

### In scope (10 new files + 1 modified)

| File | Tests | ~Lines |
|------|-------|--------|
| `tests/conftest.py` | `FakeChatModel` class, fixtures, shared sample constants | ~110 |
| `tests/test_agents.py` | Router (5) + Hidden-charge (8) + Rate-comparator (6) + Summarizer (6) = 25 | ~280 |
| `tests/test_scraper.py` | 3 parsers + helpers + aggregator + fetcher = 15 | ~170 |
| `tests/test_cache.py` | get/put/clear + TTL boundaries + corruption paths = 10 | ~130 |
| `tests/test_validator.py` | Site checks + red-flag merging + malformed URLs = 8 | ~80 |
| `tests/test_llm_router.py` | Construction + singleton (no real calls) = 4 | ~50 |
| `tests/test_pageindex_client.py` | `is_enabled`, `doc_id_for`, `query_pageindex` (mocked HTTP) = 8 | ~110 |
| `tests/test_pipeline.py` | Integration with mocked LLMs + real scraper + isolated cache = 10 | ~200 |
| `tests/test_rag.py` | Hidden-charge PageIndex branch (mocked) = 5 | ~90 |
| `tests/test_smoke.py` | CLAUDE.md fixed query, end-to-end shape assertions = 3 | ~60 |
| `pyproject.toml` (modified) | Add `pytest-cov>=5.0` to `[tool.uv].dev-dependencies` | 1 line |

**Total new test code:** ~1,280 lines across ~94 tests, plus ~110 lines of shared conftest.

**Existing, untouched:** `tests/test_ui_smoke.py` (7 tests from Phase 4).

### Out of scope

- `app.py` — covered by Phase 4's `test_ui_smoke.py` (helper functions + schema). No Streamlit `AppTest` integration in this phase.
- `knowledge_base/ingest.py` — one-shot CLI hand-verified in Phase 1. Add to Phase-5 backlog if ever needed.
- Live LLM calls. Per CLAUDE.md: "assert on output schema, not LLM text." Every `get_llm()` is patched.
- Live PageIndex calls. `requests.post` mocked at the `tools.pageindex_client` module binding.
- Performance / load tests.
- Property-based (Hypothesis), mutation testing.

### Decisions locked in Q1–Q3

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **One phase, one plan.** | Code under test is stable; conftest design is shared across files and can't be deferred. |
| D2 | **`FakeChatModel` class in `conftest.py` inheriting from `langchain_core.runnables.Runnable`.** Reused via `install_fake_llm("module", {Schema: instance})` fixture. | Readable test setup (`one line per agent`), guaranteed to work with `_PROMPT \| fake` composition, stack traces on failures are real Python frames. |
| D3 | **Coverage target: ≥80% on `agents/` + `tools/` + `pipeline.py`.** Command: `uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term-missing`. | CLAUDE.md sets 80% on agents+tools; pipeline.py added because it's the A2A entry point and has non-trivial branches. |
| D4 | **Zero network during test suite.** All LLM + PageIndex HTTP mocked. | CLAUDE.md spec; also makes CI cheap and deterministic. |
| D5 | **`test_smoke.py` runs with mocked LLM.** Assertions on shape (mode, rate count, `ScoredRate` keys, recommendation non-empty), not LLM text. | CLAUDE.md: "assert on output schema, not LLM text." |
| D6 | **`test_rag.py` covers the `USE_PAGEINDEX_RUNTIME=true` branch of the hidden-charge agent.** Mocks `query_pageindex` at the `agents.hidden_charge` module binding. | CLAUDE.md's phrasing "mock PageIndex MCP tool responses" predates Phase 3's REST design; we mock at the seam that actually exists (the client function, not MCP tools). |
| D7 | **Patch monkey-patches at the agent-module binding**, not the source. `monkeypatch.setattr("agents.router.get_llm", ...)` — not `"tools.llm_router.get_llm"`. | `from tools.llm_router import get_llm` creates a per-module reference; the source patch is a no-op once the agent module has imported. |
| D8 | **`USE_PAGEINDEX_RUNTIME=false` by default for all tests** via an autouse fixture. Tests that need the on-branch explicitly flip it via `monkeypatch.setenv`. | Prevents accidental PageIndex runtime-path leakage across tests; matches the production default. |
| D9 | **Shared sample data (`SHIPMENT_200KG`, `SAMPLE_RATE_A`, `CLAUDE_MD_SMOKE_SHIPMENT`) in `conftest.py`.** | DRY; schema changes in CLAUDE.md flow from one update. |
| D10 | **LLM-free schema assertions.** Tests assert on `ScoredRate` keys (`trust_score`, `flags`, `estimated_total_usd`, `verified_site`, etc.) being present + typed, never on LLM prose content. | Determinism under model drift. |

## 3. `conftest.py` design

Four fixture classes + shared constants + `FakeChatModel`. ~110 lines.

### 3.1 FakeChatModel

```python
from langchain_core.runnables import Runnable
from pydantic import BaseModel

class _FakeStructured(Runnable):
    """Returned by FakeChatModel.with_structured_output(Schema)."""
    def __init__(self, response: BaseModel):
        self._response = response
    def invoke(self, input, config=None, **kwargs):
        return self._response


class FakeChatModel(Runnable):
    """Drop-in replacement for ChatLiteLLM in agent tests.

    Agent calls:
        llm = get_llm(temperature=...)
        structured = llm.with_structured_output(Schema)
        chain = _PROMPT | structured
        result = chain.invoke(inputs)  # -> Schema instance

    Our fake maps {Schema: pre-built instance}. If a test calls
    with_structured_output on a schema we didn't stub, we raise
    KeyError so the misconfiguration is visible (no silent None).
    """
    def __init__(self, structured_responses: dict[type[BaseModel], BaseModel]):
        self._responses = structured_responses

    def with_structured_output(self, schema: type[BaseModel]):
        if schema not in self._responses:
            raise KeyError(
                f"FakeChatModel has no stub for {schema.__name__}. "
                f"Add {schema.__name__}: <instance> to structured_responses."
            )
        return _FakeStructured(self._responses[schema])

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError(
            "FakeChatModel.invoke() must not be called without "
            "with_structured_output(Schema) first — agents never call "
            ".invoke on the raw LLM."
        )
```

### 3.2 install_fake_llm fixture

```python
@pytest.fixture
def install_fake_llm(monkeypatch):
    """Install a FakeChatModel into an agent module's get_llm binding.

    Usage:
        def test_router(install_fake_llm):
            install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
            ...
    """
    def _install(module_name: str, responses: dict):
        fake = FakeChatModel(structured_responses=responses)
        monkeypatch.setattr(
            f"agents.{module_name}.get_llm",
            lambda temperature=0.2: fake,
        )
        return fake
    return _install
```

### 3.3 Other fixtures

```python
@pytest.fixture
def isolated_cache_db(tmp_path, monkeypatch):
    """Redirect tools.cache to a temp SQLite DB for the test."""
    db = tmp_path / "cache.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(db))
    yield db


@pytest.fixture
def reset_validator_cache():
    """Clear the validator's _patterns LRU cache before and after."""
    from tools.validator import _patterns
    _patterns.cache_clear()
    yield
    _patterns.cache_clear()


@pytest.fixture(autouse=True)
def _disable_pageindex_runtime(monkeypatch):
    """Autouse: default to USE_PAGEINDEX_RUNTIME=false for every test."""
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "false")


def _install_all_fakes(install_fake_llm):
    """Helper for pipeline + smoke tests — install defaults for all 3 LLM agents."""
    from agents.router import RouterOutput
    from agents.hidden_charge import HiddenChargeOutput
    from agents.summarizer import SummarizerOutput

    install_fake_llm("router", {
        RouterOutput: RouterOutput(reason="Stub reason — mode decided by rules.")
    })
    install_fake_llm("hidden_charge", {
        HiddenChargeOutput: HiddenChargeOutput(trust_score=85, flags=[])
    })
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(recommendation="Stub — book the top-ranked quote.")
    })
```

### 3.4 Shared sample constants

```python
SHIPMENT_200KG: dict = {
    "product": "electronics", "gross_weight_kg": 180.0,
    "length_cm": 100.0, "width_cm": 100.0, "height_cm": 100.0,
    "volume_weight_kg": 200.0, "chargeable_weight_kg": 200.0,
    "weight_basis": "volume",
    "origin": "Delhi", "destination": "Rotterdam", "urgency": "standard",
}

SAMPLE_RATE_A: dict = {
    "carrier": "Lufthansa Cargo", "mode": "air_freight", "source_site": "freightos",
    "base_price_usd": 892.0, "trust_score": 85, "estimated_total_usd": 958.9,
    "chargeable_weight_kg": 200.0, "transit_days": 7, "flags": [],
    "verified_site": True, "booking_url": "https://ship.freightos.com/book/LH-1",
    "scraped_at": "2026-04-22T00:00:00+00:00",
}

CLAUDE_MD_SMOKE_SHIPMENT: dict = {
    "product": "electronics",
    "gross_weight_kg": 12.0,
    "length_cm": 40.0, "width_cm": 30.0, "height_cm": 20.0,
    "volume_weight_kg": 4.8,
    "chargeable_weight_kg": 12.0,
    "weight_basis": "gross",
    "origin": "Delhi", "destination": "Rotterdam", "urgency": "standard",
}
```

## 4. `test_agents.py` (25 tests)

### Router (5)
- Pure `classify_mode` at three boundaries (courier, air, sea).
- Agent-level with `FakeChatModel` for the reason field.
- Dual-shape payload tolerance (bare dict vs `{"input": ...}`).

### Hidden-charge (8)
- Flagged-site short-circuit (LLM NOT called; verified by the FakeChatModel raising if queried).
- Well-itemised card scoring.
- Verified-site False for unknown domain.
- RAG-off path: `query_pageindex` not invoked.
- RAG-on path: `query_pageindex` invoked with mode + route in the question.
- RAG degraded when `doc_id_for` returns None (proceeds without RAG, no raise).
- Missing booking_url handled.
- Pydantic rejects `trust_score > 100` at fixture construction (demonstrates schema safety).

### Rate-comparator (6, no LLM)
- Formula anchor points (trust 100/50/0 → +0/25/50%).
- Clamping for out-of-range trust scores.
- Sort ascending.
- Input-dict immutability (`{**rate, ...}` spread).
- Non-list input raises `TypeError`.
- Empty list returns empty list.

### Summarizer (6)
- Returns `{recommendation: str}` dict.
- `_format_rates_table` pure-function tests (empty, single rate).
- Handles empty `ranked_rates` gracefully.
- `_format_rates_table` includes flags in output.
- `get_llm` called with `temperature=0.5` (captured via spy).
- Shipment + router_reason appear in prompt context (captured via a custom `_FakeStructured` that records its input).

## 5. Tool tests (5 files, ~45 tests)

### 5.1 `test_scraper.py` (15)
- Each parser returns correct carrier set + counts from its fixture.
- `_card_html` populated on every returned rate.
- `parse_icontainers` data-usd fallback (MSC row tests the text-path branch).
- Empty HTML → `[]` for all three parsers.
- Malformed cards skipped silently with debug log.
- Helpers: `_normalise_mode` (air, sea, LCL/FCL, courier, None default), `_parse_usd` variants + error, `_parse_duration_days`.
- `scrape_all` returns 10 rates with full `ScrapedRate` schema.
- `scrape_all` continues on per-site failure (WARN logged).
- `fetch_site` raises `NotImplementedError` when `LIVE_SCRAPING=true`.

### 5.2 `test_cache.py` (10)
- Put-then-get round-trip.
- Miss returns None.
- TTL expiry (age > 6h → None) via raw-sqlite `cached_at` mutation.
- Fresh within TTL (5h59m → hit).
- Corrupt `rates_json` → None + error log.
- Unparseable `cached_at` → None.
- Upsert overwrites via `INSERT OR REPLACE`.
- `clear_cache` drops rows.
- `CACHE_DB_PATH` env override works.
- `_connect` creates parent dir.

### 5.3 `test_validator.py` (8)
- Exact-domain, subdomain, www-stripping, unknown, empty URL, malformed URL.
- `is_flagged_site` against empty `flagged_sites`.
- `red_flags_for_mode` merges generic + mode-specific (10 entries each for air/sea).

### 5.4 `test_llm_router.py` (4)
- `get_llm()` returns `ChatLiteLLM` instance.
- `@lru_cache` singleton: repeated calls with same args return same instance.
- `maxsize=1` behaviour under temperature variation.
- `_MODEL_LIST` exposes three provider aliases.

### 5.5 `test_pageindex_client.py` (8)
- `is_enabled` default (unset → False), explicit false, case-insensitive true.
- `doc_id_for` returns registered id; None for unknown filename (registry patched to a fake dict).
- `query_pageindex` success path (fake `requests.post` response with valid body).
- Missing `PAGEINDEX_API_KEY` → None + warning log.
- Non-2xx HTTP → None + warning log.
- Network error (`requests.RequestException`) → None.
- Malformed response body (no `choices`) → None.

## 6. Integration + smoke tests (3 files, ~18 tests)

### 6.1 `test_pipeline.py` (10)
- Happy path: all three LLM-touching agents faked, 10 rates, errors empty, `_card_html` stripped.
- Second call hits cache (`cache_hit is True`).
- Courier mode for 12kg shipment.
- Sea mode for 600kg shipment.
- `on_progress` callback fires in the correct order (classifying_mode → scraping → hidden_charge:1/10..10/10 → ranking → writing_recommendation → done).
- Per-rate hidden-charge failure: rate dropped, `errors` captures it, pipeline succeeds with 9 rates.
- Empty scrape returns diagnostic (`rates=[]`, "No rate quotes available...").
- Summarizer failure degrades (empty recommendation + error entry, rates intact).
- `on_progress=None` default doesn't crash.
- Internal `_card_html` stripped from every returned rate.

### 6.2 `test_rag.py` (5)
- Hidden-charge calls `query_pageindex` when flag on. Captures call args — assert mode + route in the question.
- Hidden-charge skips `query_pageindex` when flag off (autouse default).
- RAG query format mentions mode, origin, destination.
- `doc_id_for` returns None → agent proceeds without RAG, no raise.
- `query_pageindex` returns None (network failure) → agent proceeds without RAG.

### 6.3 `test_smoke.py` (3)
- CLAUDE.md-mandated query `(electronics, 12kg, 40×30×20cm, Delhi, Rotterdam)` completes end-to-end. Asserts: `mode == "courier"`, `errors == []`, every rate has the full `ScoredRate` schema, recommendation is non-empty string.
- Rates sorted ascending by `estimated_total_usd`.
- Second run of the same query hits cache.

## 7. Implementation sequence

```
 1. pyproject.toml: add pytest-cov>=5.0 to [tool.uv] dev-dependencies; uv sync
 2. tests/conftest.py (FakeChatModel + fixtures + shared constants + _install_all_fakes)
 3. tests/test_agents.py (25 tests)
 4. tests/test_scraper.py (15 tests)
 5. tests/test_cache.py (10 tests)
 6. tests/test_validator.py (8 tests)
 7. tests/test_llm_router.py (4 tests)
 8. tests/test_pageindex_client.py (8 tests)
 9. tests/test_pipeline.py (10 tests)
10. tests/test_rag.py (5 tests)
11. tests/test_smoke.py (3 tests)
12. Run coverage: `uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term-missing`. If any module <80%, add targeted tests to close the gap.
13. CLAUDE.md update: Current state → "Phase 5 complete, coverage X%/Y%/Z% on agents/tools/pipeline". Move the few backlog items that this phase closed out (or confirm they remain).
14. Push Phase 5 commits to GitHub.
```

## 8. Acceptance criteria

- `uv run pytest` runs clean: ~94 new tests + 7 existing UI-smoke = ~101 tests, all passing.
- `uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term-missing` shows ≥80% on each of the three modules.
- Zero network during the suite. Total wall-time < 5 seconds on a cold `.venv` (excluding uv-sync).
- `tests/test_smoke.py` passes with the CLAUDE.md-mandated query.
- CLAUDE.md's Current state section reflects Phase 5 complete + coverage numbers.

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Pydantic schema constraints (`trust_score: Field(ge=0, le=100)`) reject `FakeChatModel`'s pre-set values at fixture construction | Instance values respect schema bounds; one dedicated test (`test_hidden_charge_pydantic_rejects_trust_over_100`) validates the guardrail |
| `lru_cache` leaks between tests (get_llm, validator._patterns, pageindex_client._registry) | `install_fake_llm` patches per-module binding, bypassing source cache. `reset_validator_cache` fixture handles the validator case. `pageindex_client._registry` patched per-test where needed. |
| `_card_html` field leaks into final `RecommendationResult` | Explicit test `test_run_pipeline_strips_internal_card_html_field` + assertion in `test_run_pipeline_happy_path` |
| Coverage target misses by a few percent | Task 12 in the sequence is the measure-and-close step; ~3-5 additional targeted tests typically close a 2-5% gap |
| Test suite accumulates ~1300 lines and becomes hard to navigate | File-per-module layout + explicit fixture names + shared constants in conftest keep each file <300 lines. |
| `FakeChatModel` diverges from real `ChatLiteLLM` API as LangChain evolves | The fake implements only `with_structured_output(Schema) -> Runnable`. If LangChain adds required protocol methods, tests fail fast at construction. Narrow surface area keeps the fake cheap to update. |

## 10. Phase-5 follow-ups (non-blocking; surface during implementation)

- Address the 10 Phase 5 backlog items already captured in CLAUDE.md (cache clear-cache redundancy, scraper comma bug, summarizer hardening, etc.) as tests surface them. These are tracked separately — Phase 5 tests LOCK the current behaviour in; fixes come in a follow-up "Phase 5.5 polish" commit.
- AppTest-based integration test for `app.py` form submission. Deferred: needs a Streamlit runtime harness and doesn't affect coverage targets.
- CI configuration (GitHub Actions): `uv sync --dev` + `uv run pytest --cov=... --cov-fail-under=80`. Deferred to Phase 6 alongside the deploy story.

## 11. Non-goals

- No live LLM calls.
- No live PageIndex calls.
- No `app.py` line-coverage target.
- No `knowledge_base/ingest.py` line-coverage target.
- No performance, mutation, or property-based tests.
- No CI wiring (deferred to Phase 6).
- No backlog fixes (Phase 5 locks current behaviour; fixes land in a separate commit set).

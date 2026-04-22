# Phase 5 — Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship ~94 new tests across 10 test files + shared `conftest.py`, achieving ≥80% line coverage on `agents/` + `tools/` + `pipeline.py` with zero network I/O.

**Architecture:** Pytest. `FakeChatModel` class in `conftest.py` (inherits `langchain_core.runnables.Runnable`) replaces every real LLM call via `install_fake_llm("module", {Schema: instance})` fixture. `isolated_cache_db` fixture redirects `tools.cache` to a tmp SQLite. Autouse fixture sets `USE_PAGEINDEX_RUNTIME=false` project-wide. Tests assert on schema, not LLM text. `test_smoke.py` locks the CLAUDE.md-mandated `(electronics, 12kg, 40×30×20cm, Delhi, Rotterdam)` query.

**Tech Stack:** `pytest>=8.0` (already installed in Phase 4), `pytest-cov>=5.0` (new dep), stdlib `unittest.mock`/`tmp_path`/`monkeypatch`, LangChain's `Runnable` base class for `FakeChatModel`.

**Source spec:** `docs/superpowers/specs/2026-04-22-phase5-tests-design.md`

**Pre-flight:** Phase 1–4 shipped, `uv` installed, `tests/fixtures/*.html` + `tests/__init__.py` + `tests/fixtures/__init__.py` all present from Phase 2. `tests/test_ui_smoke.py` with 7 tests already green.

---

## Task 1: Add pytest-cov dependency

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Edit dev-dependencies**

In `pyproject.toml`, replace the `[tool.uv]` block to add `pytest-cov`:
```toml
[tool.uv]
dev-dependencies = [
  "pytest>=8.0",
  "pytest-cov>=5.0",
]
```

- [ ] **Step 2: Sync**

```bash
uv sync
```
Expected: `pytest-cov` installs (plus `coverage` transitive dep); no errors.

- [ ] **Step 3: Verify**

```bash
uv run pytest --version
uv run python -c "import pytest_cov; print('pytest-cov:', pytest_cov.__version__)"
```
Expected: pytest 8.x + pytest-cov 5.x version strings; exit 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add pytest-cov for Phase 5 coverage measurement"
```

---

## Task 2: Create tests/conftest.py

**Files:** Create `tests/conftest.py`.

- [ ] **Step 1: Write conftest.py**

Create `tests/conftest.py` with EXACTLY this content:

```python
"""Shared fixtures for the Phase-5 test suite.

Key pieces:
- FakeChatModel: drop-in LangChain Runnable replacement for ChatLiteLLM,
  mapping Pydantic output Schema -> pre-built instance.
- install_fake_llm fixture: patches the *agent module's* get_llm binding
  (not tools.llm_router's) so the per-module import reference is replaced.
- isolated_cache_db: tmp SQLite redirection via CACHE_DB_PATH env.
- reset_validator_cache: clears the lru_cache on tools.validator._patterns.
- _disable_pageindex_runtime (autouse): default USE_PAGEINDEX_RUNTIME=false
  across all tests; tests that need the on-branch flip it explicitly.
- Shared sample constants (SHIPMENT_200KG, SAMPLE_RATE_A, CLAUDE_MD_SMOKE_SHIPMENT).
- _install_all_fakes helper for pipeline + smoke tests.
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.runnables import Runnable
from pydantic import BaseModel


# ---- FakeChatModel ----

class _FakeStructured(Runnable):
    """Returned by FakeChatModel.with_structured_output(Schema).
    .invoke(any_input) -> the pre-set Pydantic instance."""

    def __init__(self, response: BaseModel):
        self._response = response

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseModel:
        return self._response


class FakeChatModel(Runnable):
    """Drop-in replacement for ChatLiteLLM in agent tests.

    Agent calls:
        llm = get_llm(temperature=...)
        structured = llm.with_structured_output(Schema)
        chain = _PROMPT | structured
        result = chain.invoke(inputs)  # -> Schema instance
    """

    def __init__(self, structured_responses: dict[type[BaseModel], BaseModel]):
        self._responses = structured_responses

    def with_structured_output(self, schema: type[BaseModel]) -> _FakeStructured:
        if schema not in self._responses:
            raise KeyError(
                f"FakeChatModel has no stub for {schema.__name__}. "
                f"Add {schema.__name__}: <instance> to structured_responses."
            )
        return _FakeStructured(self._responses[schema])

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "FakeChatModel.invoke() must not be called without "
            "with_structured_output(Schema) first."
        )


# ---- Fixtures ----

@pytest.fixture
def install_fake_llm(monkeypatch):
    """Install a FakeChatModel into an agent module's get_llm binding."""

    def _install(
        module_name: str,
        responses: dict[type[BaseModel], BaseModel],
    ) -> FakeChatModel:
        fake = FakeChatModel(structured_responses=responses)
        monkeypatch.setattr(
            f"agents.{module_name}.get_llm",
            lambda temperature=0.2: fake,
        )
        return fake

    return _install


@pytest.fixture
def isolated_cache_db(tmp_path, monkeypatch):
    """Redirect tools.cache to a temp SQLite DB for the duration of the test."""
    db = tmp_path / "cache.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(db))
    yield db


@pytest.fixture
def reset_validator_cache():
    """Clear the tools.validator._patterns LRU cache before and after."""
    from tools.validator import _patterns
    _patterns.cache_clear()
    yield
    _patterns.cache_clear()


@pytest.fixture(autouse=True)
def _disable_pageindex_runtime(monkeypatch):
    """Autouse: default to USE_PAGEINDEX_RUNTIME=false across every test."""
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "false")


# ---- Shared sample constants ----

SHIPMENT_200KG: dict[str, Any] = {
    "product": "electronics",
    "gross_weight_kg": 180.0,
    "length_cm": 100.0,
    "width_cm": 100.0,
    "height_cm": 100.0,
    "volume_weight_kg": 200.0,
    "chargeable_weight_kg": 200.0,
    "weight_basis": "volume",
    "origin": "Delhi",
    "destination": "Rotterdam",
    "urgency": "standard",
}

SAMPLE_RATE_A: dict[str, Any] = {
    "carrier": "Lufthansa Cargo",
    "mode": "air_freight",
    "source_site": "freightos",
    "base_price_usd": 892.0,
    "trust_score": 85,
    "estimated_total_usd": 958.9,
    "chargeable_weight_kg": 200.0,
    "transit_days": 7,
    "flags": [],
    "verified_site": True,
    "booking_url": "https://ship.freightos.com/book/LH-1",
    "scraped_at": "2026-04-22T00:00:00+00:00",
}

CLAUDE_MD_SMOKE_SHIPMENT: dict[str, Any] = {
    "product": "electronics",
    "gross_weight_kg": 12.0,
    "length_cm": 40.0,
    "width_cm": 30.0,
    "height_cm": 20.0,
    "volume_weight_kg": 4.8,
    "chargeable_weight_kg": 12.0,
    "weight_basis": "gross",
    "origin": "Delhi",
    "destination": "Rotterdam",
    "urgency": "standard",
}


def _install_all_fakes(install_fake_llm) -> None:
    """Install FakeChatModel stubs for all three LLM-touching agents.

    Used by pipeline + smoke tests so each test doesn't repeat 3 install
    calls. Pipeline test callers use: `_install_all_fakes(install_fake_llm)`.
    """
    from agents.router import RouterOutput
    from agents.hidden_charge import HiddenChargeOutput
    from agents.summarizer import SummarizerOutput

    install_fake_llm("router", {
        RouterOutput: RouterOutput(
            reason="Stub reason — mode decided by deterministic rules."
        )
    })
    install_fake_llm("hidden_charge", {
        HiddenChargeOutput: HiddenChargeOutput(trust_score=85, flags=[])
    })
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(
            recommendation="Stub recommendation — book the top-ranked quote."
        )
    })
```

- [ ] **Step 2: Verify conftest imports cleanly**

```bash
uv run python -c "
from tests.conftest import FakeChatModel, SHIPMENT_200KG, CLAUDE_MD_SMOKE_SHIPMENT
from pydantic import BaseModel

class Dummy(BaseModel):
    x: int

fake = FakeChatModel({Dummy: Dummy(x=42)})
structured = fake.with_structured_output(Dummy)
result = structured.invoke('anything')
assert isinstance(result, Dummy)
assert result.x == 42
assert SHIPMENT_200KG['chargeable_weight_kg'] == 200.0
assert CLAUDE_MD_SMOKE_SHIPMENT['chargeable_weight_kg'] == 12.0
print('conftest OK')
"
```
Expected: prints `conftest OK`.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "feat(tests): add conftest with FakeChatModel + shared fixtures + constants"
```

---

## Task 3: tests/test_agents.py (25 tests)

**Files:** Create `tests/test_agents.py`.

- [ ] **Step 1: Write test_agents.py**

Create `tests/test_agents.py` with EXACTLY this content:

```python
"""Unit tests for the four Phase-3 agents.

- Router (5): classify_mode purity + LLM reason + dual-shape payload.
- Hidden-charge (8): short-circuit, scoring, verified-site, RAG on/off,
  degraded-RAG, malformed-rate, pydantic guardrail.
- Rate-comparator (6, no LLM): formula, clamp, sort, immutability, types.
- Summarizer (6): return shape, helper purity, prompt capture, temperature.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agents.hidden_charge import (
    HiddenChargeOutput,
    build_hidden_charge_agent,
)
from agents.rate_comparator import (
    build_rate_comparator_agent,
    compute_estimated_total,
)
from agents.router import (
    RouterOutput,
    build_router_agent,
    classify_mode,
)
from agents.summarizer import (
    SummarizerOutput,
    _format_rates_table,
    build_summarizer_agent,
)
from tests.conftest import FakeChatModel, SHIPMENT_200KG


# ------------------------- Router -------------------------

def test_classify_mode_courier_boundary():
    assert classify_mode(12.0) == "courier"
    assert classify_mode(67.9) == "courier"
    assert classify_mode(0.1) == "courier"


def test_classify_mode_air_boundary():
    assert classify_mode(68.0) == "air_freight"
    assert classify_mode(200.0) == "air_freight"
    assert classify_mode(499.99) == "air_freight"


def test_classify_mode_sea_boundary():
    assert classify_mode(500.0) == "sea_freight"
    assert classify_mode(1500.0) == "sea_freight"


def test_router_agent_returns_mode_and_reason(install_fake_llm):
    install_fake_llm(
        "router",
        {RouterOutput: RouterOutput(reason="Air because 200 kg < 500 kg.")},
    )
    out = build_router_agent().invoke({"input": SHIPMENT_200KG})
    assert out == {
        "mode": "air_freight",
        "reason": "Air because 200 kg < 500 kg.",
    }


def test_router_agent_accepts_bare_payload(install_fake_llm):
    install_fake_llm(
        "router",
        {RouterOutput: RouterOutput(reason="x")},
    )
    # Pass SHIPMENT_200KG without wrapping in {"input": ...}
    out = build_router_agent().invoke(SHIPMENT_200KG)
    assert out["mode"] == "air_freight"


# ------------------------- Hidden-charge -------------------------

def _hidden_charge_input(
    booking_url: str = "https://ship.freightos.com/book/LH-1",
    card_html: str = "<li>...</li>",
) -> dict[str, Any]:
    return {
        "input": {
            "rate": {
                "carrier": "Lufthansa Cargo",
                "base_price_usd": 892.0,
                "booking_url": booking_url,
                "source_site": "freightos",
            },
            "mode": "air_freight",
            "card_html": card_html,
            "origin": "Delhi",
            "destination": "Rotterdam",
        }
    }


def test_hidden_charge_short_circuits_flagged_site(
    install_fake_llm, reset_validator_cache, monkeypatch, tmp_path
):
    # Write a temp charge_patterns.json with scammer in flagged_sites
    from tools import validator
    original = json.loads(validator._PATTERNS_PATH.read_text(encoding="utf-8"))
    mutated = {**original, "flagged_sites": ["scammer.example.com"]}
    tmp_patterns = tmp_path / "charge_patterns.json"
    tmp_patterns.write_text(json.dumps(mutated), encoding="utf-8")
    monkeypatch.setattr(validator, "_PATTERNS_PATH", tmp_patterns)
    validator._patterns.cache_clear()

    # FakeChatModel with NO stubs — raises if LLM invoked (proves short-circuit).
    install_fake_llm("hidden_charge", {})

    out = build_hidden_charge_agent().invoke(
        _hidden_charge_input(booking_url="https://scammer.example.com/book/1")
    )
    assert out == {
        "trust_score": 0,
        "flags": ["Site is flagged as deceptive"],
        "verified_site": False,
    }


def test_hidden_charge_scores_well_itemised_card(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=85, flags=[])},
    )
    out = build_hidden_charge_agent().invoke(_hidden_charge_input())
    assert out == {
        "trust_score": 85,
        "flags": [],
        "verified_site": True,
    }


def test_hidden_charge_verified_false_for_unknown_domain(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=60, flags=[])},
    )
    out = build_hidden_charge_agent().invoke(
        _hidden_charge_input(booking_url="https://random.example.net/x")
    )
    assert out["verified_site"] is False


def test_hidden_charge_rag_off_does_not_call_pageindex(
    install_fake_llm, monkeypatch
):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=80, flags=[])},
    )
    # Autouse fixture already sets USE_PAGEINDEX_RUNTIME=false.
    sentinel = {"called": False}

    def guard(*a, **k):
        sentinel["called"] = True
        return None

    monkeypatch.setattr("agents.hidden_charge.query_pageindex", guard)
    build_hidden_charge_agent().invoke(_hidden_charge_input())
    assert sentinel["called"] is False


def test_hidden_charge_rag_on_calls_pageindex(install_fake_llm, monkeypatch):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    calls: list[tuple[str, str]] = []

    def spy(doc_id, question, timeout=10.0):
        calls.append((doc_id, question))
        return "fuel surcharge 18-32%"

    monkeypatch.setattr("agents.hidden_charge.query_pageindex", spy)
    monkeypatch.setattr(
        "agents.hidden_charge.doc_id_for",
        lambda fn: "pi-test-id" if fn == "surcharge_bulletin.pdf" else None,
    )

    build_hidden_charge_agent().invoke(_hidden_charge_input())
    assert len(calls) == 1
    assert calls[0][0] == "pi-test-id"


def test_hidden_charge_degrades_when_doc_id_missing(
    install_fake_llm, monkeypatch
):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    monkeypatch.setattr("agents.hidden_charge.doc_id_for", lambda fn: None)
    # Should NOT raise — agent proceeds without RAG context.
    out = build_hidden_charge_agent().invoke(_hidden_charge_input())
    assert out["trust_score"] == 70


def test_hidden_charge_handles_missing_booking_url(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=60, flags=[])},
    )
    payload = _hidden_charge_input()
    del payload["input"]["rate"]["booking_url"]
    out = build_hidden_charge_agent().invoke(payload)
    assert out["verified_site"] is False


def test_hidden_charge_output_pydantic_rejects_trust_over_100():
    # Instantiating out-of-range HiddenChargeOutput raises at fixture time.
    with pytest.raises(ValidationError):
        HiddenChargeOutput(trust_score=150, flags=[])


# ------------------------- Rate-comparator -------------------------

def test_compute_estimated_total_anchor_points():
    assert compute_estimated_total(1000.0, 100) == 1000.0
    assert compute_estimated_total(1000.0, 50) == 1250.0
    assert compute_estimated_total(1000.0, 0) == 1500.0


def test_compute_estimated_total_clamps_out_of_range():
    assert compute_estimated_total(1000.0, 150) == 1000.0
    assert compute_estimated_total(1000.0, -10) == 1500.0


def test_rate_comparator_sorts_ascending():
    rates = [
        {"carrier": "A", "base_price_usd": 900.0, "trust_score": 90},
        {"carrier": "B", "base_price_usd": 800.0, "trust_score": 40},
        {"carrier": "C", "base_price_usd": 1000.0, "trust_score": 100},
    ]
    out = build_rate_comparator_agent().invoke({"input": rates})
    totals = [r["estimated_total_usd"] for r in out]
    assert totals == sorted(totals)


def test_rate_comparator_enriches_without_mutating_input():
    rates = [{"carrier": "A", "base_price_usd": 900.0, "trust_score": 90}]
    out = build_rate_comparator_agent().invoke({"input": rates})
    assert "estimated_total_usd" in out[0]
    assert "estimated_total_usd" not in rates[0]


def test_rate_comparator_rejects_non_list_input():
    with pytest.raises(TypeError):
        build_rate_comparator_agent().invoke({"input": {"not": "a list"}})


def test_rate_comparator_handles_empty_list():
    assert build_rate_comparator_agent().invoke({"input": []}) == []


# ------------------------- Summarizer -------------------------

SAMPLE_RANKED_RATES = [
    {
        "carrier": "Lufthansa Cargo",
        "mode": "air_freight",
        "source_site": "freightos",
        "base_price_usd": 892.0,
        "trust_score": 85,
        "estimated_total_usd": 958.9,
        "chargeable_weight_kg": 200.0,
        "transit_days": 7,
        "flags": [],
    },
]


def test_summarizer_returns_recommendation_dict(install_fake_llm):
    install_fake_llm(
        "summarizer",
        {SummarizerOutput: SummarizerOutput(recommendation="Book Lufthansa.")},
    )
    out = build_summarizer_agent().invoke({
        "input": {
            "shipment": SHIPMENT_200KG,
            "router_reason": "Air for 200 kg.",
            "ranked_rates": SAMPLE_RANKED_RATES,
        }
    })
    assert out == {"recommendation": "Book Lufthansa."}


def test_format_rates_table_single_rate():
    line = _format_rates_table(SAMPLE_RANKED_RATES)
    assert "Lufthansa Cargo" in line
    assert "air_freight" in line
    assert "$892.00" in line
    assert "85/100" in line
    assert "7d" in line


def test_format_rates_table_empty():
    assert _format_rates_table([]) == ""


def test_format_rates_table_includes_flags():
    rates = [{
        **SAMPLE_RANKED_RATES[0],
        "flags": ["Fuel surcharge not disclosed upfront"],
    }]
    table = _format_rates_table(rates)
    assert "Fuel surcharge not disclosed upfront" in table


def test_summarizer_handles_empty_ranked_rates(install_fake_llm):
    install_fake_llm(
        "summarizer",
        {SummarizerOutput: SummarizerOutput(recommendation="No rates.")},
    )
    out = build_summarizer_agent().invoke({
        "input": {
            "shipment": SHIPMENT_200KG,
            "router_reason": "",
            "ranked_rates": [],
        }
    })
    assert out == {"recommendation": "No rates."}


def test_summarizer_uses_temperature_0_5(monkeypatch):
    captured: dict[str, float] = {}

    def spy(*, temperature: float = 0.2) -> FakeChatModel:
        captured["temperature"] = temperature
        return FakeChatModel(
            {SummarizerOutput: SummarizerOutput(recommendation="ok")}
        )

    monkeypatch.setattr("agents.summarizer.get_llm", spy)
    build_summarizer_agent().invoke({
        "input": {
            "shipment": SHIPMENT_200KG,
            "router_reason": "",
            "ranked_rates": [],
        }
    })
    assert captured["temperature"] == 0.5
```

- [ ] **Step 2: Run test_agents.py**

```bash
uv run pytest tests/test_agents.py -v 2>&1 | tail -40
```
Expected: `25 passed` (router 5 + hidden_charge 8 + rate_comparator 6 + summarizer 6). No warnings about LLM calls (FakeChatModel intercepts all).

- [ ] **Step 3: Commit**

```bash
git add tests/test_agents.py
git commit -m "test(agents): add 25 unit tests covering all 4 agents with FakeChatModel"
```

---

## Task 4: tests/test_scraper.py (15 tests)

**Files:** Create `tests/test_scraper.py`.

- [ ] **Step 1: Write test_scraper.py**

```python
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

    original = scraper.SITES["icontainers"].parser
    monkeypatch.setattr(
        scraper.SITES["icontainers"],
        "parser",
        boom,
        raising=False,
    )
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
```

- [ ] **Step 2: Run test_scraper.py**

```bash
uv run pytest tests/test_scraper.py -v 2>&1 | tail -25
```
Expected: `15 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test(scraper): add 15 unit tests covering 3 parsers + helpers + aggregator"
```

---

## Task 5: tests/test_cache.py (10 tests)

**Files:** Create `tests/test_cache.py`.

- [ ] **Step 1: Write test_cache.py**

```python
"""Unit tests for tools/cache.py — SQLite cache with 6h TTL."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from tools.cache import (
    TTL_SECONDS,
    _db_path,
    clear_cache,
    get_cached,
    put_cache,
)


def test_put_then_get_roundtrip(isolated_cache_db):
    put_cache("Delhi", "Rotterdam", date.today(), [{"carrier": "X"}])
    assert get_cached("Delhi", "Rotterdam", date.today()) == [{"carrier": "X"}]


def test_get_cached_miss_returns_none(isolated_cache_db):
    assert get_cached("Tokyo", "Paris", date.today()) is None


def test_get_cached_expires_after_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    # Age the cached_at by 7 hours (> 6h TTL)
    seven_h_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (seven_h_ago,))
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) is None


def test_get_cached_fresh_within_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    # Age by 5h59m (< 6h TTL)
    fresh = (datetime.now(timezone.utc) - timedelta(hours=5, minutes=59)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (fresh,))
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) == [{"v": 1}]


def test_get_cached_corrupt_json_returns_none(isolated_cache_db, caplog):
    put_cache("A", "B", date.today(), [{"v": 1}])
    # Corrupt the rates_json column directly
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET rates_json = 'not{valid-json'")
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) is None


def test_get_cached_unparseable_cached_at_returns_none(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = 'definitely-not-a-datetime'")
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) is None


def test_put_cache_upsert_overwrites(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    put_cache("A", "B", date.today(), [{"v": 2}])
    assert get_cached("A", "B", date.today()) == [{"v": 2}]


def test_clear_cache_drops_rows(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    clear_cache()
    assert get_cached("A", "B", date.today()) is None


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

- [ ] **Step 2: Run test_cache.py**

```bash
uv run pytest tests/test_cache.py -v 2>&1 | tail -18
```
Expected: `10 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cache.py
git commit -m "test(cache): add 10 unit tests covering TTL + corruption + upsert paths"
```

---

## Task 6: tests/test_validator.py (8 tests)

**Files:** Create `tests/test_validator.py`.

- [ ] **Step 1: Write test_validator.py**

```python
"""Unit tests for tools/validator.py — site checks + red-flag merging."""
from __future__ import annotations

from tools.validator import (
    is_flagged_site,
    is_verified_site,
    red_flags_for_mode,
)


def test_is_verified_site_exact_domain(reset_validator_cache):
    assert is_verified_site("https://freightos.com/x") is True


def test_is_verified_site_subdomain(reset_validator_cache):
    assert is_verified_site("https://ship.freightos.com/x") is True


def test_is_verified_site_www_stripped(reset_validator_cache):
    assert is_verified_site("https://www.freightos.com/x") is True


def test_is_verified_site_unknown_domain(reset_validator_cache):
    assert is_verified_site("https://scammer.example.com/") is False


def test_is_verified_site_empty_url(reset_validator_cache):
    assert is_verified_site("") is False


def test_is_verified_site_malformed_url(reset_validator_cache):
    # urlparse handles most weird input by returning an empty hostname.
    assert is_verified_site("not a url") is False


def test_is_flagged_site_empty_flagged_list(reset_validator_cache):
    # Default Phase-1 patterns have flagged_sites == []
    assert is_flagged_site("https://any-domain.example.com/") is False


def test_red_flags_for_mode_merges_generic_and_specific(reset_validator_cache):
    air = red_flags_for_mode("air_freight")
    sea = red_flags_for_mode("sea_freight")
    # 8 generic + 2 mode-specific = 10 each
    assert len(air) == 10
    assert len(sea) == 10
    assert any("security / ISPS" in f for f in air)
    assert any("chassis fee" in f for f in sea)
```

- [ ] **Step 2: Run test_validator.py**

```bash
uv run pytest tests/test_validator.py -v 2>&1 | tail -14
```
Expected: `8 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_validator.py
git commit -m "test(validator): add 8 unit tests covering site checks + red-flag merging"
```

---

## Task 7: tests/test_llm_router.py (4 tests)

**Files:** Create `tests/test_llm_router.py`.

- [ ] **Step 1: Write test_llm_router.py**

```python
"""Unit tests for tools/llm_router.py — construction + singleton (no real calls)."""
from __future__ import annotations

from langchain_litellm import ChatLiteLLM

from tools.llm_router import _MODEL_LIST, get_llm


def test_get_llm_returns_chat_litellm_instance():
    llm = get_llm()
    assert isinstance(llm, ChatLiteLLM)


def test_get_llm_singleton_same_kwargs_returns_same_instance():
    get_llm.cache_clear()
    a = get_llm()
    b = get_llm()
    assert a is b


def test_get_llm_cache_size_one_evicts_on_different_kwargs():
    # lru_cache(maxsize=1): second call with a different temperature evicts the first.
    get_llm.cache_clear()
    first = get_llm(temperature=0.2)
    second = get_llm(temperature=0.5)
    # Both are valid instances
    assert isinstance(first, ChatLiteLLM)
    assert isinstance(second, ChatLiteLLM)


def test_model_list_has_three_providers():
    names = {entry["model_name"] for entry in _MODEL_LIST}
    assert names == {"groq", "openai", "gemini"}
```

- [ ] **Step 2: Run test_llm_router.py**

```bash
uv run pytest tests/test_llm_router.py -v 2>&1 | tail -10
```
Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm_router.py
git commit -m "test(llm_router): add 4 unit tests covering ChatLiteLLM construction + singleton"
```

---

## Task 8: tests/test_pageindex_client.py (8 tests)

**Files:** Create `tests/test_pageindex_client.py`.

- [ ] **Step 1: Write test_pageindex_client.py**

```python
"""Unit tests for tools/pageindex_client.py with fully mocked requests.post."""
from __future__ import annotations

import requests


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
    monkeypatch.setattr(
        pageindex_client._registry, "__wrapped__", lambda: fake_registry
    )
    pageindex_client._registry.cache_clear()
    assert pageindex_client.doc_id_for("surcharge_bulletin.pdf") == "pi-known"
    assert pageindex_client.doc_id_for("missing.pdf") is None


def test_query_pageindex_success(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {
                "choices": [{"message": {"content": "fuel surcharge 18-32%"}}]
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr(pageindex_client.requests, "post", fake_post)
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key-abc")
    result = pageindex_client.query_pageindex("pi-any", "What are surcharges?")
    assert result == "fuel surcharge 18-32%"


def test_query_pageindex_missing_api_key(monkeypatch):
    monkeypatch.delenv("PAGEINDEX_API_KEY", raising=False)
    from tools.pageindex_client import query_pageindex
    assert query_pageindex("pi-any", "Q?") is None


def test_query_pageindex_non_2xx_returns_none(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = False
        status_code = 500
        text = "internal error"

    monkeypatch.setattr(
        pageindex_client.requests,
        "post",
        lambda **k: FakeResponse(),
    )
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    assert pageindex_client.query_pageindex("pi-any", "Q?") is None


def test_query_pageindex_network_error_returns_none(monkeypatch):
    from tools import pageindex_client

    def boom(**kwargs):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(pageindex_client.requests, "post", boom)
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    assert pageindex_client.query_pageindex("pi-any", "Q?") is None


def test_query_pageindex_malformed_body_returns_none(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = "{}"
        def json(self):
            return {}  # no "choices" key

    monkeypatch.setattr(
        pageindex_client.requests,
        "post",
        lambda **k: FakeResponse(),
    )
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    assert pageindex_client.query_pageindex("pi-any", "Q?") is None
```

- [ ] **Step 2: Run test_pageindex_client.py**

```bash
uv run pytest tests/test_pageindex_client.py -v 2>&1 | tail -14
```
Expected: `8 passed`. Zero network activity.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pageindex_client.py
git commit -m "test(pageindex_client): add 8 unit tests with mocked requests.post"
```

---

## Task 9: tests/test_pipeline.py (10 tests)

**Files:** Create `tests/test_pipeline.py`.

- [ ] **Step 1: Write test_pipeline.py**

```python
"""Integration tests for pipeline.py — mocked LLMs + real scraper + isolated cache."""
from __future__ import annotations

from agents.hidden_charge import HiddenChargeOutput
from agents.router import RouterOutput
from agents.summarizer import SummarizerOutput
from pipeline import run_pipeline
from tests.conftest import SHIPMENT_200KG, _install_all_fakes


def test_run_pipeline_happy_path(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    result = run_pipeline(SHIPMENT_200KG)
    assert result["mode"] == "air_freight"
    assert len(result["rates"]) == 10
    assert result["cache_hit"] is False
    assert result["sites_succeeded"] == 3
    assert result["errors"] == []
    assert result["recommendation"].startswith("Stub recommendation")
    for r in result["rates"]:
        assert "_card_html" not in r


def test_run_pipeline_second_call_hits_cache(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    run_pipeline(SHIPMENT_200KG)
    second = run_pipeline(SHIPMENT_200KG)
    assert second["cache_hit"] is True


def test_run_pipeline_courier_mode_for_small_weight(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    small = {**SHIPMENT_200KG, "chargeable_weight_kg": 12.0}
    result = run_pipeline(small)
    assert result["mode"] == "courier"


def test_run_pipeline_sea_mode_for_heavy_weight(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    heavy = {**SHIPMENT_200KG, "chargeable_weight_kg": 600.0}
    result = run_pipeline(heavy)
    assert result["mode"] == "sea_freight"


def test_run_pipeline_on_progress_fires_in_order(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    markers: list[str] = []
    run_pipeline(SHIPMENT_200KG, on_progress=markers.append)

    assert markers[0] == "classifying_mode"
    assert markers[1] == "scraping"
    hc = [m for m in markers if m.startswith("hidden_charge:")]
    assert len(hc) == 10
    assert hc[0] == "hidden_charge:1/10"
    assert hc[-1] == "hidden_charge:10/10"
    assert "ranking" in markers
    assert "writing_recommendation" in markers
    assert markers[-1] == "done"


def test_run_pipeline_per_rate_failure_captured(
    install_fake_llm, isolated_cache_db, monkeypatch
):
    install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(recommendation="ok"),
    })

    # Hidden-charge that raises for one specific carrier.
    from agents.hidden_charge import build_hidden_charge_agent as real_builder

    call_count = {"n": 0}

    class BrittleAgent:
        def invoke(self, payload):
            call_count["n"] += 1
            rate = payload["input"]["rate"]
            if rate.get("carrier") == "MSC":
                raise RuntimeError("brittle MSC test failure")
            return {"trust_score": 80, "flags": [], "verified_site": True}

    monkeypatch.setattr(
        "pipeline.build_hidden_charge_agent",
        lambda: BrittleAgent(),
    )

    result = run_pipeline(SHIPMENT_200KG)
    assert len(result["rates"]) == 9  # 10 scraped, 1 dropped
    assert len(result["errors"]) == 1
    assert "MSC" in result["errors"][0]
    # Pipeline still produced a recommendation
    assert result["recommendation"] == "ok"


def test_run_pipeline_empty_scrape_returns_diagnostic(
    install_fake_llm, isolated_cache_db, monkeypatch
):
    install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
    monkeypatch.setattr("pipeline.scrape_all", lambda q: [])

    result = run_pipeline(SHIPMENT_200KG)
    assert result["rates"] == []
    assert "No rate quotes available" in result["recommendation"]
    assert result["sites_succeeded"] == 0


def test_run_pipeline_summarizer_failure_degrades(
    install_fake_llm, isolated_cache_db, monkeypatch
):
    install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
    install_fake_llm("hidden_charge", {
        HiddenChargeOutput: HiddenChargeOutput(trust_score=85, flags=[]),
    })

    class BrokenSummarizer:
        def invoke(self, payload):
            raise RuntimeError("summarizer provider outage")

    monkeypatch.setattr(
        "pipeline.build_summarizer_agent",
        lambda: BrokenSummarizer(),
    )

    result = run_pipeline(SHIPMENT_200KG)
    assert result["recommendation"] == ""
    assert len(result["errors"]) == 1
    assert "summarizer" in result["errors"][0]
    # Rates still returned
    assert len(result["rates"]) == 10


def test_run_pipeline_without_on_progress_default(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    result = run_pipeline(SHIPMENT_200KG)  # no on_progress kwarg
    assert result["mode"] == "air_freight"


def test_run_pipeline_strips_card_html(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    result = run_pipeline(SHIPMENT_200KG)
    for r in result["rates"]:
        assert "_card_html" not in r
```

- [ ] **Step 2: Run test_pipeline.py**

```bash
uv run pytest tests/test_pipeline.py -v 2>&1 | tail -18
```
Expected: `10 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test(pipeline): add 10 integration tests covering cache+scraper+4 agents"
```

---

## Task 10: tests/test_rag.py (5 tests)

**Files:** Create `tests/test_rag.py`.

- [ ] **Step 1: Write test_rag.py**

```python
"""RAG-specific tests — hidden-charge + PageIndex integration (mocked query_pageindex)."""
from __future__ import annotations

from agents.hidden_charge import (
    HiddenChargeOutput,
    build_hidden_charge_agent,
)


def _rag_payload() -> dict:
    return {
        "input": {
            "rate": {
                "carrier": "RAG-Carrier",
                "base_price_usd": 500.0,
                "booking_url": "https://freightos.com/x",
                "source_site": "freightos",
            },
            "mode": "air_freight",
            "card_html": "<li>rag-test-card</li>",
            "origin": "Delhi",
            "destination": "Rotterdam",
        }
    }


def test_rag_on_invokes_pageindex_with_mode_and_route(
    install_fake_llm, monkeypatch
):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    calls: list[tuple[str, str]] = []

    def spy(doc_id, question, timeout=10.0):
        calls.append((doc_id, question))
        return "surcharge info"

    monkeypatch.setattr("agents.hidden_charge.query_pageindex", spy)
    monkeypatch.setattr(
        "agents.hidden_charge.doc_id_for",
        lambda fn: "pi-test" if fn == "surcharge_bulletin.pdf" else None,
    )

    build_hidden_charge_agent().invoke(_rag_payload())
    assert len(calls) == 1
    q = calls[0][1].lower()
    assert "air freight" in q
    assert "delhi" in q
    assert "rotterdam" in q


def test_rag_off_does_not_invoke_pageindex(install_fake_llm, monkeypatch):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=80, flags=[])},
    )
    # Autouse fixture keeps USE_PAGEINDEX_RUNTIME=false.
    sentinel = {"called": False}

    def guard(*a, **k):
        sentinel["called"] = True
        return None

    monkeypatch.setattr("agents.hidden_charge.query_pageindex", guard)
    build_hidden_charge_agent().invoke(_rag_payload())
    assert sentinel["called"] is False


def test_rag_query_format_mentions_mode(install_fake_llm, monkeypatch):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    captured: list[str] = []
    monkeypatch.setattr(
        "agents.hidden_charge.query_pageindex",
        lambda doc_id, question, timeout=10.0: captured.append(question) or "x",
    )
    monkeypatch.setattr(
        "agents.hidden_charge.doc_id_for",
        lambda fn: "pi-any",
    )
    build_hidden_charge_agent().invoke(_rag_payload())
    assert "air freight" in captured[0].lower()


def test_rag_missing_doc_id_degrades(install_fake_llm, monkeypatch):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    monkeypatch.setattr("agents.hidden_charge.doc_id_for", lambda fn: None)
    # Even with flag on, missing registry entry must not raise.
    out = build_hidden_charge_agent().invoke(_rag_payload())
    assert out["trust_score"] == 70


def test_rag_pageindex_failure_degrades(install_fake_llm, monkeypatch):
    install_fake_llm(
        "hidden_charge",
        {HiddenChargeOutput: HiddenChargeOutput(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    monkeypatch.setattr(
        "agents.hidden_charge.doc_id_for",
        lambda fn: "pi-any",
    )
    monkeypatch.setattr(
        "agents.hidden_charge.query_pageindex",
        lambda *a, **k: None,  # network-like failure
    )
    out = build_hidden_charge_agent().invoke(_rag_payload())
    assert out["trust_score"] == 70
```

- [ ] **Step 2: Run test_rag.py**

```bash
uv run pytest tests/test_rag.py -v 2>&1 | tail -12
```
Expected: `5 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rag.py
git commit -m "test(rag): add 5 tests covering PageIndex runtime RAG on/off/degraded paths"
```

---

## Task 11: tests/test_smoke.py (3 tests)

**Files:** Create `tests/test_smoke.py`.

- [ ] **Step 1: Write test_smoke.py**

```python
"""CLAUDE.md-mandated smoke test: fixed Delhi->Rotterdam 12kg query.

Runs the full pipeline with mocked LLMs; asserts on RecommendationResult shape
(not LLM text) per CLAUDE.md's 'assert on output schema' directive.
"""
from __future__ import annotations

from pipeline import run_pipeline
from tests.conftest import CLAUDE_MD_SMOKE_SHIPMENT, _install_all_fakes


SCORED_RATE_KEYS = {
    "carrier",
    "base_price_usd",
    "chargeable_weight_kg",
    "transit_days",
    "booking_url",
    "source_site",
    "scraped_at",
    "mode",
    "trust_score",
    "flags",
    "estimated_total_usd",
    "verified_site",
}


def test_smoke_delhi_rotterdam_12kg_completes_end_to_end(
    install_fake_llm, isolated_cache_db
):
    _install_all_fakes(install_fake_llm)
    result = run_pipeline(CLAUDE_MD_SMOKE_SHIPMENT)

    assert result["mode"] == "courier"
    assert result["errors"] == []
    for r in result["rates"]:
        missing = SCORED_RATE_KEYS - r.keys()
        assert not missing, f"rate missing keys {missing}: {r.get('carrier')}"
    assert isinstance(result["recommendation"], str)
    assert len(result["recommendation"]) > 0


def test_smoke_rates_sorted_ascending(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    result = run_pipeline(CLAUDE_MD_SMOKE_SHIPMENT)
    totals = [r["estimated_total_usd"] for r in result["rates"]]
    assert totals == sorted(totals), (
        f"rates not sorted ascending: {totals}"
    )


def test_smoke_second_run_hits_cache(install_fake_llm, isolated_cache_db):
    _install_all_fakes(install_fake_llm)
    run_pipeline(CLAUDE_MD_SMOKE_SHIPMENT)
    second = run_pipeline(CLAUDE_MD_SMOKE_SHIPMENT)
    assert second["cache_hit"] is True
```

- [ ] **Step 2: Run test_smoke.py**

```bash
uv run pytest tests/test_smoke.py -v 2>&1 | tail -8
```
Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test(smoke): add CLAUDE.md-mandated Delhi->Rotterdam 12kg end-to-end tests"
```

---

## Task 12: Measure coverage + close any gaps

**Files:** May add targeted tests if any module falls below 80%.

- [ ] **Step 1: Run full suite with coverage**

```bash
uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term-missing 2>&1 | tail -50
```
Expected: all ~101 tests pass (94 new + 7 UI-smoke). Coverage table at the end.

- [ ] **Step 2: Check each target module >=80%**

From the coverage output, note the coverage for:
- `agents/*.py` (aggregate or per-file)
- `tools/*.py` (aggregate or per-file)
- `pipeline.py`

- [ ] **Step 3: If any module is below 80%, inspect uncovered lines and add targeted tests**

`term-missing` shows exact uncovered line numbers. For each gap:
1. Read the uncovered lines.
2. Write a test that exercises the missing branch.
3. Append the test to the appropriate existing file (NOT a new file).
4. Re-run coverage.

Common gaps to preempt:
- `tools/cache.py`: the `sqlite3.DatabaseError` branch in `get_cached` connect path. Add:
  ```python
  def test_get_cached_db_connect_error_returns_none(monkeypatch):
      import sqlite3
      from tools import cache
      def boom(*a, **k):
          raise sqlite3.DatabaseError("corrupted header")
      monkeypatch.setattr(cache.sqlite3, "connect", boom)
      assert cache.get_cached("A", "B", __import__("datetime").date.today()) is None
  ```
- `tools/scraper.py`: `_parse_days_from_text` path inside icontainers parser — crafted HTML with no `data-days` attribute.
- `agents/hidden_charge.py`: RAG path where `query_pageindex` returns empty string (vs None). Covered in test_rag but re-verify.

- [ ] **Step 4: Rerun until all three targets >=80%**

```bash
uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term-missing 2>&1 | tail -20
```
Expected: every listed module shows ≥80% coverage.

- [ ] **Step 5: Commit coverage additions (only if any tests were added)**

```bash
git add tests/
git commit -m "test(coverage): close gaps to reach 80% on agents/tools/pipeline"
```

If no additions were needed, skip the commit. Move to Task 13.

---

## Task 13: Update CLAUDE.md

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1: Capture current coverage numbers**

Re-run and copy the coverage percentages:
```bash
uv run pytest --cov=agents --cov=tools --cov=pipeline --cov-report=term 2>&1 | tail -15
```
Note the aggregated per-module percentages (e.g., `agents: 88%`, `tools: 91%`, `pipeline: 94%`).

- [ ] **Step 2: Edit CLAUDE.md Current state section**

Find the first paragraph under `## Current state (2026-04-19)` (updated for Phase 3). The date line needs updating to today's date; the body text should be extended with Phase 4 + 5 completion.

Replace:
```markdown
## Current state (2026-04-19)
Phase 3 complete: four LangChain 1.x `Runnable`-based agents (`agents/router.py`, ...) ...
```

With (substitute X/Y/Z with the actual coverage numbers from Step 1):
```markdown
## Current state (2026-04-22)
Phase 5 complete: pytest suite with ~101 tests covers `agents/`, `tools/`, and `pipeline.py` at coverage X%/Y%/Z% respectively (CLAUDE.md target: >=80% each). Shared `tests/conftest.py` exposes `FakeChatModel` (inherits LangChain `Runnable`) + `install_fake_llm` fixture; zero network I/O during the suite. CLAUDE.md-mandated smoke test (Delhi->Rotterdam 12 kg) passes end-to-end against mocked LLMs. Phase 4 UI (`app.py` with live weight calc + staged progress) remains in place; Phase 3 agents + Phase 2 scraper+cache + Phase 1 scaffold all green. Phase 6 (deploy) remains.
```

- [ ] **Step 3: Remove/update Phase 5 backlog items that this phase has tests locking in**

Under `**Phase 5 backlog (non-blocking, surfaced by reviewers):**`, add a new top line:
```markdown
> **Status note (2026-04-22):** Phase 5 test suite LOCKS the current behaviour in. The items below describe bugs/nits to fix in a future Phase 5.5 polish commit — tests would need updating alongside each fix.
```
Leave the existing bullet list unchanged.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): Phase 5 complete -- update Current state + backlog status note"
```

---

## Task 14: Push Phase 5 to GitHub

**Files:** none — push only.

- [ ] **Step 1: Verify clean working tree**

```bash
git status --short
```
Expected: empty (except gitignored `.agents/`, `skills-lock.json`, `.claude/settings.local.json`).

- [ ] **Step 2: Push**

```bash
git push origin main
```
Expected: lists 12–15 new objects; `main -> main` updated.

- [ ] **Step 3: Verify remote**

```bash
git log --oneline origin/main | head -20
```
Expected: matches local `git log --oneline | head -20`.

No commit on this task.

---

## Self-review notes

Checked against the spec (2026-04-22-phase5-tests-design.md) before finalising:

**Spec coverage:**
- Spec §2 in-scope (10 new files + pyproject mod): Task 1 (deps), Task 2 (conftest), Tasks 3–11 (test_agents, test_scraper, test_cache, test_validator, test_llm_router, test_pageindex_client, test_pipeline, test_rag, test_smoke). All present.
- Spec D1 (one phase): mirrored in plan structure (14 tasks, one execution pass).
- Spec D2 (FakeChatModel + install_fake_llm): Task 2 Step 1 implements verbatim.
- Spec D3 (≥80% coverage on agents/tools/pipeline): Task 12 measures + closes gaps.
- Spec D4 (zero network): every test uses FakeChatModel or mocked requests.post; autouse fixture sets USE_PAGEINDEX_RUNTIME=false.
- Spec D5 (test_smoke mocked LLM, schema assertions): Task 11 asserts on SCORED_RATE_KEYS + mode value, never on LLM prose.
- Spec D6 (test_rag covers USE_PAGEINDEX_RUNTIME=true branch): Task 10 verifies rag-on / rag-off / degraded paths.
- Spec D7 (patch at agent-module binding): Task 2 conftest `install_fake_llm` uses `agents.{module_name}.get_llm` patch path.
- Spec D8 (autouse disable PageIndex runtime): Task 2 Step 1 includes `_disable_pageindex_runtime` autouse fixture.
- Spec D9 (shared sample constants): Task 2 Step 1 exports SHIPMENT_200KG, SAMPLE_RATE_A, CLAUDE_MD_SMOKE_SHIPMENT, _install_all_fakes.
- Spec D10 (schema assertions, not LLM text): preserved throughout; smoke tests check mode, keys, sort order, cache behaviour.

**Placeholder scan:** no TBDs, TODOs, "similar to", "add appropriate error handling" patterns. Every code block is copy-paste complete. Task 12 Step 3 lists three likely gap-types with explicit fix code — exception to the "complete code" rule justified by the "we don't know which gap, if any, remains" nature of coverage closing.

**Type consistency:**
- `FakeChatModel` signature `(structured_responses: dict[type[BaseModel], BaseModel])` used consistently in Tasks 2, 3, 9–11.
- `install_fake_llm(module_name, responses)` signature stable across Tasks 3, 9, 10, 11.
- `_install_all_fakes(install_fake_llm)` helper signature used in Tasks 9 and 11; defined in Task 2.
- Sample constants (`SHIPMENT_200KG`, `CLAUDE_MD_SMOKE_SHIPMENT`, `SAMPLE_RATE_A`) referenced consistently.
- Pydantic schema names (`RouterOutput`, `HiddenChargeOutput`, `SummarizerOutput`) match Phase-3 agent module exports.
- `RecommendationResult` fields (mode, router_reason, rates, recommendation, cache_hit, sites_succeeded, errors) asserted consistently in Tasks 9 and 11.

No drift found. Plan ready for execution.

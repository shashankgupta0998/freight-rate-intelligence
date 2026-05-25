# CCA-F Architecture Improvements — Design Spec

**Date:** 2026-05-25
**Author:** Shashank Gupta + Claude
**Status:** Approved
**Approach:** Bottom-Up (Approach A) — foundation first, then layers

---

## Context

The Freight Rate Intelligence app (live at freightit.streamlit.app) was audited against the Claude Certified Architect — Foundations (CCA-F) cheat sheet across all 5 domains. Five improvement areas were identified. This spec defines the phased implementation.

**Constraints:**
- Only consumer is `app.py` (Streamlit) — no external API contracts to preserve
- Tests updated per-phase, green at every phase boundary (96 existing tests, 96% coverage)
- CLAUDE.md gets a moderate trim (move Phase 5 backlog only, keep agent roster + build order)
- Anti-fabrication confidence field reflected in UI

---

## Phase 1 — Structured Error Types + Tool Refactor (D2+D5)

### 1.1 New module: `tools/errors.py`

Shared error contract for all tools and the pipeline.

```python
from enum import Enum
from typing import Any
from pydantic import BaseModel

class ErrorCategory(str, Enum):
    TRANSIENT = "transient"      # network timeout, rate limit, 503
    VALIDATION = "validation"    # bad input, parse failure
    PERMISSION = "permission"    # missing API key, 403
    BUSINESS = "business"        # flagged site, empty result set

class ToolResult(BaseModel):
    status: str                  # "ok" | "error" | "expired" | "miss" | "hit"
    data: Any = None
    is_error: bool = False
    error_category: ErrorCategory | None = None
    is_retryable: bool = False
    detail: str = ""

class PipelineError(BaseModel):
    stage: str                   # "router" | "scraper" | "hidden_charge" | "ranking" | "summarizer"
    error_category: ErrorCategory
    is_retryable: bool
    detail: str
```

### 1.2 `cache.py` changes

`get_cached()` returns `ToolResult` instead of `list | None`.

| Condition | status | is_error | error_category | data |
|-----------|--------|----------|---------------|------|
| Row found, valid | `"hit"` | False | None | `list[dict]` |
| No matching row | `"miss"` | False | None | None |
| Row found, TTL exceeded | `"expired"` | False | None | None |
| DB connection failure | `"error"` | True | TRANSIENT | None |
| Unparseable cached_at | `"error"` | True | VALIDATION | None |
| Unparseable rates_json | `"error"` | True | VALIDATION | None |

Error logs for unparseable `cached_at` / `rates_json` include `origin->destination` context (existing backlog item).

`put_cache()` returns `ToolResult` instead of `None` — status `"ok"` or `"error"`.

### 1.3 `pageindex_client.py` changes

`query_pageindex()` returns `ToolResult` instead of `str | None`.

| Condition | status | error_category | data |
|-----------|--------|---------------|------|
| Success | `"ok"` | None | answer string |
| No API key | `"error"` | PERMISSION | None |
| Network failure / timeout | `"error"` | TRANSIENT | None |
| HTTP non-2xx | `"error"` | TRANSIENT | None |
| Empty content in response | `"error"` | BUSINESS | None |

### 1.4 `scraper.py` changes

New `SiteResult` model for per-site tracking:

```python
class SiteResult(BaseModel):
    site: str
    status: str              # "ok" | "error"
    error_category: ErrorCategory | None = None
    is_retryable: bool = False
    detail: str = ""
    rate_count: int = 0
```

`scrape_all()` returns a `ScraperResult` (subclass of `ToolResult`) with:
- `data`: `list[dict]` (the concatenated rates, same as before)
- `site_results`: `list[SiteResult]` — one per configured site

```python
class ScraperResult(ToolResult):
    site_results: list[SiteResult] = []
```

The `status` is `"ok"` if at least one site succeeded, `"error"` if all sites failed.

### 1.5 Test updates

- Update `test_cache.py`: assert on `ToolResult.status` values instead of `None` / `list`
- Update `test_pageindex_client.py`: assert on `ToolResult` shape
- Update `test_scraper.py`: assert on `ToolResult` + `site_results`
- Update `test_pipeline.py`: adapt to new return types from tools

---

## Phase 2 — Pipeline Structured Errors + Compliance (D1)

### 2.1 Pipeline error propagation

`RecommendationResult` changes:

```python
class RecommendationResult(TypedDict):
    mode: str
    router_reason: str
    rates: list[dict]
    recommendation: str
    cache_hit: bool
    sites_succeeded: int
    errors: list[dict]           # was list[str], now PipelineError.model_dump()
    shipment_input: dict         # NEW — echo original input for provenance
```

Each stage wraps failures in `PipelineError`:

```python
errors.append(PipelineError(
    stage="hidden_charge",
    error_category=ErrorCategory.TRANSIENT,
    is_retryable=True,
    detail=str(e),
).model_dump())
```

### 2.2 Compliance enforcement — booking URL stripping

After rate-comparator (Step 5), before return:

```python
for rate in ranked:
    if rate.get("trust_score", 0) < 50:
        rate["booking_url"] = ""
```

The existing Streamlit check (`trust_score >= 50` before showing button) stays as defense-in-depth.

### 2.3 Hidden-charge error differentiation

Split `_default_score()` into two paths:

- **LLM failure** (retryable): `trust_score=50, flags=["Automated scoring unavailable — LLM error"], _scoring_status="llm_failed"`
- **Incomplete batch** (LLM returned fewer results): `trust_score=50, flags=["Automated scoring unavailable — incomplete batch"], _scoring_status="incomplete"`

`_scoring_status` is internal metadata for logging/debugging — does not appear in UI.

### 2.4 Test updates

- Update `test_pipeline.py`: assert `errors` items are dicts with `stage`/`error_category`/`is_retryable` keys
- Add test for compliance URL stripping: rate with `trust_score=30` should have empty `booking_url` after pipeline
- Add test for `shipment_input` echo in result
- Update hidden-charge tests for the split default paths

---

## Phase 3 — Anti-Fabrication + Few-Shot + Retry (D4)

### 3.1 Anti-fabrication in `HiddenChargeOutput`

```python
class HiddenChargeOutput(BaseModel):
    trust_score: int = Field(ge=0, le=100, ...)
    flags: list[str] = Field(...)
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

Behavior by confidence value:
- `"high"`: normal display, trust bar, book button based on score
- `"low"`: normal display, but UI adds a subtle "(low confidence)" annotation
- `"unclear"`: grey badge "Insufficient data", book button disabled, booking_url stripped

Pipeline compliance enforcement (Phase 2) extended: strip `booking_url` when `confidence == "unclear"`.

### 3.2 `SummarizerOutput` length guards

```python
class SummarizerOutput(BaseModel):
    recommendation: str = Field(
        min_length=1,
        max_length=2000,
        description="3-4 sentence plain-English recommendation..."
    )
```

### 3.3 Few-shot examples in hidden-charge prompt

Add 2 borderline examples after the scoring instructions in `_PROMPT`:

**Example 1 — Partial disclosure (score ~60, confidence high):**
```
Rate card shows: base price $1,200, fuel surcharge $180.
Missing: THC, documentation fee.
→ trust_score: 60, flags: ["destination handling charge (DHC / THC) not itemised", "documentation fee above $75 without justification"], confidence: "high"
Reasoning: Two of four expected surcharges itemised. FSC shown but THC and doc fee absent.
```

**Example 2 — Opaque quote (score ~35, confidence low):**
```
Rate card shows: total price $950, no breakdown.
→ trust_score: 35, flags: ["base price shown without itemised surcharges"], confidence: "low"
Reasoning: No fee breakdown at all. Unable to verify if surcharges are included or hidden.
```

### 3.4 Retry-with-feedback on structured output failure

Wrap `chain.invoke()` in hidden-charge with a bounded retry (max 2 retries, 3 total attempts):

```python
for attempt in range(3):
    try:
        batch = chain.invoke(prompt_vars)
        break
    except (ValidationError, OutputParserException) as e:
        if attempt == 2:
            raise
        logger.warning("hidden-charge parse failed (attempt %d): %s", attempt + 1, e)
        prompt_vars["rate_blocks"] += (
            f"\n\n[RETRY: Previous response failed validation: {e}. "
            f"Ensure output matches the schema exactly.]"
        )
```

Only `ValidationError` / `OutputParserException` trigger retry. Network/rate-limit errors are handled by LiteLLM Router, not here.

### 3.5 Router prompt tightening

```python
# Before
"You advise small business owners on freight logistics. Be concise and plain-spoken."

# After
"You advise small business owners on freight logistics. Write exactly one sentence. "
"State the freight mode, the chargeable weight, and why it crossed the threshold."
```

### 3.6 Test updates

- Add test for `confidence="unclear"` in hidden-charge output
- Add test for `SummarizerOutput` rejecting empty string and strings > 2000 chars
- Add test for retry-with-feedback: mock first LLM call to return invalid output, second call returns valid
- Update router tests for tightened prompt (existing tests should pass — output schema unchanged)

---

## Phase 4 — CLAUDE.md Trim + Skills/Rules/Commands (D3)

### 4.1 CLAUDE.md moderate trim

Remove the "Phase 5 backlog (non-blocking)" section (~30 lines). Replace with:

```
**Phase 5 backlog:** see `.claude/skills/freight-backlog/SKILL.md` for known bugs and polish items.
```

Everything else stays: stack, contracts, formulas, prohibited patterns, agent roster, build order, commands, scraper rules, trust bands, UI requirements.

### 4.2 New skill: `.claude/skills/freight-backlog/SKILL.md`

```yaml
---
name: freight-backlog
description: Phase 5 backlog — known bugs, polish items, and non-blocking improvements
context: fork
---
```

Contains the Phase 5 backlog items verbatim (moved from CLAUDE.md).

### 4.3 New rules: `.claude/rules/agents.md`

```yaml
---
paths:
  - "agents/**"
---
```

Rules:
- Always import `get_llm()` from `tools.llm_router` — never instantiate ChatGroq/ChatOpenAI/ChatGoogleGenerativeAI directly
- All agents receive `chargeable_weight_kg`, never `gross_weight_kg`
- All agents return via Pydantic BaseModel + `with_structured_output`
- Use temperature 0.2 for classification/scoring, 0.5 for prose generation

### 4.4 New slash commands

**`.claude/commands/fix-tests.md`:**
Run `uv run pytest`, parse failures, fix one by one, re-run until green.

**`.claude/commands/validate-schema.md`:**
Import all 4 agent builders, invoke with test fixtures, assert outputs match ScoredRate/RouterOutput/SummarizerOutput/HiddenChargeOutput schemas.

**`.claude/commands/run-smoke.md`:**
Run `uv run pytest tests/test_smoke.py::test_delhi_rotterdam -v`, assert end-to-end completion.

### 4.5 No test changes

This phase is configuration only. Existing tests unaffected.

---

## Phase 5 — UI Updates (Streamlit)

### 5.1 Confidence badge in rate cards

When `confidence == "unclear"`:
- Replace the colored trust bar with a **grey badge**: "Insufficient data — score is estimated"
- Show numeric score in smaller text below badge (for transparency)
- Book button **disabled** regardless of numeric score
- Booking URL already stripped by pipeline (Phase 2+3)

When `confidence == "low"`:
- Normal trust bar display
- Add subtle "(low confidence)" text annotation next to the score

When `confidence == "high"`:
- No change from current behavior

### 5.2 Structured error display

When `errors` list is non-empty, show `st.warning()` below results:
- Transient errors: "Some rate sources were temporarily unavailable. Results may be incomplete."
- Hidden-charge errors: "Automated trust scoring was unavailable for some rates. Flagged rates are marked."
- No raw error details exposed to users
- Wrap technical details in `st.expander("Technical details")` showing stage + error_category

### 5.3 Shipment echo in expander

The existing "How this was calculated" expander gains a "Your inputs" sub-section showing:
- Product, gross weight, volume weight, chargeable weight, weight basis
- Origin, destination, urgency
- Sourced from `result["shipment_input"]` (added in Phase 2)

### 5.4 Test updates

- Update `test_ui_smoke.py` if it asserts on specific HTML/component structure
- Add smoke assertions for the confidence badge rendering path

---

## Cross-cutting: Data Contract Changes

### Updated `ScoredRate` (after all phases)

```python
{
    **ScrapedRate,
    "trust_score": int,           # 0–100
    "flags": list[str],           # plain-English warnings
    "estimated_total_usd": float,
    "verified_site": bool,
    "confidence": str,            # NEW — "high" | "low" | "unclear"
    "booking_url": str,           # may be "" if trust < 50 or confidence == "unclear"
}
```

### Updated `RecommendationResult`

```python
{
    "mode": str,
    "router_reason": str,
    "rates": list[dict],
    "recommendation": str,
    "cache_hit": bool,
    "sites_succeeded": int,
    "errors": list[dict],         # CHANGED — PipelineError dicts, not strings
    "shipment_input": dict,       # NEW — provenance echo
}
```

---

## Phase ordering and dependencies

```
Phase 1 (tools/errors.py + tool refactor)
    ↓
Phase 2 (pipeline errors + compliance)
    ↓
Phase 3 (anti-fabrication + prompts + retry)
    ↓
Phase 4 (CLAUDE.md + config)  ← independent, can run anytime after Phase 1
    ↓
Phase 5 (UI updates)          ← depends on Phase 2 + 3
```

Phase 4 has no code dependencies on Phase 2/3 — it can slot in after Phase 1 if desired. Phase 5 requires both Phase 2 (structured errors, shipment echo) and Phase 3 (confidence field) to be complete.

---

## Out of scope

- Cache key tightening (weight + mode) — separate effort
- Streaming summarizer output — separate effort
- Live scraping implementation — separate effort
- PageIndex wiring for summarizer (incoterms) and rate-comparator (IATA tariff) — separate effort

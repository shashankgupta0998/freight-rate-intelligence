# Phase 3 — Agents + LangChain + LLM Router: Design

**Date:** 2026-04-18
**Author:** Shashank Gupta (with Claude)
**Status:** Approved for implementation planning
**Related:** `CLAUDE.md` (Build order §Phase 3, §Agent roster, §Prohibited patterns), `freight-rate-intelligence-PRD.md` (§F2, §F4, §F5, §F6, §F8), prior phase specs 2026-04-17 (Phase 1) + 2026-04-18 Phase 2

---

## 1. Purpose

Build the intelligence layer. Four LangChain `AgentExecutor`-wrapped agents orchestrated by a single `run_pipeline(shipment_input) -> RecommendationResult` function. A `tools/llm_router.py` funnels every LLM call through a LiteLLM Router that cascades Groq → OpenAI → Gemini on `RateLimitError`. A validator module checks booking-site legitimacy against a curated `charge_patterns.json`. An optional `tools/pageindex_client.py` provides runtime RAG against the surcharge bulletin when `USE_PAGEINDEX_RUNTIME=true`.

Portfolio story: production-shaped multi-agent pipeline where agents are proper `AgentExecutor` objects (A2A-ready), LLM fallback is explicit, and deterministic decisions stay deterministic (mode classification, price math, ranking).

## 2. Scope

### In scope

11 new files + 3 modified:

| File | Purpose | Est. lines |
|------|---------|------------|
| `agents/__init__.py` | Re-export the four `build_*_agent` constructors | 0 |
| `agents/router.py` | Rule-based mode classification + LLM-generated reason | ~90 |
| `agents/hidden_charge.py` | Per-rate trust_score + flags + verified_site | ~140 |
| `agents/rate_comparator.py` | `estimated_total_usd` + rank (no LLM) | ~110 |
| `agents/summarizer.py` | User-facing recommendation prose | ~90 |
| `tools/llm_router.py` | `get_llm()` via `ChatLiteLLM` + LiteLLM Router | ~70 |
| `tools/validator.py` | `is_verified_site`, `is_flagged_site`, `red_flags_for_mode` | ~50 |
| `tools/pageindex_client.py` | `query_pageindex(doc_id, question)` (runtime-optional) | ~60 |
| `knowledge_base/charge_patterns.json` | Curated red-flags + verified/flagged sites | ~30 JSON lines |
| `pipeline.py` (project root) | `run_pipeline(ShipmentInput) -> RecommendationResult` | ~100 |
| `pyproject.toml` | + langchain, langchain-litellm, litellm, pydantic | 5 lines |
| `tools/scraper.py` | Populate `_card_html` internal field in each parser | ~6 lines modified |
| `.env.example` | `USE_PAGEINDEX_RUNTIME=false` | 1 line |
| `CLAUDE.md` | Current state + USE_PAGEINDEX_RUNTIME documentation | ~10 lines |

Total new Python: ~710 lines. Plus small modifications to scraper.py (pass raw card HTML through for the hidden-charge agent).

### Out of scope

- **No pytest tests** — Phase 5.
- **No Streamlit app** — Phase 4.
- **No token / cost accounting** — nice-to-have.
- **No prompt caching, LangSmith / Langfuse tracing** — YAGNI until Phase 5.
- **No streaming output** — summarizer returns the full string.
- **No parallel or batched hidden-charge LLM calls** — v1 accepts serial ~6s worst-case latency.

## 3. Decisions locked in during brainstorm

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **One phase, one plan.** | Four agents are structurally similar; infrastructure is tiny. Splitting adds ceremony for little benefit. |
| D2 | **Every agent is a LangChain `AgentExecutor`.** Router / rate-comparator are no-tool, LLM-optional AgentExecutors. | A2A uniformity: each agent exposes the same `.invoke(input_dict) -> output_dict` shape. Future A2A endpoint wrapping is symmetric. |
| D3 | **LiteLLM Router manages the Groq → OpenAI → Gemini fallback chain; LangChain wraps it via `ChatLiteLLM` from `langchain-litellm`.** | User explicitly requested LiteLLM per original CLAUDE.md spec, not LangChain's native `.with_fallbacks()`. LiteLLM handles provider-switching; LangChain handles prompt/chain composition. |
| D4 | **Router: Python rules decide `mode`; LLM generates `reason` prose only.** | Mode logic is deterministic (`<68kg courier, <500kg air, ≥500kg sea`). LLM is used where it adds value. |
| D5 | **Hidden-charge: `charge_patterns.json` always-on; PageIndex runtime retrieval optional via `USE_PAGEINDEX_RUNTIME=false` (default).** | Demo works reliably day one; PageIndex is a portfolio RAG-at-runtime story when the flag flips. |
| D6 | **Validator called by hidden-charge; `flagged_sites` short-circuits trust_score=0.** | Validator stays tiny and pure; hidden-charge is the only consumer. |
| D7 | **`estimated_total_usd = base_price × (1 + (100 - trust_score) / 100 × 0.5)`. Computed in rate_comparator, no LLM.** | Linear, explainable. trust 100 → +0%, trust 50 → +25%, trust 0 → +50%. Maps to the PRD's "30–80% hidden surcharge" reality. |
| D8 | **Orchestrator = `pipeline.py` at project root; `app.py` (Phase 4) stays thin.** | Single `run_pipeline(ShipmentInput) -> RecommendationResult` function. Testable in isolation, natural A2A endpoint wrapper later. |
| D9 | **Rate-comparator has NO LLM call.** Wrapped in `AgentExecutor` only for A2A uniformity. | Ranking math is deterministic. |
| D10 | **Pydantic v2 schemas + `with_structured_output(Schema)`** for every LLM call. | Grammar-constrained decoding beats string-parsed JSON. All three providers (Groq, OpenAI, Gemini) support it via LangChain. |
| D11 | **`temperature=0.2` default; `0.5` for summarizer prose.** | Low temp for classification / scoring; higher for creative recommendations. |
| D12 | **`_card_html` as internal field on each ScrapedRate dict.** Scraper populates it; hidden-charge reads it; pipeline strips it before returning. | Cleanest way to pass raw HTML to the hidden-charge agent without re-parsing fixtures. `_` prefix signals "internal, not ScrapedRate contract." |
| D13 | **Pipeline never raises for data-availability reasons.** Returns `RecommendationResult` with `rates=[]` + diagnostic message on total scrape failure. | Streamlit UI (Phase 4) gets a consistent shape regardless. |

## 4. `tools/llm_router.py` — LiteLLM Router + LangChain adapter

### Dependencies to add in `pyproject.toml`

```toml
dependencies = [
  "requests>=2.31",
  "python-dotenv>=1.0",
  "beautifulsoup4>=4.12",
  "lxml>=5.2",
  "langchain>=0.3",
  "langchain-core>=0.3",
  "langchain-litellm>=0.1",
  "litellm>=1.50",
  "pydantic>=2.7",
]
```

**No** `langchain-groq` / `langchain-openai` / `langchain-google-genai`. LiteLLM handles all three providers.

### Module shape

```python
"""LLM router — single entry point for all agent LLM calls.

get_llm() returns a LangChain ChatLiteLLM configured with a LiteLLM Router
that falls back Groq -> OpenAI -> Gemini on RateLimitError / provider
outages. All agents import get_llm() — never instantiate ChatGroq,
ChatOpenAI, or ChatGoogleGenerativeAI directly (see CLAUDE.md Prohibited
patterns).
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_litellm import ChatLiteLLM
from litellm import Router

load_dotenv()

_MODEL_LIST = [
    {
        "model_name": "groq",
        "litellm_params": {
            "model": "groq/llama-3.3-70b-versatile",
            "api_key": os.getenv("GROQ_API_KEY"),
        },
    },
    {
        "model_name": "openai",
        "litellm_params": {
            "model": "openai/gpt-4o-mini",
            "api_key": os.getenv("OPENAI_API_KEY"),
        },
    },
    {
        "model_name": "gemini",
        "litellm_params": {
            "model": "gemini/gemini-1.5-flash",
            "api_key": os.getenv("GEMINI_API_KEY"),
        },
    },
]


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.2):
    """Return a LangChain ChatLiteLLM singleton.

    LiteLLM Router handles provider selection + fallback on RateLimitError.
    Cached so every AgentExecutor shares one underlying client.
    """
    router = Router(
        model_list=_MODEL_LIST,
        fallbacks=[
            {"groq": ["openai", "gemini"]},
            {"openai": ["gemini"]},
        ],
        cooldown_time=60,
    )
    return ChatLiteLLM(
        router=router,
        model="groq",              # primary; fallbacks cascade on failure
        temperature=temperature,
    )
```

**Router config note:** each provider has its own `model_name` alias (`groq`/`openai`/`gemini`). The `fallbacks` parameter spells out the cascade: if `groq` fails, LiteLLM tries `openai`; if `openai` also fails, it tries `gemini`. `cooldown_time=60` parks a deployment for 60 seconds after a failure so burst retries don't hit the same broken provider. This structure is explicit and matches LiteLLM's documented fallback semantics; if the actual library behaviour during implementation differs, the fallback is a ~30-line custom `BaseChatModel` — see the open nit below.

### Open technical nit

If `langchain-litellm`'s API drifts during implementation (newer package than the core LangChain libraries), fallback is a ~30-line custom `BaseChatModel` that calls `litellm.completion()` directly. Flagged; resolved in the implementation plan.

## 5. `tools/validator.py` + `knowledge_base/charge_patterns.json`

### `charge_patterns.json`

```json
{
  "red_flags": [
    "base price shown without itemised surcharges",
    "fuel surcharge (FSC) not disclosed upfront",
    "peak season surcharge (PSS) absent from the quote",
    "destination handling charge (DHC / THC) not itemised",
    "chassis fee or terminal drop fee unlisted for sea freight",
    "security / ISPS surcharge missing from air freight quote",
    "documentation fee above $75 without justification",
    "bunker adjustment factor (BAF) or currency adjustment factor (CAF) not shown for sea"
  ],
  "mode_specific_red_flags": {
    "air_freight": [
      "fuel surcharge (FSC) not disclosed upfront",
      "security / ISPS surcharge missing from air freight quote"
    ],
    "sea_freight": [
      "chassis fee or terminal drop fee unlisted for sea freight",
      "bunker adjustment factor (BAF) or currency adjustment factor (CAF) not shown for sea"
    ]
  },
  "verified_sites": [
    "freightos.com",
    "ship.freightos.com",
    "flexport.com",
    "dhl.com",
    "maersk.com",
    "icontainers.com",
    "searates.com"
  ],
  "flagged_sites": []
}
```

### `tools/validator.py` (~50 lines)

```python
"""Booking-site legitimacy checker.

Loads charge_patterns.json once at import time. Exposes three pure
functions for use by the hidden-charge agent. No LLM, no network.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("validator")

_PATTERNS_PATH = Path(__file__).parent.parent / "knowledge_base" / "charge_patterns.json"


@lru_cache(maxsize=1)
def _patterns() -> dict:
    """Load charge_patterns.json once; fail loud if missing or malformed."""
    text = _PATTERNS_PATH.read_text(encoding="utf-8")
    return json.loads(text)


def _domain(url: str) -> str:
    """Extract the hostname from a URL; returns '' for malformed input."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def is_verified_site(booking_url: str) -> bool:
    """True if the URL's domain (or parent domain) is in verified_sites."""
    host = _domain(booking_url)
    if not host:
        return False
    verified = _patterns().get("verified_sites", [])
    return any(host == v or host.endswith("." + v) for v in verified)


def is_flagged_site(booking_url: str) -> bool:
    """True if the URL's domain is in flagged_sites (trust_score auto-0)."""
    host = _domain(booking_url)
    if not host:
        return False
    flagged = _patterns().get("flagged_sites", [])
    return any(host == f or host.endswith("." + f) for f in flagged)


def red_flags_for_mode(mode: str) -> list[str]:
    """Return generic + mode-specific red-flag patterns for the LLM prompt."""
    p = _patterns()
    return list(p.get("red_flags", [])) + list(
        p.get("mode_specific_red_flags", {}).get(mode, [])
    )
```

### Key properties

- **Pure functions**, no state beyond the single cached JSON read.
- **Subdomain matching** via `host.endswith("." + v)`.
- **Fail loud on malformed JSON** — no defensive fallback.
- **LRU-cached** file read.

## 6. The four agents

### Shared conventions

- Every agent is a LangChain `AgentExecutor` built by a `build_<name>_agent() -> AgentExecutor` factory.
- Every LLM call uses `llm.with_structured_output(Schema)` where `Schema` is a Pydantic v2 model.
- Every agent imports `get_llm()` from `tools.llm_router`. Never instantiates a ChatModel directly.
- Agent `.invoke({"input": ...})` returns a typed dict matching the output contract.

### Router — `agents/router.py` (~90 lines)

**Contract:** `ShipmentInput dict → {mode: str, reason: str}`

**Internals:**

```python
def classify_mode(chargeable_weight_kg: float) -> str:
    if chargeable_weight_kg < 68: return "courier"
    if chargeable_weight_kg < 500: return "air_freight"
    return "sea_freight"

class RouterOutput(BaseModel):
    reason: str = Field(description="One-sentence user-facing explanation.")

def build_router_agent() -> AgentExecutor:
    """Returns an AgentExecutor that:
      1. Extracts chargeable_weight_kg from input
      2. mode = classify_mode(weight)   — deterministic
      3. Builds prompt with mode + shipment context
      4. llm.with_structured_output(RouterOutput).invoke(prompt) -> {reason}
      5. Returns {"mode": mode, "reason": output.reason}
    """
```

### Hidden-charge — `agents/hidden_charge.py` (~140 lines)

**Contract:** `{rate: ScrapedRate, mode: str, card_html: str} → {trust_score: int, flags: list[str], verified_site: bool}`

**Three-stage logic:**

1. **Short-circuit:** `is_flagged_site(rate.booking_url)` → return `trust_score=0`, `flags=["Site is flagged as deceptive"]`, `verified_site=False`. Never reaches the LLM.

2. **Context gathering:** `red_flags = red_flags_for_mode(mode)` from validator. Plus optionally (`if USE_PAGEINDEX_RUNTIME=true`): `_gather_rag_context(mode, origin, destination)` calling `query_pageindex(surcharge_doc_id, question)` for detailed surcharge bulletin guidance.

3. **LLM scoring:** prompt includes the card HTML excerpt, the rate dict, the red-flag list, and any RAG context. Asks the LLM to score 0–100 transparency and list exhibited red-flag patterns.

```python
class HiddenChargeOutput(BaseModel):
    trust_score: int = Field(ge=0, le=100, description="0-100 transparency score")
    flags: list[str] = Field(description="Plain-English warnings from the red-flag list")
```

After LLM call, attach `verified_site = is_verified_site(booking_url)` and return all three fields.

### Rate-comparator — `agents/rate_comparator.py` (~110 lines)

**Contract:** `list[partial ScoredRate] → list[ScoredRate]` (sorted ascending by `estimated_total_usd`)

**Zero LLM calls.** Deterministic math:

```python
def compute_estimated_total(base: float, trust_score: int) -> float:
    factor = (100 - trust_score) / 100 * 0.5
    return round(base * (1 + factor), 2)
```

Each rate gets `estimated_total_usd` attached, then the list is sorted. `AgentExecutor` wrapper is ceremony for A2A uniformity; if A2A never ships this collapses to a plain function (captured in backlog).

### Summarizer — `agents/summarizer.py` (~90 lines)

**Contract:** `{shipment, router_reason, ranked_rates} → {recommendation: str}`

```python
class SummarizerOutput(BaseModel):
    recommendation: str = Field(
        description="Plain-English top pick + warnings for small business owners."
    )
```

Prompt template:

> "You are advising a small business owner with no freight expertise. Their shipment is {product, weight, origin, destination}. Mode: {router_reason}. Here are the top 3 ranked quotes (carrier, mode, base price, trust score, flags). Write a 3–4 sentence plain-English recommendation: which quote to book, why, and what to watch out for."

`llm.with_structured_output(SummarizerOutput).invoke(prompt)` with `temperature=0.5`.

### Summary table — LLM usage per agent

| Agent | LLM call? | Temperature | Schema |
|---|---|---|---|
| Router | Yes — `reason` only | 0.2 | `RouterOutput` |
| Hidden-charge | Yes — per rate | 0.2 | `HiddenChargeOutput` |
| Rate-comparator | **No** — pure math/sort | — | — |
| Summarizer | Yes — prose generation | 0.5 | `SummarizerOutput` |

For 10 rates in v1: **12 LLM calls per request** (1 + 10 + 1). Worst-case ~6 s serial. Accepted for v1.

## 7. `tools/pageindex_client.py` — runtime-optional RAG

```python
"""PageIndex runtime retrieval — used only when USE_PAGEINDEX_RUNTIME=true.

Wraps POST /chat/completions (OpenAI-compatible) scoped to a doc_id. The
hidden-charge agent calls query_pageindex(doc_id, question) to get a
surcharge-bulletin answer. Default is OFF — charge_patterns.json is the
always-on data source for hidden-charge scoring.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("pageindex_client")

PAGEINDEX_CHAT_URL = "https://api.pageindex.ai/chat/completions"
REGISTRY_PATH = Path(__file__).parent.parent / "knowledge_base" / "doc_registry.json"


def is_enabled() -> bool:
    return os.getenv("USE_PAGEINDEX_RUNTIME", "false").lower() == "true"


@lru_cache(maxsize=1)
def _registry() -> dict:
    """Load {filename: {doc_id, sha256}} — fail loud if missing."""
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def doc_id_for(filename: str) -> str | None:
    """Look up a PageIndex doc_id by local filename; None if not ingested."""
    entry = _registry().get(filename)
    return entry["doc_id"] if entry else None


def query_pageindex(doc_id: str, question: str, timeout: float = 10.0) -> str | None:
    """Ask PageIndex a natural-language question scoped to one document.

    Returns the assistant's answer as a string, or None on any failure
    (network, non-2xx, empty body). Caller must tolerate None and fall
    back to charge_patterns.json only.
    """
    api_key = os.getenv("PAGEINDEX_API_KEY")
    if not api_key:
        logger.warning("PAGEINDEX_API_KEY not set -- skipping runtime retrieval")
        return None
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
                response.status_code,
                response.text[:200],
            )
            return None
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logger.warning("PageIndex returned empty content: %s", body)
            return None
        return content.strip()
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("PageIndex query raised: %s", e)
        return None
```

### Integration with hidden-charge agent

```python
# inside agents/hidden_charge.py
from tools.pageindex_client import is_enabled, doc_id_for, query_pageindex

def _gather_rag_context(mode: str, origin: str, destination: str) -> str:
    """Return extra context from PageIndex, or empty string when disabled/failed."""
    if not is_enabled():
        return ""
    doc_id = doc_id_for("surcharge_bulletin.pdf")
    if not doc_id:
        logger.warning("surcharge_bulletin.pdf not in doc_registry -- run ingest first")
        return ""
    q = (
        f"What typical surcharges apply to a {mode.replace('_', ' ')} shipment "
        f"from {origin} to {destination}? List each fee name and typical amount."
    )
    answer = query_pageindex(doc_id, q)
    return answer or ""
```

### Key properties

- **`is_enabled()` first** — when the flag is `false`, zero runtime cost.
- **Soft-failure** — network / parse errors return `None`; hidden-charge proceeds with just `charge_patterns.json`.
- **No retries** — consistent with Phase-1 ingest continue-on-error.
- **`doc_registry.json` is the source of truth** for PageIndex doc_ids; the client reads filenames, not raw doc_ids.
- **Timeout 10s** — PageIndex chat typically 1–3s; 10s margin without blocking Streamlit indefinitely.

## 8. `pipeline.py` — orchestrator

```python
"""End-to-end pipeline: ShipmentInput -> RecommendationResult.

Composes scraper + cache + all four agents into a linear flow:

  1. Router agent         → {mode, reason}
  2. Cache check          → list[ScrapedRate] or MISS
  3. Scraper (on miss)    → list[ScrapedRate]; put_cache on success
  4. Hidden-charge agent  → per rate: + {trust_score, flags, verified_site}
  5. Rate-comparator      → + {estimated_total_usd}, sorted by est_total asc
  6. Summarizer agent     → recommendation prose

Returns one RecommendationResult dict. Exceptions in any per-rate step
are caught and logged; the rate is dropped but the pipeline continues.
If the pipeline can produce zero ranked rates, returns a
RecommendationResult with `rates=[]` and a diagnostic recommendation
string — never raises to the caller.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TypedDict

from agents import (
    build_hidden_charge_agent,
    build_rate_comparator_agent,
    build_router_agent,
    build_summarizer_agent,
)
from tools.cache import get_cached, put_cache
from tools.scraper import Query, scrape_all

logger = logging.getLogger("pipeline")


class RecommendationResult(TypedDict):
    mode: str
    router_reason: str
    rates: list[dict]
    recommendation: str
    cache_hit: bool
    sites_succeeded: int
    errors: list[str]


def run_pipeline(shipment_input: dict) -> RecommendationResult:
    errors: list[str] = []

    # Step 1: Router
    router = build_router_agent()
    route = router.invoke({"input": shipment_input})

    # Steps 2 & 3: Cache then scrape
    today = date.today()
    cached = get_cached(
        shipment_input["origin"], shipment_input["destination"], today
    )
    cache_hit = cached is not None
    if cache_hit:
        scraped = cached
    else:
        scraped = scrape_all(Query(
            origin=shipment_input["origin"],
            destination=shipment_input["destination"],
            chargeable_weight_kg=shipment_input["chargeable_weight_kg"],
            mode=route["mode"],
        ))
        if scraped:
            put_cache(
                shipment_input["origin"],
                shipment_input["destination"],
                today, scraped,
            )
    sites_succeeded = len({r["source_site"] for r in scraped})

    # Step 4: Hidden-charge scoring per rate
    hidden_charge = build_hidden_charge_agent()
    partial_scored: list[dict] = []
    for rate in scraped:
        try:
            result = hidden_charge.invoke({
                "input": {
                    "rate": rate,
                    "mode": route["mode"],
                    "card_html": rate.get("_card_html", ""),
                }
            })
            scored = {**rate, **result}
            scored.pop("_card_html", None)
            partial_scored.append(scored)
        except Exception as e:
            logger.error("hidden-charge failed on %s/%s: %s",
                         rate.get("source_site"), rate.get("carrier"), e)
            errors.append(f"hidden-charge failed on {rate.get('carrier')}: {e}")

    # Step 5: Rate-comparator
    comparator = build_rate_comparator_agent()
    ranked = comparator.invoke({"input": partial_scored})

    # Step 6: Summarizer
    if not ranked:
        return {
            "mode": route["mode"],
            "router_reason": route["reason"],
            "rates": [],
            "recommendation": (
                "No rate quotes available for this route. "
                "Try again later or broaden your origin/destination."
            ),
            "cache_hit": cache_hit,
            "sites_succeeded": sites_succeeded,
            "errors": errors,
        }

    summarizer = build_summarizer_agent()
    summary = summarizer.invoke({"input": {
        "shipment": shipment_input,
        "router_reason": route["reason"],
        "ranked_rates": ranked[:3],
    }})

    return {
        "mode": route["mode"],
        "router_reason": route["reason"],
        "rates": ranked,
        "recommendation": summary["recommendation"],
        "cache_hit": cache_hit,
        "sites_succeeded": sites_succeeded,
        "errors": errors,
    }
```

## 9. Error handling + latency

### Failure matrix

| Failure | Behaviour | User-visible? |
|---|---|---|
| Router LLM call fails | LiteLLM fallback; if all three fail → raise | Yes (Streamlit error) |
| Cache read corrupted | `get_cached` returns None; falls through to scrape | No |
| Scraper: one site fails | Phase-2 continue-on-error; `sites_succeeded` decreases | Indirect |
| Scraper: all sites fail | `scraped = []` → diagnostic recommendation | Yes (graceful) |
| Hidden-charge on one rate fails | Logged + errors list + rate dropped | errors count |
| All hidden-charge calls fail | `partial_scored = []` → diagnostic recommendation | Yes (graceful) |
| Rate-comparator fails | Raises (bug — deterministic math) | Yes (bug) |
| Summarizer fails | Empty `recommendation` + errors entry | Yes (degraded) |
| PageIndex runtime query fails | `query_pageindex` returns None; charge_patterns.json-only | No (soft degrade) |

Pipeline never raises for data-availability reasons. Only genuine bugs propagate.

### Latency envelope

v1 serial worst case:
- Router: 1 LLM call (~500 ms)
- Scraper: fixtures, ~20 ms
- Hidden-charge: 10 rates × 1 LLM call = ~5 s serial
- Rate-comparator: no LLM, ~5 ms
- Summarizer: 1 LLM call (~800 ms, larger prompt)

Total: **~6.3 s worst case, ~12 LLM calls**. Cached runs shave ~50 ms; still ~6 s because LLM calls dominate. Accepted; Streamlit spinner covers it.

Mitigations in backlog: parallelise hidden-charge via `ThreadPoolExecutor`, or batch all 10 cards into one LLM call.

## 10. Implementation sequence

```
 1. pyproject.toml: add langchain, langchain-litellm, litellm, pydantic
 2. tools/llm_router.py                     — get_llm() via LiteLLM Router
 3. knowledge_base/charge_patterns.json     — red-flags + site lists
 4. tools/validator.py                      — is_verified_site/flagged_site + red_flags_for_mode
 5. tools/pageindex_client.py               — query_pageindex
 6. agents/__init__.py                      — re-exports
 7. agents/router.py                        — classify_mode + LLM reason
 8. agents/hidden_charge.py                 — trust_score + flags + verified_site
 9. agents/rate_comparator.py               — estimated_total + rank (no LLM)
10. agents/summarizer.py                    — recommendation prose
11. tools/scraper.py: populate `_card_html` in all three parsers
12. pipeline.py                             — run_pipeline orchestrator
13. .env.example: add USE_PAGEINDEX_RUNTIME=false
14. Manual E2E: uv run python -c "from pipeline import run_pipeline; ..."
15. CLAUDE.md: update Current state + document USE_PAGEINDEX_RUNTIME flag
```

## 11. Acceptance criteria

Phase 3 is complete when all of these hold:

- `uv sync` installs langchain + langchain-litellm + litellm + pydantic without errors.
- `from tools.llm_router import get_llm; llm = get_llm(); llm.invoke("hello")` returns a non-empty response from Groq (primary).
- `from tools.validator import is_verified_site; is_verified_site("https://www.freightos.com/book/x")` returns `True`.
- `USE_PAGEINDEX_RUNTIME=true uv run python -c "from tools.pageindex_client import query_pageindex, doc_id_for; print(query_pageindex(doc_id_for('surcharge_bulletin.pdf'), 'what are air freight surcharges?'))"` returns a non-empty string.
- `USE_PAGEINDEX_RUNTIME=false ...` — `query_pageindex` not invoked (check via log output).
- `run_pipeline({"chargeable_weight_kg": 12, "origin": "Delhi", "destination": "Rotterdam", ...full ShipmentInput})` with a 12kg shipment returns a `RecommendationResult` with:
  - `mode == "courier"` (<68kg threshold)
  - `router_reason` — non-empty
  - `recommendation` — non-empty
  - `errors` — empty (per-rate warnings OK)
- `run_pipeline({"chargeable_weight_kg": 200, ...})` — 200 kg shipment — returns 10 ranked rates (4+3+3), `mode == "air_freight"`, summary mentions top carrier.
- Second identical call → `cache_hit == True`, scraping skipped, rates identical.
- `USE_PAGEINDEX_RUNTIME=true` run → at least one rate's `flags` contains PageIndex-sourced text not present in `charge_patterns.json`.
- CLAUDE.md's Current state reflects Phase 3 complete; USE_PAGEINDEX_RUNTIME flag documented.

## 12. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| `langchain-litellm` API drift (newer package) | Fallback: 30-line custom `BaseChatModel` calling `litellm.completion()` directly. Flagged; resolved in plan. |
| Groq `llama-3.3-70b-versatile` deprecated again | LiteLLM fallback to OpenAI ensures pipeline still runs. |
| PageIndex `/chat/completions` schema changes | `query_pageindex` returns `None` on any non-matching shape; charge_patterns.json fallback always works. |
| 12 LLM calls per request → cost + latency concerns | Flagged. Backlog: parallelise or batch hidden-charge. v1 accepts ~6s. |
| `with_structured_output` fails when LiteLLM fallback switches providers | All three providers support it; fallback triggers retry on provider change. |
| `_card_html` internal field leaks into serialised output | `pipeline.py` explicitly `pop("_card_html", None)`; caught in acceptance test. |
| `USE_PAGEINDEX_RUNTIME=true` but `doc_registry.json` missing | `doc_id_for` returns `None`, logs warning, hidden-charge continues without RAG. |

## 13. Phase 5 / future backlog

- **Latency optimisation:** parallelise hidden-charge via ThreadPoolExecutor OR batch all N cards into one LLM call. Not v1.
- **Summarizer Incoterms RAG:** optional `query_pageindex(incoterms_doc_id, ...)` — design supports it, not wired.
- **Rate-comparator AgentExecutor collapse:** if A2A never ships, simplify to plain function.
- **Streaming:** summarizer output not streamed; Phase 4 Streamlit can add.
- **Prompt caching / LangSmith / Langfuse:** YAGNI until Phase 5.
- **Carrier trust baseline:** known reliable carriers (Maersk, DHL) could start with +10 baseline. Not v1.
- **Phase-2 backlog still open:** `cache.py` `clear_cache` leak, error log keys, `_parse_days_from_text` comma bug, unused `Query` fields.

## 14. Non-goals for Phase 3

- No retries for in-pipeline LLM calls beyond LiteLLM's built-in provider fallback.
- No A2A endpoint wiring (AgentExecutor structure is the hook; the HTTP layer comes later).
- No distributed / async orchestration.
- No cost tracking.
- No prompt-caching, memoisation of LLM responses.
- No rate-limit-aware backpressure — LiteLLM handles provider-side 429s via fallback.
- No Incoterms-based advice in summarizer (hook exists, not wired).
- No tests (Phase 5).
- No Streamlit UI (Phase 4).

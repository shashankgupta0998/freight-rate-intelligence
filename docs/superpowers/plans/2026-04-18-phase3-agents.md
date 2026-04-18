# Phase 3 — Agents + LangChain + LLM Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the intelligence layer — four LangChain `Runnable`-based agents (router, hidden-charge, rate-comparator, summarizer) orchestrated by a single `run_pipeline(ShipmentInput) -> RecommendationResult` function, with LiteLLM managing the Groq → OpenAI → Gemini fallback chain.

> **Note (post-spec discovery):** LangChain 1.x removed the `AgentExecutor` class. The spec's original phrasing referred to `AgentExecutor`-wrapped agents, but in LangChain 1.x the equivalent agent-object interface is `Runnable` (same stable `.invoke(input) -> output` protocol; what A2A exposure needs). All four agents use `Runnable` directly. The user-facing contract is unchanged.

**Architecture:** `tools/llm_router.py` exposes `get_llm()` — the single LLM entry point; all four agents route through it. `tools/validator.py` does booking-site checks against `knowledge_base/charge_patterns.json`. `tools/pageindex_client.py` adds runtime-optional RAG (default off). Each agent is a LangChain `AgentExecutor` with a consistent `.invoke({"input": ...}) -> dict` surface for future A2A exposure. Router and rate-comparator use Python rules for their core logic; LLM is only invoked for prose/judgment. `pipeline.py` at project root chains everything linearly with continue-on-error semantics per rate.

**Tech Stack:** Python 3.11+, `langchain` + `langchain-litellm` + `litellm` (provider fallback), `pydantic` v2 (structured output), stdlib `logging`/`dataclasses`/`functools`. Managed via `uv` + `pyproject.toml`.

**Source spec:** `docs/superpowers/specs/2026-04-18-phase3-agents-design.md`

**Tests:** Deferred to Phase 5 per the approved spec and project build order. Each task uses manual verification commands (`uv run python -c ...`) with expected output. Every function is factored to be mockable (`get_llm` is a single patchable entry point; agents are builder functions returning `Runnable` instances).

**Pre-flight:** `uv` is installed, Phase 1 + Phase 2 deliverables are on disk, `.env` has real keys for `GROQ_API_KEY` (required), `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PAGEINDEX_API_KEY`.

---

## Task 1: Add LangChain + LiteLLM + Pydantic dependencies

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Edit pyproject.toml dependencies list**

Replace the `dependencies = [...]` block with EXACTLY:

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

Leave `[project]` metadata, `[tool.uv]`, `[tool.hatch.build.targets.wheel]`, and `[build-system]` untouched.

- [ ] **Step 2: Run uv sync**

```bash
uv sync
```
Expected: resolves ~30+ packages (LangChain + LiteLLM both pull transitive deps). No errors.

If `langchain-litellm>=0.1` can't be resolved (package name may differ depending on registry state), STOP and report BLOCKED. The implementation-plan fallback is a ~30-line custom `BaseChatModel` calling `litellm.completion()` directly — that would require a plan revision.

- [ ] **Step 3: Verify imports**

```bash
uv run python -c "
import langchain
import langchain_core
import langchain_litellm
import litellm
import pydantic
print('langchain:', langchain.__version__)
print('litellm:', litellm.__version__)
print('pydantic:', pydantic.VERSION)
"
```
Expected: prints three version strings; exit 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add langchain + langchain-litellm + litellm + pydantic for Phase 3"
```

---

## Task 2: Implement tools/llm_router.py

**Files:** Create `tools/llm_router.py`.

- [ ] **Step 1: Write llm_router.py**

Create `tools/llm_router.py` with EXACTLY this content:

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
        model="groq",
        temperature=temperature,
    )
```

- [ ] **Step 2: Manual verification — Groq primary works**

```bash
uv run python -c "
from tools.llm_router import get_llm
llm = get_llm()
resp = llm.invoke('Say the word OK and nothing else.')
print(type(resp).__name__, '->', repr(resp.content)[:80])
"
```
Expected: prints something like `AIMessage -> 'OK'` or `AIMessage -> 'OK.'`. No errors. Network call lands at Groq (primary).

If the output reports a `ValidationError` about `model` parameter or a `ChatLiteLLM` signature mismatch, the `langchain-litellm` package API has drifted from our assumption. STOP and report BLOCKED with the exact error — the implementation plan needs revision to use a custom `BaseChatModel`.

- [ ] **Step 3: Manual verification — same instance returned (lru_cache)**

```bash
uv run python -c "
from tools.llm_router import get_llm
a = get_llm()
b = get_llm()
assert a is b, 'get_llm should return cached singleton'
print('singleton OK')
"
```
Expected: prints `singleton OK`.

- [ ] **Step 4: Commit**

```bash
git add tools/llm_router.py
git commit -m "feat(llm_router): add get_llm() with LiteLLM Groq->OpenAI->Gemini fallback"
```

---

## Task 3: Create charge_patterns.json and validator.py

**Files:**
- Create: `knowledge_base/charge_patterns.json`
- Create: `tools/validator.py`

- [ ] **Step 1: Write charge_patterns.json**

Create `knowledge_base/charge_patterns.json` with EXACTLY this content:

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

- [ ] **Step 2: Write tools/validator.py**

Create `tools/validator.py` with EXACTLY this content:

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

- [ ] **Step 3: Manual verification**

```bash
uv run python -c "
from tools.validator import is_verified_site, is_flagged_site, red_flags_for_mode

# Verified site checks
assert is_verified_site('https://www.freightos.com/book/abc') is True, 'www.freightos.com should match'
assert is_verified_site('https://ship.freightos.com/book/abc') is True, 'ship.freightos.com should match'
assert is_verified_site('https://random-scam.example.com/') is False, 'unknown domain should not match'
assert is_verified_site('') is False, 'empty URL should be False'

# Flagged site (empty list → always False for v1)
assert is_flagged_site('https://any-domain.com/') is False

# Red flags
air = red_flags_for_mode('air_freight')
sea = red_flags_for_mode('sea_freight')
assert len(air) == 10, f'expected 10 air flags (8 generic + 2 mode-specific), got {len(air)}'
assert len(sea) == 10, f'expected 10 sea flags (8 generic + 2 mode-specific), got {len(sea)}'
assert any('security / ISPS' in f for f in air)
assert any('chassis fee' in f for f in sea)
print('validator OK')
"
```
Expected: prints `validator OK`.

- [ ] **Step 4: Commit**

```bash
git add knowledge_base/charge_patterns.json tools/validator.py
git commit -m "feat(validator): add charge_patterns.json + booking-site validator helpers"
```

---

## Task 4: Implement tools/pageindex_client.py

**Files:** Create `tools/pageindex_client.py`.

- [ ] **Step 1: Write pageindex_client.py**

Create `tools/pageindex_client.py` with EXACTLY this content:

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

- [ ] **Step 2: Manual verification — flag detection**

```bash
uv run python -c "
import os
from tools.pageindex_client import is_enabled

os.environ.pop('USE_PAGEINDEX_RUNTIME', None)
assert is_enabled() is False, 'default (unset) should be False'

os.environ['USE_PAGEINDEX_RUNTIME'] = 'false'
assert is_enabled() is False, 'explicit false should be False'

os.environ['USE_PAGEINDEX_RUNTIME'] = 'TRUE'
assert is_enabled() is True, 'case-insensitive true should be True'

os.environ['USE_PAGEINDEX_RUNTIME'] = 'true'
assert is_enabled() is True
print('is_enabled OK')
"
```
Expected: prints `is_enabled OK`.

- [ ] **Step 3: Manual verification — doc_id lookup**

```bash
uv run python -c "
from tools.pageindex_client import doc_id_for

surcharge_id = doc_id_for('surcharge_bulletin.pdf')
assert surcharge_id is not None, 'surcharge_bulletin.pdf must be in doc_registry.json from Phase 1'
assert surcharge_id.startswith('pi-'), f'doc_id should start with pi-, got {surcharge_id!r}'

missing = doc_id_for('nonexistent.pdf')
assert missing is None, 'unknown filename should return None'
print('doc_id_for OK')
"
```
Expected: prints `doc_id_for OK`.

- [ ] **Step 4: Manual verification — live query (makes one real PageIndex API call)**

```bash
USE_PAGEINDEX_RUNTIME=true uv run python -c "
from tools.pageindex_client import query_pageindex, doc_id_for

doc_id = doc_id_for('surcharge_bulletin.pdf')
answer = query_pageindex(doc_id, 'What surcharges apply to air freight?')
assert answer is not None, 'expected non-None answer'
assert len(answer) > 20, f'answer suspiciously short: {answer!r}'
print('query_pageindex OK:')
print(answer[:200])
"
```
Expected: prints `query_pageindex OK:` followed by a non-empty string describing air-freight surcharges. The call takes 1–5 seconds.

If the call fails (network, 4xx, etc.), the function should return `None` — but for this verification we assert non-None to confirm the endpoint is reachable. If it fails, STOP and investigate: check PAGEINDEX_API_KEY in `.env`, check internet, check that PageIndex's `/chat/completions` endpoint hasn't changed shape.

- [ ] **Step 5: Commit**

```bash
git add tools/pageindex_client.py
git commit -m "feat(pageindex): add runtime-optional PageIndex client via /chat/completions"
```

---

## Task 5: Create agents/__init__.py (empty placeholder)

**Files:** Create `agents/__init__.py` (empty).

- [ ] **Step 1: Create directory and empty file**

```bash
mkdir -p agents
touch agents/__init__.py
```

- [ ] **Step 2: Verify**

```bash
ls -la agents/
uv run python -c "import agents; print('agents package importable')"
```
Expected: `agents/__init__.py` exists (0 bytes); import prints `agents package importable`.

- [ ] **Step 3: Commit**

```bash
git add agents/__init__.py
git commit -m "feat: scaffold agents/ package"
```

Note: `agents/__init__.py` will be populated with re-exports in Task 10 after all four agents exist.

---

## Task 6: Implement agents/router.py

**Files:** Create `agents/router.py`.

- [ ] **Step 1: Write router.py**

Create `agents/router.py` with EXACTLY this content:

```python
"""Router agent — classifies shipment mode from chargeable weight.

Mode is decided by deterministic thresholds (CLAUDE.md); LLM generates
only the user-facing reason text. Returned as a LangChain Runnable for
A2A uniformity (all four agents share the same .invoke() shape).

Note: LangChain 1.x removed AgentExecutor; Runnable is the equivalent
agent-object interface with a stable .invoke(input) -> output protocol.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from tools.llm_router import get_llm

logger = logging.getLogger("agent.router")


def classify_mode(chargeable_weight_kg: float) -> str:
    """Deterministic mode classification per CLAUDE.md thresholds."""
    if chargeable_weight_kg < 68:
        return "courier"
    if chargeable_weight_kg < 500:
        return "air_freight"
    return "sea_freight"


class RouterOutput(BaseModel):
    reason: str = Field(
        description=(
            "One-sentence user-facing explanation of why this freight mode "
            "was chosen for the shipment."
        )
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You advise small business owners on freight logistics. "
     "Be concise and plain-spoken."),
    ("human",
     "Shipment: product={product}, chargeable_weight={weight} kg, "
     "origin={origin}, destination={destination}.\n"
     "Mode already classified as '{mode}' based on weight thresholds "
     "(<68kg courier, <500kg air, >=500kg sea).\n"
     "Write ONE sentence explaining why this mode fits this shipment."),
])


class _RouterRunnable(Runnable):
    """Internal Runnable wrapping deterministic mode classification + LLM reason."""

    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> dict:
        shipment = inputs["input"] if "input" in inputs else inputs
        weight = float(shipment["chargeable_weight_kg"])
        mode = classify_mode(weight)
        llm = get_llm(temperature=0.2)
        structured = llm.with_structured_output(RouterOutput)
        chain = _PROMPT | structured
        result = chain.invoke({
            "product": shipment.get("product", "unknown"),
            "weight": weight,
            "origin": shipment.get("origin", "?"),
            "destination": shipment.get("destination", "?"),
            "mode": mode,
        })
        logger.info("router: %s (%s kg)", mode, weight)
        return {"mode": mode, "reason": result.reason}


def build_router_agent() -> Runnable:
    """Return a LangChain Runnable for the router agent.

    The Runnable exposes .invoke({"input": shipment_dict}) -> {"mode", "reason"}.
    This shape is consistent across all four Phase-3 agents (A2A-ready).
    """
    return _RouterRunnable()
```

- [ ] **Step 2: Manual verification — classify_mode is pure**

```bash
uv run python -c "
from agents.router import classify_mode
assert classify_mode(12) == 'courier'
assert classify_mode(67.9) == 'courier'
assert classify_mode(68) == 'air_freight'
assert classify_mode(200) == 'air_freight'
assert classify_mode(499.99) == 'air_freight'
assert classify_mode(500) == 'sea_freight'
assert classify_mode(1500) == 'sea_freight'
print('classify_mode OK')
"
```
Expected: prints `classify_mode OK`.

- [ ] **Step 3: Manual verification — router agent end-to-end (real LLM call)**

```bash
uv run python -c "
import logging
from agents.router import build_router_agent

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

router = build_router_agent()
out = router.invoke({'input': {
    'product': 'electronics',
    'chargeable_weight_kg': 12.0,
    'origin': 'Delhi',
    'destination': 'Rotterdam',
}})
assert out['mode'] == 'courier', f'expected courier, got {out[\"mode\"]}'
assert isinstance(out['reason'], str) and len(out['reason']) > 10, f'bad reason: {out[\"reason\"]!r}'
print('router agent OK:')
print('  mode:', out['mode'])
print('  reason:', out['reason'])

out2 = router.invoke({'input': {
    'product': 'furniture',
    'chargeable_weight_kg': 600.0,
    'origin': 'Mumbai',
    'destination': 'Hamburg',
}})
assert out2['mode'] == 'sea_freight', f'expected sea_freight, got {out2[\"mode\"]}'
print('600kg → sea_freight OK')
"
```
Expected: prints mode + reason for a 12 kg shipment (courier) and confirms a 600 kg shipment routes to sea_freight. Two real LLM calls to Groq.

- [ ] **Step 4: Commit**

```bash
git add agents/router.py
git commit -m "feat(router): add mode classifier with deterministic rules + LLM reason"
```

---

## Task 7: Implement agents/hidden_charge.py

**Files:** Create `agents/hidden_charge.py`.

- [ ] **Step 1: Write hidden_charge.py**

Create `agents/hidden_charge.py` with EXACTLY this content:

```python
"""Hidden-charge agent — scores each rate's transparency (0-100) and
lists surcharge red-flags exhibited by the rate card.

Flow per rate:
  1. Short-circuit: is_flagged_site(booking_url) -> trust_score=0
  2. Gather: red_flags_for_mode(mode) from charge_patterns.json;
             optionally query_pageindex(surcharge_bulletin.pdf, ...)
             when USE_PAGEINDEX_RUNTIME=true.
  3. LLM: score trust_score + list exhibited flags.
  4. Attach verified_site = is_verified_site(booking_url).
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from tools.llm_router import get_llm
from tools.pageindex_client import doc_id_for, is_enabled, query_pageindex
from tools.validator import is_flagged_site, is_verified_site, red_flags_for_mode

logger = logging.getLogger("agent.hidden_charge")


class HiddenChargeOutput(BaseModel):
    trust_score: int = Field(
        ge=0, le=100,
        description="Transparency score 0-100. Higher = more surcharges itemised upfront."
    )
    flags: list[str] = Field(
        description=(
            "Plain-English warnings drawn from the provided red-flag patterns "
            "that this quote exhibits. Empty list if none apply."
        )
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a freight auditing expert. You review freight quote HTML "
     "against known red-flag patterns and score transparency."),
    ("human",
     "Rate card HTML:\n```\n{card_html}\n```\n\n"
     "Parsed rate dict: carrier={carrier}, base_price_usd=${price}, "
     "mode={mode}, booking_url={booking_url}\n\n"
     "Red-flag patterns to check for ({mode}):\n{red_flags}\n\n"
     "{rag_context}"
     "Return a trust_score (0-100) and the list of red-flag patterns "
     "(from the list above, verbatim) that this quote exhibits. "
     "A quote with all surcharges itemised should score 85-100; a quote "
     "with only a base price and no fee breakdown should score 30-50; a "
     "quote missing standard fees for its mode should score below 30."),
])


def _gather_rag_context(mode: str, origin: str, destination: str) -> str:
    """Return extra context from PageIndex, or empty string when disabled/failed."""
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
    answer = query_pageindex(doc_id, question)
    if not answer:
        return ""
    return (
        "Additional context from surcharge bulletin:\n"
        f"```\n{answer}\n```\n\n"
    )


class _HiddenChargeRunnable(Runnable):
    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> dict:
        payload = inputs["input"] if "input" in inputs else inputs
        rate: dict = payload["rate"]
        mode: str = payload["mode"]
        card_html: str = payload.get("card_html", "")
        origin: str = payload.get("origin", rate.get("origin", "unknown"))
        destination: str = payload.get(
            "destination", rate.get("destination", "unknown")
        )

        booking_url = rate.get("booking_url", "")

        # Short-circuit flagged sites
        if is_flagged_site(booking_url):
            logger.info(
                "hidden-charge: %s flagged-site short-circuit", booking_url
            )
            return {
                "trust_score": 0,
                "flags": ["Site is flagged as deceptive"],
                "verified_site": False,
            }

        # Gather inputs for the LLM
        red_flags = red_flags_for_mode(mode)
        rag_context = _gather_rag_context(mode, origin, destination)

        llm = get_llm(temperature=0.2)
        structured = llm.with_structured_output(HiddenChargeOutput)
        chain = _PROMPT | structured
        result: HiddenChargeOutput = chain.invoke({
            "card_html": card_html or "(no HTML excerpt available)",
            "carrier": rate.get("carrier", "unknown"),
            "price": rate.get("base_price_usd", 0),
            "mode": mode,
            "booking_url": booking_url or "(none)",
            "red_flags": "\n".join(f"- {f}" for f in red_flags),
            "rag_context": rag_context,
        })

        verified = is_verified_site(booking_url)
        logger.info(
            "hidden-charge: %s/%s -> trust=%d flags=%d verified=%s",
            rate.get("source_site", "?"),
            rate.get("carrier", "?"),
            result.trust_score,
            len(result.flags),
            verified,
        )
        return {
            "trust_score": int(result.trust_score),
            "flags": list(result.flags),
            "verified_site": verified,
        }


def build_hidden_charge_agent() -> Runnable:
    """Return the hidden-charge agent as a Runnable with .invoke() surface."""
    return _HiddenChargeRunnable()
```

- [ ] **Step 2: Manual verification — flagged-site short-circuit (no LLM call)**

Temporarily add a flagged site to `charge_patterns.json`:

```bash
uv run python -c "
import json
from pathlib import Path

path = Path('knowledge_base/charge_patterns.json')
data = json.loads(path.read_text())
data['flagged_sites'] = ['scammer.example.com']
path.write_text(json.dumps(data, indent=2))

# Clear validator cache so it re-reads
from tools.validator import _patterns
_patterns.cache_clear()

from agents.hidden_charge import build_hidden_charge_agent
agent = build_hidden_charge_agent()
out = agent.invoke({'input': {
    'rate': {
        'carrier': 'BadCarrier',
        'base_price_usd': 100.0,
        'booking_url': 'https://scammer.example.com/book/1',
        'source_site': 'freightos',
    },
    'mode': 'air_freight',
    'card_html': '<div>whatever</div>',
}})
assert out == {'trust_score': 0, 'flags': ['Site is flagged as deceptive'], 'verified_site': False}, f'unexpected: {out}'
print('flagged-site short-circuit OK')

# Restore charge_patterns.json
data['flagged_sites'] = []
path.write_text(json.dumps(data, indent=2))
_patterns.cache_clear()
"
```
Expected: prints `flagged-site short-circuit OK`. No LLM call is made (verified by absence of network activity; Groq API unused).

- [ ] **Step 3: Manual verification — real LLM call against Freightos fixture card**

```bash
uv run python -c "
import logging
from pathlib import Path
from agents.hidden_charge import build_hidden_charge_agent

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

# Use an inline approximation of one Freightos card (matches the Phase-2 fixture)
card_html = '''
<li class=\"quote-card\" data-carrier=\"lufthansa-cargo\">
  <span class=\"carrier-name\">Lufthansa Cargo</span>
  <span class=\"mode-label\">Air Freight</span>
  <span class=\"price-usd\">\$892.00</span>
  <time class=\"transit\" datetime=\"P7D\">7 days</time>
  <ul class=\"surcharges\">
    <li><span class=\"fee-name\">Fuel surcharge</span><span class=\"fee-amount\">\$78</span></li>
    <li><span class=\"fee-name\">Security fee</span><span class=\"fee-amount\">\$25</span></li>
  </ul>
  <a class=\"book-link\" href=\"https://ship.freightos.com/book/LH-ABC123\">Book</a>
</li>
'''

agent = build_hidden_charge_agent()
out = agent.invoke({'input': {
    'rate': {
        'carrier': 'Lufthansa Cargo',
        'base_price_usd': 892.0,
        'booking_url': 'https://ship.freightos.com/book/LH-ABC123',
        'source_site': 'freightos',
    },
    'mode': 'air_freight',
    'card_html': card_html,
}})
assert 0 <= out['trust_score'] <= 100
assert isinstance(out['flags'], list)
assert out['verified_site'] is True, 'ship.freightos.com should be verified'
print('hidden-charge agent OK:')
print('  trust_score:', out['trust_score'])
print('  flags:', out['flags'])
print('  verified_site:', out['verified_site'])
"
```
Expected: prints trust_score (likely 75-95 since Lufthansa card has itemised surcharges), flags list (usually 0-2 entries), verified_site=True. One real LLM call to Groq.

- [ ] **Step 4: Commit**

```bash
git add agents/hidden_charge.py
git commit -m "feat(hidden_charge): add trust-score + flags + verified-site agent"
```

---

## Task 8: Implement agents/rate_comparator.py

**Files:** Create `agents/rate_comparator.py`.

- [ ] **Step 1: Write rate_comparator.py**

Create `agents/rate_comparator.py` with EXACTLY this content:

```python
"""Rate-comparator — adds estimated_total_usd and sorts by it ascending.

Deterministic; no LLM calls. Wrapped in a Runnable for A2A uniformity
with the other three agents.

Formula: estimated_total = base_price * (1 + (100 - trust_score)/100 * 0.5)
  trust 100 -> +0%, trust 50 -> +25%, trust 0 -> +50%
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import Runnable

logger = logging.getLogger("agent.rate_comparator")


def compute_estimated_total(base_price_usd: float, trust_score: int) -> float:
    """Apply linear surcharge factor derived from trust_score.

    Returns USD total rounded to 2 decimal places.
    """
    factor = (100 - max(0, min(100, trust_score))) / 100 * 0.5
    return round(base_price_usd * (1 + factor), 2)


class _RateComparatorRunnable(Runnable):
    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> list[dict]:
        payload = inputs["input"] if "input" in inputs else inputs
        if not isinstance(payload, list):
            raise TypeError(
                f"rate_comparator expects a list of partial ScoredRate dicts, "
                f"got {type(payload).__name__}"
            )

        out: list[dict] = []
        for rate in payload:
            base = float(rate.get("base_price_usd", 0.0))
            trust = int(rate.get("trust_score", 0))
            total = compute_estimated_total(base, trust)
            out.append({**rate, "estimated_total_usd": total})

        out.sort(key=lambda r: r["estimated_total_usd"])
        logger.info("rate_comparator: ranked %d rates", len(out))
        return out


def build_rate_comparator_agent() -> Runnable:
    """Return the rate-comparator agent (no LLM; pure math + sort)."""
    return _RateComparatorRunnable()
```

- [ ] **Step 2: Manual verification — formula**

```bash
uv run python -c "
from agents.rate_comparator import compute_estimated_total

assert compute_estimated_total(1000.0, 100) == 1000.0, 'trust 100 -> +0%'
assert compute_estimated_total(1000.0, 50) == 1250.0, 'trust 50 -> +25%'
assert compute_estimated_total(1000.0, 0) == 1500.0, 'trust 0 -> +50%'
# Edge: out-of-range clamping
assert compute_estimated_total(1000.0, 150) == 1000.0, 'trust > 100 clamps to 100'
assert compute_estimated_total(1000.0, -10) == 1500.0, 'trust < 0 clamps to 0'
print('compute_estimated_total OK')
"
```
Expected: prints `compute_estimated_total OK`.

- [ ] **Step 3: Manual verification — sort + enrichment**

```bash
uv run python -c "
from agents.rate_comparator import build_rate_comparator_agent

agent = build_rate_comparator_agent()
rates = [
    {'carrier': 'A', 'base_price_usd': 900.0, 'trust_score': 90},
    {'carrier': 'B', 'base_price_usd': 800.0, 'trust_score': 40},
    {'carrier': 'C', 'base_price_usd': 1000.0, 'trust_score': 100},
]
out = agent.invoke({'input': rates})

# Each rate gets estimated_total_usd
for r in out:
    assert 'estimated_total_usd' in r

# Sorted ascending
totals = [r['estimated_total_usd'] for r in out]
assert totals == sorted(totals), f'not sorted: {totals}'

# Original dicts not mutated (pipeline correctness)
assert 'estimated_total_usd' not in rates[0], 'input dicts should not be mutated'

print('rate_comparator OK:')
for r in out:
    print(f'  {r[\"carrier\"]:10} base=\${r[\"base_price_usd\"]} trust={r[\"trust_score\"]:3} est_total=\${r[\"estimated_total_usd\"]}')
"
```
Expected: prints three rates sorted by estimated_total_usd ascending, with the high-trust carrier likely beating low-trust despite similar base prices.

- [ ] **Step 4: Commit**

```bash
git add agents/rate_comparator.py
git commit -m "feat(rate_comparator): add estimated_total formula + rank (no LLM)"
```

---

## Task 9: Implement agents/summarizer.py

**Files:** Create `agents/summarizer.py`.

- [ ] **Step 1: Write summarizer.py**

Create `agents/summarizer.py` with EXACTLY this content:

```python
"""Summarizer — generates a 3-4 sentence plain-English recommendation
from the ranked rates + router reason + original shipment input.

LLM temperature 0.5 (higher than other agents — prose generation).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from tools.llm_router import get_llm

logger = logging.getLogger("agent.summarizer")


class SummarizerOutput(BaseModel):
    recommendation: str = Field(
        description=(
            "3-4 sentence plain-English recommendation for a small business "
            "owner: which quote to book, why it is the best value, and one "
            "key thing to watch out for."
        )
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You advise small business owners who ship freight internationally. "
     "They have no freight-broker expertise. Be direct, practical, "
     "and warn them about hidden costs."),
    ("human",
     "Shipment: {shipment_json}\n"
     "Mode: {router_reason}\n\n"
     "Top 3 ranked quotes:\n{rates_table}\n\n"
     "Write a 3-4 sentence recommendation: which to book, why it is the "
     "best value, and one key thing to watch out for based on the flags."),
])


def _format_rates_table(rates: list[dict]) -> str:
    lines = []
    for i, r in enumerate(rates, 1):
        flags_str = "; ".join(r.get("flags", [])) or "none"
        lines.append(
            f"{i}. {r.get('carrier', '?')} ({r.get('mode', '?')}, "
            f"{r.get('source_site', '?')}): "
            f"base=${r.get('base_price_usd', 0):.2f}, "
            f"trust={r.get('trust_score', 0)}/100, "
            f"est.total=${r.get('estimated_total_usd', 0):.2f}, "
            f"transit={r.get('transit_days', 0)}d, "
            f"flags=[{flags_str}]"
        )
    return "\n".join(lines)


class _SummarizerRunnable(Runnable):
    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> dict:
        payload = inputs["input"] if "input" in inputs else inputs
        shipment = payload["shipment"]
        router_reason = payload.get("router_reason", "")
        ranked_rates = payload.get("ranked_rates", [])

        llm = get_llm(temperature=0.5)
        structured = llm.with_structured_output(SummarizerOutput)
        chain = _PROMPT | structured
        result: SummarizerOutput = chain.invoke({
            "shipment_json": json.dumps({
                k: shipment.get(k) for k in
                ("product", "chargeable_weight_kg", "origin", "destination")
            }),
            "router_reason": router_reason or "(not provided)",
            "rates_table": _format_rates_table(ranked_rates) or "(no rates)",
        })
        logger.info(
            "summarizer: %d chars recommendation", len(result.recommendation)
        )
        return {"recommendation": result.recommendation}


def build_summarizer_agent() -> Runnable:
    """Return the summarizer agent as a Runnable with .invoke() surface."""
    return _SummarizerRunnable()
```

- [ ] **Step 2: Manual verification — real LLM call with synthetic ranked list**

```bash
uv run python -c "
import logging
from agents.summarizer import build_summarizer_agent

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

agent = build_summarizer_agent()
out = agent.invoke({'input': {
    'shipment': {
        'product': 'electronics',
        'chargeable_weight_kg': 200.0,
        'origin': 'Delhi',
        'destination': 'Rotterdam',
    },
    'router_reason': 'Air freight recommended because chargeable weight is 200 kg.',
    'ranked_rates': [
        {'carrier': 'Lufthansa Cargo', 'mode': 'air_freight', 'source_site': 'freightos',
         'base_price_usd': 892.0, 'trust_score': 85, 'estimated_total_usd': 958.9,
         'transit_days': 7, 'flags': []},
        {'carrier': 'Emirates SkyCargo', 'mode': 'air_freight', 'source_site': 'freightos',
         'base_price_usd': 845.0, 'trust_score': 80, 'estimated_total_usd': 929.5,
         'transit_days': 8, 'flags': ['Peak season surcharge not itemised']},
        {'carrier': 'Qatar Airways Cargo', 'mode': 'air_freight', 'source_site': 'freightos',
         'base_price_usd': 910.0, 'trust_score': 55, 'estimated_total_usd': 1114.75,
         'transit_days': 6, 'flags': ['Fuel surcharge (FSC) not disclosed upfront']},
    ],
}})
assert 'recommendation' in out
rec = out['recommendation']
assert isinstance(rec, str) and len(rec) > 50, f'too short: {rec!r}'
print('summarizer OK:')
print(rec)
"
```
Expected: one real LLM call to Groq; prints a 3–4 sentence recommendation that mentions at least one of the three carriers and references the trust/flags. ~800 ms latency.

- [ ] **Step 3: Commit**

```bash
git add agents/summarizer.py
git commit -m "feat(summarizer): add plain-English recommendation agent (temp 0.5)"
```

---

## Task 10: Populate agents/__init__.py with re-exports

**Files:** Modify `agents/__init__.py`.

- [ ] **Step 1: Write re-exports**

Replace the empty `agents/__init__.py` with EXACTLY:

```python
from agents.hidden_charge import build_hidden_charge_agent
from agents.rate_comparator import build_rate_comparator_agent
from agents.router import build_router_agent
from agents.summarizer import build_summarizer_agent

__all__ = [
    "build_hidden_charge_agent",
    "build_rate_comparator_agent",
    "build_router_agent",
    "build_summarizer_agent",
]
```

- [ ] **Step 2: Verify imports**

```bash
uv run python -c "
from agents import (
    build_hidden_charge_agent,
    build_rate_comparator_agent,
    build_router_agent,
    build_summarizer_agent,
)
print('all four agents importable from `agents`')
"
```
Expected: prints `all four agents importable from agents`.

- [ ] **Step 3: Commit**

```bash
git add agents/__init__.py
git commit -m "feat(agents): re-export the four build_*_agent factories from package init"
```

---

## Task 11: Add _card_html field population to tools/scraper.py

**Files:** Modify `tools/scraper.py`.

- [ ] **Step 1: Edit parse_freightos**

Find in `tools/scraper.py`:
```python
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
```

Replace with:
```python
            rates.append({
                "carrier": carrier,
                "base_price_usd": price,
                "transit_days": transit,
                "booking_url": booking_url,
                "mode": mode,
                "_card_html": str(card),
            })
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.debug("freightos: skipped malformed card: %s", e)
    return rates


def parse_icontainers(html: str) -> list[dict]:
```

- [ ] **Step 2: Edit parse_icontainers**

Find:
```python
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
```

Replace with:
```python
            rates.append({
                "carrier": carrier,
                "base_price_usd": price,
                "transit_days": transit,
                "booking_url": booking_url,
                "mode": mode,
                "_card_html": str(row),
            })
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.debug("icontainers: skipped malformed row: %s", e)
    return rates


def parse_searates(html: str) -> list[dict]:
```

- [ ] **Step 3: Edit parse_searates**

Find:
```python
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
```

Replace with:
```python
            rates.append({
                "carrier": carrier,
                "base_price_usd": price,
                "transit_days": transit,
                "booking_url": booking_url,
                "mode": mode,
                "_card_html": str(article),
            })
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.debug("searates: skipped malformed article: %s", e)
    return rates
```

- [ ] **Step 4: Manual verification — _card_html is populated**

```bash
uv run python -c "
from tools.scraper import scrape_all, Query

rates = scrape_all(Query('Delhi', 'Rotterdam', 200.0))
assert len(rates) == 10
for r in rates:
    assert '_card_html' in r, f'missing _card_html: {r}'
    assert len(r['_card_html']) > 50, f'suspicious _card_html: {r[\"_card_html\"][:50]!r}'
print('scraper _card_html field OK (10 rates)')
print()
print('Sample Freightos card HTML (first 200 chars):')
print(next(r for r in rates if r['source_site'] == 'freightos')['_card_html'][:200])
"
```
Expected: prints `scraper _card_html field OK (10 rates)` and a short HTML excerpt.

- [ ] **Step 5: Commit**

```bash
git add tools/scraper.py
git commit -m "feat(scraper): pass raw card HTML via _card_html internal field for hidden-charge agent"
```

---

## Task 12: Implement pipeline.py

**Files:** Create `pipeline.py` at project root.

- [ ] **Step 1: Write pipeline.py**

Create `pipeline.py` with EXACTLY this content:

```python
"""End-to-end pipeline: ShipmentInput -> RecommendationResult.

Composes scraper + cache + all four agents into a linear flow:

  1. Router agent         -> {mode, reason}
  2. Cache check          -> list[ScrapedRate] or MISS
  3. Scraper (on miss)    -> list[ScrapedRate]; put_cache on success
  4. Hidden-charge agent  -> per rate: + {trust_score, flags, verified_site}
  5. Rate-comparator      -> + {estimated_total_usd}, sorted by est_total asc
  6. Summarizer agent     -> recommendation prose

Returns one RecommendationResult dict. Exceptions in any per-rate step
are caught and logged; the rate is dropped but the pipeline continues.
If the pipeline can produce zero ranked rates, returns a
RecommendationResult with rates=[] and a diagnostic recommendation
string -- never raises to the caller.
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
                    "origin": shipment_input["origin"],
                    "destination": shipment_input["destination"],
                }
            })
            scored = {**rate, **result}
            scored.pop("_card_html", None)
            partial_scored.append(scored)
        except Exception as e:
            logger.error(
                "hidden-charge failed on %s/%s: %s",
                rate.get("source_site"), rate.get("carrier"), e,
            )
            errors.append(
                f"hidden-charge failed on {rate.get('carrier')}: {e}"
            )

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
    try:
        summary = summarizer.invoke({"input": {
            "shipment": shipment_input,
            "router_reason": route["reason"],
            "ranked_rates": ranked[:3],
        }})
        recommendation = summary["recommendation"]
    except Exception as e:
        logger.error("summarizer failed: %s", e)
        errors.append(f"summarizer failed: {e}")
        recommendation = ""

    return {
        "mode": route["mode"],
        "router_reason": route["reason"],
        "rates": ranked,
        "recommendation": recommendation,
        "cache_hit": cache_hit,
        "sites_succeeded": sites_succeeded,
        "errors": errors,
    }
```

- [ ] **Step 2: Manual verification — full pipeline, 200kg shipment**

This is the main acceptance test. Makes ~12 real LLM calls (router + 10 hidden-charge + summarizer). Takes ~5-10 seconds.

```bash
uv run python -c "
import logging
from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

shipment = {
    'product': 'electronics',
    'gross_weight_kg': 180.0,
    'length_cm': 100.0,
    'width_cm': 100.0,
    'height_cm': 100.0,
    'volume_weight_kg': 200.0,
    'chargeable_weight_kg': 200.0,
    'weight_basis': 'volume',
    'origin': 'Delhi',
    'destination': 'Rotterdam',
    'urgency': 'standard',
}

result = run_pipeline(shipment)

print()
print('mode:', result['mode'])
print('router_reason:', result['router_reason'])
print('cache_hit:', result['cache_hit'])
print('sites_succeeded:', result['sites_succeeded'])
print('errors:', result['errors'])
print()
print(f'{len(result[\"rates\"])} ranked rates:')
for i, r in enumerate(result['rates'], 1):
    print(f'  {i}. {r[\"carrier\"]:22} {r[\"source_site\"]:12} '
          f'base=\${r[\"base_price_usd\"]:.2f} trust={r[\"trust_score\"]:3} '
          f'est=\${r[\"estimated_total_usd\"]:.2f} flags={len(r[\"flags\"])}')
print()
print('RECOMMENDATION:')
print(result['recommendation'])

# Assertions
assert result['mode'] == 'air_freight', f'expected air_freight for 200kg, got {result[\"mode\"]}'
assert result['cache_hit'] is False, 'first call should miss cache'
assert result['sites_succeeded'] == 3
assert len(result['rates']) >= 7, f'expected >=7 ranked rates (some may drop on LLM errors), got {len(result[\"rates\"])}'
assert result['recommendation'], 'expected non-empty recommendation'
# estimated_total_usd sorted ascending
totals = [r['estimated_total_usd'] for r in result['rates']]
assert totals == sorted(totals), 'rates not sorted by estimated_total_usd'
# No _card_html leaks
for r in result['rates']:
    assert '_card_html' not in r, f'_card_html leaked into output: {r}'
print()
print('pipeline 200kg PASS')
"
```

Expected: prints ranked rates (7-10 depending on per-rate LLM stability), mode=air_freight, and a non-empty recommendation. Takes ~5-10 seconds. Ends with `pipeline 200kg PASS`.

- [ ] **Step 3: Manual verification — second call hits cache**

Immediately after Step 2:

```bash
uv run python -c "
import logging
from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

result = run_pipeline({
    'product': 'electronics',
    'gross_weight_kg': 180.0,
    'length_cm': 100.0, 'width_cm': 100.0, 'height_cm': 100.0,
    'volume_weight_kg': 200.0,
    'chargeable_weight_kg': 200.0,
    'weight_basis': 'volume',
    'origin': 'Delhi',
    'destination': 'Rotterdam',
    'urgency': 'standard',
})
assert result['cache_hit'] is True, 'expected cache hit on second call'
print('cache_hit:', result['cache_hit'])
print('pipeline cache-hit PASS')
"
```
Expected: prints `cache_hit: True` followed by `pipeline cache-hit PASS`. Note: LLM calls still happen (router + hidden-charge + summarizer); only scraping is skipped.

- [ ] **Step 4: Cleanup the local cache DB**

```bash
rm -f knowledge_base/rate_cache.db
```

- [ ] **Step 5: Commit**

```bash
git add pipeline.py
git commit -m "feat(pipeline): add run_pipeline orchestrator composing scraper + cache + 4 agents"
```

---

## Task 13: Update .env.example + CLAUDE.md

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append USE_PAGEINDEX_RUNTIME flag to .env.example**

Read the current `.env.example`. After the existing `LOG_LEVEL=INFO` line, add:

```
# Phase 3: set to true to enable PageIndex runtime RAG for hidden-charge agent
USE_PAGEINDEX_RUNTIME=false
```

Final `.env.example` should end with:
```
# Feature flags
LIVE_SCRAPING=false
LOG_LEVEL=INFO
# Phase 3: set to true to enable PageIndex runtime RAG for hidden-charge agent
USE_PAGEINDEX_RUNTIME=false
```

- [ ] **Step 2: Update CLAUDE.md Current state section**

Find:
```markdown
## Current state (2026-04-18)
Phase 2 complete: `tools/scraper.py` normalises three hand-crafted HTML fixtures (freightos / icontainers / searates, Delhi→Rotterdam 200 kg) into 10 `ScrapedRate` dicts via three distinct parsers; `tools/cache.py` provides a SQLite rate cache with 6 h read-time TTL; scraper+cache compose cleanly (MISS → scrape → PUT → HIT round-trip verified). Phase 1 deliverables remain in place (`knowledge_base/ingest.py`, PageIndex MCP via `.mcp.json`). Phases 3–6 (agents, UI, tests, deploy) remain. Follow the **Build order** section.
```

Replace with:
```markdown
## Current state (2026-04-18)
Phase 3 complete: four LangChain `AgentExecutor`-wrapped agents (`agents/router.py`, `agents/hidden_charge.py`, `agents/rate_comparator.py`, `agents/summarizer.py`) composed by `pipeline.py` (`run_pipeline(ShipmentInput) -> RecommendationResult`). `tools/llm_router.py` exposes `get_llm()` backed by a LiteLLM Router with Groq → OpenAI → Gemini fallback. `tools/validator.py` + `knowledge_base/charge_patterns.json` handle booking-site + red-flag checks. `tools/pageindex_client.py` provides runtime-optional RAG (default off via `USE_PAGEINDEX_RUNTIME=false`). Router + rate_comparator are rule-based with AgentExecutor-shaped wrappers for A2A uniformity; hidden_charge + summarizer make real LLM calls. End-to-end verified: Delhi→Rotterdam 200kg returns 7-10 ranked rates with trust scores and a plain-English recommendation. Phase 2 + Phase 1 deliverables remain in place. Phases 4–6 (Streamlit UI, tests, deploy) remain.
```

- [ ] **Step 3: Update CLAUDE.md Phase 2 notes block**

Find:
```markdown
**Phase 2 notes:**
- `LIVE_SCRAPING=false` is both default and production in v1. `LIVE_SCRAPING=true` raises `NotImplementedError` from `tools.scraper.fetch_site`.
- Cache key is `(origin, destination, query_date)` per CLAUDE.md — known to be too coarse (ignores weight + mode); acceptable for single-route demo, tighten to `(origin, destination, date, mode, weight_bucket)` when multi-route support lands.
```

Replace with:
```markdown
**Phase 2 + 3 notes:**
- `LIVE_SCRAPING=false` is both default and production in v1. `LIVE_SCRAPING=true` raises `NotImplementedError` from `tools.scraper.fetch_site`.
- `USE_PAGEINDEX_RUNTIME=false` is the default; set to `true` to let the hidden-charge agent fetch surcharge-bulletin context from PageIndex's `/chat/completions` endpoint for each rate. `charge_patterns.json` is always the primary data source; PageIndex is additive context only.
- Cache key is `(origin, destination, query_date)` per CLAUDE.md — known to be too coarse (ignores weight + mode); acceptable for single-route demo, tighten to `(origin, destination, date, mode, weight_bucket)` when multi-route support lands.
- Pipeline makes ~12 LLM calls per request (1 router + N hidden-charge + 1 summarizer, where N = scraped rate count). Worst-case ~6 s serial latency. Phase 5 optimisations: parallelise or batch hidden-charge.
```

- [ ] **Step 4: Extend CLAUDE.md Phase 5 backlog section**

Find:
```markdown
**Phase 5 backlog (non-blocking, surfaced by reviewers):**
- `tools/cache.py`: `clear_cache` has a redundant `_connect().close()` line that leaks on a failing reconnect — drop it; table is recreated lazily on next call.
- `tools/cache.py`: error logs for unparseable `cached_at` / `rates_json` should include origin/destination in the `%s->%s` format used elsewhere.
- `tools/scraper.py`: `_parse_days_from_text` reuses `_PRICE_RE` but doesn't strip commas; `"2,000 days"` raises `ValueError` (silently drops the row via the per-parser except). Use a dedicated `r"\d+"` or strip commas.
- `tools/scraper.py`: `Query.origin` / `destination` / `mode` are unused in v1 (reserved for live mode) — document with a one-line note or defer trimming until live mode is wired.
```

Replace with:
```markdown
**Phase 5 backlog (non-blocking, surfaced by reviewers):**
- `tools/cache.py`: `clear_cache` has a redundant `_connect().close()` line that leaks on a failing reconnect — drop it; table is recreated lazily on next call.
- `tools/cache.py`: error logs for unparseable `cached_at` / `rates_json` should include origin/destination in the `%s->%s` format used elsewhere.
- `tools/scraper.py`: `_parse_days_from_text` reuses `_PRICE_RE` but doesn't strip commas; `"2,000 days"` raises `ValueError` (silently drops the row via the per-parser except). Use a dedicated `r"\d+"` or strip commas.
- `tools/scraper.py`: `Query.origin` / `destination` / `mode` are unused in v1 (reserved for live mode) — document with a one-line note or defer trimming until live mode is wired.
- `pipeline.py`: hidden-charge LLM calls are serial (~0.5s × N rates). Parallelise via `ThreadPoolExecutor` or batch all N cards into one LLM call for ~3× latency reduction.
- `agents/rate_comparator.py`: no LLM call; the `Runnable` wrapper is pure A2A ceremony. If A2A never ships, collapse to a plain function.
- `agents/summarizer.py`: output isn't streamed; Phase 4 Streamlit can add streaming if UX demands.
- `agents/summarizer.py`: optional `query_pageindex(incoterms_doc_id, ...)` call for Incoterms-aware advice — hook exists in design, not wired.
```

- [ ] **Step 5: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs(claude): Phase 3 complete -- update state, flag docs, backlog"
```

---

## Task 14: Push Phase 3 commits to GitHub

**Files:** none — push only.

- [ ] **Step 1: Verify clean working tree**

```bash
git status --short
```
Expected: empty (or only ignored files: `.venv/`, `rate_cache.db`, `.env`).

- [ ] **Step 2: Push**

```bash
git push origin main
```
Expected: lists 13-14 new objects; `main -> main` updated.

- [ ] **Step 3: Verify remote**

```bash
git log --oneline origin/main | head -15
```
Expected: matches local `git log --oneline | head -15` exactly.

No commit on this task.

---

## Self-review notes

Checked against spec 2026-04-18-phase3-agents-design.md before finalising:

**Spec coverage:**
- Spec §2 In scope (11 new + 3 modified files): every file has a task. pyproject deps (Task 1), llm_router (Task 2), charge_patterns.json + validator (Task 3), pageindex_client (Task 4), agents/__init__.py (Tasks 5 + 10), router (Task 6), hidden_charge (Task 7), rate_comparator (Task 8), summarizer (Task 9), scraper _card_html (Task 11), pipeline (Task 12), .env.example + CLAUDE.md (Task 13), push (Task 14).
- Spec §3 decisions D1–D13 all implemented: single plan (D1), AgentExecutor-shaped Runnables (D2), LiteLLM Router config (D3, Task 2), router rules + LLM reason (D4, Task 6), charge_patterns.json primary + PageIndex optional (D5, Tasks 3 + 4 + 7), validator short-circuit (D6, Task 7 Step 2), linear surcharge formula (D7, Task 8), pipeline.py at root (D8, Task 12), rate_comparator no LLM (D9, Task 8), Pydantic + with_structured_output (D10, Tasks 6/7/9), temperature 0.2/0.5 (D11, Tasks 6/7/9), `_card_html` internal field (D12, Tasks 11 + 12), pipeline never raises for data (D13, Task 12 Step 1 diagnostic-message return).
- Spec §4 llm_router architecture: Task 2 implements `_MODEL_LIST`, `get_llm`, `lru_cache`, Router config with explicit fallbacks cascade.
- Spec §5 validator + charge_patterns: Task 3.
- Spec §6 four agents: Tasks 6 (router), 7 (hidden_charge), 8 (rate_comparator), 9 (summarizer). All with Pydantic output schemas, correct prompts, correct temperatures.
- Spec §7 pageindex_client: Task 4 verbatim.
- Spec §8 pipeline.py: Task 12 implements composition + continue-on-error + diagnostic fallback for empty ranked list.
- Spec §9 error handling / latency: Task 12 implements continue-on-error per rate, diagnostic message on empty, try/except around summarizer.
- Spec §10 implementation sequence (15 steps) → Tasks 1-13 (plus push as Task 14).
- Spec §11 acceptance criteria (10 bullets): each is exercised in the verification steps across Tasks 2, 3, 4, 6, 7, 8, 9, 12.

**Placeholder scan:** no TBDs, TODOs, "fill in details", "similar to Task N", or vague error-handling directives. Every code block is complete and copy-pasteable. The only "if this fails, report BLOCKED" instructions are in Tasks 1 + 2 around the `langchain-litellm` dep, which is a legitimate external risk called out in the spec's §4 open-nit and §12 risks table.

**Type consistency:**
- `get_llm` signature: `get_llm(temperature: float = 0.2)` — called consistently with `temperature=0.2` (router, hidden_charge) and `temperature=0.5` (summarizer).
- `classify_mode`: `classify_mode(chargeable_weight_kg: float) -> str` — values `"courier" | "air_freight" | "sea_freight"`; hidden_charge uses the same literal values; rate_comparator doesn't touch mode.
- `RouterOutput`, `HiddenChargeOutput`, `SummarizerOutput` all Pydantic v2 `BaseModel` with field descriptions.
- `build_router_agent`, `build_hidden_charge_agent`, `build_rate_comparator_agent`, `build_summarizer_agent` — all return `Runnable`-compatible objects with `.invoke({"input": ...}) -> dict` shape. `agents/__init__.py` re-exports each by the same name.
- `compute_estimated_total(base, trust)` used in rate_comparator and matches the formula from spec D7.
- `RecommendationResult` TypedDict fields (`mode, router_reason, rates, recommendation, cache_hit, sites_succeeded, errors`) populated in every `return` branch of `run_pipeline` (confirmed in Task 12).
- `_card_html` field populated by Task 11 in all three parsers; consumed by Task 7 hidden_charge via `card_html` key in its input payload; stripped before return in Task 12 pipeline `scored.pop("_card_html", None)`.

No drift found. Plan ready for execution.

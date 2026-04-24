"""Shared fixtures for the Phase-5 test suite.

Key pieces:
- FakeChatModel: drop-in LangChain Runnable replacement for ChatLiteLLM,
  mapping Pydantic output Schema -> pre-built instance OR a callable that
  takes the formatted prompt value and returns a Pydantic instance (used
  by the batched hidden-charge agent, whose response length depends on
  the number of rate blocks in the prompt).
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

from typing import Any, Callable, Union

import pytest
from langchain_core.runnables import Runnable
from pydantic import BaseModel


# Each response may be a pre-built instance OR a callable that receives
# the prompt value passed to structured.invoke() and returns an instance.
FakeResponse = Union[BaseModel, Callable[[Any], BaseModel]]


# ---- FakeChatModel ----

class _FakeStructured(Runnable):
    """Returned by FakeChatModel.with_structured_output(Schema).
    .invoke(prompt_value) -> the pre-set Pydantic instance, or the result
    of calling the stub callable with the prompt value."""

    def __init__(self, response: FakeResponse):
        self._response = response

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseModel:
        if callable(self._response):
            return self._response(input)
        return self._response


class FakeChatModel(Runnable):
    """Drop-in replacement for ChatLiteLLM in agent tests.

    Agent calls:
        llm = get_llm(temperature=...)
        structured = llm.with_structured_output(Schema)
        chain = _PROMPT | structured
        result = chain.invoke(inputs)  # -> Schema instance
    """

    def __init__(self, structured_responses: dict[type[BaseModel], FakeResponse]):
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


def batch_hc_stub(trust_score: int = 85, flags: list[str] | None = None):
    """Build a callable stub that returns a BatchHiddenChargeOutput sized
    to match the number of '=== Rate ' blocks in the formatted prompt.

    Every non-flagged rate in a batch gets the same (trust_score, flags).
    Tests that need per-rate variation can construct their own callable.
    """
    from agents.hidden_charge import (
        BatchHiddenChargeOutput,
        HiddenChargeOutput,
    )

    _flags = list(flags) if flags is not None else []

    def _stub(prompt_value: Any) -> BatchHiddenChargeOutput:
        text = str(prompt_value)
        n = text.count("=== Rate ")
        return BatchHiddenChargeOutput(
            results=[
                HiddenChargeOutput(trust_score=trust_score, flags=list(_flags))
                for _ in range(max(n, 1))
            ],
        )

    return _stub


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

    The hidden_charge stub is batched (single call per run) and returns
    one HiddenChargeOutput per '=== Rate ' block in the formatted prompt.
    """
    from agents.router import RouterOutput
    from agents.hidden_charge import BatchHiddenChargeOutput
    from agents.summarizer import SummarizerOutput

    install_fake_llm("router", {
        RouterOutput: RouterOutput(
            reason="Stub reason — mode decided by deterministic rules."
        )
    })
    install_fake_llm("hidden_charge", {
        BatchHiddenChargeOutput: batch_hc_stub(trust_score=85, flags=[]),
    })
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(
            recommendation="Stub recommendation — book the top-ranked quote."
        )
    })

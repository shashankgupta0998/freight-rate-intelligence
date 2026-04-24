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
    BatchHiddenChargeOutput,
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
from tests.conftest import FakeChatModel, SHIPMENT_200KG, batch_hc_stub


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

def _batch_input(
    rates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a batched hidden-charge input. Defaults to a single Lufthansa rate."""
    if rates is None:
        rates = [{
            "carrier": "Lufthansa Cargo",
            "base_price_usd": 892.0,
            "booking_url": "https://ship.freightos.com/book/LH-1",
            "source_site": "freightos",
            "_card_html": "<li>...</li>",
        }]
    return {
        "input": {
            "rates": rates,
            "mode": "air_freight",
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

    out = build_hidden_charge_agent().invoke(_batch_input([{
        "carrier": "Scammy Freight",
        "base_price_usd": 100.0,
        "booking_url": "https://scammer.example.com/book/1",
        "source_site": "scammer",
    }]))
    assert out == [{
        "trust_score": 0,
        "flags": ["Site is flagged as deceptive"],
        "verified_site": False,
    }]


def test_hidden_charge_scores_well_itemised_card(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=85, flags=[])},
    )
    out = build_hidden_charge_agent().invoke(_batch_input())
    assert out == [{
        "trust_score": 85,
        "flags": [],
        "verified_site": True,
    }]


def test_hidden_charge_batch_scores_each_rate(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=75, flags=[])},
    )
    rates = [
        {
            "carrier": f"Carrier-{i}",
            "base_price_usd": 100.0 * (i + 1),
            "booking_url": f"https://ship.freightos.com/book/{i}",
            "source_site": "freightos",
            "_card_html": f"<li>rate-{i}</li>",
        }
        for i in range(4)
    ]
    out = build_hidden_charge_agent().invoke(_batch_input(rates))
    assert len(out) == 4
    for entry in out:
        assert entry == {"trust_score": 75, "flags": [], "verified_site": True}


def test_hidden_charge_batch_preserves_order_with_mixed_sites(install_fake_llm):
    """Flagged + non-flagged rates mixed -- output order must match input order."""
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
    )
    rates = [
        {
            "carrier": "Good-A",
            "booking_url": "https://ship.freightos.com/a",
            "source_site": "freightos",
            "_card_html": "<li>a</li>",
        },
        {
            "carrier": "Unknown-B",
            "booking_url": "https://random.example.net/b",
            "source_site": "random",
            "_card_html": "<li>b</li>",
        },
        {
            "carrier": "Good-C",
            "booking_url": "https://ship.freightos.com/c",
            "source_site": "freightos",
            "_card_html": "<li>c</li>",
        },
    ]
    out = build_hidden_charge_agent().invoke(_batch_input(rates))
    assert len(out) == 3
    assert out[0]["verified_site"] is True
    assert out[1]["verified_site"] is False
    assert out[2]["verified_site"] is True
    assert all(r["trust_score"] == 70 for r in out)


def test_hidden_charge_verified_false_for_unknown_domain(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=60, flags=[])},
    )
    out = build_hidden_charge_agent().invoke(_batch_input([{
        "carrier": "Mystery Air",
        "base_price_usd": 500.0,
        "booking_url": "https://random.example.net/x",
        "source_site": "random",
        "_card_html": "<li>...</li>",
    }]))
    assert out[0]["verified_site"] is False


def test_hidden_charge_rag_off_does_not_call_pageindex(
    install_fake_llm, monkeypatch
):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=80, flags=[])},
    )
    # Autouse fixture already sets USE_PAGEINDEX_RUNTIME=false.
    sentinel = {"called": False}

    def guard(*a, **k):
        sentinel["called"] = True
        return None

    monkeypatch.setattr("agents.hidden_charge.query_pageindex", guard)
    build_hidden_charge_agent().invoke(_batch_input())
    assert sentinel["called"] is False


def test_hidden_charge_rag_on_calls_pageindex_once_per_batch(
    install_fake_llm, monkeypatch
):
    """Even with N rates in a batch, PageIndex is queried exactly once."""
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
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

    rates = [
        {
            "carrier": f"C-{i}",
            "booking_url": f"https://ship.freightos.com/{i}",
            "source_site": "freightos",
            "_card_html": f"<li>{i}</li>",
        }
        for i in range(5)
    ]
    build_hidden_charge_agent().invoke(_batch_input(rates))
    assert len(calls) == 1
    assert calls[0][0] == "pi-test-id"


def test_hidden_charge_degrades_when_doc_id_missing(
    install_fake_llm, monkeypatch
):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    monkeypatch.setattr("agents.hidden_charge.doc_id_for", lambda fn: None)
    # Should NOT raise — agent proceeds without RAG context.
    out = build_hidden_charge_agent().invoke(_batch_input())
    assert out[0]["trust_score"] == 70


def test_hidden_charge_handles_missing_booking_url(install_fake_llm):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=60, flags=[])},
    )
    payload = _batch_input()
    del payload["input"]["rates"][0]["booking_url"]
    out = build_hidden_charge_agent().invoke(payload)
    assert out[0]["verified_site"] is False


def test_hidden_charge_empty_rates_returns_empty_list(install_fake_llm):
    # No LLM stub needed — empty input must short-circuit before LLM.
    install_fake_llm("hidden_charge", {})
    out = build_hidden_charge_agent().invoke({
        "input": {
            "rates": [],
            "mode": "air_freight",
            "origin": "Delhi",
            "destination": "Rotterdam",
        }
    })
    assert out == []


def test_hidden_charge_llm_failure_falls_back_to_defaults(monkeypatch):
    """If the batched LLM call raises, every non-flagged rate gets a
    neutral default score rather than the whole batch being dropped."""
    from langchain_core.runnables import Runnable

    class ExplodingStructured(Runnable):
        def invoke(self, input, config=None, **kwargs):
            raise RuntimeError("LLM outage")

    class ExplodingFake:
        def with_structured_output(self, schema):
            return ExplodingStructured()

    monkeypatch.setattr(
        "agents.hidden_charge.get_llm",
        lambda temperature=0.2: ExplodingFake(),
    )

    rates = [
        {
            "carrier": "A",
            "booking_url": "https://ship.freightos.com/a",
            "source_site": "freightos",
            "_card_html": "<li>a</li>",
        },
        {
            "carrier": "B",
            "booking_url": "https://ship.freightos.com/b",
            "source_site": "freightos",
            "_card_html": "<li>b</li>",
        },
    ]
    out = build_hidden_charge_agent().invoke(_batch_input(rates))
    assert len(out) == 2
    for entry in out:
        assert entry["trust_score"] == 50
        assert entry["flags"] == ["Automated scoring unavailable"]
        assert entry["verified_site"] is True


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

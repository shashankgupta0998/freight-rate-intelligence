"""RAG-specific tests — hidden-charge + PageIndex integration (mocked query_pageindex).

Post Phase-5.5 batching: PageIndex is queried at most ONCE per batch (not per rate),
since origin/destination/mode are batch-level inputs.
"""
from __future__ import annotations

from agents.hidden_charge import (
    BatchHiddenChargeOutput,
    build_hidden_charge_agent,
)
from tests.conftest import batch_hc_stub


def _rag_payload(n: int = 1) -> dict:
    """Build a batched hidden-charge input with `n` rates."""
    rates = [
        {
            "carrier": f"RAG-Carrier-{i}",
            "base_price_usd": 500.0 + i,
            "booking_url": f"https://freightos.com/x/{i}",
            "source_site": "freightos",
            "_card_html": f"<li>rag-test-card-{i}</li>",
        }
        for i in range(n)
    ]
    return {
        "input": {
            "rates": rates,
            "mode": "air_freight",
            "origin": "Delhi",
            "destination": "Rotterdam",
        }
    }


def test_rag_on_invokes_pageindex_with_mode_and_route(
    install_fake_llm, monkeypatch
):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
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
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=80, flags=[])},
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
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
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
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    monkeypatch.setattr("agents.hidden_charge.doc_id_for", lambda fn: None)
    # Even with flag on, missing registry entry must not raise.
    out = build_hidden_charge_agent().invoke(_rag_payload())
    assert out[0]["trust_score"] == 70


def test_rag_pageindex_failure_degrades(install_fake_llm, monkeypatch):
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
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
    assert out[0]["trust_score"] == 70


def test_rag_on_queried_only_once_per_batch(install_fake_llm, monkeypatch):
    """The PageIndex query is batch-level -- N rates yield 1 query, not N."""
    install_fake_llm(
        "hidden_charge",
        {BatchHiddenChargeOutput: batch_hc_stub(trust_score=70, flags=[])},
    )
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "true")
    call_count = {"n": 0}

    def spy(doc_id, question, timeout=10.0):
        call_count["n"] += 1
        return "surcharge info"

    monkeypatch.setattr("agents.hidden_charge.query_pageindex", spy)
    monkeypatch.setattr(
        "agents.hidden_charge.doc_id_for",
        lambda fn: "pi-test",
    )

    build_hidden_charge_agent().invoke(_rag_payload(n=10))
    assert call_count["n"] == 1

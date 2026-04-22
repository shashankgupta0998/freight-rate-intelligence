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

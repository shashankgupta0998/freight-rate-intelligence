"""Integration tests for pipeline.py — mocked LLMs + real scraper + isolated cache."""
from __future__ import annotations

from agents.hidden_charge import BatchHiddenChargeOutput
from agents.router import RouterOutput
from agents.summarizer import SummarizerOutput
from pipeline import run_pipeline
from tests.conftest import SHIPMENT_200KG, _install_all_fakes, batch_hc_stub


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
    # Post Phase-5.5 batching: a single "hidden_charge" marker, not per-rate.
    hc = [m for m in markers if m == "hidden_charge"]
    assert len(hc) == 1
    assert "ranking" in markers
    assert "writing_recommendation" in markers
    assert markers[-1] == "done"


def test_run_pipeline_batch_failure_captured(
    install_fake_llm, isolated_cache_db, monkeypatch
):
    """If the batched hidden-charge agent itself raises, pipeline captures
    the error and returns a diagnostic recommendation (no rates to rank)."""
    install_fake_llm("router", {RouterOutput: RouterOutput(reason="x")})
    install_fake_llm("summarizer", {
        SummarizerOutput: SummarizerOutput(recommendation="ok"),
    })

    class BrittleAgent:
        def invoke(self, payload):
            raise RuntimeError("brittle batch failure")

    monkeypatch.setattr(
        "pipeline.build_hidden_charge_agent",
        lambda: BrittleAgent(),
    )

    result = run_pipeline(SHIPMENT_200KG)
    assert result["rates"] == []
    assert len(result["errors"]) == 1
    assert "hidden-charge batch failed" in result["errors"][0]
    assert "No rate quotes available" in result["recommendation"]


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
        BatchHiddenChargeOutput: batch_hc_stub(trust_score=85, flags=[]),
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

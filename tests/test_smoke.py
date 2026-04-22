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

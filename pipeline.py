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

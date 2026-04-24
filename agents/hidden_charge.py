"""Hidden-charge agent — scores transparency for a BATCH of rates in a
single LLM call (was N calls per pipeline run before the Phase 5.5
batching refactor).

Input shape:
    {"input": {
        "rates": list[dict],     # full ScrapedRate dicts (with _card_html)
        "mode": str,
        "origin": str,
        "destination": str,
    }}

Output shape: list of dicts aligned 1:1 with input rates, each:
    {"trust_score": int, "flags": list[str], "verified_site": bool}

Flow:
  1. Per rate: short-circuit flagged sites (trust=0, no LLM cost).
  2. Gather shared RAG context (single PageIndex query per batch).
  3. Single LLM call scoring all non-flagged rates.
  4. Pad / align LLM results and attach verified_site per rate.

If the batched LLM call fails, every non-short-circuited rate receives
a neutral default (trust_score=50, flag="Automated scoring unavailable")
so the pipeline can still render rate cards.
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

_DEFAULT_UNAVAILABLE_FLAG = "Automated scoring unavailable"


class HiddenChargeOutput(BaseModel):
    """Per-rate transparency score — inner element of BatchHiddenChargeOutput."""

    trust_score: int = Field(
        ge=0, le=100,
        description="Transparency score 0-100. Higher = more surcharges itemised upfront.",
    )
    flags: list[str] = Field(
        description=(
            "Plain-English warnings drawn from the provided red-flag patterns "
            "that this quote exhibits. Empty list if none apply."
        ),
    )


class BatchHiddenChargeOutput(BaseModel):
    """Results for a batch of rates — one HiddenChargeOutput per input rate,
    in the same order as the input rates."""

    results: list[HiddenChargeOutput] = Field(
        description=(
            "One score per input rate, in the SAME ORDER as the input list. "
            "The list length MUST equal the number of input rate blocks."
        ),
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a freight auditing expert. You review freight quote HTML "
     "against known red-flag patterns and score transparency."),
    ("human",
     "Route: {origin} -> {destination}, mode={mode}\n\n"
     "Red-flag patterns to check for ({mode}):\n{red_flags}\n\n"
     "{rag_context}"
     "Score each of the following {n} rate cards for transparency. "
     "Return a list of results in the SAME ORDER as the input cards.\n\n"
     "{rate_blocks}\n\n"
     "For each card, return a trust_score (0-100) and the list of red-flag "
     "patterns (from the list above, verbatim) that this quote exhibits. "
     "A quote with all surcharges itemised should score 85-100; a quote "
     "with only a base price and no fee breakdown should score 30-50; a "
     "quote missing standard fees for its mode should score below 30."),
])


def _format_rate_block(index: int, rate: dict, card_html: str) -> str:
    return (
        f"=== Rate {index} ===\n"
        f"carrier: {rate.get('carrier', 'unknown')}\n"
        f"base_price_usd: ${rate.get('base_price_usd', 0)}\n"
        f"booking_url: {rate.get('booking_url', '(none)')}\n"
        f"rate card HTML:\n```\n{card_html or '(no HTML excerpt available)'}\n```"
    )


def _gather_rag_context(mode: str, origin: str, destination: str) -> str:
    """Return extra context from PageIndex, or empty string when disabled/failed.

    One PageIndex query per batch (not per rate) since origin/destination/mode
    are batch-level inputs.
    """
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


def _default_score() -> dict[str, Any]:
    return {"trust_score": 50, "flags": [_DEFAULT_UNAVAILABLE_FLAG]}


class _HiddenChargeRunnable(Runnable):
    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> list[dict]:
        payload = inputs["input"] if "input" in inputs else inputs
        rates: list[dict] = payload["rates"]
        mode: str = payload["mode"]
        origin: str = payload.get("origin", "unknown")
        destination: str = payload.get("destination", "unknown")

        if not rates:
            return []

        # Step 1: short-circuit flagged sites (no LLM cost).
        outputs: list[dict | None] = [None] * len(rates)
        to_score: list[tuple[int, dict]] = []
        for i, rate in enumerate(rates):
            booking_url = rate.get("booking_url", "")
            if is_flagged_site(booking_url):
                logger.info(
                    "hidden-charge: %s flagged-site short-circuit", booking_url
                )
                outputs[i] = {
                    "trust_score": 0,
                    "flags": ["Site is flagged as deceptive"],
                    "verified_site": False,
                }
            else:
                to_score.append((i, rate))

        # Step 2: one LLM call for all non-flagged rates (if any).
        llm_results: list[HiddenChargeOutput] = []
        llm_failed = False
        if to_score:
            red_flags = red_flags_for_mode(mode)
            rag_context = _gather_rag_context(mode, origin, destination)

            rate_blocks = "\n\n".join(
                _format_rate_block(
                    local_idx,
                    rate,
                    rate.get("_card_html", ""),
                )
                for local_idx, (_, rate) in enumerate(to_score)
            )

            llm = get_llm(temperature=0.2)
            structured = llm.with_structured_output(BatchHiddenChargeOutput)
            chain = _PROMPT | structured
            try:
                batch: BatchHiddenChargeOutput = chain.invoke({
                    "origin": origin,
                    "destination": destination,
                    "mode": mode,
                    "red_flags": "\n".join(f"- {f}" for f in red_flags),
                    "rag_context": rag_context,
                    "n": len(to_score),
                    "rate_blocks": rate_blocks,
                })
                llm_results = list(batch.results)
            except Exception as e:
                logger.error("hidden-charge batch LLM failed: %s", e)
                llm_failed = True

        # Step 3: align LLM results with to_score order; pad with defaults.
        for local_idx, (global_idx, rate) in enumerate(to_score):
            if local_idx < len(llm_results):
                r = llm_results[local_idx]
                score = {
                    "trust_score": int(r.trust_score),
                    "flags": list(r.flags),
                }
            else:
                if not llm_failed:
                    logger.warning(
                        "hidden-charge: no LLM result for rate %d (%s/%s), using default",
                        global_idx,
                        rate.get("source_site", "?"),
                        rate.get("carrier", "?"),
                    )
                score = _default_score()
            outputs[global_idx] = {
                **score,
                "verified_site": is_verified_site(rate.get("booking_url", "")),
            }

        results = [o for o in outputs if o is not None]
        logger.info(
            "hidden-charge batch: %d rates (flagged=%d, llm_scored=%d, defaulted=%d)",
            len(results),
            len(rates) - len(to_score),
            min(len(llm_results), len(to_score)),
            max(0, len(to_score) - len(llm_results)),
        )
        return results


def build_hidden_charge_agent() -> Runnable:
    """Return the batched hidden-charge agent as a Runnable with .invoke() surface."""
    return _HiddenChargeRunnable()

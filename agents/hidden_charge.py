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

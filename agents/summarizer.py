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

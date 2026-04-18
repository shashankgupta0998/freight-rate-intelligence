"""Router agent — classifies shipment mode from chargeable weight.

Mode is decided by deterministic thresholds (CLAUDE.md); LLM generates
only the user-facing reason text. Returned as a LangChain Runnable for
A2A uniformity (all four agents share the same .invoke() shape).

Note: LangChain 1.x removed AgentExecutor; Runnable is the equivalent
agent-object interface with a stable .invoke(input) -> output protocol.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from tools.llm_router import get_llm

logger = logging.getLogger("agent.router")


def classify_mode(chargeable_weight_kg: float) -> str:
    """Deterministic mode classification per CLAUDE.md thresholds."""
    if chargeable_weight_kg < 68:
        return "courier"
    if chargeable_weight_kg < 500:
        return "air_freight"
    return "sea_freight"


class RouterOutput(BaseModel):
    reason: str = Field(
        description=(
            "One-sentence user-facing explanation of why this freight mode "
            "was chosen for the shipment."
        )
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You advise small business owners on freight logistics. "
     "Be concise and plain-spoken."),
    ("human",
     "Shipment: product={product}, chargeable_weight={weight} kg, "
     "origin={origin}, destination={destination}.\n"
     "Mode already classified as '{mode}' based on weight thresholds "
     "(<68kg courier, <500kg air, >=500kg sea).\n"
     "Write ONE sentence explaining why this mode fits this shipment."),
])


class _RouterRunnable(Runnable):
    """Internal Runnable wrapping deterministic mode classification + LLM reason."""

    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> dict:
        shipment = inputs["input"] if "input" in inputs else inputs
        weight = float(shipment["chargeable_weight_kg"])
        mode = classify_mode(weight)
        llm = get_llm(temperature=0.2)
        structured = llm.with_structured_output(RouterOutput)
        chain = _PROMPT | structured
        result = chain.invoke({
            "product": shipment.get("product", "unknown"),
            "weight": weight,
            "origin": shipment.get("origin", "?"),
            "destination": shipment.get("destination", "?"),
            "mode": mode,
        })
        logger.info("router: %s (%s kg)", mode, weight)
        return {"mode": mode, "reason": result.reason}


def build_router_agent() -> Runnable:
    """Return a LangChain Runnable for the router agent.

    The Runnable exposes .invoke({"input": shipment_dict}) -> {"mode", "reason"}.
    This shape is consistent across all four Phase-3 agents (A2A-ready).
    """
    return _RouterRunnable()

"""Rate-comparator — adds estimated_total_usd and sorts by it ascending.

Deterministic; no LLM calls. Wrapped in a Runnable for A2A uniformity
with the other three agents.

Formula: estimated_total = base_price * (1 + (100 - trust_score)/100 * 0.5)
  trust 100 -> +0%, trust 50 -> +25%, trust 0 -> +50%
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import Runnable

logger = logging.getLogger("agent.rate_comparator")


def compute_estimated_total(base_price_usd: float, trust_score: int) -> float:
    """Apply linear surcharge factor derived from trust_score.

    Returns USD total rounded to 2 decimal places.
    """
    factor = (100 - max(0, min(100, trust_score))) / 100 * 0.5
    return round(base_price_usd * (1 + factor), 2)


class _RateComparatorRunnable(Runnable):
    def invoke(self, inputs: dict, config: Any = None, **kwargs) -> list[dict]:
        payload = inputs["input"] if "input" in inputs else inputs
        if not isinstance(payload, list):
            raise TypeError(
                f"rate_comparator expects a list of partial ScoredRate dicts, "
                f"got {type(payload).__name__}"
            )

        out: list[dict] = []
        for rate in payload:
            base = float(rate.get("base_price_usd", 0.0))
            trust = int(rate.get("trust_score", 0))
            total = compute_estimated_total(base, trust)
            out.append({**rate, "estimated_total_usd": total})

        out.sort(key=lambda r: r["estimated_total_usd"])
        logger.info("rate_comparator: ranked %d rates", len(out))
        return out


def build_rate_comparator_agent() -> Runnable:
    """Return the rate-comparator agent (no LLM; pure math + sort)."""
    return _RateComparatorRunnable()

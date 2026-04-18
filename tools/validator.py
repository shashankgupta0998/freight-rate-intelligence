"""Booking-site legitimacy checker.

Loads charge_patterns.json once at import time. Exposes three pure
functions for use by the hidden-charge agent. No LLM, no network.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("validator")

_PATTERNS_PATH = Path(__file__).parent.parent / "knowledge_base" / "charge_patterns.json"


@lru_cache(maxsize=1)
def _patterns() -> dict:
    """Load charge_patterns.json once; fail loud if missing or malformed."""
    text = _PATTERNS_PATH.read_text(encoding="utf-8")
    return json.loads(text)


def _domain(url: str) -> str:
    """Extract the hostname from a URL; returns '' for malformed input."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def is_verified_site(booking_url: str) -> bool:
    """True if the URL's domain (or parent domain) is in verified_sites."""
    host = _domain(booking_url)
    if not host:
        return False
    verified = _patterns().get("verified_sites", [])
    return any(host == v or host.endswith("." + v) for v in verified)


def is_flagged_site(booking_url: str) -> bool:
    """True if the URL's domain is in flagged_sites (trust_score auto-0)."""
    host = _domain(booking_url)
    if not host:
        return False
    flagged = _patterns().get("flagged_sites", [])
    return any(host == f or host.endswith("." + f) for f in flagged)


def red_flags_for_mode(mode: str) -> list[str]:
    """Return generic + mode-specific red-flag patterns for the LLM prompt."""
    p = _patterns()
    return list(p.get("red_flags", [])) + list(
        p.get("mode_specific_red_flags", {}).get(mode, [])
    )

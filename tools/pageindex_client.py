"""PageIndex runtime retrieval — used only when USE_PAGEINDEX_RUNTIME=true.

Wraps POST /chat/completions (OpenAI-compatible) scoped to a doc_id. The
hidden-charge agent calls query_pageindex(doc_id, question) to get a
surcharge-bulletin answer. Default is OFF — charge_patterns.json is the
always-on data source for hidden-charge scoring.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("pageindex_client")

PAGEINDEX_CHAT_URL = "https://api.pageindex.ai/chat/completions"
REGISTRY_PATH = Path(__file__).parent.parent / "knowledge_base" / "doc_registry.json"


def is_enabled() -> bool:
    return os.getenv("USE_PAGEINDEX_RUNTIME", "false").lower() == "true"


@lru_cache(maxsize=1)
def _registry() -> dict:
    """Load {filename: {doc_id, sha256}} — fail loud if missing."""
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def doc_id_for(filename: str) -> str | None:
    """Look up a PageIndex doc_id by local filename; None if not ingested."""
    entry = _registry().get(filename)
    return entry["doc_id"] if entry else None


def query_pageindex(doc_id: str, question: str, timeout: float = 10.0) -> str | None:
    """Ask PageIndex a natural-language question scoped to one document.

    Returns the assistant's answer as a string, or None on any failure
    (network, non-2xx, empty body). Caller must tolerate None and fall
    back to charge_patterns.json only.
    """
    api_key = os.getenv("PAGEINDEX_API_KEY")
    if not api_key:
        logger.warning("PAGEINDEX_API_KEY not set -- skipping runtime retrieval")
        return None
    try:
        response = requests.post(
            PAGEINDEX_CHAT_URL,
            headers={"api_key": api_key, "Content-Type": "application/json"},
            json={
                "messages": [{"role": "user", "content": question}],
                "doc_id": doc_id,
                "stream": False,
            },
            timeout=timeout,
        )
        if not response.ok:
            logger.warning(
                "PageIndex query failed: HTTP %d -- %s",
                response.status_code,
                response.text[:200],
            )
            return None
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logger.warning("PageIndex returned empty content: %s", body)
            return None
        return content.strip()
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("PageIndex query raised: %s", e)
        return None

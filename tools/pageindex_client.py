"""PageIndex runtime retrieval — returns ToolResult instead of bare str|None.

Used only when USE_PAGEINDEX_RUNTIME=true. Wraps POST /chat/completions
scoped to a doc_id.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

from tools.errors import ErrorCategory, ToolResult

load_dotenv()
logger = logging.getLogger("pageindex_client")

PAGEINDEX_CHAT_URL = "https://api.pageindex.ai/chat/completions"
REGISTRY_PATH = Path(__file__).parent.parent / "knowledge_base" / "doc_registry.json"


def is_enabled() -> bool:
    return os.getenv("USE_PAGEINDEX_RUNTIME", "false").lower() == "true"


@lru_cache(maxsize=1)
def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def doc_id_for(filename: str) -> str | None:
    entry = _registry().get(filename)
    return entry["doc_id"] if entry else None


def query_pageindex(doc_id: str, question: str, timeout: float = 10.0) -> ToolResult:
    api_key = os.getenv("PAGEINDEX_API_KEY")
    if not api_key:
        logger.warning("PAGEINDEX_API_KEY not set -- skipping runtime retrieval")
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.PERMISSION,
            detail="PAGEINDEX_API_KEY not set",
        )
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
                response.status_code, response.text[:200],
            )
            return ToolResult(
                status="error", is_error=True,
                error_category=ErrorCategory.TRANSIENT,
                is_retryable=True,
                detail=f"HTTP {response.status_code}",
            )
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            logger.warning("PageIndex returned empty content: %s", body)
            return ToolResult(
                status="error", is_error=True,
                error_category=ErrorCategory.BUSINESS,
                detail="empty content in response",
            )
        return ToolResult(status="ok", data=content.strip())
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("PageIndex query raised: %s", e)
        return ToolResult(
            status="error", is_error=True,
            error_category=ErrorCategory.TRANSIENT,
            is_retryable=True, detail=str(e),
        )

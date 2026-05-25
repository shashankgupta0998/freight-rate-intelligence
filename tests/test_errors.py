"""Unit tests for tools/errors.py — shared error contract."""
from __future__ import annotations

from tools.errors import ErrorCategory, PipelineError, ScraperResult, SiteResult, ToolResult


def test_tool_result_ok():
    r = ToolResult(status="ok", data=[1, 2, 3])
    assert r.is_error is False
    assert r.error_category is None
    assert r.data == [1, 2, 3]


def test_tool_result_error():
    r = ToolResult(
        status="error",
        is_error=True,
        error_category=ErrorCategory.TRANSIENT,
        is_retryable=True,
        detail="connection timeout",
    )
    assert r.is_error is True
    assert r.error_category == ErrorCategory.TRANSIENT
    assert r.is_retryable is True


def test_pipeline_error_model_dump():
    e = PipelineError(
        stage="scraper",
        error_category=ErrorCategory.TRANSIENT,
        is_retryable=True,
        detail="site down",
    )
    d = e.model_dump()
    assert d["stage"] == "scraper"
    assert d["error_category"] == "transient"
    assert d["is_retryable"] is True


def test_site_result_defaults():
    s = SiteResult(site="freightos")
    assert s.status == "ok"
    assert s.error_category is None
    assert s.rate_count == 0


def test_scraper_result_inherits_tool_result():
    r = ScraperResult(status="ok", data=[{"carrier": "X"}], site_results=[])
    assert isinstance(r, ToolResult)
    assert r.site_results == []


def test_error_category_values():
    assert ErrorCategory.TRANSIENT == "transient"
    assert ErrorCategory.VALIDATION == "validation"
    assert ErrorCategory.PERMISSION == "permission"
    assert ErrorCategory.BUSINESS == "business"

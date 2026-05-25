"""Shared error contract for all tools and the pipeline.

Every tool returns a ToolResult (or subclass) instead of bare values/None.
The pipeline collects PipelineError dicts for structured error reporting.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"
    VALIDATION = "validation"
    PERMISSION = "permission"
    BUSINESS = "business"


class ToolResult(BaseModel):
    status: str
    data: Any = None
    is_error: bool = False
    error_category: ErrorCategory | None = None
    is_retryable: bool = False
    detail: str = ""


class SiteResult(BaseModel):
    site: str
    status: str = "ok"
    error_category: ErrorCategory | None = None
    is_retryable: bool = False
    detail: str = ""
    rate_count: int = 0


class ScraperResult(ToolResult):
    site_results: list[SiteResult] = []


class PipelineError(BaseModel):
    stage: str
    error_category: ErrorCategory
    is_retryable: bool
    detail: str

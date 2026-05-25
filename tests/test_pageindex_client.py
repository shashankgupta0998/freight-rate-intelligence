"""Unit tests for tools/pageindex_client.py with fully mocked requests.post."""
from __future__ import annotations

import requests

from tools.errors import ErrorCategory


def test_is_enabled_default_false(monkeypatch):
    monkeypatch.delenv("USE_PAGEINDEX_RUNTIME", raising=False)
    from tools.pageindex_client import is_enabled
    assert is_enabled() is False


def test_is_enabled_case_insensitive_true(monkeypatch):
    monkeypatch.setenv("USE_PAGEINDEX_RUNTIME", "TRUE")
    from tools.pageindex_client import is_enabled
    assert is_enabled() is True


def test_doc_id_for_known_and_unknown_filenames(monkeypatch):
    from tools import pageindex_client

    fake_registry = {
        "surcharge_bulletin.pdf": {"doc_id": "pi-known", "sha256": "abc"},
    }
    monkeypatch.setattr(pageindex_client, "_registry", lambda: fake_registry)
    assert pageindex_client.doc_id_for("surcharge_bulletin.pdf") == "pi-known"
    assert pageindex_client.doc_id_for("missing.pdf") is None


def test_query_pageindex_success(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": "fuel surcharge 18-32%"}}]}

    monkeypatch.setattr(pageindex_client.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key-abc")
    result = pageindex_client.query_pageindex("pi-any", "What are surcharges?")
    assert result.status == "ok"
    assert result.data == "fuel surcharge 18-32%"


def test_query_pageindex_missing_api_key(monkeypatch):
    monkeypatch.delenv("PAGEINDEX_API_KEY", raising=False)
    from tools.pageindex_client import query_pageindex
    result = query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.PERMISSION


def test_query_pageindex_non_2xx(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = False
        status_code = 500
        text = "internal error"

    monkeypatch.setattr(pageindex_client.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    result = pageindex_client.query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.TRANSIENT
    assert result.is_retryable is True


def test_query_pageindex_network_error(monkeypatch):
    from tools import pageindex_client

    def boom(*args, **kwargs):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(pageindex_client.requests, "post", boom)
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    result = pageindex_client.query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.TRANSIENT


def test_query_pageindex_malformed_body(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = "{}"
        def json(self):
            return {}

    monkeypatch.setattr(pageindex_client.requests, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    result = pageindex_client.query_pageindex("pi-any", "Q?")
    assert result.status == "error"
    assert result.error_category == ErrorCategory.BUSINESS

"""Unit tests for tools/pageindex_client.py with fully mocked requests.post."""
from __future__ import annotations

import requests


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
            return {
                "choices": [{"message": {"content": "fuel surcharge 18-32%"}}]
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr(pageindex_client.requests, "post", fake_post)
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key-abc")
    result = pageindex_client.query_pageindex("pi-any", "What are surcharges?")
    assert result == "fuel surcharge 18-32%"


def test_query_pageindex_missing_api_key(monkeypatch):
    monkeypatch.delenv("PAGEINDEX_API_KEY", raising=False)
    from tools.pageindex_client import query_pageindex
    assert query_pageindex("pi-any", "Q?") is None


def test_query_pageindex_non_2xx_returns_none(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = False
        status_code = 500
        text = "internal error"

    monkeypatch.setattr(
        pageindex_client.requests,
        "post",
        lambda *a, **k: FakeResponse(),
    )
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    assert pageindex_client.query_pageindex("pi-any", "Q?") is None


def test_query_pageindex_network_error_returns_none(monkeypatch):
    from tools import pageindex_client

    def boom(*args, **kwargs):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(pageindex_client.requests, "post", boom)
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    assert pageindex_client.query_pageindex("pi-any", "Q?") is None


def test_query_pageindex_malformed_body_returns_none(monkeypatch):
    from tools import pageindex_client

    class FakeResponse:
        ok = True
        status_code = 200
        text = "{}"
        def json(self):
            return {}  # no "choices" key

    monkeypatch.setattr(
        pageindex_client.requests,
        "post",
        lambda *a, **k: FakeResponse(),
    )
    monkeypatch.setenv("PAGEINDEX_API_KEY", "test-key")
    assert pageindex_client.query_pageindex("pi-any", "Q?") is None

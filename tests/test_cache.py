"""Unit tests for tools/cache.py — SQLite cache with 6h TTL, returns ToolResult."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from tools.cache import TTL_SECONDS, clear_cache, get_cached, put_cache
from tools.errors import ErrorCategory


def test_put_then_get_roundtrip(isolated_cache_db):
    put_cache("Delhi", "Rotterdam", date.today(), [{"carrier": "X"}])
    result = get_cached("Delhi", "Rotterdam", date.today())
    assert result.status == "hit"
    assert result.data == [{"carrier": "X"}]
    assert result.is_error is False


def test_get_cached_miss(isolated_cache_db):
    result = get_cached("Tokyo", "Paris", date.today())
    assert result.status == "miss"
    assert result.data is None
    assert result.is_error is False


def test_get_cached_expires_after_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    seven_h_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (seven_h_ago,))
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "expired"
    assert result.data is None


def test_get_cached_fresh_within_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    fresh = (datetime.now(timezone.utc) - timedelta(hours=5, minutes=59)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (fresh,))
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "hit"
    assert result.data == [{"v": 1}]


def test_get_cached_corrupt_json(isolated_cache_db, caplog):
    put_cache("A", "B", date.today(), [{"v": 1}])
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET rates_json = 'not{valid-json'")
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "error"
    assert result.is_error is True
    assert result.error_category == ErrorCategory.VALIDATION


def test_get_cached_unparseable_cached_at(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = 'definitely-not-a-datetime'")
    conn.commit()
    conn.close()
    result = get_cached("A", "B", date.today())
    assert result.status == "error"
    assert result.error_category == ErrorCategory.VALIDATION


def test_put_cache_upsert_overwrites(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    put_cache("A", "B", date.today(), [{"v": 2}])
    result = get_cached("A", "B", date.today())
    assert result.data == [{"v": 2}]


def test_clear_cache_drops_rows(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    clear_cache()
    result = get_cached("A", "B", date.today())
    assert result.status == "miss"


def test_cache_db_path_env_override(tmp_path, monkeypatch):
    alt = tmp_path / "alt.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(alt))
    put_cache("A", "B", date.today(), [{"v": 1}])
    assert alt.exists()


def test_connect_creates_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "c.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(nested))
    put_cache("X", "Y", date.today(), [])
    assert nested.exists()

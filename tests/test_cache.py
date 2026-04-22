"""Unit tests for tools/cache.py — SQLite cache with 6h TTL."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from tools.cache import (
    TTL_SECONDS,
    _db_path,
    clear_cache,
    get_cached,
    put_cache,
)


def test_put_then_get_roundtrip(isolated_cache_db):
    put_cache("Delhi", "Rotterdam", date.today(), [{"carrier": "X"}])
    assert get_cached("Delhi", "Rotterdam", date.today()) == [{"carrier": "X"}]


def test_get_cached_miss_returns_none(isolated_cache_db):
    assert get_cached("Tokyo", "Paris", date.today()) is None


def test_get_cached_expires_after_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    # Age the cached_at by 7 hours (> 6h TTL)
    seven_h_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (seven_h_ago,))
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) is None


def test_get_cached_fresh_within_ttl(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    # Age by 5h59m (< 6h TTL)
    fresh = (datetime.now(timezone.utc) - timedelta(hours=5, minutes=59)).isoformat()
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = ?", (fresh,))
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) == [{"v": 1}]


def test_get_cached_corrupt_json_returns_none(isolated_cache_db, caplog):
    put_cache("A", "B", date.today(), [{"v": 1}])
    # Corrupt the rates_json column directly
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET rates_json = 'not{valid-json'")
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) is None


def test_get_cached_unparseable_cached_at_returns_none(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    conn = sqlite3.connect(isolated_cache_db)
    conn.execute("UPDATE rate_cache SET cached_at = 'definitely-not-a-datetime'")
    conn.commit()
    conn.close()
    assert get_cached("A", "B", date.today()) is None


def test_put_cache_upsert_overwrites(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    put_cache("A", "B", date.today(), [{"v": 2}])
    assert get_cached("A", "B", date.today()) == [{"v": 2}]


def test_clear_cache_drops_rows(isolated_cache_db):
    put_cache("A", "B", date.today(), [{"v": 1}])
    clear_cache()
    assert get_cached("A", "B", date.today()) is None


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

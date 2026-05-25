"""SQLite-backed rate cache with 6h TTL, returning structured ToolResult.

Key: (origin, destination, query_date). Value: JSON-serialised list[ScrapedRate].
Expiry is read-time (no background eviction). Upsert semantics on writes.

Override the DB path with the CACHE_DB_PATH env var (default:
knowledge_base/rate_cache.db — covered by the existing *.db gitignore rule).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from tools.errors import ErrorCategory, ToolResult

logger = logging.getLogger("cache")

TTL_SECONDS = 6 * 60 * 60  # 6h per CLAUDE.md


def _db_path() -> Path:
    """Resolve the cache DB path from env or fall back to the default."""
    env_path = os.getenv("CACHE_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path("knowledge_base/rate_cache.db")


def _connect() -> sqlite3.Connection:
    """Open a connection, ensuring the parent dir and table both exist."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_cache (
            origin       TEXT NOT NULL,
            destination  TEXT NOT NULL,
            query_date   TEXT NOT NULL,
            rates_json   TEXT NOT NULL,
            cached_at    TEXT NOT NULL,
            PRIMARY KEY (origin, destination, query_date)
        )
        """
    )
    conn.commit()
    return conn


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_cached(origin: str, destination: str, query_date: date) -> ToolResult:
    """Return a ToolResult describing the cache lookup outcome.

    Status values:
      - "hit"     : row found, TTL valid, rates parsed successfully
      - "miss"    : no matching row
      - "expired" : row found but age > TTL_SECONDS
      - "error"   : DB connection failure or unparseable data
    """
    key = (origin, destination, query_date.isoformat())
    try:
        conn = _connect()
    except sqlite3.DatabaseError as e:
        logger.error("DB connect failed for %s->%s: %s", origin, destination, e)
        return ToolResult(
            status="error",
            is_error=True,
            error_category=ErrorCategory.TRANSIENT,
            is_retryable=True,
            detail=str(e),
        )
    try:
        row = conn.execute(
            "SELECT rates_json, cached_at FROM rate_cache "
            "WHERE origin = ? AND destination = ? AND query_date = ?",
            key,
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        logger.info("MISS %s->%s %s (not cached)", origin, destination, key[2])
        return ToolResult(status="miss")

    rates_json, cached_at_str = row
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
    except ValueError:
        logger.error(
            "cached_at unparseable for %s->%s: %r -- treating as error",
            origin,
            destination,
            cached_at_str,
        )
        return ToolResult(
            status="error",
            is_error=True,
            error_category=ErrorCategory.VALIDATION,
            detail=f"unparseable cached_at: {cached_at_str!r}",
        )

    age = _now_utc() - cached_at
    if age.total_seconds() > TTL_SECONDS:
        logger.info(
            "EXPIRED %s->%s %s (aged %s)", origin, destination, key[2], age
        )
        return ToolResult(status="expired")

    try:
        rates = json.loads(rates_json)
    except json.JSONDecodeError as e:
        logger.error(
            "rates_json unparseable for %s->%s: %s -- treating as error",
            origin,
            destination,
            e,
        )
        return ToolResult(
            status="error",
            is_error=True,
            error_category=ErrorCategory.VALIDATION,
            detail=f"unparseable rates_json: {e}",
        )

    logger.info("HIT %s->%s %s (aged %s)", origin, destination, key[2], age)
    return ToolResult(status="hit", data=rates)


def put_cache(
    origin: str, destination: str, query_date: date, rates: list[dict]
) -> None:
    """Upsert the rates list for the given key."""
    key = (origin, destination, query_date.isoformat())
    rates_json = json.dumps(rates, sort_keys=True)
    cached_at = _now_utc().isoformat()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO rate_cache "
            "(origin, destination, query_date, rates_json, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (*key, rates_json, cached_at),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info(
        "PUT %s->%s %s (%d rates)", origin, destination, key[2], len(rates)
    )


def clear_cache() -> None:
    """Drop and recreate the rate_cache table. For dev + tests."""
    conn = _connect()
    try:
        conn.execute("DROP TABLE IF EXISTS rate_cache")
        conn.commit()
    finally:
        conn.close()
    # Re-create the table via a fresh connection (avoids leaking on reconnect failure)
    conn2 = _connect()
    conn2.close()
    logger.info("CLEAR rate_cache dropped and recreated")

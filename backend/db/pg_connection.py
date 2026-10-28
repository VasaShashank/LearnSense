"""
PostgreSQL connection pool management for LearnSense institutional persistence.

This module owns the async connection pool created from DATABASE_URL.  Every
institutional repository should import ``get_pg_pool`` to acquire a connection.
The pool is created lazily on first use so that unit tests that never call
``get_pg_pool`` do not require a real database.

Environment variables
---------------------
DATABASE_URL (required for PostgreSQL operations)
    Full libpq-compatible connection string, e.g.
    ``postgresql://user:password@host:5432/dbname``
    When running against Supabase, use the connection pooler (port 6543) for
    transaction-mode pooling, or the direct connection (port 5432) for
    session-mode access.

PG_MIN_SIZE / PG_MAX_SIZE (optional)
    Pool size bounds.  Defaults to 1 / 5.

PG_SSLMODE (optional)
    SSL mode passed to asyncpg. Defaults to "require" for managed PostgreSQL;
    set to "disable" only for a trusted local database without TLS.
"""

from __future__ import annotations

import logging
import os
import asyncio
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit
from typing import Optional

logger = logging.getLogger(__name__)

# Attempt to import asyncpg; if not installed the pool is never created, and
# callers will receive a RuntimeError with a clear message.
try:
    import asyncpg  # type: ignore
    _asyncpg_available = True
except ImportError:
    asyncpg = None  # type: ignore
    _asyncpg_available = False

_pool: Optional["asyncpg.Pool"] = None  # type: ignore[name-defined]
_pool_lock: Optional[asyncio.Lock] = None


def _normalize_database_url(database_url: str) -> str:
    """Percent-encode URI user-info before handing the DSN to asyncpg.

    asyncpg currently splits the authority on the first ``@``. A literal ``@``
    in a password therefore corrupts its host parsing; normalize user-info so
    reserved credentials are unambiguous. Already-escaped values are decoded
    and re-escaped once, preserving their actual credential bytes.
    """
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use the postgres or postgresql scheme")

    user_info, separator, host_spec = parsed.netloc.rpartition("@")
    if not separator:
        return database_url

    username, colon, password = user_info.partition(":")
    normalized_user = quote(unquote(username), safe="")
    normalized_info = normalized_user
    if colon:
        normalized_info += ":" + quote(unquote(password), safe="")

    return urlunsplit((
        parsed.scheme,
        f"{normalized_info}@{host_spec}",
        parsed.path,
        parsed.query,
        parsed.fragment,
    ))


async def get_pg_pool() -> "asyncpg.Pool":  # type: ignore[name-defined]
    """Return the shared asyncpg connection pool, creating it on first call.

    Raises
    ------
    RuntimeError
        If asyncpg is not installed, or if DATABASE_URL is not configured.
    """
    global _pool, _pool_lock
    if _pool is not None:
        return _pool

    if not _asyncpg_available:
        raise RuntimeError(
            "asyncpg is not installed. "
            "Run: pip install asyncpg  (or add it to requirements.txt)"
        )

    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    async with _pool_lock:
        if _pool is not None:
            return _pool

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Configure it in .env (see .env.example) before using PostgreSQL persistence."
            )

        min_size = int(os.getenv("PG_MIN_SIZE", "1"))
        max_size = int(os.getenv("PG_MAX_SIZE", "5"))

        logger.info(
            "Creating PostgreSQL connection pool (min=%d, max=%d)", min_size, max_size
        )
        database_url = _normalize_database_url(database_url)
        uri_ssl_mode = parse_qs(urlsplit(database_url).query).get("sslmode", [None])[-1]
        ssl_mode = os.getenv("PG_SSLMODE", "").strip() or uri_ssl_mode or "require"
        _pool = await asyncpg.create_pool(
            dsn=database_url,
            ssl=ssl_mode,
            min_size=min_size,
            max_size=max_size,
            command_timeout=10,
        )
        return _pool


async def close_pg_pool() -> None:
    """Gracefully close the shared pool (call on application shutdown)."""
    global _pool, _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None
            logger.info("PostgreSQL connection pool closed.")


def reset_pool_for_testing() -> None:
    """Reset the pool singleton. Only call from test fixtures."""
    global _pool
    _pool = None


def is_pg_configured() -> bool:
    """Return True when DATABASE_URL is non-empty.

    Use this to decide at service startup whether PostgreSQL is available
    without attempting an actual connection.
    """
    return bool(os.getenv("DATABASE_URL", "").strip())

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
    Against Supabase, use the direct connection
    (``db.<project-ref>.supabase.co:5432``) or the session pooler
    (``<region>.pooler.supabase.com:5432``). The transaction pooler (port 6543,
    or any DSN with ``pgbouncer=true``) is refused: asyncpg caches prepared
    statements per connection, which transaction pooling does not support.

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

SUPABASE_TRANSACTION_POOLER_PORT = 6543
DIRECT_OR_SESSION_HINT = (
    "Use a direct connection (db.<project-ref>.supabase.co:5432) or the Supabase "
    "session pooler (<region>.pooler.supabase.com:5432)."
)


class UnsupportedConnectionError(RuntimeError):
    """DATABASE_URL points at a connection type LearnSense does not support."""


def transaction_pooler_reason(dsn: str) -> Optional[str]:
    """Why ``dsn`` is (or may be) a transaction-mode pooler, or None.

    Detects Supabase's transaction pooler port and an explicit ``pgbouncer=true``.
    A transaction pooler on another port cannot be recognised from the DSN.
    The returned text never contains credentials or the DSN.
    """
    parts = urlsplit(dsn)
    try:
        port = parts.port or 5432
    except ValueError:
        return None  # reported by dsn_port_problem
    if port == SUPABASE_TRANSACTION_POOLER_PORT:
        return f"port {SUPABASE_TRANSACTION_POOLER_PORT} is Supabase's transaction pooler"
    query = {k.lower(): [v.lower() for v in vs] for k, vs in parse_qs(parts.query).items()}
    if any(v in ("true", "1", "yes") for v in query.get("pgbouncer", [])):
        return "the DSN declares a PgBouncer pooler (pgbouncer=true)"
    return None


def dsn_port_problem(dsn: str) -> Optional[str]:
    """Credential-free message when the DSN port cannot be parsed, or None."""
    try:
        urlsplit(dsn).port
    except ValueError:
        return "DATABASE_URL is not usable: its port is not a valid number."
    return None


def api_connection_problem(dsn: str) -> Optional[str]:
    """Credential-free reason the API must not use ``dsn``, or None."""
    port_problem = dsn_port_problem(dsn)
    if port_problem:
        return port_problem
    reason = transaction_pooler_reason(dsn)
    if reason is None:
        return None
    return (
        f"DATABASE_URL is not supported: {reason}. The API's asyncpg pool caches "
        "prepared statements per connection, which transaction pooling breaks. "
        + DIRECT_OR_SESSION_HINT
    )


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
    UnsupportedConnectionError
        If DATABASE_URL is a transaction pooler (checked before connecting).
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
        problem = api_connection_problem(database_url)
        if problem:
            raise UnsupportedConnectionError(problem)

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

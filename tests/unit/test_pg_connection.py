"""Unit coverage for URI normalization and fail-closed PostgreSQL startup."""

from __future__ import annotations

import asyncio
from urllib.parse import quote, unquote, urlsplit

import pytest

from backend.db import pg_connection


def test_normalize_database_url_repairs_literal_at_in_password():
    dsn = "postgresql://db-user:part@part@db.example.test:5432/postgres"

    normalized = pg_connection._normalize_database_url(dsn)
    parsed = urlsplit(normalized)

    assert parsed.hostname == "db.example.test"
    assert unquote(parsed.password) == "part@part"
    assert parsed.port == 5432


def test_normalize_database_url_round_trips_url_reserved_password_characters():
    password = "p@:/?#[]!$&'()*+,;=%"
    encoded_password = quote(password, safe="")
    dsn = f"postgresql://db-user:{encoded_password}@db.example.test:5432/postgres"

    normalized = pg_connection._normalize_database_url(dsn)
    parsed = urlsplit(normalized)

    assert unquote(parsed.password) == password
    assert parsed.hostname == "db.example.test"


def test_pool_uses_normalized_dsn_and_requires_ssl_by_default(monkeypatch):
    calls = []
    pool = object()

    class FakeAsyncpg:
        @staticmethod
        async def create_pool(**kwargs):
            calls.append(kwargs)
            return pool

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://db-user:part@part@db.example.test:5432/postgres",
    )
    monkeypatch.delenv("PG_SSLMODE", raising=False)
    monkeypatch.setattr(pg_connection, "_pool", None)
    monkeypatch.setattr(pg_connection, "_pool_lock", None)
    monkeypatch.setattr(pg_connection, "_asyncpg_available", True)
    monkeypatch.setattr(pg_connection, "asyncpg", FakeAsyncpg)

    result = asyncio.run(pg_connection.get_pg_pool())

    assert result is pool
    assert len(calls) == 1
    assert calls[0]["ssl"] == "require"
    assert unquote(urlsplit(calls[0]["dsn"]).password) == "part@part"
    assert urlsplit(calls[0]["dsn"]).hostname == "db.example.test"


def test_pool_honors_uri_sslmode(monkeypatch):
    calls = []

    class FakeAsyncpg:
        @staticmethod
        async def create_pool(**kwargs):
            calls.append(kwargs)
            return object()

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://db-user:secret@db.example.test:5432/postgres?sslmode=verify-full",
    )
    monkeypatch.delenv("PG_SSLMODE", raising=False)
    monkeypatch.setattr(pg_connection, "_pool", None)
    monkeypatch.setattr(pg_connection, "_pool_lock", None)
    monkeypatch.setattr(pg_connection, "_asyncpg_available", True)
    monkeypatch.setattr(pg_connection, "asyncpg", FakeAsyncpg)

    asyncio.run(pg_connection.get_pg_pool())

    assert calls[0]["ssl"] == "verify-full"


def test_required_pg_startup_fails_when_database_url_is_missing(monkeypatch):
    from backend.app import on_startup

    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is not configured"):
        asyncio.run(on_startup())


def test_required_pg_startup_propagates_pool_initialization_failure(monkeypatch, tmp_path):
    from backend.app import on_startup
    from backend.db import pg_connection as pg
    from backend.services import institution_service

    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db-user:secret@db.example.test:5432/postgres")

    async def fail_pool():
        raise OSError("simulated PostgreSQL initialization failure")

    async def await_on_test_loop(coro):
        return await coro

    monkeypatch.setattr(pg, "get_pg_pool", fail_pool)
    monkeypatch.setattr(institution_service, "_await_background", await_on_test_loop)
    service = institution_service.InstitutionService(base_dir=str(tmp_path / "institutions"))
    assert service._pg_enabled is True

    with pytest.raises(OSError, match="simulated PostgreSQL initialization failure"):
        asyncio.run(on_startup())

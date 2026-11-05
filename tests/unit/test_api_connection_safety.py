"""H1: the API refuses Supabase transaction-pooler connections.

No database is contacted: the asyncpg pool factory is replaced by a recorder (or by a
tripwire that fails the test if it is reached).
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

import backend.app as appmod
from backend.db import migrations as mig
from backend.db import pg_connection as pg
from backend.services import institution_service

SECRET = "s3cr3t-pass"

REFUSED = [
    f"postgresql://postgres.ref:{SECRET}@aws-0-eu-west-1.pooler.supabase.com:6543/postgres",
    f"postgresql://u:{SECRET}@127.0.0.1:6543/app",
    f"postgresql://u:{SECRET}@db.example.test:5432/app?pgbouncer=true",
    f"postgres://u:{SECRET}@db.example.test/app?PGBOUNCER=True",
    f"postgresql://u:{SECRET}@db.example.test:7000/app?sslmode=require&pgbouncer=1",
]
ACCEPTED = [
    f"postgresql://postgres:{SECRET}@db.abcdefgh.supabase.co:5432/postgres",            # direct
    f"postgresql://postgres.ref:{SECRET}@aws-0-eu-west-1.pooler.supabase.com:5432/postgres",  # session pooler
    f"postgresql://u:{SECRET}@localhost/app",                                           # default port
    f"postgresql://u:{SECRET}@127.0.0.1:55432/app?sslmode=disable",                     # local/CI
    f"postgresql://u:{SECRET}@db.example.test:5432/app?pgbouncer=false",
]


@pytest.mark.parametrize("dsn", REFUSED)
def test_transaction_pooler_dsns_are_refused_without_credentials(dsn):
    problem = pg.api_connection_problem(dsn)
    assert problem and problem.startswith("DATABASE_URL is not supported")
    assert "5432" in problem and "session pooler" in problem
    assert SECRET not in problem and "@" not in problem.split("(")[0]


@pytest.mark.parametrize("dsn", ACCEPTED)
def test_direct_and_session_connections_are_accepted(dsn):
    assert pg.api_connection_problem(dsn) is None
    assert mig.migration_connection_problem(dsn) is None


@pytest.mark.parametrize("dsn", REFUSED)
def test_api_and_migrations_share_the_same_rule(dsn):
    problem = mig.migration_connection_problem(dsn)
    assert problem and "migrations" in problem and SECRET not in problem


def test_invalid_port_is_reported_without_credentials():
    dsn = f"postgresql://u:{SECRET}@db.example.test:notaport/app"
    assert pg.api_connection_problem(dsn) == "DATABASE_URL is not usable: its port is not a valid number."
    assert mig.migration_connection_problem(dsn) == "The DSN port is not a valid number."


@pytest.fixture
def fake_asyncpg(monkeypatch):
    calls = []

    async def create_pool(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(fake_pool=True)

    monkeypatch.setattr(pg, "asyncpg", SimpleNamespace(create_pool=create_pool))
    monkeypatch.setattr(pg, "_asyncpg_available", True)
    pg.reset_pool_for_testing()
    yield calls
    pg.reset_pool_for_testing()


@pytest.mark.parametrize("dsn", REFUSED)
def test_pool_refuses_before_connecting(fake_asyncpg, monkeypatch, dsn):
    monkeypatch.setenv("DATABASE_URL", dsn)
    with pytest.raises(pg.UnsupportedConnectionError) as exc:
        asyncio.run(pg.get_pg_pool())
    assert SECRET not in str(exc.value)
    assert fake_asyncpg == []          # no connection attempted
    assert pg._pool is None


@pytest.mark.parametrize("dsn", ACCEPTED)
def test_pool_is_created_for_direct_and_session_connections(fake_asyncpg, monkeypatch, dsn):
    monkeypatch.setenv("DATABASE_URL", dsn)
    pool = asyncio.run(pg.get_pg_pool())
    assert getattr(pool, "fake_pool", False) is True
    assert len(fake_asyncpg) == 1


@pytest.fixture
def startup_env(monkeypatch, fake_asyncpg):
    async def on_test_loop(coro):
        return await coro

    monkeypatch.setattr(institution_service, "_await_background", on_test_loop)
    monkeypatch.setattr(appmod, "_run_startup_preflight", lambda: {})
    monkeypatch.setattr(appmod, "_preflight_results", {})
    return fake_asyncpg


@pytest.mark.parametrize("required", ["1", "0"])
def test_startup_refuses_a_transaction_pooler_in_every_mode(startup_env, monkeypatch, caplog, required):
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", required)
    monkeypatch.setenv("DATABASE_URL", REFUSED[0])
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(pg.UnsupportedConnectionError) as exc:
            asyncio.run(appmod.on_startup())
    assert "6543" in str(exc.value) and "5432" in str(exc.value)
    assert SECRET not in str(exc.value) + caplog.text
    assert startup_env == []           # refused before any connection attempt


def test_startup_accepts_a_session_pooler(startup_env, monkeypatch):
    seen = []

    async def pool():
        seen.append(True)
        return SimpleNamespace()

    async def inspect(_pool):
        return {"missing": [], "modified": [], "unverified": []}

    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    monkeypatch.setenv("DATABASE_URL", ACCEPTED[1])
    monkeypatch.setattr(pg, "get_pg_pool", pool)
    import backend.db.schema_check as schema_check
    monkeypatch.setattr(schema_check, "inspect_migrations", inspect)
    asyncio.run(appmod.on_startup())
    assert seen and appmod._preflight_results["postgres_schema"] == {"status": "OK"}


def test_json_mode_startup_is_unaffected(startup_env, monkeypatch):
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    asyncio.run(appmod.on_startup())
    assert "postgres_schema" not in appmod._preflight_results

"""Startup verification of required PostgreSQL migrations (001, 002).

Everything runs against a fake pool; no database is contacted. The conftest
PostgreSQL guard stays active and would raise on any real driver use.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

import backend.app as appmod
from backend.db import pg_connection as pg
from backend.db import schema_check
from backend.services import institution_service

SECRET_DSN = "postgresql://svc-user:s3cr3t-pass@db.example.test:5432/postgres"
# Required versions come from migrations/ (same source as scripts/migrate.py).
ALL = tuple(schema_check.REQUIRED_MIGRATIONS)


# Correct checksums for every migration file (what scripts/migrate.py records).
CHECKSUMS = {m.version: m.checksum for m in __import__("backend.db.migrations", fromlist=["x"]).discover_migrations()}


class FakeConn:
    """Answers the read-only queries of backend.db.migrations.recorded_migrations."""

    def __init__(self, registered, versions, log, checksums=None, has_checksum_column=True):
        self.registered, self.versions, self.log = registered, versions, log
        self.checksums = CHECKSUMS if checksums is None else checksums
        self.has_checksum_column = has_checksum_column

    async def fetchval(self, sql, *args):
        self.log.append(sql)
        if "information_schema" in sql:
            return 1 if self.has_checksum_column else None
        return "schema_migrations" if self.registered else None

    async def fetch(self, sql, *args):
        self.log.append(sql)
        if "checksum" in sql:
            return [{"version": v, "checksum": self.checksums.get(v)} for v in self.versions]
        return [{"version": v} for v in self.versions]


class FakePool:
    def __init__(self, registered=True, versions=ALL, checksums=None, has_checksum_column=True):
        self.log = []
        self._conn = FakeConn(registered, versions, self.log, checksums, has_checksum_column)

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest.fixture
def startup_env(monkeypatch):
    async def on_test_loop(coro):
        return await coro

    monkeypatch.setattr(institution_service, "_await_background", on_test_loop)
    monkeypatch.setattr(appmod, "_run_startup_preflight", lambda: {})
    monkeypatch.setattr(appmod, "_preflight_results", {})

    def use_pool(pool):
        async def get_pool():
            return pool

        monkeypatch.setattr(pg, "get_pg_pool", get_pool)

    def configure(required: bool, database_url: str = SECRET_DSN):
        monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "1" if required else "0")
        monkeypatch.setenv("DATABASE_URL", database_url)

    return use_pool, configure


# --- Checker ----------------------------------------------------------------

@pytest.mark.parametrize(
    "registered,versions,missing",
    [
        (False, (), list(ALL)),                     # schema_migrations table absent
        (True, (), list(ALL)),
        (True, ("001",), list(ALL[1:])),
        (True, ALL[1:], ["001"]),                   # gap at the start is still reported
        (True, ALL, []),
        (True, ALL + ("999",), []),                 # later/unknown versions are tolerated here
    ],
)
def test_find_missing_migrations(registered, versions, missing):
    pool = FakePool(registered, versions)
    assert asyncio.run(schema_check.find_missing_migrations(pool)) == missing
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in pool.log)


def test_required_versions_match_migration_files():
    assert ALL[:2] == ("001", "002") and len(ALL) >= 6
    assert list(ALL) == [f"{i:03d}" for i in range(1, len(ALL) + 1)]


def test_error_message_is_actionable_and_free_of_connection_details():
    message = schema_check.describe_missing(["001", "002"])
    assert "001, 002" in message
    assert "migrations/001_institutional_schema.sql" in message
    assert "migrations/002_revoke_institutional_client_privileges.sql" in message
    assert "scripts/migrate.py apply" in message
    assert "never applies migrations automatically" in message
    assert "s3cr3t" not in message and "db.example.test" not in message


# --- Required mode ----------------------------------------------------------

@pytest.mark.parametrize(
    "pool,expected",
    [
        (FakePool(registered=False), ", ".join(ALL)),
        (FakePool(versions=ALL[:-1]), rf"migration\(s\) {ALL[-1]} not recorded"),
    ],
)
def test_required_mode_fails_startup_when_migrations_missing(startup_env, pool, expected):
    use_pool, configure = startup_env
    use_pool(pool)
    configure(required=True)
    with pytest.raises(schema_check.SchemaNotReadyError, match=expected) as info:
        asyncio.run(appmod.on_startup())
    assert "s3cr3t" not in str(info.value)
    assert appmod._preflight_results == {}  # never reached readiness


def test_required_mode_starts_when_all_migrations_recorded(startup_env):
    use_pool, configure = startup_env
    pool = FakePool()
    use_pool(pool)
    configure(required=True)
    asyncio.run(appmod.on_startup())
    assert appmod._preflight_results["postgres_schema"] == {"status": "OK"}
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in pool.log)


# --- Optional mode ----------------------------------------------------------

def test_optional_mode_warns_loudly_and_reports_not_ready(startup_env, caplog):
    use_pool, configure = startup_env
    use_pool(FakePool(versions=("001",)))
    configure(required=False)
    with caplog.at_level(logging.WARNING):
        asyncio.run(appmod.on_startup())  # must not raise
    assert "POSTGRESQL SCHEMA NOT READY" in caplog.text
    status = appmod._preflight_results["postgres_schema"]
    assert status["status"] == "FAILED" and "002" in status["reason"] and ALL[-1] in status["reason"]
    assert asyncio.run(appmod.health_check())["status"] == "degraded"


def test_optional_mode_unverifiable_database_is_not_reported_ready(
    startup_env, monkeypatch, caplog
):
    _use_pool, configure = startup_env
    configure(required=False)

    async def broken_pool():
        raise OSError(f"cannot reach {SECRET_DSN}")

    monkeypatch.setattr(pg, "get_pg_pool", broken_pool)
    with caplog.at_level(logging.WARNING):
        asyncio.run(appmod.on_startup())  # must not raise
    status = appmod._preflight_results["postgres_schema"]
    assert status["status"] == "FAILED" and "UNVERIFIED" in caplog.text
    assert "s3cr3t" not in caplog.text and "s3cr3t" not in str(status)


def test_optional_mode_complete_schema_is_ok(startup_env):
    use_pool, configure = startup_env
    use_pool(FakePool())
    configure(required=False)
    asyncio.run(appmod.on_startup())
    assert appmod._preflight_results["postgres_schema"] == {"status": "OK"}


# --- JSON / PostgreSQL-disabled mode ----------------------------------------

def test_json_mode_startup_is_unchanged_and_never_touches_postgres(startup_env, monkeypatch):
    use_pool, configure = startup_env

    async def must_not_be_called():
        raise AssertionError("PostgreSQL must not be touched in JSON mode")

    monkeypatch.setattr(pg, "get_pg_pool", must_not_be_called)
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    asyncio.run(appmod.on_startup())
    assert "postgres_schema" not in appmod._preflight_results



# --- Startup checksum verification (Batch B) ----------------------------------------------

def test_inspection_reports_modified_and_unverified_history():
    tampered = {**CHECKSUMS, "003": "0" * 64}
    report = asyncio.run(schema_check.inspect_migrations(FakePool(checksums=tampered)))
    assert report == {"missing": [], "modified": ["003"], "unverified": []}
    no_sums = {v: None for v in ALL}
    report = asyncio.run(schema_check.inspect_migrations(FakePool(checksums=no_sums)))
    assert report["unverified"] == list(ALL) and report["modified"] == []
    old_db = asyncio.run(schema_check.inspect_migrations(FakePool(versions=("001", "002"), has_checksum_column=False)))
    assert old_db["unverified"] == ["001", "002"] and old_db["missing"] == list(ALL[2:])


def test_required_mode_refuses_a_modified_applied_migration(startup_env):
    use_pool, configure = startup_env
    use_pool(FakePool(checksums={**CHECKSUMS, "001": "f" * 64}))
    configure(required=True)
    with pytest.raises(schema_check.SchemaNotReadyError, match="checksum differs for 001") as info:
        asyncio.run(appmod.on_startup())
    assert "never edit an applied migration" in str(info.value)
    assert "s3cr3t" not in str(info.value)


def test_required_mode_refuses_unverified_history_with_the_operator_action(startup_env):
    use_pool, configure = startup_env
    use_pool(FakePool(checksums={**CHECKSUMS, "002": None}))
    configure(required=True)
    with pytest.raises(schema_check.SchemaNotReadyError, match="no checksum recorded for 002") as info:
        asyncio.run(appmod.on_startup())
    assert "scripts/migrate.py apply" in str(info.value)


def test_optional_mode_reports_checksum_problems_without_blocking(startup_env, caplog):
    use_pool, configure = startup_env
    use_pool(FakePool(checksums={**CHECKSUMS, "004": "e" * 64}))
    configure(required=False)
    with caplog.at_level(logging.WARNING):
        asyncio.run(appmod.on_startup())
    assert appmod._preflight_results["postgres_schema"] == {"status": "FAILED", "reason": "checksum mismatch: 004"}
    assert "SCHEMA NOT READY" in caplog.text


def test_startup_inspection_is_read_only():
    pool = FakePool(checksums={**CHECKSUMS, "005": None})
    asyncio.run(schema_check.inspect_migrations(pool))
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in pool.log)

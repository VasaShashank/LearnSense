"""Phase 0: ordinary test runs must not be able to reach PostgreSQL.

Nothing here opens a network connection. Fake DSNs point at an unroutable port and a
socket-level tripwire proves no connect attempt is made.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.support.pg_safety import ALLOW_FLAG, TEST_URL_VAR, resolve_live_pg

REPO = Path(__file__).resolve().parents[2]
FAKE_DSN = "postgresql://nobody:not-a-secret@127.0.0.1:9/never"
# RFC 5737 TEST-NET-1: never routable, so any connect to it is unmistakably ours.
TRIPWIRE_HOST = "192.0.2.1"
TRIPWIRE_DSN = f"postgresql://nobody:not-a-secret@{TRIPWIRE_HOST}:5432/never"


# --- Opt-in policy ----------------------------------------------------------

@pytest.mark.parametrize(
    "environ,ambient,enabled",
    [
        ({}, None, False),
        ({ALLOW_FLAG: "1"}, None, False),                       # flag without URL
        ({TEST_URL_VAR: FAKE_DSN}, None, False),                # URL without flag
        ({ALLOW_FLAG: "true", TEST_URL_VAR: FAKE_DSN}, None, False),  # flag must be "1"
        ({"DATABASE_URL": FAKE_DSN}, None, False),              # app URL never opts in
        ({ALLOW_FLAG: "1", TEST_URL_VAR: FAKE_DSN}, FAKE_DSN, False),  # same as app URL
        ({ALLOW_FLAG: "1", TEST_URL_VAR: FAKE_DSN}, None, True),
        ({ALLOW_FLAG: "1", TEST_URL_VAR: FAKE_DSN}, "postgresql://other/db", True),
    ],
)
def test_live_pg_requires_explicit_disposable_database(environ, ambient, enabled):
    ok, url, reason = resolve_live_pg(environ, ambient)
    assert ok is enabled
    assert (url == FAKE_DSN) is enabled
    assert bool(reason) is (not enabled)


# --- Ordinary-run guard -----------------------------------------------------

def test_ordinary_run_has_no_database_configured():
    from backend.db.pg_connection import is_pg_configured

    assert os.environ.get("DATABASE_URL") == ""
    assert os.environ.get("LEARNSENSE_REQUIRE_PG") == "0"
    assert is_pg_configured() is False


def test_asyncpg_driver_is_blocked_for_ordinary_tests():
    asyncpg = pytest.importorskip("asyncpg")
    with pytest.raises(RuntimeError, match="Blocked by tests/conftest.py"):
        asyncio.run(asyncpg.create_pool(dsn=FAKE_DSN))
    with pytest.raises(RuntimeError, match="Blocked by tests/conftest.py"):
        asyncio.run(asyncpg.connect(FAKE_DSN))


def test_get_pg_pool_cannot_connect_even_if_a_test_sets_database_url(monkeypatch):
    """Backstop: a test that configures DATABASE_URL itself still opens no socket."""
    pytest.importorskip("asyncpg")
    from backend.db import pg_connection

    attempts = []

    real_connect = socket.socket.connect

    def tripwire(self, address, *args, **kwargs):
        # asyncio's own loopback self-pipe also calls connect; only flag the DSN host.
        if TRIPWIRE_HOST in str(address):
            attempts.append(address)
            raise AssertionError("socket connect to the configured database attempted")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", tripwire)
    monkeypatch.setenv("DATABASE_URL", TRIPWIRE_DSN)
    monkeypatch.setattr(pg_connection, "_pool", None)
    monkeypatch.setattr(pg_connection, "_pool_lock", None)

    with pytest.raises(RuntimeError, match="Blocked by tests/conftest.py"):
        asyncio.run(pg_connection.get_pg_pool())
    assert attempts == []
    assert pg_connection._pool is None


def test_institution_service_built_in_ordinary_test_is_json_only(tmp_path):
    from backend.services.institution_service import InstitutionService

    service = InstitutionService(base_dir=str(tmp_path / "inst"))
    assert service._pg_enabled is False


# --- .env cannot re-inject DATABASE_URL --------------------------------------

_PROBE = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, {repo!r})
    {guard}
    import backend.app  # loads .env keys that are absent from os.environ
    from backend.db.pg_connection import is_pg_configured
    print("PG_CONFIGURED=" + str(is_pg_configured()))
    """
)


def _probe(tmp_path: Path, *, guarded: bool) -> str:
    (tmp_path / ".env").write_text(f"DATABASE_URL={FAKE_DSN}\n", encoding="utf-8")
    # Minimal environment: the parent has already imported the app and mutated
    # os.environ, which must not influence what the child's import sees.
    keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "HOME")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update({"LLM_MODE": "mock", "LEARNSENSE_TEST_HARNESS": "1"})
    code = _PROBE.format(
        repo=str(REPO), guard="import tests.conftest" if guarded else "pass"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return next(
        line for line in result.stdout.splitlines() if line.startswith("PG_CONFIGURED=")
    )


def test_dotenv_injects_database_url_without_the_guard(tmp_path):
    """Control: proves the probe is not vacuous (the hazard is real)."""
    assert _probe(tmp_path, guarded=False) == "PG_CONFIGURED=True"


def test_dotenv_cannot_inject_database_url_with_the_guard(tmp_path):
    assert _probe(tmp_path, guarded=True) == "PG_CONFIGURED=False"

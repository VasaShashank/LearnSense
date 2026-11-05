"""P1 Batch B: credential handling in backup/restore (S3), migration connection
safety, and the checksum backfill report.

No database is contacted: the backup/restore scripts run against recording fake
PostgreSQL tools, and migration checks use fakes or unroutable DSNs. Real PostgreSQL
behavior is covered by tests/integration/test_p1_postgres_live.py (opt-in).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import pg_credentials  # noqa: E402

from backend.db import migrations as mig  # noqa: E402

SECRET = "s3cr3t-P@ss:x/y"
DSN = f"postgresql://backup_user:{quote(SECRET, safe='')}@db.internal:5432/learnsense?sslmode=require"


# --- pg_credentials -----------------------------------------------------------------

def test_split_dsn_removes_the_password_and_builds_an_escaped_pgpass_line():
    safe, line = pg_credentials.split_dsn(DSN)
    assert safe == "postgresql://backup_user@db.internal:5432/learnsense?sslmode=require"
    assert SECRET not in safe and quote(SECRET, safe="") not in safe
    assert line == r"db.internal:5432:learnsense:backup_user:s3cr3t-P@ss\:x/y"


@pytest.mark.parametrize("dsn,expected_safe", [
    ("postgresql://u@h/db", "postgresql://u@h/db"),
    ("postgresql://h:6000/db?sslmode=disable", "postgresql://h:6000/db?sslmode=disable"),
])
def test_split_dsn_without_password_writes_no_pgpass(dsn, expected_safe):
    assert pg_credentials.split_dsn(dsn) == (expected_safe, None)


@pytest.mark.parametrize("dsn", ["mysql://u:p@h/db", "postgresql://u@h/db?password=x"])
def test_split_dsn_rejects_unsupported_forms(dsn):
    with pytest.raises(ValueError):
        pg_credentials.split_dsn(dsn)


def test_cli_prints_only_the_safe_dsn_and_writes_a_private_pgpass(tmp_path):
    pgpass = tmp_path / "pgpass"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/pg_credentials.py"), "--dsn-env", "LS_PROBE_DSN",
         "--pgpass-file", str(pgpass)],
        capture_output=True, text=True, env={**os.environ, "LS_PROBE_DSN": DSN}, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert result.stdout.strip() == "postgresql://backup_user@db.internal:5432/learnsense?sslmode=require"
    assert SECRET.split(":")[0] in pgpass.read_text(encoding="utf-8")
    if os.name == "posix":
        assert stat.S_IMODE(pgpass.stat().st_mode) == 0o600


# --- Scripts never pass the password to child processes -----------------------------------

_FAKE_TOOL = r"""#!/usr/bin/env bash
tool="$(basename "$0")"
{
  printf 'TOOL=%s ARGV=' "$tool"; printf '[%s]' "$@"
  printf ' PGPASSFILE_SET=%s' "${PGPASSFILE:+1}"
  if [ -n "${PGPASSFILE:-}" ] && [ -f "$PGPASSFILE" ]; then
    printf ' PGPASS_HAS_SECRET=%s PGPASSFILE=%s' "$(grep -cF "$PROBE_SECRET" "$PGPASSFILE")" "$PGPASSFILE"
  fi
  echo
} >> "$PROBE_LOG"
args="$*"
out_file=""
for a in "$@"; do case "$a" in --file=*) out_file="${a#--file=}";; esac; done
case "$tool" in
  pg_dump) : > "$out_file" ;;
  psql)
    if [[ "$args" == *current_database* ]]; then echo fake_db
    elif [[ "$args" == *pg_tables* ]]; then echo 0
    elif [[ "$args" != *" -c "* && "$args" != *"-f "* ]]; then cat >/dev/null; echo 1
    else echo 1; fi ;;
  pg_restore)
    if [[ "$args" == *--list* ]]; then
      echo "1; 2615 2200 SCHEMA - public owner"; echo "200; 1259 16400 TABLE public t owner"
    elif [[ "$args" == *--schema-only* ]]; then
      echo "GRANT SELECT ON TABLE public.t TO service_role;" > "$out_file"
    fi ;;
esac
exit 0
"""


@pytest.fixture
def fake_pg_bin(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("bash is required for the backup/restore scripts")
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for tool in ("pg_dump", "psql", "pg_restore"):
        path = bin_dir / tool
        path.write_text(_FAKE_TOOL, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    return bin_dir


def _run_script(script, args, fake_pg_bin, tmp_path):
    log = tmp_path / "probe.log"
    env = {**os.environ, "PG_BIN": fake_pg_bin.as_posix(), "PYTHON": sys.executable,
           "LS_PROBE_DSN": DSN, "PROBE_LOG": log.as_posix(),
           # pgpass escapes ':' and '\'; the file holds the escaped form.
           "PROBE_SECRET": SECRET.replace("\\", "\\\\").replace(":", "\\:")}
    result = subprocess.run(
        [shutil.which("bash"), f"scripts/{script}", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _assert_no_password_in_children(result, lines):
    assert lines, "the fake PostgreSQL tools were never called"
    for line in lines:
        assert SECRET not in line and quote(SECRET, safe="") not in line, line
        assert "PGPASSFILE_SET=1" in line and "PGPASS_HAS_SECRET=1" in line, line
    assert SECRET not in result.stdout + result.stderr
    assert quote(SECRET, safe="") not in result.stdout + result.stderr
    pgpass_paths = {part.split("=", 1)[1] for line in lines for part in line.split() if part.startswith("PGPASSFILE=")}
    for path in pgpass_paths:
        still_there = subprocess.run([shutil.which("bash"), "-c", 'test -e "$1"', "_", path])
        assert still_there.returncode != 0, "temporary pgpass file was not removed"


def test_backup_script_passes_no_password_to_postgresql_tools(fake_pg_bin, tmp_path):
    result, lines = _run_script(
        "backup_postgres.sh", ["--dsn-env", "LS_PROBE_DSN", "--out", (tmp_path / "out").as_posix()],
        fake_pg_bin, tmp_path,
    )
    assert result.returncode == 0, result.stderr
    _assert_no_password_in_children(result, lines)
    dump_calls = [line for line in lines if line.startswith("TOOL=pg_dump")]
    assert len(dump_calls) == 1 and "[--schema=public]" in dump_calls[0]


def test_restore_script_passes_no_password_and_skips_the_public_schema_object(fake_pg_bin, tmp_path):
    dump = tmp_path / "x.dump"
    dump.write_text("fake", encoding="utf-8")
    result, lines = _run_script(
        "restore_postgres.sh",
        ["--dsn-env", "LS_PROBE_DSN", "--dump", dump.as_posix(), "--confirm-database", "fake_db"],
        fake_pg_bin, tmp_path,
    )
    assert result.returncode == 0, result.stderr
    _assert_no_password_in_children(result, lines)
    restore_call = [line for line in lines if line.startswith("TOOL=pg_restore") and "[--single-transaction]" in line]
    assert len(restore_call) == 1 and "[--use-list=" in restore_call[0]


def test_restore_script_keeps_its_confirmation_guard(fake_pg_bin, tmp_path):
    dump = tmp_path / "x.dump"
    dump.write_text("fake", encoding="utf-8")
    result, lines = _run_script(
        "restore_postgres.sh",
        ["--dsn-env", "LS_PROBE_DSN", "--dump", dump.as_posix(), "--confirm-database", "other_db"],
        fake_pg_bin, tmp_path,
    )
    assert result.returncode == 3 and "refusing" in result.stderr
    assert not any(line.startswith("TOOL=pg_restore") for line in lines)


# --- Migration connection safety -----------------------------------------------------

@pytest.mark.parametrize("dsn,refused", [
    ("postgresql://u:p@aws-0-eu-west-1.pooler.supabase.com:6543/postgres", True),   # transaction pooler
    ("postgresql://u:p@127.0.0.1:6543/postgres", True),
    ("postgresql://u:p@db.example.test:5432/app?pgbouncer=true", True),
    ("postgresql://u:p@aws-0-eu-west-1.pooler.supabase.com:5432/postgres", False),  # session pooler
    ("postgresql://u:p@db.abcdefgh.supabase.co:5432/postgres", False),              # direct
    ("postgresql://u:p@localhost/app", False),
])
def test_migration_connection_rules(dsn, refused):
    problem = mig.migration_connection_problem(dsn)
    assert (problem is not None) is refused
    if problem:
        assert "u:p" not in problem and "direct connection" in problem


def test_migrate_cli_refuses_a_transaction_pooler_before_connecting():
    for dsn in ("postgresql://u:topsecret@127.0.0.1:6543/postgres",
                "postgresql://u:topsecret@127.0.0.1:9/postgres?pgbouncer=true"):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/migrate.py"), "apply", "--dsn-env", "LS_POOLER_DSN"],
            capture_output=True, text=True, cwd=REPO, timeout=60,
            env={**os.environ, "LS_POOLER_DSN": dsn, "DATABASE_URL": ""},
        )
        assert result.returncode == 2
        assert "pooler" in result.stderr.lower() and "could not complete" not in result.stderr
        assert "topsecret" not in result.stdout + result.stderr


class _PidConn:
    def __init__(self, pids):
        self._pids = list(pids)

    async def fetchval(self, sql):
        assert "pg_backend_pid" in sql
        return self._pids.pop(0)


def test_session_probe_refuses_statements_on_different_backends():
    with pytest.raises(mig.MigrationError, match="different server sessions"):
        asyncio.run(mig.ensure_session_connection(_PidConn([101, 102, 101])))
    asyncio.run(mig.ensure_session_connection(_PidConn([7, 7, 7])))

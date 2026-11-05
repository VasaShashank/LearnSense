"""Static and CLI guards for the Supabase pre-migration check (no database needed).

The check is executed for real against Supabase-shaped databases in
tests/integration/test_supabase_migration_rehearsal_live.py (opt-in live tests).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import premigration_check  # noqa: E402

from backend.db.migrations import _FILE_PATTERN  # noqa: E402

CHECK_SQL = REPO / "scripts/sql/supabase_premigration_check.sql"
CONTINGENCY = REPO / "scripts/sql/contingency_007_organization_name_ci.sql"
MUTATING = r"\b(INSERT|UPDATE|DELETE|TRUNCATE|CREATE|ALTER|DROP|GRANT|REVOKE|COPY|CALL|DO|SET|RESET|VACUUM|ANALYZE|LOCK|COMMENT|REFRESH|EXECUTE|PREPARE|MERGE)\b"


def _split(sql: str):
    code = re.sub(r"--[^\n]*", "", sql)
    dynamic = re.findall(r"\$q\$(.*?)\$q\$", code, re.S)
    outer = re.sub(r"\$q\$.*?\$q\$", "''", code, flags=re.S)
    strip_strings = lambda s: re.sub(r"'(?:[^']|'')*'", "''", s)  # noqa: E731
    return strip_strings(outer), [strip_strings(q) for q in dynamic]


def test_check_sql_is_a_single_read_only_select():
    outer, dynamic = _split(CHECK_SQL.read_text(encoding="utf-8"))
    assert outer.count(";") == 1, "the check must stay ONE statement (SQL Editor shows only the last result)"
    assert outer.lstrip().upper().startswith("WITH")
    assert re.findall(MUTATING, outer, re.I) == []
    assert dynamic and all(q.strip().upper().startswith("SELECT") for q in dynamic)
    assert all(re.findall(MUTATING, q, re.I) == [] for q in dynamic)
    depth = 0
    for ch in outer:
        depth += (ch == "(") - (ch == ")")
        assert depth >= 0
    assert depth == 0


def test_check_sql_check_rows_have_unique_sort_keys_and_known_statuses():
    outer, _ = _split(CHECK_SQL.read_text(encoding="utf-8"))
    sorts = re.findall(r"^SELECT (\d+), '", outer, re.M)
    assert len(sorts) == len(set(sorts)) and len(sorts) >= 55
    statuses = set(re.findall(r"'(PASS|WARN|FAIL|INFO|UNAVAILABLE)'", CHECK_SQL.read_text(encoding="utf-8")))
    assert statuses == {"PASS", "WARN", "FAIL", "INFO", "UNAVAILABLE"}


def test_contingency_007_is_idempotent_and_adoptable():
    sql = CONTINGENCY.read_text(encoding="utf-8")
    assert _FILE_PATTERN.match("007_organization_name_ci.sql")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_name_ci" in sql
    assert "ON CONFLICT (version) DO NOTHING" in sql and "VALUES ('007'" in sql
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1
    assert not (REPO / "migrations/007_organization_name_ci.sql").exists(), \
        "adopt 007 only when the pre-migration check proves it is needed (docs/operations/supabase-migration.md)"


def _cli(env_value, *extra):
    env = {**os.environ, "DATABASE_URL": ""}
    env.pop("LS_CHECK", None)
    if env_value is not None:
        env["LS_CHECK"] = env_value
    return subprocess.run([sys.executable, str(REPO / "scripts/premigration_check.py"), "--dsn-env", "LS_CHECK", *extra],
                          capture_output=True, text=True, cwd=REPO, timeout=60, env=env)


@pytest.mark.parametrize("dsn", [
    "postgresql://u:topsecret@127.0.0.1:6543/postgres",
    "postgresql://u:topsecret@db.example.test:5432/app?pgbouncer=true",
    "postgresql://u:topsecret@db.example.test:notaport/app",
])
def test_cli_refuses_unsupported_connections_without_echoing_credentials(dsn):
    result = _cli(dsn)
    assert result.returncode == 2
    assert "topsecret" not in result.stdout + result.stderr


def test_cli_requires_the_dsn_variable():
    result = _cli(None)
    assert result.returncode == 2 and "LS_CHECK" in result.stderr


def test_markdown_report_escapes_cells():
    rows = [{"sort": 1, "section": "s", "check_name": "a|b", "status": "FAIL",
             "observed": "x\ny", "expected": "", "action": None}]
    md = premigration_check.render_markdown(rows, {"target": "t", "run_at": "now", "sql_sha256": "h",
                                                   "summary": premigration_check.summarize(rows)})
    assert "a\\|b" in md and "x y" in md and "FAIL 1" in md

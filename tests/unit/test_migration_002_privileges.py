"""Structural checks for the forward-only institutional privilege migration."""

from pathlib import Path
import re


MIGRATION_PATH = Path("migrations/002_revoke_institutional_client_privileges.sql")
INSTITUTIONAL_TABLES = (
    "organizations",
    "org_memberships",
    "course_classes",
    "class_enrollments",
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8").lower()


def test_migration_002_exists_and_is_transactional():
    sql = _sql().strip()
    assert sql.startswith("--")
    assert "begin;" in sql
    assert sql.endswith("commit;")


def test_revokes_all_client_privileges_on_each_institutional_table():
    sql = re.sub(r"\s+", " ", _sql())
    expected = (
        "revoke all privileges on table "
        "public.organizations, public.org_memberships, public.course_classes, "
        "public.class_enrollments from public, anon, authenticated;"
    )
    assert expected in sql
    for table in INSTITUTIONAL_TABLES:
        assert f"public.{table}" in sql


def test_server_roles_are_not_revoked_and_rls_is_not_changed():
    sql = _sql()
    revoke = sql.split("revoke all privileges on table", 1)[1].split(";", 1)[0]
    assert "postgres" not in revoke
    assert "service_role" not in revoke
    assert "disable row level security" not in sql
    assert "create policy" not in sql


def test_version_002_is_recorded_idempotently():
    sql = _sql()
    assert "insert into public.schema_migrations" in sql
    assert "values ('002', 'revoke direct client privileges on institutional tables')" in sql
    assert "on conflict (version) do nothing" in sql


def test_revoke_and_version_record_are_safe_to_repeat():
    sql = _sql()
    assert sql.count("revoke all privileges on table") == 1
    assert "on conflict (version) do nothing" in sql

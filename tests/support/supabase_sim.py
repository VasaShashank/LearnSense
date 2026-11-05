"""A disposable database shaped like the existing LearnSense Supabase project.

Used by the migration-rehearsal tests (tests/integration/test_supabase_migration_rehearsal_live.py).
It reproduces what the compatibility audit recorded about production:

* Supabase roles: ``postgres`` (NOT a superuser, BYPASSRLS) owns the application
  tables; ``anon``/``authenticated``/``service_role``/``supabase_auth_admin`` exist;
  Supabase's default privileges grant new tables in ``public`` to the API roles.
* ``auth.users`` (owned by ``supabase_auth_admin``, readable by ``postgres``).
* Migrations 001 and 002 recorded, ``schema_migrations`` WITHOUT a checksum column.
* TEXT ids; RLS enabled but not forced; no policies; client grants revoked (002).
* The enrollment unique key in the live column order ``(learner_id, class_id)``.
* 5 organizations, 8 memberships, 3 classes, 2 enrollments; every user id is a real
  ``auth.users`` id.

Everything application-owned is created as the ``postgres`` role by connecting as the
disposable server's superuser with ``options=-c role=postgres`` (no extra login role
or password is created). Cluster-wide side effects on the disposable server: the
roles above are created if missing (an existing ``postgres`` role is left untouched).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote, urlsplit, urlunsplit

REPO = Path(__file__).resolve().parents[2]
_NS = uuid.UUID("0b9f3c52-6a0e-4b8f-9d0e-7a3f1c2b5e44")

CLUSTER_ROLES = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
        CREATE ROLE postgres NOLOGIN NOSUPERUSER CREATEDB CREATEROLE BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN CREATE ROLE supabase_auth_admin NOLOGIN; END IF;
END$$;
"""

# Run as the server superuser inside the new database: what Supabase provisions.
SUPABASE_DATABASE_SETUP = """
GRANT ALL ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION supabase_auth_admin;
CREATE TABLE IF NOT EXISTS auth.users (
    id          UUID PRIMARY KEY,
    email       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ
);
ALTER TABLE auth.users OWNER TO supabase_auth_admin;
GRANT USAGE ON SCHEMA auth TO postgres, service_role;
GRANT SELECT ON auth.users TO postgres;
GRANT ALL ON auth.users TO service_role;
"""


def user(tag: str) -> str:
    return str(uuid.uuid5(_NS, tag))


@dataclass
class Seed:
    users: Dict[str, str] = field(default_factory=lambda: {t: user(t) for t in
                                                           ("admin_a", "teacher_a", "learner_1", "learner_2",
                                                            "admin_b", "admin_c")})
    orgs: List[tuple] = field(default_factory=lambda: [
        ("org_a1000001", "Northfield Academy"), ("org_a1000002", "Riverside College"),
        ("org_a1000003", "Hillcrest School"), ("org_a1000004", "Lakeside Institute"),
        ("org_a1000005", "Meadow Learning")])

    def memberships(self):
        u = self.users
        return [  # (membership_id, org_id, user_id, role)
            ("mem_a0000001", "org_a1000001", u["admin_a"], "ADMIN"),
            ("mem_a0000002", "org_a1000001", u["teacher_a"], "TEACHER"),
            ("mem_a0000003", "org_a1000001", u["learner_1"], "LEARNER"),
            ("mem_a0000004", "org_a1000001", u["learner_2"], "LEARNER"),
            ("mem_a0000005", "org_a1000002", u["admin_b"], "ADMIN"),
            ("mem_a0000006", "org_a1000003", u["admin_a"], "ADMIN"),
            ("mem_a0000007", "org_a1000004", u["admin_c"], "ADMIN"),
            ("mem_a0000008", "org_a1000005", u["admin_b"], "ADMIN"),
        ]

    def classes(self):
        u = self.users
        return [  # (class_id, org_id, subject_id, title, teacher_ids)
            ("cls_a0000001", "org_a1000001", "subj_math", "Algebra I", [u["teacher_a"]]),
            ("cls_a0000002", "org_a1000001", "subj_bio", "Biology", [u["teacher_a"]]),
            ("cls_a0000003", "org_a1000003", "subj_hist", "History", []),
        ]

    def enrollments(self):
        u = self.users
        return [(f"enr_cls_a0000001_{u[t]}", "cls_a0000001", u[t]) for t in ("learner_1", "learner_2")]


def with_database(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, parts.query, parts.fragment))


def as_role(dsn: str, role: str = "postgres") -> str:
    """Same server session user, but every statement runs as ``role`` (SET ROLE at startup)."""
    parts = urlsplit(dsn)
    option = "options=" + quote(f"-c role={role}", safe="")
    query = f"{parts.query}&{option}" if parts.query else option
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def legacy_001(uq_index: bool) -> str:
    """Migration 001 as the live database received it (differences recorded by the audit)."""
    sql = (REPO / "migrations" / "001_institutional_schema.sql").read_text(encoding="utf-8")
    sql = sql.replace("CONSTRAINT uq_class_enrollments_class_learner UNIQUE (class_id, learner_id)",
                      "CONSTRAINT class_enrollments_learner_id_class_id_key UNIQUE (learner_id, class_id)")
    if not uq_index:
        sql, n = re.subn(r"CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_name_ci\s+ON organizations \(LOWER\(name\)\);",
                         "", sql)
        assert n == 1, "001 no longer contains the expected uq_organizations_name_ci statement"
    assert "UNIQUE (learner_id, class_id)" in sql
    return sql


async def _execute(dsn: str, *statements: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn)
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


async def create_existing_production(server_dsn: str, name: str, *, uq_index: bool = True) -> Seed:
    """Create database ``name`` shaped like the existing Supabase project; return its seed."""
    import json

    import asyncpg

    await _execute(server_dsn, CLUSTER_ROLES, f'CREATE DATABASE "{name}"')
    admin = with_database(server_dsn, name)
    await _execute(admin, SUPABASE_DATABASE_SETUP)
    seed = Seed()
    await _execute(admin, *[f"INSERT INTO auth.users (id, email) VALUES ('{uid}', '{tag}@example.test')"
                            for tag, uid in seed.users.items()])

    conn = await asyncpg.connect(dsn=as_role(admin))
    try:
        assert await conn.fetchval("SELECT current_user") == "postgres"
        await conn.execute(legacy_001(uq_index))
        await conn.execute((REPO / "migrations" / "002_revoke_institutional_client_privileges.sql").read_text(encoding="utf-8"))
        await conn.executemany("INSERT INTO organizations (org_id, name) VALUES ($1, $2)", seed.orgs)
        await conn.executemany("INSERT INTO org_memberships (membership_id, org_id, user_id, role) VALUES ($1, $2, $3, $4)",
                               seed.memberships())
        await conn.executemany(
            "INSERT INTO course_classes (class_id, org_id, subject_id, title, teacher_ids) VALUES ($1, $2, $3, $4, $5::jsonb)",
            [(c, o, s, t, json.dumps(ids)) for c, o, s, t, ids in seed.classes()])
        await conn.executemany("INSERT INTO class_enrollments (enrollment_id, class_id, learner_id) VALUES ($1, $2, $3)",
                               seed.enrollments())
    finally:
        await conn.close()
    return seed


async def snapshot(dsn: str) -> Dict[str, list]:
    """Pre-existing rows of the four institutional tables, by their original columns only."""
    import asyncpg

    queries = {
        "organizations": "SELECT org_id, name, domain FROM organizations ORDER BY org_id",
        "org_memberships": "SELECT membership_id, org_id, user_id, role::text, is_active FROM org_memberships ORDER BY membership_id",
        "course_classes": "SELECT class_id, org_id, subject_id, title, teacher_ids::text FROM course_classes ORDER BY class_id",
        "class_enrollments": "SELECT enrollment_id, class_id, learner_id, enrolled_at FROM class_enrollments ORDER BY enrollment_id",
    }
    conn = await asyncpg.connect(dsn=dsn)
    try:
        return {table: [tuple(r) for r in await conn.fetch(sql)] for table, sql in queries.items()}
    finally:
        await conn.close()

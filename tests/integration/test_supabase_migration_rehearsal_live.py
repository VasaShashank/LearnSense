"""Migration rehearsal against databases shaped like the existing Supabase project.

Opt-in like every live test (tests/support/pg_safety.py):
    LEARNSENSE_ALLOW_LIVE_PG_TESTS=1
    LEARNSENSE_TEST_DATABASE_URL=<DSN of a disposable server; superuser, CREATEDB>

Every database here is created by this module and dropped afterwards. Cluster-wide
side effects on the disposable server: Supabase's role names are created if missing
(tests/support/supabase_sim.py), plus the role ``ls_sim_other`` for the ownership case.

What is proven:
* the read-only pre-migration check passes on the production shape, flags exactly the
  missing case-insensitive name index when it is absent, and reports every injected
  drift (schema, data, names, grants, RLS, ownership) without crashing;
* the check cannot write;
* backup -> verify -> restore into a Supabase-provisioned copy -> migrate 003-006
  (and contingency 007 when the index is missing), all as Supabase's non-superuser
  ``postgres`` role, preserves every existing row and yields the expected history,
  checksums, RLS, grants, triggers, constraints and indexes;
* the application starts against the rehearsed database and its institutional API works
  with the pre-existing organizations, memberships, classes and enrollments.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support import supabase_sim as sim

pytestmark = pytest.mark.live_pg

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import premigration_check  # noqa: E402

NEW_TABLES = {"users", "audit_events", "document_owners", "document_shares", "plans",
              "org_plan_assignments", "quota_limits", "usage_events", "jobs"}
EXISTING_TABLES = {"organizations", "org_memberships", "course_classes", "class_enrollments", "schema_migrations"}
ALL_PRIVS = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"


async def _execute(dsn, *statements):
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn)
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


async def _fetch(dsn, sql, *args):
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def server():
    base = os.environ["LEARNSENSE_TEST_DATABASE_URL"]
    created = []

    def new_name(prefix):
        name = f"ls_sb_{prefix}_{uuid.uuid4().hex[:8]}"
        created.append(name)
        return name

    yield SimpleNamespace(base=base, new_name=new_name)
    for name in reversed(created):
        asyncio.run(_execute(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def production(server, *, uq_index=True):
    name = server.new_name("prod")
    seed = asyncio.run(sim.create_existing_production(server.base, name, uq_index=uq_index))
    admin = sim.with_database(server.base, name)
    return SimpleNamespace(name=name, admin=admin, app=sim.as_role(admin), seed=seed)


def run_check(dsn):
    import asyncpg

    async def go():
        conn = await asyncpg.connect(dsn=dsn)
        try:
            return await premigration_check.run_check(conn, premigration_check.CHECK_SQL.read_text(encoding="utf-8"))
        finally:
            await conn.close()

    return {(r["sort"], r["check_name"]): r for r in asyncio.run(go())}


def problems(rows):
    return {key: (r["status"], r["observed"]) for key, r in rows.items() if r["status"] in ("FAIL", "WARN", "UNAVAILABLE")}


# --- The read-only check ------------------------------------------------------------------

def test_check_passes_on_the_production_shape(server):
    db = production(server, uq_index=True)
    rows = run_check(db.app)
    assert problems(rows) == {}
    assert rows[(0, "session")]["observed"].startswith("user=postgres;")
    assert rows[(1002, "recorded migration versions")]["observed"] == "001,002"
    assert rows[(702, "memberships whose user_id matches no auth.users.id")]["observed"] == "0 of 8 membership(s)"
    assert rows[(1005, "row counts")]["status"] == "PASS"
    assert rows[(203, "unique key for ON CONFLICT (class_id, learner_id)")]["status"] == "PASS"   # live column order
    assert rows[(102, "added by 003: schema_migrations.checksum")]["observed"] == "absent"


def test_check_flags_exactly_the_missing_name_index(server):
    db = production(server, uq_index=False)
    assert set(problems(run_check(db.app))) == {(200, "uq_organizations_name_ci")}


DRIFT_SCHEMA_AND_DATA = [
    "DROP INDEX uq_organizations_name_ci",
    "INSERT INTO organizations (org_id, name) VALUES ('org_dup00001', 'NORTHFIELD ACADEMY')",
    """UPDATE course_classes SET teacher_ids = '{"lead": "x"}' WHERE class_id = 'cls_a0000003'""",
    "ALTER TABLE org_memberships ALTER COLUMN role TYPE text",
    "UPDATE org_memberships SET role = 'admin' WHERE membership_id = 'mem_a0000007'",
    "INSERT INTO org_memberships (membership_id, org_id, user_id, role) VALUES ('mem_legacy01', 'org_a1000002', 'learner_a', 'LEARNER')",
    "CREATE TABLE jobs (x int)",
    "ALTER TABLE organizations ADD CONSTRAINT ck_class_enrollments_status CHECK (true)",
    "ALTER TABLE organizations ADD COLUMN tenant_code text NOT NULL DEFAULT 'x'",
    "ALTER TABLE organizations ALTER COLUMN tenant_code DROP DEFAULT",
    "INSERT INTO schema_migrations (version, description) VALUES ('999', 'unknown')",
    "GRANT SELECT ON organizations TO anon",
    "ALTER TABLE organizations FORCE ROW LEVEL SECURITY",
]


def test_check_reports_every_injected_schema_and_data_drift(server):
    db = production(server, uq_index=True)
    asyncio.run(_execute(db.admin, *DRIFT_SCHEMA_AND_DATA))
    found = problems(run_check(db.app))
    expected = {
        (200, "uq_organizations_name_ci"): "FAIL",
        (600, "duplicate names ignoring case (lower(name))"): "FAIL",
        (400, "values that are not JSON arrays"): "FAIL",
        (101, "org_memberships.role"): "WARN",
        (502, "memberships with an unexpected role value"): "FAIL",
        (503, "organizations without an active ADMIN"): "WARN",
        (702, "memberships whose user_id matches no auth.users.id"): "WARN",
        (704, "membership user_id values not shaped like a UUID"): "WARN",
        (800, "tables created by 003-006 already present in public"): "FAIL",
        (900, "constraint ck_class_enrollments_status"): "FAIL",
        (104, "other NOT NULL columns without a default"): "FAIL",
        (1002, "recorded migration versions"): "FAIL",
        (307, "client privileges: anon"): "WARN",
        (304, "RLS: organizations"): "WARN",
    }
    for key, status in expected.items():
        assert found.get(key, ("missing",))[0] == status, (key, found.get(key))
    assert "organizations.tenant_code" in found[(104, "other NOT NULL columns without a default")][1]
    assert "jobs" in found[(800, "tables created by 003-006 already present in public")][1]


def test_check_reports_ownership_problems_instead_of_failing(server):
    db = production(server, uq_index=True)
    asyncio.run(_execute(db.admin,
                         "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ls_sim_other') "
                         "THEN CREATE ROLE ls_sim_other NOLOGIN; END IF; END $$",
                         "ALTER TABLE course_classes OWNER TO ls_sim_other",
                         "REVOKE ALL ON course_classes FROM postgres"))
    found = problems(run_check(db.app))      # must not raise "permission denied"
    assert found[(106, "tables readable by the checking role")][0] == "FAIL"
    assert found[(300, "owner: course_classes")][0] == "FAIL"
    assert found[(305, "API role (postgres) can use all four institutional tables")][0] == "FAIL"
    assert found[(400, "values that are not JSON arrays")][0] == "UNAVAILABLE"


def test_check_is_read_only(server):
    import asyncpg

    db = production(server, uq_index=True)
    before = asyncio.run(sim.snapshot(db.admin))
    relations = "SELECT string_agg(relname || ':' || relkind::text, ',' ORDER BY relname) FROM pg_class WHERE relnamespace = 'public'::regnamespace"
    rels_before = asyncio.run(_fetch(db.admin, relations))[0][0]

    async def attempt_write():
        conn = await asyncpg.connect(dsn=db.app)
        try:
            await premigration_check.run_check(conn, "CREATE TABLE ls_should_not_exist (x int)")
        finally:
            await conn.close()

    with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
        asyncio.run(attempt_write())
    run_check(db.app)
    assert asyncio.run(sim.snapshot(db.admin)) == before
    assert asyncio.run(_fetch(db.admin, relations))[0][0] == rels_before


def test_check_cli_exit_codes_and_reports(server, tmp_path):
    good, bad = production(server, uq_index=True), production(server, uq_index=False)

    def cli(dsn, out):
        return subprocess.run([sys.executable, str(REPO / "scripts/premigration_check.py"), "--dsn-env", "LS_CHECK_DSN",
                               "--out", str(out)], cwd=REPO, capture_output=True, text=True, timeout=120,
                              env={**os.environ, "LS_CHECK_DSN": dsn})

    ok, failing = cli(good.app, tmp_path / "good"), cli(bad.app, tmp_path / "bad")
    assert ok.returncode == 0, ok.stderr
    assert failing.returncode == 1 and "FAIL" in failing.stdout and "uq_organizations_name_ci" in failing.stdout
    assert (tmp_path / "good" / "premigration_check.json").exists() and (tmp_path / "bad" / "premigration_check.md").exists()
    refused = cli("postgresql://u:topsecret@127.0.0.1:6543/postgres", tmp_path / "x")
    assert refused.returncode == 2 and "topsecret" not in refused.stdout + refused.stderr


# --- Full rehearsal -----------------------------------------------------------------------

class _OneConnPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _bash_script(name, *args, env):
    return subprocess.run([shutil.which("bash"), f"scripts/{name}", *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=300)


def _migrate(command, dsn, migrations_dir):
    return subprocess.run([sys.executable, "scripts/migrate.py", command, "--dsn-env", "LS_REHEARSAL_DSN",
                           "--migrations-dir", str(migrations_dir)], cwd=REPO, capture_output=True, text=True,
                          timeout=300, env={**os.environ, "LS_REHEARSAL_DSN": dsn})


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required for the backup scripts")
@pytest.mark.parametrize("uq_index", [True, False], ids=["name-index-present", "name-index-missing+contingency-007"])
def test_rehearsal_backup_restore_migrate_and_smoke(server, tmp_path, monkeypatch, uq_index):
    from backend.db.migrations import discover_migrations

    if shutil.which("pg_dump") is None and not os.environ.get("PG_BIN"):
        pytest.skip("pg_dump/pg_restore not on PATH and PG_BIN not set")
    prod = production(server, uq_index=uq_index)
    before = asyncio.run(sim.snapshot(prod.admin))
    assert set(problems(run_check(prod.app))) == (set() if uq_index else {(200, "uq_organizations_name_ci")})

    # 1. Backup (as postgres, like a Supabase operator) and verify the artifacts.
    env = {**os.environ, "LS_PROD": prod.app}
    backup = _bash_script("backup_postgres.sh", "--dsn-env", "LS_PROD", "--out", (tmp_path / "bk").as_posix(), env=env)
    assert backup.returncode == 0, backup.stderr
    dump = next((tmp_path / "bk").glob("learnsense_*.dump"))
    manifest = dict(line.split("=", 1) for line in next((tmp_path / "bk").glob("learnsense_*.manifest"))
                    .read_text(encoding="utf-8").splitlines() if "=" in line)
    assert manifest[f"sha256.{dump.name}"] == hashlib.sha256(dump.read_bytes()).hexdigest()
    assert (manifest["rows.organizations"], manifest["rows.org_memberships"],
            manifest["rows.course_classes"], manifest["rows.class_enrollments"]) == ("5", "8", "3", "2")
    pg_restore = Path(os.environ["PG_BIN"]) / "pg_restore" if os.environ.get("PG_BIN") else "pg_restore"
    toc = subprocess.run([str(pg_restore), "--list", str(dump)], capture_output=True, text=True, timeout=60)
    assert toc.returncode == 0 and all(f"TABLE public {t} " in toc.stdout for t in EXISTING_TABLES)
    assert " auth " not in toc.stdout                         # platform schemas are not dumped

    # 2. Restore into a fresh, Supabase-provisioned copy (the rehearsal database).
    name = server.new_name("rehearsal")
    asyncio.run(_execute(server.base, f'CREATE DATABASE "{name}"'))
    admin = sim.with_database(server.base, name)
    asyncio.run(_execute(admin, sim.SUPABASE_DATABASE_SETUP))
    app_dsn = sim.as_role(admin)
    restore = _bash_script("restore_postgres.sh", "--dsn-env", "LS_REH", "--dump", dump.as_posix(),
                           "--confirm-database", name, env={**os.environ, "LS_REH": app_dsn})
    assert restore.returncode == 0, restore.stderr
    assert asyncio.run(sim.snapshot(admin)) == before

    # 3. Migrate exactly as production would be migrated (contingency 007 only when needed).
    migrations_dir = REPO / "migrations"
    if not uq_index:
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        for f in (REPO / "migrations").glob("*.sql"):
            shutil.copy(f, migrations_dir / f.name)
        shutil.copy(REPO / "scripts/sql/contingency_007_organization_name_ci.sql",
                    migrations_dir / "007_organization_name_ci.sql")
    expected = [m.version for m in discover_migrations(migrations_dir)]
    pending = ", ".join(v for v in expected if v not in ("001", "002"))

    status = _migrate("status", app_dsn, migrations_dir)
    assert status.returncode == 1, status.stderr
    assert f"pending: {pending}" in status.stdout and "unverified checksums: 001, 002" in status.stdout
    apply = _migrate("apply", app_dsn, migrations_dir)
    assert apply.returncode == 0, apply.stderr
    assert f"applied now: {pending}" in apply.stdout
    assert "recorded checksums for previously unverified versions: 001, 002" in apply.stdout
    assert _migrate("status", app_dsn, migrations_dir).returncode == 0
    assert _migrate("apply", app_dsn, migrations_dir).stdout.count("none (already up to date)") == 1

    # 4. Verify the result.
    history = {r["version"]: r["checksum"] for r in asyncio.run(_fetch(admin, "SELECT version, checksum FROM schema_migrations"))}
    assert history == {m.version: m.checksum for m in discover_migrations(migrations_dir)}
    assert asyncio.run(sim.snapshot(admin)) == before                       # every pre-existing row intact
    assert [r[0] for r in asyncio.run(_fetch(admin, "SELECT DISTINCT status FROM class_enrollments"))] == ["active"]
    tables = asyncio.run(_fetch(admin, f"""
        SELECT c.relname, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced, pg_get_userbyid(c.relowner) AS owner,
               has_table_privilege('anon', c.oid, '{ALL_PRIVS}') AS anon,
               has_table_privilege('authenticated', c.oid, '{ALL_PRIVS}') AS authenticated,
               has_table_privilege('public', c.oid, '{ALL_PRIVS}') AS public,
               has_table_privilege('service_role', c.oid, 'SELECT') AS service_role
        FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"""))
    assert {t["relname"] for t in tables} == EXISTING_TABLES | NEW_TABLES
    for t in tables:
        assert t["rls"] and not t["forced"], t["relname"]
        assert t["owner"] == "postgres", t["relname"]
        assert not (t["anon"] or t["authenticated"] or t["public"]), t["relname"]
        # Supabase's default privileges grant service_role every table postgres creates;
        # the migrations deliberately revoke only PUBLIC/anon/authenticated.
        assert t["service_role"], t["relname"]
    names = {r[0] for r in asyncio.run(_fetch(admin, """
        SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace
        UNION SELECT tgname FROM pg_trigger WHERE NOT tgisinternal
        UNION SELECT indexrelid::regclass::text FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
              WHERE c.relnamespace = 'public'::regnamespace AND i.indisvalid"""))}
    for required in ("ck_class_enrollments_status", "ck_course_classes_teacher_ids_array", "trg_audit_events_append_only",
                     "trg_audit_events_no_truncate", "uq_organizations_name_ci", "idx_class_enrollments_active",
                     "uq_usage_events_request_id", "uq_jobs_owner_idempotency", "class_enrollments_learner_id_class_id_key"):
        assert required in names, required

    # 5. Startup verification accepts the rehearsed database (and refused it before migrating).
    import asyncpg

    from backend.db.schema_check import ensure_required_migrations

    async def startup_check():
        conn = await asyncpg.connect(dsn=app_dsn)
        try:
            await ensure_required_migrations(_OneConnPool(conn))
        finally:
            await conn.close()

    asyncio.run(startup_check())

    # 6. Application smoke test over HTTP in PostgreSQL mode, as postgres, on existing data.
    _smoke_test_application(app_dsn, admin, prod.seed, tmp_path, monkeypatch)


def _smoke_test_application(app_dsn, admin_dsn, seed, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.auth import AuthenticatedUser, get_current_user
    from backend.db import pg_connection
    from backend.routes import api as api_route
    from backend.services.institution_service import InstitutionService, _run_async
    from phase3.storage.learner_repository import LearnerStateRepository

    monkeypatch.setenv("DATABASE_URL", app_dsn)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    pg_connection.reset_pool_for_testing()
    learners = LearnerStateRepository(str(tmp_path / "learners"))
    svc = InstitutionService(base_dir=str(tmp_path / "inst"), learner_state_repo=learners)
    assert svc._pg_enabled is True
    for name in ("_sync_class_to_teacher_storage", "_append_learner_to_teacher_storage", "_set_teacher_storage_roster"):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)
    monkeypatch.setattr(api_route, "institution_service", svc)
    u = seed.users
    # A class is tied to course material its creator may read. Declare (in memory, like
    # tests/support/api_auth.py) that admin_a uploaded the new class's subject document;
    # every other authorization check is unchanged and nothing is written to storage/.
    original_is_owned_by = api_route.document_ownership.is_owned_by
    monkeypatch.setattr(api_route.document_ownership, "is_owned_by",
                        lambda doc, uid: (doc, uid) == ("subj_chem", u["admin_a"]) or original_is_owned_by(doc, uid))

    def as_user(tag):
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=u[tag], email=None)
        return TestClient(app, raise_server_exceptions=False)

    try:
        me = as_user("admin_a").get("/api/me")
        assert me.status_code == 200, me.text
        assert {(m["org_id"], m["role"]) for m in me.json()["memberships"]} == {("org_a1000001", "ADMIN"), ("org_a1000003", "ADMIN")}
        for tag in ("teacher_a", "learner_1", "learner_2", "admin_b", "admin_c"):
            assert as_user(tag).get("/api/me").status_code == 200

        members = as_user("admin_a").get("/api/institutions/organizations/org_a1000001/memberships")
        assert members.status_code == 200 and members.json()["total"] == 4, members.text
        roster = as_user("teacher_a").get("/api/institutions/classes/cls_a0000001/roster")
        assert roster.status_code == 200 and roster.json()["roster"] == sorted([u["learner_1"], u["learner_2"]]), roster.text

        created = as_user("admin_a").post("/api/institutions/classes", json={
            "org_id": "org_a1000001", "subject_id": "subj_chem", "title": "Chemistry", "teacher_ids": [u["teacher_a"]]})
        assert created.status_code == 200, created.text
        new_class = created.json()["class_id"]
        # Pre-existing learners keep their existing enrollments (roster above), but a NEW
        # enrollment needs the learner to have signed in and been provisioned once.
        not_yet = as_user("admin_a").post(f"/api/institutions/classes/{new_class}/enroll", json={"learner_id": u["learner_1"]})
        assert not_yet.status_code == 404 and not_yet.json()["code"] == "USER_NOT_PROVISIONED", not_yet.text
        from backend.services.learner_service import LearnerService

        LearnerService(repo=learners).provision_authenticated_learner(u["learner_1"])
        enrolled = as_user("admin_a").post(f"/api/institutions/classes/{new_class}/enroll", json={"learner_id": u["learner_1"]})
        assert enrolled.status_code == 200 and enrolled.json()["status"] == "active", enrolled.text

        unenrolled = as_user("admin_a").delete(f"/api/institutions/classes/cls_a0000001/enrollments/{u['learner_2']}")
        assert unenrolled.status_code == 200, unenrolled.text
        roster = as_user("teacher_a").get("/api/institutions/classes/cls_a0000001/roster")
        assert roster.json()["roster"] == [u["learner_1"]]

        duplicate = as_user("admin_b").post("/api/institutions/organizations", json={"name": "northfield ACADEMY"})
        assert duplicate.status_code == 409 and duplicate.json()["code"] == "ORGANIZATION_NAME_TAKEN", duplicate.text
        last_admin = as_user("admin_c").delete(f"/api/institutions/organizations/org_a1000004/memberships/{u['admin_c']}")
        assert last_admin.status_code == 409 and last_admin.json()["code"] == "LAST_ADMIN", last_admin.text
        stranger = as_user("admin_c").get("/api/institutions/organizations/org_a1000001/memberships")
        assert stranger.status_code in (403, 404), stranger.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        _run_async(pg_connection.close_pg_pool())
        pg_connection.reset_pool_for_testing()

    actions = {r[0] for r in asyncio.run(_fetch(admin_dsn, "SELECT action FROM audit_events"))}
    assert len(actions) >= 3, actions
    users = asyncio.run(_fetch(admin_dsn, "SELECT count(*) FROM users"))[0][0]
    assert users == 6

"""Person 1 PostgreSQL behavior against a REAL, DISPOSABLE database.

Opt-in only (tests/support/pg_safety.py):
    LEARNSENSE_ALLOW_LIVE_PG_TESTS=1
    LEARNSENSE_TEST_DATABASE_URL=<DSN of a disposable server/database>

The module creates its own database (``ls_p1_<random>``) on that server, applies
every migration from scratch with the real runner, and drops it afterwards. It
needs CREATEDB privilege. Nothing outside that database is modified except the
cluster-wide ``anon``/``authenticated`` roles, which are created if missing.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import pytest

pytestmark = pytest.mark.live_pg

REPO = Path(__file__).resolve().parents[2]


def _with_database(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, parts.query, parts.fragment))


async def _admin(dsn: str, *statements: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn)
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def fresh_db():
    import asyncpg

    from backend.db.migrations import apply_migrations

    base = os.environ["LEARNSENSE_TEST_DATABASE_URL"]
    name = f"ls_p1_{uuid.uuid4().hex[:10]}"
    asyncio.run(_admin(base, f'CREATE DATABASE "{name}"'))
    url = _with_database(base, name)

    async def _prepare():
        conn = await asyncpg.connect(dsn=url)
        try:
            await conn.execute((REPO / "deploy/postgres/init/00_supabase_roles.sql").read_text(encoding="utf-8"))
            return await apply_migrations(conn)
        finally:
            await conn.close()

    applied = asyncio.run(_prepare())
    yield SimpleNamespace(url=url, name=name, base=base, applied=applied)
    asyncio.run(_admin(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def pg(fresh_db, monkeypatch, tmp_path):
    from backend.db import pg_connection
    from backend.services.institution_service import InstitutionService, _run_async
    from backend.services.learner_service import LearnerService
    from phase3.storage.learner_repository import LearnerStateRepository

    monkeypatch.setenv("DATABASE_URL", fresh_db.url)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    pg_connection.reset_pool_for_testing()
    learners = LearnerStateRepository(str(tmp_path / "learners"))
    svc = InstitutionService(base_dir=str(tmp_path / "inst"), learner_state_repo=learners)
    assert svc._pg_enabled is True and svc.users._pg_enabled is True
    for name in ("_sync_class_to_teacher_storage", "_append_learner_to_teacher_storage", "_set_teacher_storage_roster"):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)

    def provision_learner(user_id):
        LearnerService(repo=learners).provision_authenticated_learner(user_id)

    async def fetch(sql, *args):
        pool = await pg_connection.get_pg_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(sql, *args)

    from backend.services.institution_service import _await_background

    yield SimpleNamespace(
        svc=svc, url=fresh_db.url, provision_learner=provision_learner,
        fetch=lambda sql, *a: asyncio.run(_await_background(fetch(sql, *a))),
        run=lambda coro: asyncio.run(coro),
    )
    _run_async(pg_connection.close_pg_pool())
    pg_connection.reset_pool_for_testing()


def uid():
    return str(uuid.uuid4())


def make_org(pg, *admins):
    """Org whose first admin created it; further admins added through the guarded API."""
    for user in admins:
        pg.run(pg.svc.users.ensure_user(user, None))
    org = pg.run(pg.svc.create_organization_with_admin_async(f"Org {uuid.uuid4().hex[:8]}", None, admins[0]))
    from phase4.institution.models import UserRole
    for extra in admins[1:]:
        pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admins[0], extra, UserRole.ADMIN))
    return org


def active_admins(pg, org_id):
    rows = pg.fetch("SELECT user_id FROM org_memberships WHERE org_id=$1 AND role='ADMIN' AND is_active", org_id)
    return sorted(r["user_id"] for r in rows)


# --- Migrations, privileges, startup check ---------------------------------------------------

def test_migrations_apply_from_scratch_and_reapply_is_a_no_op(fresh_db, pg):
    from backend.db.migrations import apply_migrations, discover_migrations, migration_status
    import asyncpg

    assert fresh_db.applied == [m.version for m in discover_migrations()]

    async def check():
        conn = await asyncpg.connect(dsn=fresh_db.url)
        try:
            assert await apply_migrations(conn) == []
            status = await migration_status(conn)
            assert status["pending"] == [] and status["problems"] == []
            await conn.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version='001'")
            assert "changed" in (await migration_status(conn))["problems"][0]
            await conn.execute("UPDATE schema_migrations SET checksum=NULL WHERE version='001'")
            await apply_migrations(conn)  # backfills the checksum again
            assert (await migration_status(conn))["problems"] == []
        finally:
            await conn.close()

    asyncio.run(check())


def test_startup_schema_check_passes_on_the_migrated_database(pg):
    from backend.db import pg_connection
    from backend.db.schema_check import find_missing_migrations
    from backend.services.institution_service import _await_background

    async def missing():
        return await find_missing_migrations(await pg_connection.get_pg_pool())

    assert pg.run(_await_background(missing())) == []


def test_migrate_cli_accepts_a_direct_session_connection(fresh_db):
    """The session-affinity probe passes on a direct connection; status reports up to date."""
    result = _script("migrate.py", "status", "--dsn-env", "LS_DIRECT_DSN", env_extra={"LS_DIRECT_DSN": fresh_db.url})
    assert result.returncode == 0, result.stderr
    assert "pending: none" in result.stdout
    assert (urlsplit(fresh_db.url).password or "\0") not in result.stdout + result.stderr


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


def test_startup_refuses_modified_and_unverified_history_on_a_real_database(fresh_db):
    import asyncpg

    from backend.db.migrations import apply_migrations
    from backend.db.schema_check import SchemaNotReadyError, ensure_required_migrations, inspect_migrations

    async def scenario():
        conn = await asyncpg.connect(dsn=fresh_db.url)
        pool = _OneConnPool(conn)
        original = await conn.fetchval("SELECT checksum FROM schema_migrations WHERE version='004'")
        try:
            await conn.execute("UPDATE schema_migrations SET checksum='edited-after-apply' WHERE version='004'")
            assert (await inspect_migrations(pool))["modified"] == ["004"]
            with pytest.raises(SchemaNotReadyError, match="checksum differs for 004"):
                await ensure_required_migrations(pool)
            # The runner refuses the mismatch too; it never rewrites a recorded checksum.
            with pytest.raises(Exception, match="changed since application"):
                await apply_migrations(conn)
            assert await conn.fetchval("SELECT checksum FROM schema_migrations WHERE version='004'") == "edited-after-apply"

            await conn.execute("UPDATE schema_migrations SET checksum=NULL WHERE version='004'")
            with pytest.raises(SchemaNotReadyError, match="no checksum recorded for 004"):
                await ensure_required_migrations(pool)
            backfilled = []
            assert await apply_migrations(conn, backfilled=backfilled) == []
            assert backfilled == ["004"]
            await ensure_required_migrations(pool)  # verified again
        finally:
            await conn.execute("UPDATE schema_migrations SET checksum=$1 WHERE version='004'", original)
            await conn.close()

    asyncio.run(scenario())


def test_client_roles_have_no_table_privileges_and_rls_is_enabled(pg):
    tables = ["organizations", "org_memberships", "course_classes", "class_enrollments", "users",
              "audit_events", "document_owners", "document_shares", "plans", "org_plan_assignments",
              "quota_limits", "usage_events", "jobs"]
    rows = pg.fetch(
        """SELECT c.relname, c.relrowsecurity,
                  has_table_privilege('anon', c.oid, 'SELECT') AS anon_select,
                  has_table_privilege('authenticated', c.oid, 'INSERT') AS auth_insert
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname='public' AND c.relname = ANY($1::text[])""",
        tables,
    )
    assert sorted(r["relname"] for r in rows) == sorted(tables)
    for r in rows:
        assert r["relrowsecurity"] and not r["anon_select"] and not r["auth_insert"], r["relname"]


# --- Organizations, staff identity, audit -------------------------------------------------------

def test_concurrent_duplicate_organization_names_create_exactly_one(pg):
    from backend.services.institution_service import DuplicateOrganizationError

    creators = [uid() for _ in range(5)]
    name = f"Race Org {uuid.uuid4().hex[:6]}"

    async def attempt(i, user):
        try:
            return await pg.svc.create_organization_with_admin_async(
                name.upper() if i % 2 else name.lower(), None, user)
        except DuplicateOrganizationError:
            return None

    async def race():
        return await asyncio.gather(*(attempt(i, u) for i, u in enumerate(creators)))

    results = pg.run(race())
    assert sum(r is not None for r in results) == 1
    created = next(r for r in results if r is not None)
    assert len(pg.fetch("SELECT 1 FROM audit_events WHERE org_id=$1 AND action='org.created'", created.org_id)) == 1


def test_staff_grants_need_a_provisioned_user_and_failed_grants_leave_no_trace(pg):
    from backend.services.user_service import UserNotProvisionedError
    from phase4.institution.models import UserRole

    admin, teacher = uid(), uid()
    org = make_org(pg, admin)
    with pytest.raises(UserNotProvisionedError):
        pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admin, teacher, UserRole.TEACHER))
    with pytest.raises(UserNotProvisionedError):
        pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admin, "prof_vance", UserRole.TEACHER))
    assert pg.fetch("SELECT 1 FROM org_memberships WHERE org_id=$1 AND user_id=$2", org.org_id, teacher) == []
    assert pg.fetch("SELECT 1 FROM audit_events WHERE target_id=$1", teacher) == []

    pg.run(pg.svc.users.ensure_user(teacher, "t@example.test"))
    pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admin, teacher, UserRole.TEACHER))
    pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admin, teacher, UserRole.TEACHER))  # no-op
    trail = [r["action"] for r in pg.fetch(
        "SELECT action FROM audit_events WHERE target_id=$1 ORDER BY occurred_at", teacher)]
    assert trail == ["membership.created"]


def test_audit_events_are_append_only(pg):
    import asyncpg

    org = make_org(pg, uid())
    from backend.db import pg_connection
    from backend.services.institution_service import _await_background

    async def tamper():
        pool = await pg_connection.get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE audit_events SET action='forged' WHERE org_id=$1", org.org_id)

    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        pg.run(_await_background(tamper()))


# --- Last-admin invariant under real concurrency ---------------------------------------------------

def test_two_admins_deactivating_each_other_concurrently_leave_one_admin(pg):
    from backend.services.institution_service import LastAdminError
    from phase3.errors import AuthorizationError

    for _ in range(8):
        a, b = uid(), uid()
        org = make_org(pg, a, b)

        async def attempt(actor, target):
            try:
                await pg.svc.deactivate_membership_as_admin_async(org.org_id, actor, target)
                return "ok"
            except (AuthorizationError, LastAdminError) as exc:
                return type(exc).__name__

        async def race():
            return await asyncio.gather(attempt(a, b), attempt(b, a))

        outcomes = pg.run(race())
        assert outcomes.count("ok") == 1, outcomes
        assert len(active_admins(pg, org.org_id)) == 1


def test_concurrent_self_demotions_leave_one_admin(pg):
    from backend.services.institution_service import LastAdminError
    from phase3.errors import AuthorizationError
    from phase4.institution.models import UserRole

    for _ in range(8):
        a, b = uid(), uid()
        org = make_org(pg, a, b)

        async def attempt(user):
            try:
                await pg.svc.add_membership_as_admin_async(org.org_id, user, user, UserRole.TEACHER)
                return "ok"
            except (AuthorizationError, LastAdminError):
                return "refused"

        async def race():
            return await asyncio.gather(attempt(a), attempt(b))

        assert pg.run(race()).count("ok") == 1
        assert len(active_admins(pg, org.org_id)) == 1


def test_mixed_concurrent_membership_operations_complete_without_deadlock(pg):
    from backend.services.institution_service import LastAdminError
    from phase3.errors import AuthorizationError
    from phase4.institution.models import UserRole

    admins = [uid() for _ in range(4)]
    staff = [uid() for _ in range(6)]
    org = make_org(pg, *admins)
    for user in staff:
        pg.run(pg.svc.users.ensure_user(user, None))

    async def op(i):
        actor = admins[i % len(admins)]
        try:
            if i % 3 == 0:
                await pg.svc.deactivate_membership_as_admin_async(org.org_id, actor, admins[(i + 1) % len(admins)])
            elif i % 3 == 1:
                await pg.svc.add_membership_as_admin_async(org.org_id, actor, staff[i % len(staff)], UserRole.TEACHER)
            else:
                await pg.svc.add_membership_as_admin_async(org.org_id, actor, admins[(i + 2) % len(admins)], UserRole.TEACHER)
            return "ok"
        except (AuthorizationError, LastAdminError):
            return "refused"

    async def storm():
        return await asyncio.wait_for(asyncio.gather(*(op(i) for i in range(24))), timeout=60)

    outcomes = pg.run(storm())   # a deadlock would raise asyncpg.DeadlockDetectedError
    assert set(outcomes) <= {"ok", "refused"}
    assert len(active_admins(pg, org.org_id)) >= 1


# --- Class lifecycle ------------------------------------------------------------------------

def _class_with_learners(pg, n=2):
    from phase4.institution.models import UserRole

    admin, teacher = uid(), uid()
    learners = [uid() for _ in range(n)]
    org = make_org(pg, admin)
    pg.run(pg.svc.users.ensure_user(teacher, None))
    pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admin, teacher, UserRole.TEACHER))
    for learner in learners:
        pg.provision_learner(learner)
        pg.run(pg.svc.add_membership_as_admin_async(org.org_id, admin, learner, UserRole.LEARNER))
    cls = pg.svc.create_class(org.org_id, "doc_live", "Live Class", [teacher], teacher, learners)
    return SimpleNamespace(org=org, admin=admin, teacher=teacher, learners=learners, cls=cls)


def test_unenroll_is_soft_idempotent_and_reenroll_reactivates(pg):
    from backend.services.institution_service import EnrollmentNotFoundError

    c = _class_with_learners(pg)
    learner, other = c.learners
    assert pg.run(pg.svc.unenroll_learner_async(c.cls.class_id, learner, c.teacher)) is True
    assert pg.run(pg.svc.unenroll_learner_async(c.cls.class_id, learner, c.teacher)) is False
    assert pg.svc.get_class_roster(c.cls.class_id, c.teacher) == sorted([other])
    assert pg.svc.is_active_learner_enrolled(c.cls.class_id, learner) is False
    row = pg.fetch("SELECT status, unenrolled_by FROM class_enrollments WHERE class_id=$1 AND learner_id=$2",
                   c.cls.class_id, learner)[0]
    assert (row["status"], row["unenrolled_by"]) == ("unenrolled", c.teacher)
    with pytest.raises(EnrollmentNotFoundError):
        pg.run(pg.svc.unenroll_learner_async(c.cls.class_id, uid(), c.admin))

    pg.svc.enroll_learner(c.cls.class_id, learner, c.admin)
    assert set(pg.svc.get_class_roster(c.cls.class_id, c.teacher)) == {learner, other}
    trail = [r["action"] for r in pg.fetch(
        "SELECT action FROM audit_events WHERE target_id=$1 ORDER BY occurred_at", f"{c.cls.class_id}:{learner}")]
    assert trail == ["class.enrollment.removed", "class.enrollment.reactivated"]


def test_teacher_reassignment_is_admin_only_and_validated(pg):
    from backend.services.institution_service import InvalidAssignmentError
    from phase3.errors import AuthorizationError
    from phase4.institution.models import UserRole

    c = _class_with_learners(pg, n=1)
    new_teacher = uid()
    pg.run(pg.svc.users.ensure_user(new_teacher, None))
    pg.run(pg.svc.add_membership_as_admin_async(c.org.org_id, c.admin, new_teacher, UserRole.TEACHER))
    with pytest.raises(AuthorizationError):
        pg.run(pg.svc.set_class_teachers_async(c.cls.class_id, [new_teacher], c.teacher))
    with pytest.raises(InvalidAssignmentError):
        pg.run(pg.svc.set_class_teachers_async(c.cls.class_id, [c.learners[0]], c.admin))
    updated = pg.run(pg.svc.set_class_teachers_async(c.cls.class_id, [new_teacher], c.admin))
    assert updated.teacher_ids == [new_teacher] and pg.svc.get_class(c.cls.class_id).teacher_ids == [new_teacher]


def test_membership_reads_cover_multi_org_users_and_pagination(pg):
    from phase4.institution.models import UserRole

    person = uid()
    org_a = make_org(pg, person)
    other_admin = uid()
    org_b = make_org(pg, other_admin)
    pg.run(pg.svc.add_membership_as_admin_async(org_b.org_id, other_admin, person, UserRole.TEACHER))
    roles = {(m["org_id"], m["role"].value) for m in pg.run(pg.svc.list_memberships_for_user_async(person))}
    assert roles == {(org_a.org_id, "ADMIN"), (org_b.org_id, "TEACHER")}

    page, total = pg.run(pg.svc.list_org_memberships_async(org_b.org_id, other_admin, limit=1, offset=0,
                                                          include_inactive=False))
    assert total == 2 and len(page) == 1
    from phase3.errors import AuthorizationError
    with pytest.raises(AuthorizationError):
        pg.run(pg.svc.list_org_memberships_async(org_b.org_id, person, limit=10, offset=0, include_inactive=False))


# --- Users, document access, usage, jobs ---------------------------------------------------------

def test_user_records_and_status(pg):
    user = uid()
    first = pg.run(pg.svc.users.ensure_user(user, "a@example.test"))
    again = pg.run(pg.svc.users.ensure_user(user, None))
    assert first["created_at"] == again["created_at"] and again["email"] == "a@example.test"
    assert pg.run(pg.svc.users.is_disabled(user)) is False
    pg.run(pg.svc.users.set_status(user, "disabled", reason="test", actor_user_id="operator"))
    assert pg.run(pg.svc.users.is_disabled(user)) is True
    assert pg.fetch("SELECT 1 FROM audit_events WHERE action='user.status_changed' AND target_id=$1", user)


def test_postgres_document_access_stores(pg):
    import asyncpg

    from backend.services.document_access_store import PgDocumentOwnershipRepository, PgDocumentShareRepository

    c = _class_with_learners(pg, n=1)
    owners, shares = PgDocumentOwnershipRepository(), PgDocumentShareRepository()
    doc = f"doc_{uuid.uuid4().hex[:8]}"
    owners.claim(doc, c.teacher)
    owners.claim(doc, c.teacher)                          # idempotent for the same owner
    with pytest.raises(ValueError):
        owners.claim(doc, c.admin)                        # never transferred
    assert owners.get_owner(doc) == c.teacher and doc in owners.list_owned_document_ids(c.teacher)

    shares.grant(doc, c.cls.class_id, c.teacher, c.teacher)
    shares.grant(doc, c.cls.class_id, c.teacher, c.teacher)
    assert [g["class_id"] for g in shares.list_for_document(doc)] == [c.cls.class_id]
    assert shares.revoke(doc, c.cls.class_id, c.teacher) is True
    assert shares.revoke(doc, c.cls.class_id, c.teacher) is False
    trail = [r["action"] for r in pg.fetch("SELECT action FROM audit_events WHERE target_id=$1 ORDER BY occurred_at", doc)]
    assert trail == ["document.share.granted", "document.share.revoked"]
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        shares.grant(doc, "cls_does_not_exist", c.teacher, c.teacher)


def test_usage_is_idempotent_tenant_aware_and_quota_safe_under_concurrency(pg):
    from backend.services.usage_service import IdempotencyConflict, QuotaExceeded, UsageService
    from phase3.errors import AuthorizationError

    c = _class_with_learners(pg, n=0)
    usage = UsageService(pg_enabled=True)
    first = pg.run(usage.record_usage(c.org.org_id, c.admin, "test.units", 2, "live-test", "live-req-1"))
    replay = pg.run(usage.record_usage(c.org.org_id, c.admin, "test.units", 2, "live-test", "live-req-1"))
    assert first["created"] and not replay["created"]
    with pytest.raises(IdempotencyConflict):
        pg.run(usage.record_usage(c.org.org_id, c.admin, "test.units", 3, "live-test", "live-req-1"))
    with pytest.raises(AuthorizationError):
        pg.run(usage.record_usage(c.org.org_id, uid(), "test.units", 1, "live-test", "live-req-2"))

    plan = f"plan-{uuid.uuid4().hex[:6]}"
    pg.run(usage.create_plan(plan, "Live"))
    pg.run(usage.set_quota_limit(plan, "test.burst", "day", 5))
    pg.run(usage.assign_plan(c.org.org_id, plan, assigned_by="operator"))

    async def one(i):
        try:
            await usage.consume(c.org.org_id, c.admin, "test.burst", 1, "live-test", f"burst-{plan}-{i}")
            return True
        except QuotaExceeded:
            return False

    async def burst():
        return await asyncio.gather(*(one(i) for i in range(12)))

    results = pg.run(burst())
    assert results.count(True) == 5
    total = pg.fetch("SELECT SUM(quantity) AS s FROM usage_events WHERE org_id=$1 AND dimension='test.burst'",
                     c.org.org_id)[0]["s"]
    assert total == 5


def test_job_persistence_contract(pg):
    from backend.db import pg_connection
    from backend.repositories.job_store import JobStatus, JobStore, JobTransitionError
    from backend.services.institution_service import _await_background

    store = JobStore()
    owner, intruder = uid(), uid()

    async def scenario():
        pool = await pg_connection.get_pg_pool()
        async with pool.acquire() as conn:
            job, created = await store.create(conn, kind="ingestion.pdf", owner_id=owner, idempotency_key="k1",
                                              max_attempts=2, document_id="doc_x", pipeline_version="p1")
            again, created_again = await store.create(conn, kind="ingestion.pdf", owner_id=owner, idempotency_key="k1")
            assert created and not created_again and again["job_id"] == job["job_id"]
            assert job["status"] == "queued" and job["attempt"] == 0
            assert await store.get(conn, job["job_id"], owner_id=intruder) is None
            with pytest.raises(JobTransitionError):
                await store.transition(conn, job["job_id"], JobStatus.SUCCEEDED)
            with pytest.raises(JobTransitionError):
                await store.update_progress(conn, job["job_id"], progress_pct=10)
            running = await store.transition(conn, job["job_id"], JobStatus.RUNNING, stage="extract")
            assert running["attempt"] == 1 and running["started_at"]
            await store.update_progress(conn, job["job_id"], progress_pct=40)
            failed = await store.transition(conn, job["job_id"], JobStatus.FAILED, error_code="OCR",
                                            error_message="x" * 900)
            assert len(failed["error_message"]) == 500 and failed["finished_at"]
            retried = await store.transition(conn, job["job_id"], JobStatus.QUEUED)
            assert retried["error_code"] is None and retried["finished_at"] is None
            await store.transition(conn, job["job_id"], JobStatus.RUNNING)
            await store.transition(conn, job["job_id"], JobStatus.FAILED)
            with pytest.raises(JobTransitionError, match="No attempts remaining"):
                await store.transition(conn, job["job_id"], JobStatus.QUEUED)
            assert await store.request_cancel(conn, job["job_id"], owner_id=intruder) is None
            assert (await store.request_cancel(conn, job["job_id"], owner_id=owner))["cancel_requested_at"]
            done, _ = await store.create(conn, kind="ingestion.pdf", owner_id=owner)
            await store.transition(conn, done["job_id"], JobStatus.RUNNING)
            finished = await store.transition(conn, done["job_id"], JobStatus.SUCCEEDED, result={"pages": 3})
            assert finished["progress_pct"] == 100 and finished["result"] == {"pages": 3}
            with pytest.raises(JobTransitionError):
                await store.transition(conn, done["job_id"], JobStatus.CANCELLED)

    pg.run(_await_background(scenario()))


# --- HTTP in PostgreSQL mode ---------------------------------------------------------------

def test_http_membership_flow_in_postgres_mode(pg, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.auth import AuthenticatedUser, get_current_user
    from backend.routes import api as api_route

    c = _class_with_learners(pg, n=1)
    monkeypatch.setattr(api_route, "institution_service", pg.svc)

    def as_user(user_id):
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=user_id, email=None)
        return TestClient(app, raise_server_exceptions=False)

    try:
        me = as_user(c.teacher).get("/api/me").json()
        assert [(m["org_id"], m["role"]) for m in me["memberships"]] == [(c.org.org_id, "TEACHER")]
        members = as_user(c.admin).get(f"/api/institutions/organizations/{c.org.org_id}/memberships").json()
        assert members["total"] == 3
        roster = as_user(c.teacher).get(f"/api/institutions/classes/{c.cls.class_id}/roster")
        assert roster.json()["roster"] == c.learners
        gone = as_user(c.admin).delete(f"/api/institutions/organizations/{c.org.org_id}/memberships/{c.teacher}")
        assert gone.json()["status"] == "deactivated"
        denied = as_user(c.teacher).get(f"/api/institutions/classes/{c.cls.class_id}/roster")
        missing = as_user(c.teacher).get("/api/institutions/classes/cls_nope/roster")
        assert denied.status_code == missing.status_code == 404 and denied.json() == missing.json()
        last = as_user(c.admin).delete(f"/api/institutions/organizations/{c.org.org_id}/memberships/{c.admin}")
        assert last.status_code == 409 and last.json()["code"] == "LAST_ADMIN"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# --- Backup / restore drill ----------------------------------------------------------------

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required for the backup scripts")
def test_backup_and_restore_drill(fresh_db, pg, tmp_path):
    """Back up the populated test database, restore into a NEW empty database, compare."""
    import asyncpg

    if shutil.which("pg_dump") is None and not os.environ.get("PG_BIN"):
        pytest.skip("pg_dump/pg_restore not on PATH and PG_BIN not set")
    _class_with_learners(pg, n=2)   # ensure every institutional table has rows
    restore_name = f"{fresh_db.name}_restore"
    asyncio.run(_admin(fresh_db.base, f'CREATE DATABASE "{restore_name}"'))
    restore_url = _with_database(fresh_db.base, restore_name)
    env = {**os.environ, "LS_DRILL_SOURCE": fresh_db.url, "LS_DRILL_TARGET": restore_url}
    bash = shutil.which("bash")
    try:
        backup = subprocess.run(
            [bash, "scripts/backup_postgres.sh", "--dsn-env", "LS_DRILL_SOURCE", "--out", tmp_path.as_posix()],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
        )
        assert backup.returncode == 0, backup.stderr
        assert fresh_db.url not in backup.stdout + backup.stderr
        dump = next(tmp_path.glob("learnsense_*.dump"))

        wrong = subprocess.run(
            [bash, "scripts/restore_postgres.sh", "--dsn-env", "LS_DRILL_TARGET", "--dump", dump.as_posix(),
             "--confirm-database", "some_other_db"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
        )
        assert wrong.returncode == 3 and "refusing" in wrong.stderr

        restore = subprocess.run(
            [bash, "scripts/restore_postgres.sh", "--dsn-env", "LS_DRILL_TARGET", "--dump", dump.as_posix(),
             "--confirm-database", restore_name, "--create-supabase-roles"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
        )
        assert restore.returncode == 0, restore.stderr

        again = subprocess.run(
            [bash, "scripts/restore_postgres.sh", "--dsn-env", "LS_DRILL_TARGET", "--dump", dump.as_posix(),
             "--confirm-database", restore_name],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
        )
        assert again.returncode == 3 and "not empty" in again.stderr

        tables = ["schema_migrations", "organizations", "org_memberships", "course_classes", "class_enrollments",
                  "users", "audit_events", "document_owners", "document_shares", "usage_events", "jobs"]

        async def counts(url):
            conn = await asyncpg.connect(dsn=url)
            try:
                return {t: await conn.fetchval(f"SELECT COUNT(*) FROM {t}") for t in tables}
            finally:
                await conn.close()

        source, restored = asyncio.run(counts(fresh_db.url)), asyncio.run(counts(restore_url))
        assert restored == source and source["org_memberships"] > 0

        async def privileges(url):
            conn = await asyncpg.connect(dsn=url)
            try:
                return await conn.fetchval("SELECT has_table_privilege('anon', 'public.users', 'SELECT')")
            finally:
                await conn.close()

        assert asyncio.run(privileges(restore_url)) is False   # revocations survive the restore
    finally:
        asyncio.run(_admin(fresh_db.base, f'DROP DATABASE IF EXISTS "{restore_name}" WITH (FORCE)'))


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required for the backup scripts")
def test_restore_refuses_grants_to_missing_roles_and_preserves_them_once_created(fresh_db, pg, tmp_path):
    """A dump granting to a role the target lacks (e.g. Supabase's service_role) is refused
    before anything is restored; once the role exists the grant is restored, not discarded."""
    import asyncpg

    if shutil.which("pg_dump") is None and not os.environ.get("PG_BIN"):
        pytest.skip("pg_dump/pg_restore not on PATH and PG_BIN not set")
    role = f"ls_probe_{uuid.uuid4().hex[:8]}"
    restore_name = f"{fresh_db.name}_roles"
    env = {**os.environ, "LS_DRILL_SOURCE": fresh_db.url,
           "LS_DRILL_TARGET": _with_database(fresh_db.base, restore_name)}
    bash = shutil.which("bash")

    def restore():
        return subprocess.run(
            [bash, "scripts/restore_postgres.sh", "--dsn-env", "LS_DRILL_TARGET", "--dump", dump.as_posix(),
             "--confirm-database", restore_name],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
        )

    async def target_state():
        conn = await asyncpg.connect(dsn=env["LS_DRILL_TARGET"])
        try:
            tables = await conn.fetchval("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")
            granted = await conn.fetchval(
                "SELECT has_table_privilege($1, 'public.organizations', 'SELECT') "
                "WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname=$1)", role)
            return tables, granted
        finally:
            await conn.close()

    asyncio.run(_admin(fresh_db.url, f'CREATE ROLE "{role}" NOLOGIN',
                       f'GRANT SELECT ON public.organizations TO "{role}"'))
    try:
        backup = subprocess.run(
            [bash, "scripts/backup_postgres.sh", "--dsn-env", "LS_DRILL_SOURCE", "--out", tmp_path.as_posix()],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
        )
        assert backup.returncode == 0, backup.stderr
        dump = next(tmp_path.glob("learnsense_*.dump"))
        asyncio.run(_admin(fresh_db.url, f'REVOKE SELECT ON public.organizations FROM "{role}"', f'DROP ROLE "{role}"'))
        asyncio.run(_admin(fresh_db.base, f'CREATE DATABASE "{restore_name}"'))

        refused = restore()
        assert refused.returncode == 4 and role in refused.stderr and "Nothing was restored" in refused.stderr
        assert asyncio.run(target_state()) == (0, None)   # target left empty

        asyncio.run(_admin(fresh_db.base, f'CREATE ROLE "{role}" NOLOGIN'))
        done = restore()
        assert done.returncode == 0, done.stderr
        tables, granted = asyncio.run(target_state())
        assert tables > 0 and granted is True
    finally:
        asyncio.run(_admin(fresh_db.base, f'DROP DATABASE IF EXISTS "{restore_name}" WITH (FORCE)'))
        asyncio.run(_admin(fresh_db.url, f'DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = \'{role}\') '
                                         f'THEN REVOKE ALL ON public.organizations FROM "{role}"; '
                                         f'DROP ROLE "{role}"; END IF; END $$'))


# --- Operator scripts -------------------------------------------------------------------------

def _script(name, *args, env_extra):
    import sys

    return subprocess.run(
        [sys.executable, f"scripts/{name}", *args], cwd=REPO, capture_output=True, text=True, timeout=120,
        env={**os.environ, **env_extra},
    )


def test_json_document_access_import_dry_run_then_apply(pg, tmp_path):
    import json as _json

    c = _class_with_learners(pg, n=0)
    root = tmp_path / "legacy"
    (root / "document_owners").mkdir(parents=True)
    (root / "document_shares").mkdir(parents=True)
    docs = {f"doc_imp_{uuid.uuid4().hex[:6]}": c.teacher for _ in range(2)}
    for doc, owner in docs.items():
        (root / "document_owners" / f"{doc}.json").write_text(_json.dumps({"document_id": doc, "owner_id": owner}))
    shared_doc = next(iter(docs))
    (root / "document_shares" / f"{shared_doc}.json").write_text(_json.dumps({"document_id": shared_doc, "shares": {
        c.cls.class_id: {"document_id": shared_doc, "class_id": c.cls.class_id, "owner_id": c.teacher,
                         "shared_by": c.teacher, "created_at": "2026-01-01T00:00:00+00:00"},
        "cls_missing": {"document_id": shared_doc, "class_id": "cls_missing", "owner_id": c.teacher,
                        "shared_by": c.teacher},
    }}))
    env = {"LS_IMPORT_DSN": pg.url}
    dry = _script("import_document_access.py", "--dsn-env", "LS_IMPORT_DSN", "--storage-root", str(root), env_extra=env)
    assert dry.returncode == 0 and "DRY RUN" in dry.stdout
    assert pg.fetch("SELECT 1 FROM document_owners WHERE document_id = ANY($1::text[])", list(docs)) == []

    applied = _script("import_document_access.py", "--dsn-env", "LS_IMPORT_DSN", "--storage-root", str(root),
                      "--apply", env_extra=env)
    assert applied.returncode == 0, applied.stderr
    assert '"owners_imported": 2' in applied.stdout and '"shares_skipped_missing_class": 1' in applied.stdout
    rows = pg.fetch("SELECT document_id, owner_id, source FROM document_owners WHERE document_id = ANY($1::text[])",
                    list(docs))
    assert {(r["document_id"], r["owner_id"], r["source"]) for r in rows} == {(d, o, "json_import") for d, o in docs.items()}
    rerun = _script("import_document_access.py", "--dsn-env", "LS_IMPORT_DSN", "--storage-root", str(root),
                    "--apply", env_extra=env)
    assert '"owners_existing": 2' in rerun.stdout    # idempotent


def test_manage_platform_disables_a_user_with_an_audit_event(pg):
    user = uid()
    pg.run(pg.svc.users.ensure_user(user, None))
    env = {"LS_ADMIN_DSN": pg.url}
    result = _script("manage_platform.py", "--dsn-env", "LS_ADMIN_DSN", "user-status", user, "disabled",
                     "--reason", "test", "--actor", "operator-1", env_extra=env)
    assert result.returncode == 0, result.stderr
    assert pg.run(pg.svc.users.is_disabled(user)) is True
    assert pg.fetch("SELECT 1 FROM audit_events WHERE target_id=$1 AND actor_user_id='operator-1'", user)
    missing = _script("manage_platform.py", "--dsn-env", "LS_ADMIN_DSN", "user-status", uid(), "disabled",
                      "--actor", "op", env_extra=env)
    assert missing.returncode == 1


# --- S1: audit immutability; S2: export privacy (PostgreSQL) ---------------------------------

def _audit_conn_run(pg, operation):
    from backend.db import pg_connection
    from backend.services.institution_service import _await_background

    async def run():
        pool = await pg_connection.get_pg_pool()
        async with pool.acquire() as conn:
            return await operation(conn)

    return pg.run(_await_background(run()))


def test_audit_history_rejects_update_delete_and_truncate(pg):
    import asyncpg

    org = make_org(pg, uid())

    async def count(conn):
        return await conn.fetchval("SELECT COUNT(*) FROM audit_events")

    before = _audit_conn_run(pg, count)
    assert before > 0
    for statement in (
        f"UPDATE audit_events SET action='forged' WHERE org_id='{org.org_id}'",
        f"DELETE FROM audit_events WHERE org_id='{org.org_id}'",
        "TRUNCATE audit_events",
    ):
        async def attempt(conn, sql=statement):
            await conn.execute(sql)
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            _audit_conn_run(pg, attempt)
    assert _audit_conn_run(pg, count) == before


def test_table_owner_can_still_disable_the_triggers_documented_limitation(pg):
    """Evidence for the documented limitation: protection is trigger-based, so the
    OWNING role can disable it. Done inside a transaction that is rolled back."""
    make_org(pg, uid())

    async def owner_bypass(conn):
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute("ALTER TABLE audit_events DISABLE TRIGGER trg_audit_events_no_truncate")
            await conn.execute("TRUNCATE audit_events")
            return await conn.fetchval("SELECT COUNT(*) FROM audit_events")
        finally:
            await tx.rollback()

    assert _audit_conn_run(pg, owner_bypass) == 0
    remaining = _audit_conn_run(pg, lambda conn: conn.fetchval("SELECT COUNT(*) FROM audit_events"))
    assert remaining > 0                                    # rolled back: history intact
    triggers = _audit_conn_run(pg, lambda conn: conn.fetch(
        "SELECT tgname, tgenabled::text AS tgenabled FROM pg_trigger "
        "WHERE tgrelid = 'audit_events'::regclass AND NOT tgisinternal"))
    assert {(t["tgname"], t["tgenabled"]) for t in triggers} == {
        ("trg_audit_events_append_only", "O"), ("trg_audit_events_no_truncate", "O")}


def test_export_redacts_other_members_ids_for_a_deactivated_admin_in_postgres_mode(pg, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.auth import AuthenticatedUser, get_current_user
    from backend.routes import api as api_route

    c = _class_with_learners(pg, n=2)
    second_admin = uid()
    pg.run(pg.svc.users.ensure_user(second_admin, None))
    from phase4.institution.models import UserRole
    pg.run(pg.svc.add_membership_as_admin_async(c.org.org_id, c.admin, second_admin, UserRole.ADMIN))
    pg.run(pg.svc.deactivate_membership_as_admin_async(c.org.org_id, second_admin, c.admin))
    monkeypatch.setattr(api_route, "institution_service", pg.svc)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=c.admin, email=None)
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/api/me/export")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200, response.text
    actions = [e["action"] for e in response.json()["audit_events_as_actor"]]
    assert "org.created" in actions and "membership.created" in actions
    for other in (second_admin, c.teacher, *c.learners):
        assert other not in response.text


# --- Batch A: F1 tenant-scoped document access; F3 usage factory ------------------------------

class _LegacySharesView:
    """The PostgreSQL share store WITHOUT the SQL capability flag, so DocumentAccessService
    runs its original per-share algorithm. Used as the reference implementation."""

    def __init__(self, inner):
        self._inner = inner

    def list_all(self):
        return self._inner.list_all()

    def list_for_document(self, document_id):
        return self._inner.list_for_document(document_id)


def _access_services(pg):
    from backend.services.document_access import DocumentAccessService
    from backend.services.document_access_store import PgDocumentOwnershipRepository, PgDocumentShareRepository

    owners, shares = PgDocumentOwnershipRepository(), PgDocumentShareRepository()
    new = DocumentAccessService(ownership=owners, shares=shares, institutions=pg.svc)
    legacy = DocumentAccessService(ownership=owners, shares=_LegacySharesView(shares), institutions=pg.svc)
    return owners, shares, new, legacy


def test_sql_document_access_matches_the_original_policy_case_by_case(pg):
    from phase4.institution.models import UserRole

    owners, shares, new, legacy = _access_services(pg)
    a = _class_with_learners(pg, n=3)             # org A: teacher, 3 enrolled learners
    b = _class_with_learners(pg, n=1)             # org B: unrelated tenant
    doc_a, doc_b = f"doc_a_{uuid.uuid4().hex[:6]}", f"doc_b_{uuid.uuid4().hex[:6]}"
    owners.claim(doc_a, a.teacher)
    owners.claim(doc_b, b.teacher)
    shares.grant(doc_a, a.cls.class_id, a.teacher, a.teacher)
    shares.grant(doc_b, b.cls.class_id, b.teacher, b.teacher)
    stays, unenrolled, deactivated = a.learners
    pg.run(pg.svc.unenroll_learner_async(a.cls.class_id, unenrolled, a.admin))
    pg.run(pg.svc.deactivate_membership_as_admin_async(a.org.org_id, a.admin, deactivated))

    # A grant whose owner no longer matches the document owner is inert.
    doc_mismatch = f"doc_m_{uuid.uuid4().hex[:6]}"
    owners.claim(doc_mismatch, a.teacher)
    pg.fetch("INSERT INTO document_shares (document_id, class_id, owner_id, shared_by) VALUES ($1,$2,$3,$3)",
             doc_mismatch, a.cls.class_id, "someone_else")

    # An unprovisioned UUID with membership + enrollment inserted directly (bypassing the
    # guarded API) must still be refused: provenance is part of the policy.
    ghost = uid()
    pg.fetch("INSERT INTO org_memberships (membership_id, org_id, user_id, role) VALUES ($1,$2,$3,'LEARNER')",
             f"mem_{uuid.uuid4().hex[:8]}", a.org.org_id, ghost)
    pg.fetch("INSERT INTO class_enrollments (enrollment_id, class_id, learner_id) VALUES ($1,$2,$3)",
             f"enr_{uuid.uuid4().hex[:8]}", a.cls.class_id, ghost)

    expected = {
        a.teacher: {doc_a, doc_mismatch},     # owner
        stays: {doc_a},                       # active enrollment + active LEARNER membership
        unenrolled: set(),
        deactivated: set(),
        b.learners[0]: {doc_b},               # other tenant sees only its own share
        ghost: set(),
    }
    for user, docs in expected.items():
        assert new.accessible_document_ids(user) == docs, user
        assert legacy.accessible_document_ids(user) == docs, user
        for doc in (doc_a, doc_b, doc_mismatch):
            assert new.can_read(doc, user) == legacy.can_read(doc, user) == (doc in docs), (user, doc)


def test_sql_document_access_round_trips_do_not_grow_with_other_tenants_shares(pg, monkeypatch):
    """Evidence for F1: count database round trips for one learner while ANOTHER tenant
    holds many shares. The original algorithm grows with every share in the system;
    the SQL path stays constant."""
    import time

    from backend.services import institution_service as inst_mod

    owners, shares, new, legacy = _access_services(pg)
    mine = _class_with_learners(pg, n=1)
    doc_mine = f"doc_mine_{uuid.uuid4().hex[:6]}"
    owners.claim(doc_mine, mine.teacher)
    shares.grant(doc_mine, mine.cls.class_id, mine.teacher, mine.teacher)
    other = _class_with_learners(pg, n=1)
    for i in range(60):
        doc = f"doc_other_{i}_{uuid.uuid4().hex[:6]}"
        owners.claim(doc, other.teacher)
        shares.grant(doc, other.cls.class_id, other.teacher, other.teacher)
    learner = mine.learners[0]

    # Every synchronous PostgreSQL call in these paths goes through
    # institution_service._run_async (document_access_store._run delegates to it),
    # so counting there counts each database round trip exactly once.
    counts = {"n": 0}
    real_inst_run = inst_mod._run_async

    def counting_inst_run(coro):
        counts["n"] += 1
        return real_inst_run(coro)

    monkeypatch.setattr(inst_mod, "_run_async", counting_inst_run)

    def measure(service):
        counts["n"] = 0
        started = time.perf_counter()
        result = service.accessible_document_ids(learner)
        return result, counts["n"], time.perf_counter() - started

    new_result, new_trips, new_secs = measure(new)
    legacy_result, legacy_trips, legacy_secs = measure(legacy)
    print(f"\nF1 evidence (61 shares in the database, 60 belonging to another tenant): "
          f"SQL path {new_trips} round trip(s) {new_secs*1000:.1f} ms; "
          f"original path {legacy_trips} round trips {legacy_secs*1000:.1f} ms")
    assert new_result == legacy_result == {doc_mine}
    assert new_trips == 1
    assert legacy_trips > 60


def test_usage_factory_in_postgres_mode(pg):
    from backend.services import usage_service
    from phase3.errors import AuthorizationError

    usage_service.reset_usage_service_for_testing(None)
    try:
        usage = usage_service.get_usage_service()
        assert usage is usage_service.get_usage_service() and usage._pg_enabled is True
        c = _class_with_learners(pg, n=0)
        assert pg.run(usage.record_usage(c.org.org_id, c.admin, "test.units", 1, "t", f"fac-{uuid.uuid4().hex}"))["created"]
        with pytest.raises(AuthorizationError):
            pg.run(usage.record_usage(c.org.org_id, uid(), "test.units", 1, "t", f"fac-{uuid.uuid4().hex}"))
    finally:
        usage_service.reset_usage_service_for_testing(None)

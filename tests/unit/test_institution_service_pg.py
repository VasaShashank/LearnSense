"""
Unit tests for InstitutionService.

Tests exercise the service in JSON-only mode (DATABASE_URL unset), which is the
mode that runs without a real PostgreSQL server.  PostgreSQL-mode behavior is
covered by test_institution_repository.py (repository layer) and
test_pg_tenant_isolation.py (service+PG integration).

Key behaviors tested:
  * Organizations can be created and retrieved.
  * Memberships enforce uniqueness semantics.
  * require_role raises AuthorizationError for wrong roles.
  * create_class enforces creator authorization.
  * enroll_learner requires ADMIN/TEACHER in the class's org.
  * Cross-tenant roster access is blocked.
  * Class creation cross-syncs to storage/classes.
  * With LEARNSENSE_REQUIRE_PG=1 and no DATABASE_URL, __init__ raises RuntimeError.
"""

from __future__ import annotations

import os
import uuid
import pytest
from pathlib import Path

from phase4.institution.models import UserRole
from phase3.errors import AuthorizationError
from phase3.learner.models import LearnerState
from phase3.storage.learner_repository import LearnerStateRepository


LEARNER_1 = str(uuid.UUID("a20d9df0-2792-4fc2-9d94-20ac476863e0"))
LEARNER_2 = str(uuid.UUID("bb1d9df0-2792-4fc2-9d94-20ac476863e0"))


def _provision_fixture_learner(service, learner_id):
    service.learner_state_repo.save_state(
        LearnerState(learner_id=learner_id, identity_provider="supabase")
    )


# ---------------------------------------------------------------------------
# Fixture: isolated InstitutionService in JSON mode
# ---------------------------------------------------------------------------

@pytest.fixture()
def svc(tmp_path, monkeypatch):
    """Create an InstitutionService backed by a temp dir, in JSON mode."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    monkeypatch.chdir(tmp_path)
    from backend.services.institution_service import InstitutionService
    return InstitutionService(
        base_dir=str(tmp_path / "institutions"),
        learner_state_repo=LearnerStateRepository(str(tmp_path / "learner_states")),
    )


# ---------------------------------------------------------------------------
# Organization tests
# ---------------------------------------------------------------------------

class TestOrganizations:
    def test_create_and_retrieve(self, svc):
        org = svc.create_organization(name="Alpha University", domain="alpha.edu")
        assert org.org_id.startswith("org_")
        assert org.name == "Alpha University"
        assert org.domain == "alpha.edu"

        fetched = svc.get_organization(org.org_id)
        assert fetched is not None
        assert fetched.org_id == org.org_id

    def test_get_missing_returns_none(self, svc):
        assert svc.get_organization("org_nonexistent") is None

    def test_list_returns_all_orgs(self, svc):
        svc.create_organization(name="Alpha")
        svc.create_organization(name="Beta")
        orgs = svc.list_organizations()
        names = [o.name for o in orgs]
        assert "Alpha" in names
        assert "Beta" in names

    def test_list_seeds_demo_org_when_empty(self, svc):
        orgs = svc.list_organizations()
        assert len(orgs) >= 1
        assert any("Apex" in o.name for o in orgs)


# ---------------------------------------------------------------------------
# Membership tests
# ---------------------------------------------------------------------------

class TestMemberships:
    def test_add_and_get_membership(self, svc):
        org = svc.create_organization(name="Delta")
        mem = svc.add_membership(org.org_id, "user-A", UserRole.TEACHER)
        assert mem.org_id == org.org_id
        assert mem.user_id == "user-A"
        assert mem.role == UserRole.TEACHER
        assert mem.is_active is True

    def test_get_missing_membership_returns_none(self, svc):
        org = svc.create_organization(name="Epsilon")
        assert svc.get_membership(org.org_id, "no-such-user") is None

    def test_overwriting_membership_updates_file(self, svc):
        org = svc.create_organization(name="Zeta")
        svc.add_membership(org.org_id, "u1", UserRole.LEARNER)
        svc.add_membership(org.org_id, "u1", UserRole.TEACHER)
        mem = svc.get_membership(org.org_id, "u1")
        assert mem.role == UserRole.TEACHER


# ---------------------------------------------------------------------------
# require_role tests
# ---------------------------------------------------------------------------

class TestRequireRole:
    def test_correct_role_passes(self, svc):
        org = svc.create_organization(name="Eta")
        svc.add_membership(org.org_id, "admin-u", UserRole.ADMIN)
        mem = svc.require_role(org.org_id, "admin-u", [UserRole.ADMIN, UserRole.TEACHER])
        assert mem.role == UserRole.ADMIN

    def test_wrong_role_raises_authorization_error(self, svc):
        org = svc.create_organization(name="Theta")
        svc.add_membership(org.org_id, "learner-u", UserRole.LEARNER)
        with pytest.raises(AuthorizationError):
            svc.require_role(org.org_id, "learner-u", [UserRole.ADMIN, UserRole.TEACHER])

    def test_no_membership_raises_authorization_error(self, svc):
        org = svc.create_organization(name="Iota")
        with pytest.raises(AuthorizationError):
            svc.require_role(org.org_id, "ghost-user", [UserRole.ADMIN])

    def test_require_role_never_trusts_client_org_id(self, svc):
        """A caller who is admin in org1 must not gain access to org2 resources."""
        org1 = svc.create_organization(name="Org1")
        org2 = svc.create_organization(name="Org2")
        svc.add_membership(org1.org_id, "admin-u", UserRole.ADMIN)
        # admin-u has no membership in org2 — must be denied.
        with pytest.raises(AuthorizationError):
            svc.require_role(org2.org_id, "admin-u", [UserRole.ADMIN])


# ---------------------------------------------------------------------------
# Class creation tests
# ---------------------------------------------------------------------------

class TestClassCreation:
    def test_teacher_can_create_class(self, svc):
        org = svc.create_organization(name="Kappa")
        svc.add_membership(org.org_id, "teacher-u", UserRole.TEACHER)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id="subj_1",
            title="Physics I",
            teacher_ids=["teacher-u"],
            creator_user_id="teacher-u",
        )
        assert cls.class_id.startswith("cls_")
        assert cls.org_id == org.org_id

    def test_admin_can_create_class(self, svc):
        org = svc.create_organization(name="Lambda")
        svc.add_membership(org.org_id, "admin-u", UserRole.ADMIN)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id="subj_2",
            title="Chemistry I",
            teacher_ids=[],
            creator_user_id="admin-u",
        )
        assert cls.class_id.startswith("cls_")

    def test_learner_cannot_create_class(self, svc):
        org = svc.create_organization(name="Mu")
        svc.add_membership(org.org_id, "learner-u", UserRole.LEARNER)
        with pytest.raises(AuthorizationError):
            svc.create_class(
                org_id=org.org_id,
                subject_id="subj_3",
                title="Unauthorized",
                teacher_ids=[],
                creator_user_id="learner-u",
            )

    def test_class_synced_to_teacher_storage(self, svc, tmp_path):
        """Class creation must project into storage/classes for teacher_service."""
        org = svc.create_organization(name="Nu")
        svc.add_membership(org.org_id, "t-u", UserRole.TEACHER)
        svc.add_membership(org.org_id, LEARNER_1, UserRole.LEARNER)
        svc.add_membership(org.org_id, LEARNER_2, UserRole.LEARNER)
        _provision_fixture_learner(svc, LEARNER_1)
        _provision_fixture_learner(svc, LEARNER_2)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id="subj_sync",
            title="Synced Class",
            teacher_ids=["t-u"],
            creator_user_id="t-u",
            enrolled_learner_ids=[LEARNER_1, LEARNER_2],
        )
        teacher_file = Path("storage/classes") / f"{cls.class_id}.json"
        assert teacher_file.exists(), "Class must be projected to storage/classes"
        import json
        with open(teacher_file) as f:
            data = json.load(f)
        assert data["class_id"] == cls.class_id
        assert set(data["enrolled_learner_ids"]) == {LEARNER_1, LEARNER_2}


# ---------------------------------------------------------------------------
# Enrollment tests
# ---------------------------------------------------------------------------

class TestEnrollment:
    def _setup_class(self, svc):
        org = svc.create_organization(name="Xi")
        svc.add_membership(org.org_id, "teacher-u", UserRole.TEACHER)
        svc.add_membership(org.org_id, LEARNER_1, UserRole.LEARNER)
        _provision_fixture_learner(svc, LEARNER_1)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id="subj_e",
            title="Enroll Test",
            teacher_ids=["teacher-u"],
            creator_user_id="teacher-u",
        )
        return org, cls

    def test_teacher_can_enroll_learner(self, svc):
        org, cls = self._setup_class(svc)
        enr = svc.enroll_learner(
            class_id=cls.class_id,
            learner_id=LEARNER_1,
            enroller_user_id="teacher-u",
        )
        assert enr.class_id == cls.class_id
        assert enr.learner_id == LEARNER_1

    def test_learner_cannot_enroll(self, svc):
        org, cls = self._setup_class(svc)
        with pytest.raises(AuthorizationError):
            svc.enroll_learner(
                class_id=cls.class_id,
                learner_id=LEARNER_1,
                enroller_user_id="learner-u",
            )

    def test_enroll_nonexistent_class_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="does not exist"):
            svc.enroll_learner(
                class_id="cls_fake",
                learner_id="l1",
                enroller_user_id="t1",
            )


# ---------------------------------------------------------------------------
# Roster / cross-tenant isolation tests
# ---------------------------------------------------------------------------

class TestRosterAndTenantIsolation:
    def test_teacher_sees_roster(self, svc):
        org = svc.create_organization(name="Omicron")
        svc.add_membership(org.org_id, "t1", UserRole.TEACHER)
        svc.add_membership(org.org_id, LEARNER_1, UserRole.LEARNER)
        _provision_fixture_learner(svc, LEARNER_1)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id="s1",
            title="Roster Test",
            teacher_ids=["t1"],
            creator_user_id="t1",
        )
        svc.enroll_learner(cls.class_id, LEARNER_1, enroller_user_id="t1")
        roster = svc.get_class_roster(cls.class_id, caller_user_id="t1")
        assert LEARNER_1 in roster

    def test_unassigned_teacher_cannot_read_class_roster(self, svc):
        org = svc.create_organization(name="Assignment boundary")
        svc.add_membership(org.org_id, "assigned", UserRole.TEACHER)
        svc.add_membership(org.org_id, "other-teacher", UserRole.TEACHER)
        cls = svc.create_class(
            org_id=org.org_id, subject_id="s", title="Assigned",
            teacher_ids=["assigned"], creator_user_id="assigned",
        )
        with pytest.raises(AuthorizationError):
            svc.get_class_roster(cls.class_id, caller_user_id="other-teacher")

    def test_class_creation_rejects_nonmember_roster_and_teacher(self, svc):
        org = svc.create_organization(name="Membership validation")
        svc.add_membership(org.org_id, "admin", UserRole.ADMIN)
        with pytest.raises(AuthorizationError):
            svc.create_class(
                org_id=org.org_id, subject_id="s", title="Invalid teacher",
                teacher_ids=["not-a-teacher"], creator_user_id="admin",
            )
        svc.add_membership(org.org_id, "teacher", UserRole.TEACHER)
        with pytest.raises(AuthorizationError):
            svc.create_class(
                org_id=org.org_id, subject_id="s", title="Invalid learner",
                teacher_ids=["teacher"], creator_user_id="admin",
                enrolled_learner_ids=["not-a-learner"],
            )

    def test_cross_tenant_roster_access_is_blocked(self, svc):
        """An intruder from org2 must NOT read org1's class roster."""
        org1 = svc.create_organization(name="Pi")
        org2 = svc.create_organization(name="Rho")

        svc.add_membership(org1.org_id, "t1", UserRole.TEACHER)
        svc.add_membership(org2.org_id, "intruder", UserRole.TEACHER)

        cls = svc.create_class(
            org_id=org1.org_id,
            subject_id="s1",
            title="Secret Class",
            teacher_ids=["t1"],
            creator_user_id="t1",
        )

        with pytest.raises(AuthorizationError):
            svc.get_class_roster(cls.class_id, caller_user_id="intruder")

    def test_roster_for_nonexistent_class_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="does not exist"):
            svc.get_class_roster("cls_fake", caller_user_id="anyone")

    def test_learner_cannot_read_roster(self, svc):
        org = svc.create_organization(name="Sigma")
        svc.add_membership(org.org_id, "t1", UserRole.TEACHER)
        svc.add_membership(org.org_id, "l1", UserRole.LEARNER)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id="s2",
            title="Learner Block Test",
            teacher_ids=["t1"],
            creator_user_id="t1",
        )
        with pytest.raises(AuthorizationError):
            svc.get_class_roster(cls.class_id, caller_user_id="l1")


# ---------------------------------------------------------------------------
# Production enforcement
# ---------------------------------------------------------------------------

class TestProductionEnforcement:
    def test_require_pg_without_database_url_raises(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "1")
        from backend.services import institution_service as _mod
        # Force re-import to pick up env changes
        import importlib
        importlib.reload(_mod)
        with pytest.raises(RuntimeError, match="LEARNSENSE_REQUIRE_PG"):
            _mod.InstitutionService()
        # Cleanup: reload without env var
        monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
        importlib.reload(_mod)


def test_create_organization_with_admin_assigns_creator(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    from backend.services.institution_service import InstitutionService

    service = InstitutionService(base_dir=str(tmp_path / "orgs"))
    org = asyncio.run(
        service.create_organization_with_admin_async(
            name="Creator Admin Org",
            domain="creator.example",
            creator_user_id="auth-user-1",
        )
    )
    membership = service.get_membership(org.org_id, "auth-user-1")
    assert membership is not None
    assert membership.role == UserRole.ADMIN
    assert membership.is_active is True


def test_add_membership_requires_active_admin(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    from backend.services.institution_service import InstitutionService

    service = InstitutionService(base_dir=str(tmp_path / "orgs"))
    org = service.create_organization(name="Membership Auth Org")
    service.add_membership(org.org_id, "learner-user", UserRole.LEARNER)

    with pytest.raises(AuthorizationError):
        asyncio.run(
            service.add_membership_as_admin_async(
                org_id=org.org_id,
                acting_user_id="learner-user",
                target_user_id="target-user",
                role=UserRole.ADMIN,
            )
        )

    assert service.get_membership(org.org_id, "target-user") is None


def test_list_organizations_for_user_only_returns_active_memberships(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    from backend.services.institution_service import InstitutionService

    service = InstitutionService(base_dir=str(tmp_path / "orgs"))
    org1 = service.create_organization(name="Visible Org")
    org2 = service.create_organization(name="Hidden Org")
    service.add_membership(org1.org_id, "user-1", UserRole.LEARNER)
    service.add_membership(org2.org_id, "user-2", UserRole.LEARNER)

    visible = asyncio.run(service.list_organizations_for_user_async("user-1"))
    assert [org.org_id for org in visible] == [org1.org_id]


def test_list_classes_for_user_only_returns_active_tenant_classes(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    from backend.services.institution_service import InstitutionService

    service = InstitutionService(base_dir=str(tmp_path / "orgs"))
    org1 = service.create_organization(name="Visible Classes")
    org2 = service.create_organization(name="Hidden Classes")
    service.add_membership(org1.org_id, "user-1", UserRole.TEACHER)
    service.add_membership(org2.org_id, "user-1", UserRole.LEARNER)
    service.add_membership(org2.org_id, "user-2", UserRole.TEACHER)
    class1 = service.create_class(
        org_id=org1.org_id, subject_id="s1", title="Visible",
        teacher_ids=["user-1"], creator_user_id="user-1",
    )
    class2 = service.create_class(
        org_id=org2.org_id, subject_id="s2", title="Hidden",
        teacher_ids=["user-2"], creator_user_id="user-2",
    )
    service.add_membership(org2.org_id, "user-1", UserRole.LEARNER)
    inactive_path = service.members_dir / f"{org2.org_id}_user-1.json"
    import json
    payload = json.loads(inactive_path.read_text(encoding="utf-8"))
    payload["is_active"] = False
    inactive_path.write_text(json.dumps(payload), encoding="utf-8")

    visible = asyncio.run(service.list_classes_for_user_async("user-1"))
    assert [course_class.class_id for course_class in visible] == [class1.class_id]
    assert asyncio.run(
        service.list_classes_for_user_async("user-1", org_id=org2.org_id)
    ) == []


def test_pg_initial_admin_failure_propagates_inside_transaction(tmp_path, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from backend.services.institution_service import InstitutionService

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    service = InstitutionService(base_dir=str(tmp_path / "orgs"))
    events = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            events.append("transaction-start")
            try:
                yield
            except Exception:
                events.append("transaction-rollback")
                raise
            else:
                events.append("transaction-commit")

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    class Repo:
        async def create_organization(self, conn, **kwargs):
            events.append("organization-insert")
            return None

        async def create_membership(self, conn, **kwargs):
            events.append("admin-insert-failed")
            raise RuntimeError("membership insert failed")

    async def fake_pool():
        return Pool()

    service._pool = fake_pool
    service._repo = Repo()
    with pytest.raises(RuntimeError, match="membership insert failed"):
        asyncio.run(
            service._pg_create_organization_with_admin(
                "org_test", "mem_test", "Atomic Org", None, "creator"
            )
        )
    assert events == [
        "transaction-start", "organization-insert", "admin-insert-failed",
        "transaction-rollback",
    ]


def test_pg_pool_is_created_once_for_concurrent_first_requests(monkeypatch):
    import asyncio
    from backend.db import pg_connection

    calls = []
    fake_pool = object()

    class FakeAsyncpg:
        @staticmethod
        async def create_pool(**kwargs):
            calls.append(kwargs)
            await asyncio.sleep(0)
            return fake_pool

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(pg_connection, "_pool", None)
    monkeypatch.setattr(pg_connection, "_pool_lock", None)
    monkeypatch.setattr(pg_connection, "asyncpg", FakeAsyncpg)
    monkeypatch.setattr(pg_connection, "_asyncpg_available", True)

    async def get_together():
        return await asyncio.gather(
            pg_connection.get_pg_pool(), pg_connection.get_pg_pool()
        )

    pools = asyncio.run(get_together())
    assert pools == [fake_pool, fake_pool]
    assert len(calls) == 1

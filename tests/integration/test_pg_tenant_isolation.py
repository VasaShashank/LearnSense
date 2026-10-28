"""
Integration tests for cross-tenant isolation and schema expectations.

These tests exercise the InstitutionService in JSON mode (no real database
required) and validate the API-level authentication enforcement.  Tests are
designed to pass with only the filesystem backend so CI does not need a
Supabase connection.

A separate section marks tests that require a real DATABASE_URL and are
skipped automatically when not configured.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helper: build an isolated service
# ---------------------------------------------------------------------------

@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)
    from backend.services.institution_service import InstitutionService
    return InstitutionService(base_dir=str(tmp_path / "inst"))


# ---------------------------------------------------------------------------
# Cross-tenant isolation via service layer
# ---------------------------------------------------------------------------

class TestCrossTenantIsolation:
    """Verify that a principal in org2 cannot access resources owned by org1."""

    def _build_org_with_teacher_and_class(self, svc, org_name, teacher_id, subject="s1"):
        from phase4.institution.models import UserRole
        org = svc.create_organization(name=org_name)
        svc.add_membership(org.org_id, teacher_id, UserRole.TEACHER)
        cls = svc.create_class(
            org_id=org.org_id,
            subject_id=subject,
            title=f"{org_name} Class",
            teacher_ids=[teacher_id],
            creator_user_id=teacher_id,
        )
        return org, cls

    def test_teacher_in_org2_cannot_read_org1_roster(self, svc):
        from phase3.errors import AuthorizationError
        from phase4.institution.models import UserRole

        org1, cls1 = self._build_org_with_teacher_and_class(svc, "University A", "teacher_a")
        org2, _cls2 = self._build_org_with_teacher_and_class(svc, "University B", "teacher_b")

        with pytest.raises(AuthorizationError):
            svc.get_class_roster(cls1.class_id, caller_user_id="teacher_b")

    def test_teacher_in_org2_cannot_enroll_into_org1_class(self, svc):
        from phase3.errors import AuthorizationError
        from phase4.institution.models import UserRole

        org1, cls1 = self._build_org_with_teacher_and_class(svc, "Univ C", "t_c")
        org2, _ = self._build_org_with_teacher_and_class(svc, "Univ D", "t_d")

        with pytest.raises(AuthorizationError):
            svc.enroll_learner(cls1.class_id, "some_learner", enroller_user_id="t_d")

    def test_teacher_in_org2_cannot_create_class_in_org1(self, svc):
        from phase3.errors import AuthorizationError
        from phase4.institution.models import UserRole

        org1, _ = self._build_org_with_teacher_and_class(svc, "Univ E", "t_e")
        org2, _ = self._build_org_with_teacher_and_class(svc, "Univ F", "t_f")

        with pytest.raises(AuthorizationError):
            svc.create_class(
                org_id=org1.org_id,
                subject_id="s_x",
                title="Intruder Class",
                teacher_ids=["t_f"],
                creator_user_id="t_f",
            )

    def test_cross_org_class_id_guessing_blocked(self, svc):
        """
        A caller who knows a class_id must not bypass org isolation by supplying
        a class_id from a different tenant.  The service fetches the class first,
        discovers the real org_id, and then checks the caller's membership in
        THAT org — never in a caller-supplied org.
        """
        from phase3.errors import AuthorizationError
        from phase4.institution.models import UserRole

        org1, cls1 = self._build_org_with_teacher_and_class(svc, "Univ G", "t_g")
        org2, _ = self._build_org_with_teacher_and_class(svc, "Univ H", "t_h")

        # t_h knows cls1.class_id (from URL sniffing) but belongs to org2.
        with pytest.raises(AuthorizationError):
            svc.get_class_roster(cls1.class_id, caller_user_id="t_h")


# ---------------------------------------------------------------------------
# Schema / migration expectations (no DB needed — structural checks only)
# ---------------------------------------------------------------------------

class TestMigrationFileExists:
    def test_migration_001_exists(self):
        migration_path = Path("migrations/001_institutional_schema.sql")
        assert migration_path.exists(), (
            "migrations/001_institutional_schema.sql must exist. "
            "Run: psql $DATABASE_URL -f migrations/001_institutional_schema.sql"
        )

    def test_migration_contains_required_tables(self):
        migration_path = Path("migrations/001_institutional_schema.sql")
        sql = migration_path.read_text(encoding="utf-8").lower()
        required_tables = [
            "organizations",
            "org_memberships",
            "course_classes",
            "class_enrollments",
            "schema_migrations",
        ]
        for table in required_tables:
            assert table in sql, f"Migration must create table '{table}'"

    def test_migration_includes_foreign_keys(self):
        migration_path = Path("migrations/001_institutional_schema.sql")
        sql = migration_path.read_text(encoding="utf-8").lower()
        assert "references organizations" in sql, "org_memberships must reference organizations"
        assert "references course_classes" in sql, "class_enrollments must reference course_classes"

    def test_migration_enables_default_deny_row_security(self):
        sql = Path("migrations/001_institutional_schema.sql").read_text(encoding="utf-8").lower()
        for table in (
            "organizations", "org_memberships", "course_classes", "class_enrollments"
        ):
            assert f"alter table {table} enable row level security" in sql

    def test_migration_enforces_case_insensitive_organization_names(self):
        sql = Path("migrations/001_institutional_schema.sql").read_text(encoding="utf-8").lower()
        assert "create unique index if not exists uq_organizations_name_ci" in sql
        assert "on organizations (lower(name))" in sql

    def test_migration_is_idempotent(self):
        """Migration must use IF NOT EXISTS / ON CONFLICT DO NOTHING."""
        migration_path = Path("migrations/001_institutional_schema.sql")
        sql = migration_path.read_text(encoding="utf-8").lower()
        assert "if not exists" in sql, "Migration must use IF NOT EXISTS for idempotency"
        assert "on conflict" in sql, "Migration must use ON CONFLICT DO NOTHING for idempotency"


# ---------------------------------------------------------------------------
# API-level authentication enforcement (no DB required)
# ---------------------------------------------------------------------------

class TestApiAuthEnforcement:
    """Verify that the roster endpoint still enforces authentication after the refactor."""

    def test_roster_endpoint_rejects_missing_token(self):
        from fastapi.testclient import TestClient
        from backend.app import app

        client = TestClient(app)
        response = client.get("/api/institutions/classes/class-xyz/roster")
        assert response.status_code == 401

    def test_roster_endpoint_uses_verified_identity(self, monkeypatch):
        """The endpoint must NOT accept a caller_user_id query parameter."""
        from fastapi.testclient import TestClient
        from backend.app import app
        from backend.auth import AuthenticatedUser, get_current_user

        seen = {}

        def fake_get_class_roster(class_id, caller_user_id):
            seen["class_id"] = class_id
            seen["caller_user_id"] = caller_user_id
            return []

        monkeypatch.setattr(
            "backend.routes.api.institution_service.get_class_roster",
            fake_get_class_roster,
        )
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            id="verified-teacher-xyz", email="t@example.com"
        )
        try:
            client = TestClient(app)
            response = client.get(
                "/api/institutions/classes/class-xyz/roster?caller_user_id=attacker-id"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        # The verified identity must be used, not the attacker-supplied query param.
        assert seen["caller_user_id"] == "verified-teacher-xyz"
        assert seen["caller_user_id"] != "attacker-id"


# ---------------------------------------------------------------------------
# Live PostgreSQL integration tests (skipped when DATABASE_URL is absent)
# ---------------------------------------------------------------------------

_pg_available = bool(os.getenv("DATABASE_URL", "").strip())

@pytest.mark.skipif(not _pg_available, reason="DATABASE_URL not configured — skipping live PG tests")
class TestLivePostgreSQL:
    """
    These tests run only when DATABASE_URL is set.  They verify the full
    round-trip through InstitutionRepository against a real Supabase/PG database.

    Requires migration 001 to have been applied first:
        psql $DATABASE_URL -f migrations/001_institutional_schema.sql
    """

    @pytest.fixture()
    def pg_svc(self):
        from backend.services.institution_service import InstitutionService
        return InstitutionService()

    def test_pg_create_and_retrieve_organization(self, pg_svc):
        import uuid
        name = f"PG Test Org {uuid.uuid4().hex[:6]}"
        org = pg_svc.create_organization(name=name, domain="pgtest.edu")
        assert org.org_id.startswith("org_")

        fetched = pg_svc.get_organization(org.org_id)
        assert fetched is not None
        assert fetched.name == name

    def test_pg_tenant_isolation(self, pg_svc):
        from phase4.institution.models import UserRole
        from phase3.errors import AuthorizationError
        import uuid

        suffix = uuid.uuid4().hex[:6]
        org1 = pg_svc.create_organization(name=f"PG Org1 {suffix}")
        org2 = pg_svc.create_organization(name=f"PG Org2 {suffix}")

        pg_svc.add_membership(org1.org_id, f"t1_{suffix}", UserRole.TEACHER)
        pg_svc.add_membership(org2.org_id, f"intruder_{suffix}", UserRole.TEACHER)

        cls = pg_svc.create_class(
            org_id=org1.org_id,
            subject_id="subj_pg",
            title=f"PG Class {suffix}",
            teacher_ids=[f"t1_{suffix}"],
            creator_user_id=f"t1_{suffix}",
        )

        with pytest.raises(AuthorizationError):
            pg_svc.get_class_roster(cls.class_id, caller_user_id=f"intruder_{suffix}")

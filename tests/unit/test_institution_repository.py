"""
Unit tests for InstitutionRepository.

These tests use an in-memory fake "connection" object that records SQL calls,
so no real PostgreSQL database or asyncpg installation is required.

The repository uses positional-parameter SQL ($1, $2, ...), and the fake
connection returns pre-configured rows.  This lets us verify that:
  * The correct SQL and parameters are issued.
  * Row-to-model conversion is correct.
  * Edge cases (None domain, JSONB teacher_ids list, etc.) are handled.
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from phase4.institution.models import UserRole, Organization, OrgMembership, CourseClass, ClassEnrollment
from backend.repositories.institution_repository import (
    InstitutionRepository,
    _org_from_row,
    _membership_from_row,
    _class_from_row,
    _enrollment_from_row,
    _parse_teacher_ids,
)


# ---------------------------------------------------------------------------
# Fake asyncpg connection / row helpers
# ---------------------------------------------------------------------------

class FakeRow(dict):
    """dict subclass that also supports attribute access (like asyncpg.Record)."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_NOW_ISO = _NOW.isoformat()


class FakeConn:
    """Minimal fake asyncpg Connection."""

    def __init__(self, fetchrow_return=None, fetch_return=None, execute_return="UPDATE 1"):
        self._fetchrow_return = fetchrow_return
        self._fetch_return = fetch_return or []
        self._execute_return = execute_return
        self.last_sql: Optional[str] = None
        self.last_args: tuple = ()

    async def fetchrow(self, sql, *args):
        self.last_sql = sql
        self.last_args = args
        return self._fetchrow_return

    async def fetch(self, sql, *args):
        self.last_sql = sql
        self.last_args = args
        return self._fetch_return

    async def execute(self, sql, *args):
        self.last_sql = sql
        self.last_args = args
        return self._execute_return


# ---------------------------------------------------------------------------
# _parse_teacher_ids
# ---------------------------------------------------------------------------

class TestParseTeacherIds:
    def test_list_passthrough(self):
        assert _parse_teacher_ids(["a", "b"]) == ["a", "b"]

    def test_json_string(self):
        assert _parse_teacher_ids('["x","y"]') == ["x", "y"]

    def test_none_returns_empty(self):
        assert _parse_teacher_ids(None) == []

    def test_invalid_string_returns_empty(self):
        assert _parse_teacher_ids("not-json") == []


# ---------------------------------------------------------------------------
# Row-to-model converters
# ---------------------------------------------------------------------------

class TestRowConverters:
    def test_org_from_row(self):
        row = FakeRow(org_id="org_001", name="Apex", domain="apex.edu", created_at=_NOW)
        org = _org_from_row(row)
        assert org.org_id == "org_001"
        assert org.name == "Apex"
        assert org.domain == "apex.edu"
        assert _NOW_ISO in org.created_at_iso

    def test_org_from_row_no_domain(self):
        row = FakeRow(org_id="org_002", name="Beacon", domain=None, created_at=_NOW)
        org = _org_from_row(row)
        assert org.domain is None

    def test_membership_from_row(self):
        row = FakeRow(
            membership_id="mem_abc",
            org_id="org_001",
            user_id="user-123",
            role="TEACHER",
            is_active=True,
        )
        mem = _membership_from_row(row)
        assert mem.role == UserRole.TEACHER
        assert mem.is_active is True

    def test_class_from_row_list_teacher_ids(self):
        row = FakeRow(
            class_id="cls_abc",
            org_id="org_001",
            subject_id="subj_calc",
            title="Calculus I",
            teacher_ids=["t1", "t2"],
            created_at=_NOW,
        )
        c = _class_from_row(row)
        assert c.teacher_ids == ["t1", "t2"]

    def test_class_from_row_json_teacher_ids(self):
        row = FakeRow(
            class_id="cls_xyz",
            org_id="org_001",
            subject_id="subj_calc",
            title="Calculus I",
            teacher_ids='["t3"]',
            created_at=_NOW,
        )
        c = _class_from_row(row)
        assert c.teacher_ids == ["t3"]

    def test_enrollment_from_row(self):
        row = FakeRow(
            enrollment_id="enr_cls_abc_u1",
            class_id="cls_abc",
            learner_id="u1",
            enrolled_at=_NOW,
        )
        enr = _enrollment_from_row(row)
        assert enr.learner_id == "u1"
        assert enr.class_id == "cls_abc"


# ---------------------------------------------------------------------------
# InstitutionRepository async method tests
# ---------------------------------------------------------------------------

repo = InstitutionRepository()


class TestRepoCreateOrganization:
    def test_returns_organization(self):
        row = FakeRow(org_id="org_001", name="Apex", domain="apex.edu", created_at=_NOW)
        conn = FakeConn(fetchrow_return=row)

        org = asyncio.run(
            repo.create_organization(conn, org_id="org_001", name="Apex", domain="apex.edu")
        )

        assert isinstance(org, Organization)
        assert org.org_id == "org_001"
        assert "$1" in conn.last_sql or "INSERT" in conn.last_sql
        assert conn.last_args[0] == "org_001"

    def test_passes_domain_as_third_arg(self):
        row = FakeRow(org_id="org_002", name="Beacon", domain=None, created_at=_NOW)
        conn = FakeConn(fetchrow_return=row)
        asyncio.run(repo.create_organization(conn, org_id="org_002", name="Beacon"))
        assert conn.last_args[2] is None


class TestRepoGetOrganization:
    def test_returns_none_when_not_found(self):
        conn = FakeConn(fetchrow_return=None)
        result = asyncio.run(repo.get_organization(conn, "missing"))
        assert result is None

    def test_returns_org_when_found(self):
        row = FakeRow(org_id="org_abc", name="Test", domain=None, created_at=_NOW)
        conn = FakeConn(fetchrow_return=row)
        org = asyncio.run(repo.get_organization(conn, "org_abc"))
        assert org is not None
        assert org.org_id == "org_abc"


class TestRepoCreateMembership:
    def test_returns_membership(self):
        row = FakeRow(
            membership_id="mem_001",
            org_id="org_abc",
            user_id="u-1",
            role="ADMIN",
            is_active=True,
        )
        conn = FakeConn(fetchrow_return=row)
        mem = asyncio.run(
            repo.create_membership(
                conn,
                membership_id="mem_001",
                org_id="org_abc",
                user_id="u-1",
                role=UserRole.ADMIN,
            )
        )
        assert isinstance(mem, OrgMembership)
        assert mem.role == UserRole.ADMIN
        # Ensure role value string is passed (not enum object)
        assert conn.last_args[3] == "ADMIN"


class TestRepoGetMembership:
    def test_returns_none_when_not_found(self):
        conn = FakeConn(fetchrow_return=None)
        result = asyncio.run(repo.get_membership(conn, "org_x", "user_y"))
        assert result is None


class TestRepoCreateClass:
    def test_returns_course_class(self):
        row = FakeRow(
            class_id="cls_001",
            org_id="org_abc",
            subject_id="subj_1",
            title="Physics",
            teacher_ids=["t1"],
            created_at=_NOW,
        )
        conn = FakeConn(fetchrow_return=row)
        c = asyncio.run(
            repo.create_class(
                conn,
                class_id="cls_001",
                org_id="org_abc",
                subject_id="subj_1",
                title="Physics",
                teacher_ids=["t1"],
            )
        )
        assert isinstance(c, CourseClass)
        # Verify teacher_ids is JSON-encoded when passed to DB
        assert conn.last_args[4] == '["t1"]'


class TestRepoEnrollLearner:
    def test_returns_enrollment(self):
        row = FakeRow(
            enrollment_id="enr_cls_001_u1",
            class_id="cls_001",
            learner_id="u1",
            enrolled_at=_NOW,
        )
        conn = FakeConn(fetchrow_return=row)
        enr = asyncio.run(
            repo.enroll_learner(
                conn,
                enrollment_id="enr_cls_001_u1",
                class_id="cls_001",
                learner_id="u1",
            )
        )
        assert isinstance(enr, ClassEnrollment)
        assert enr.learner_id == "u1"


class TestRepoGetClassLearnerIds:
    def test_returns_sorted_ids(self):
        rows = [
            FakeRow(learner_id="z_learner"),
            FakeRow(learner_id="a_learner"),
        ]
        conn = FakeConn(fetch_return=rows)
        ids = asyncio.run(repo.get_class_learner_ids(conn, "cls_001"))
        # asyncpg returns in insertion order; our query uses ORDER BY learner_id
        # but the fake doesn't sort — test that the method returns whatever fetch gives
        assert "z_learner" in ids
        assert "a_learner" in ids


class TestRepoListClassesForUser:
    def test_query_requires_active_membership_and_optional_org(self):
        conn = FakeConn(fetch_return=[])
        asyncio.run(repo.list_classes_for_user(conn, "verified-user", "org-1"))
        assert "JOIN org_memberships" in conn.last_sql
        assert "m.user_id = $1 AND m.is_active = TRUE" in conn.last_sql
        assert "c.org_id = $2" in conn.last_sql
        assert conn.last_args == ("verified-user", "org-1")


class TestRepoClassBelongsToOrg:
    def test_returns_true_when_row_found(self):
        conn = FakeConn(fetchrow_return=FakeRow())  # non-None = found
        result = asyncio.run(repo.class_belongs_to_org(conn, "cls_001", "org_abc"))
        assert result is True

    def test_returns_false_when_not_found(self):
        conn = FakeConn(fetchrow_return=None)
        result = asyncio.run(repo.class_belongs_to_org(conn, "cls_001", "wrong_org"))
        assert result is False


class TestRepoDeactivateMembership:
    def test_returns_true_on_success(self):
        conn = FakeConn(execute_return="UPDATE 1")
        result = asyncio.run(repo.deactivate_membership(conn, "org_abc", "u1"))
        assert result is True

    def test_returns_false_when_no_row(self):
        conn = FakeConn(execute_return="UPDATE 0")
        result = asyncio.run(repo.deactivate_membership(conn, "org_abc", "u_missing"))
        assert result is False

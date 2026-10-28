"""
PostgreSQL repository layer for institutional entities.

All public methods are **async** and accept an ``asyncpg.Connection`` (or
compatible) injected by the caller so that the caller controls transaction
boundaries.  The repository itself never commits or rolls back — it only
executes SQL.

Usage pattern (from a service using the pool)
---------------------------------------------
    from backend.db.pg_connection import get_pg_pool
    from backend.repositories.institution_repository import InstitutionRepository

    pool = await get_pg_pool()
    repo = InstitutionRepository()

    async with pool.acquire() as conn:
        org = await repo.create_organization(conn, name="Apex", domain="apex.edu")

    # For multi-step writes that must be atomic:
    async with pool.acquire() as conn:
        async with conn.transaction():
            cls = await repo.create_class(conn, ...)
            for lid in learner_ids:
                await repo.enroll_learner(conn, ...)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from phase4.institution.models import (
    ClassEnrollment,
    CourseClass,
    OrgMembership,
    Organization,
    UserRole,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_teacher_ids(raw: Any) -> List[str]:
    """Coerce the JSONB teacher_ids column to a Python list of strings."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


class InstitutionRepository:
    """Data-access layer for institutional entities stored in PostgreSQL."""

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------

    async def create_organization(
        self,
        conn: Any,
        *,
        org_id: str,
        name: str,
        domain: Optional[str] = None,
    ) -> Organization:
        """Insert a new organization row and return the hydrated model."""
        row = await conn.fetchrow(
            """
            INSERT INTO organizations (org_id, name, domain, created_at)
            VALUES ($1, $2, $3, NOW())
            RETURNING org_id, name, domain, created_at
            """,
            org_id,
            name,
            domain,
        )
        return _org_from_row(row)

    async def get_organization(self, conn: Any, org_id: str) -> Optional[Organization]:
        """Fetch an organization by primary key."""
        row = await conn.fetchrow(
            "SELECT org_id, name, domain, created_at FROM organizations WHERE org_id = $1",
            org_id,
        )
        return _org_from_row(row) if row else None

    async def list_organizations(self, conn: Any) -> List[Organization]:
        """Return all organizations ordered by name."""
        rows = await conn.fetch(
            "SELECT org_id, name, domain, created_at FROM organizations ORDER BY name"
        )
        return [_org_from_row(r) for r in rows]

    async def list_organizations_for_user(self, conn: Any, user_id: str) -> List[Organization]:
        """List only organizations with an active membership for this user."""
        rows = await conn.fetch(
            """
            SELECT o.org_id, o.name, o.domain, o.created_at
            FROM organizations AS o
            JOIN org_memberships AS m ON m.org_id = o.org_id
            WHERE m.user_id = $1 AND m.is_active = TRUE
            ORDER BY o.name
            """,
            user_id,
        )
        return [_org_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # Memberships
    # ------------------------------------------------------------------

    async def create_membership(
        self,
        conn: Any,
        *,
        membership_id: str,
        org_id: str,
        user_id: str,
        role: UserRole,
    ) -> OrgMembership:
        """Upsert a membership and return the hydrated model."""
        row = await conn.fetchrow(
            """
            INSERT INTO org_memberships (membership_id, org_id, user_id, role, is_active, created_at, updated_at)
            VALUES ($1, $2, $3, $4, TRUE, NOW(), NOW())
            ON CONFLICT (org_id, user_id) DO UPDATE
                SET role      = EXCLUDED.role,
                    is_active = TRUE,
                    updated_at = NOW()
            RETURNING membership_id, org_id, user_id, role, is_active
            """,
            membership_id,
            org_id,
            user_id,
            role.value,
        )
        return _membership_from_row(row)

    async def get_membership(
        self, conn: Any, org_id: str, user_id: str, *, for_update: bool = False
    ) -> Optional[OrgMembership]:
        """Return the membership for (org_id, user_id) or None."""
        row = await conn.fetchrow(
            """
            SELECT membership_id, org_id, user_id, role, is_active
            FROM org_memberships
            WHERE org_id = $1 AND user_id = $2
            """ + (" FOR UPDATE" if for_update else ""),
            org_id,
            user_id,
        )
        return _membership_from_row(row) if row else None

    async def deactivate_membership(
        self, conn: Any, org_id: str, user_id: str
    ) -> bool:
        """Mark a membership as inactive. Returns True if a row was updated."""
        result = await conn.execute(
            """
            UPDATE org_memberships
            SET is_active = FALSE, updated_at = NOW()
            WHERE org_id = $1 AND user_id = $2 AND is_active = TRUE
            """,
            org_id,
            user_id,
        )
        # result is e.g. "UPDATE 1"
        return result.endswith("1")

    # ------------------------------------------------------------------
    # Classes
    # ------------------------------------------------------------------

    async def create_class(
        self,
        conn: Any,
        *,
        class_id: str,
        org_id: str,
        subject_id: str,
        title: str,
        teacher_ids: List[str],
    ) -> CourseClass:
        """Insert a new course class row."""
        row = await conn.fetchrow(
            """
            INSERT INTO course_classes (class_id, org_id, subject_id, title, teacher_ids, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
            RETURNING class_id, org_id, subject_id, title, teacher_ids, created_at
            """,
            class_id,
            org_id,
            subject_id,
            title,
            json.dumps(teacher_ids),
        )
        return _class_from_row(row)

    async def get_class(self, conn: Any, class_id: str) -> Optional[CourseClass]:
        """Fetch a course class by primary key."""
        row = await conn.fetchrow(
            """
            SELECT class_id, org_id, subject_id, title, teacher_ids, created_at
            FROM course_classes
            WHERE class_id = $1
            """,
            class_id,
        )
        return _class_from_row(row) if row else None

    async def list_classes(
        self, conn: Any, org_id: Optional[str] = None
    ) -> List[CourseClass]:
        """List all classes, optionally filtered to a specific organization."""
        if org_id is not None:
            rows = await conn.fetch(
                """
                SELECT class_id, org_id, subject_id, title, teacher_ids, created_at
                FROM course_classes
                WHERE org_id = $1
                ORDER BY title
                """,
                org_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT class_id, org_id, subject_id, title, teacher_ids, created_at
                FROM course_classes
                ORDER BY title
                """
            )
        return [_class_from_row(r) for r in rows]

    async def list_classes_for_user(
        self, conn: Any, user_id: str, org_id: Optional[str] = None
    ) -> List[CourseClass]:
        """List classes only in organizations where the user is active."""
        query = """
            SELECT DISTINCT c.class_id, c.org_id, c.subject_id, c.title,
                            c.teacher_ids, c.created_at
            FROM course_classes AS c
            JOIN org_memberships AS m ON m.org_id = c.org_id
            WHERE m.user_id = $1 AND m.is_active = TRUE
        """
        args: tuple = (user_id,)
        if org_id is not None:
            query += " AND c.org_id = $2"
            args = (user_id, org_id)
        query += " ORDER BY c.title"
        rows = await conn.fetch(query, *args)
        return [_class_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # Enrollments
    # ------------------------------------------------------------------

    async def enroll_learner(
        self,
        conn: Any,
        *,
        enrollment_id: str,
        class_id: str,
        learner_id: str,
    ) -> ClassEnrollment:
        """Upsert an enrollment and return the hydrated model."""
        row = await conn.fetchrow(
            """
            INSERT INTO class_enrollments (enrollment_id, class_id, learner_id, enrolled_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (class_id, learner_id) DO UPDATE
                SET enrollment_id = EXCLUDED.enrollment_id
            RETURNING enrollment_id, class_id, learner_id, enrolled_at
            """,
            enrollment_id,
            class_id,
            learner_id,
        )
        return _enrollment_from_row(row)

    async def get_class_learner_ids(self, conn: Any, class_id: str) -> List[str]:
        """Return sorted list of learner_ids enrolled in a class."""
        rows = await conn.fetch(
            """
            SELECT learner_id
            FROM class_enrollments
            WHERE class_id = $1
            ORDER BY learner_id
            """,
            class_id,
        )
        return [r["learner_id"] for r in rows]

    async def get_enrollment(
        self, conn: Any, class_id: str, learner_id: str
    ) -> Optional[ClassEnrollment]:
        """Return an existing enrollment or None."""
        row = await conn.fetchrow(
            """
            SELECT enrollment_id, class_id, learner_id, enrolled_at
            FROM class_enrollments
            WHERE class_id = $1 AND learner_id = $2
            """,
            class_id,
            learner_id,
        )
        return _enrollment_from_row(row) if row else None

    # ------------------------------------------------------------------
    # Cross-tenant guard helpers
    # ------------------------------------------------------------------

    async def class_belongs_to_org(
        self, conn: Any, class_id: str, org_id: str
    ) -> bool:
        """Return True only if class_id exists AND belongs to org_id."""
        row = await conn.fetchrow(
            "SELECT 1 FROM course_classes WHERE class_id = $1 AND org_id = $2",
            class_id,
            org_id,
        )
        return row is not None


# ---------------------------------------------------------------------------
# Row → model helpers
# ---------------------------------------------------------------------------

def _org_from_row(row: Any) -> Organization:
    created = row["created_at"]
    created_iso = (
        created.isoformat() if isinstance(created, datetime) else str(created)
    )
    return Organization(
        org_id=row["org_id"],
        name=row["name"],
        domain=row["domain"],
        created_at_iso=created_iso,
    )


def _membership_from_row(row: Any) -> OrgMembership:
    return OrgMembership(
        membership_id=row["membership_id"],
        org_id=row["org_id"],
        user_id=row["user_id"],
        role=UserRole(row["role"]),
        is_active=bool(row["is_active"]),
    )


def _class_from_row(row: Any) -> CourseClass:
    created = row["created_at"]
    created_iso = (
        created.isoformat() if isinstance(created, datetime) else str(created)
    )
    return CourseClass(
        class_id=row["class_id"],
        org_id=row["org_id"],
        subject_id=row["subject_id"],
        title=row["title"],
        teacher_ids=_parse_teacher_ids(row["teacher_ids"]),
        created_at_iso=created_iso,
    )


def _enrollment_from_row(row: Any) -> ClassEnrollment:
    enrolled = row["enrolled_at"]
    enrolled_iso = (
        enrolled.isoformat() if isinstance(enrolled, datetime) else str(enrolled)
    )
    return ClassEnrollment(
        enrollment_id=row["enrollment_id"],
        class_id=row["class_id"],
        learner_id=row["learner_id"],
        enrolled_at_iso=enrolled_iso,
    )

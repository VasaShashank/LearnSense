"""
Institution & B2B Service Facade for TAPROOT / LearnSense.
Manages multi-tenant organizations, classes, memberships, and role-based permissions (§11).

Persistence Strategy
--------------------
* **PostgreSQL (production)**: When ``DATABASE_URL`` is set, all reads and writes
  go to the PostgreSQL tables created by migration 001.  Filesystem JSON storage
  is still maintained in parallel so that ``teacher_service`` (which reads
  ``storage/classes``) continues to work without modification.  The PostgreSQL
  store is authoritative; the JSON copy is a projection for backward compatibility.

* **JSON-only (development / testing)**: When ``DATABASE_URL`` is absent the
  service operates on the filesystem only, as before.  This mode is logged as a
  warning on startup so developers know they are not hitting the real database.

* **Production enforcement**: If ``LEARNSENSE_REQUIRE_PG=1`` is set, the service
  raises ``RuntimeError`` immediately when PostgreSQL is unavailable instead of
  silently falling back.

Authorization
-------------
``require_role`` checks membership from the active backend store.  The caller's
identity must always be a verified ``AuthenticatedUser.id`` passed down from the
route layer — never a client-supplied value.
"""

import asyncio
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase4.institution.models import (
    Organization,
    OrgMembership,
    CourseClass,
    ClassEnrollment,
    UserRole,
)
from phase3.errors import AuthenticationError, AuthorizationError
from phase3.storage.learner_repository import LearnerStateRepository
from storage.id_validation import validate_canonical_learner_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: Any, base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(base_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


_background_loop = None
_background_loop_thread = None
_background_loop_lock = threading.Lock()


def _get_background_loop():
    """Return a persistent event loop for synchronous service callers.

    asyncpg pools are bound to the event loop on which they are created. A fresh
    asyncio.run() per request can leave a shared pool attached to a closed loop.
    Keep one loop alive for sync-to-async service calls instead.
    """
    global _background_loop, _background_loop_thread
    with _background_loop_lock:
        if _background_loop is not None and _background_loop.is_running():
            return _background_loop

        ready = threading.Event()
        loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        thread = threading.Thread(
            target=run_loop, name="learnsense-db-event-loop", daemon=True
        )
        thread.start()
        ready.wait()
        _background_loop = loop
        _background_loop_thread = thread
        return loop


def _submit_background(coro):
    """Submit an async database operation to the persistent database loop."""
    loop = _get_background_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop)


def _run_async(coro):
    """Synchronously wait for a database operation on the persistent loop."""
    loop = _get_background_loop()
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop is loop:
        coro.close()
        raise RuntimeError(
            "Synchronous institutional service methods cannot run on the "
            "PostgreSQL event-loop thread; use an async service method."
        )
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


async def _await_background(coro):
    """Await a database operation while keeping the asyncpg pool on one loop."""
    return await asyncio.wrap_future(_submit_background(coro))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class InstitutionService:
    """
    Manages organizational boundaries, course rosters, and role-based tenant access.

    The service exposes synchronous methods to preserve compatibility with
    existing synchronous call-sites.  PostgreSQL I/O is wrapped with
    ``_run_async`` which bridges sync→async.  Routes that can await directly
    should call the ``*_async`` variants when they exist.
    """

    def __init__(
        self,
        base_dir: str = "storage/institutions",
        learner_state_repo: Optional[LearnerStateRepository] = None,
    ):
        self.base_dir = Path(base_dir)
        self.learner_state_repo = learner_state_repo or LearnerStateRepository()
        self.orgs_dir = self.base_dir / "organizations"
        self.members_dir = self.base_dir / "memberships"
        self.classes_dir = self.base_dir / "classes"
        self.enrollments_dir = self.base_dir / "enrollments"

        for d in [self.orgs_dir, self.members_dir, self.classes_dir, self.enrollments_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Determine whether PostgreSQL is available.
        from backend.db.pg_connection import is_pg_configured
        self._pg_enabled = is_pg_configured()
        self._require_pg = os.getenv("LEARNSENSE_REQUIRE_PG", "0").strip() == "1"

        if self._pg_enabled:
            logger.info("InstitutionService: PostgreSQL persistence enabled.")
        else:
            if self._require_pg:
                raise RuntimeError(
                    "LEARNSENSE_REQUIRE_PG=1 but DATABASE_URL is not set. "
                    "Configure DATABASE_URL or unset LEARNSENSE_REQUIRE_PG."
                )
            logger.warning(
                "InstitutionService: DATABASE_URL is not configured — "
                "falling back to JSON filesystem persistence. "
                "Set DATABASE_URL for production use."
            )

        if self._pg_enabled:
            from backend.repositories.institution_repository import InstitutionRepository
            self._repo = InstitutionRepository()
        else:
            self._repo = None

    def _require_provisioned_learner(self, learner_id: str) -> None:
        """Require canonical Supabase identity and trusted learner provenance."""
        try:
            canonical_id = validate_canonical_learner_id(learner_id)
            state = self.learner_state_repo.load_state(canonical_id)
        except (TypeError, ValueError):
            state = None
            canonical_id = None
        if (
            state is None
            or canonical_id is None
            or state.learner_id != canonical_id
            or state.identity_provider != "supabase"
        ):
            raise AuthorizationError(
                "Learner must be provisioned with a verified Supabase identity before institutional use."
            )

    # -----------------------------------------------------------------------
    # Internal: pool acquisition
    # -----------------------------------------------------------------------

    async def _pool(self):
        from backend.db.pg_connection import get_pg_pool
        return await get_pg_pool()

    # -----------------------------------------------------------------------
    # Organizations
    # -----------------------------------------------------------------------

    async def create_organization_with_admin_async(
        self, name: str, domain: Optional[str], creator_user_id: str
    ) -> Organization:
        """Create an organization and grant its creator ADMIN atomically."""
        org_id = f"org_{uuid.uuid4().hex[:8]}"
        mem_id = f"mem_{uuid.uuid4().hex[:8]}"

        if self._pg_enabled:
            org, membership = await _await_background(
                self._pg_create_organization_with_admin(
                    org_id, mem_id, name, domain, creator_user_id
                )
            )
        else:
            org = Organization(
                org_id=org_id,
                name=name,
                domain=domain,
                created_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            membership = OrgMembership(
                membership_id=mem_id,
                org_id=org_id,
                user_id=creator_user_id,
                role=UserRole.ADMIN,
                is_active=True,
            )

        _atomic_write_json(self.orgs_dir / f"{org_id}.json", org.model_dump(mode="json"), self.orgs_dir)
        _atomic_write_json(
            self.members_dir / f"{org_id}_{creator_user_id}.json",
            membership.model_dump(mode="json"),
            self.members_dir,
        )
        return org

    async def _pg_create_organization_with_admin(
        self, org_id: str, mem_id: str, name: str, domain: Optional[str], creator_user_id: str
    ):
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                org = await self._repo.create_organization(
                    conn, org_id=org_id, name=name, domain=domain
                )
                membership = await self._repo.create_membership(
                    conn,
                    membership_id=mem_id,
                    org_id=org_id,
                    user_id=creator_user_id,
                    role=UserRole.ADMIN,
                )
        return org, membership

    async def add_membership_as_admin_async(
        self, org_id: str, acting_user_id: str, target_user_id: str, role: UserRole
    ) -> OrgMembership:
        """Add/update a membership only when the caller is an active org admin."""
        if self._pg_enabled:
            mem_id = f"mem_{uuid.uuid4().hex[:8]}"
            membership = await _await_background(
                self._pg_add_membership_as_admin(
                    mem_id, org_id, acting_user_id, target_user_id, role
                )
            )
        else:
            current = self.get_membership(org_id, acting_user_id)
            if not current or not current.is_active or current.role != UserRole.ADMIN:
                from phase3.errors import AuthorizationError
                raise AuthorizationError("Only an active organization admin can manage memberships")
            if role == UserRole.LEARNER:
                self._require_provisioned_learner(target_user_id)
            membership = self.add_membership(org_id, target_user_id, role)

        _atomic_write_json(
            self.members_dir / f"{org_id}_{target_user_id}.json",
            membership.model_dump(mode="json"),
            self.members_dir,
        )
        return membership

    async def _pg_add_membership_as_admin(
        self, mem_id: str, org_id: str, acting_user_id: str,
        target_user_id: str, role: UserRole
    ) -> OrgMembership:
        """Authorize and mutate membership under one transaction and row lock."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                current = await self._repo.get_membership(
                    conn, org_id, acting_user_id, for_update=True
                )
                if not current or not current.is_active or current.role != UserRole.ADMIN:
                    raise AuthorizationError(
                        "Only an active organization admin can manage memberships"
                    )
                if role == UserRole.LEARNER:
                    self._require_provisioned_learner(target_user_id)
                return await self._repo.create_membership(
                    conn, membership_id=mem_id, org_id=org_id,
                    user_id=target_user_id, role=role
                )

    async def list_organizations_for_user_async(self, user_id: str) -> List[Organization]:
        """Return only organizations where this user has an active membership."""
        if self._pg_enabled:
            return await _await_background(self._pg_list_organizations_for_user(user_id))

        organizations = []
        for membership_path in self.members_dir.glob("*.json"):
            try:
                with open(membership_path, "r", encoding="utf-8") as f:
                    membership = OrgMembership.model_validate(json.load(f))
                if membership.user_id != user_id or not membership.is_active:
                    continue
                org = self.get_organization(membership.org_id)
                if org is not None:
                    organizations.append(org)
            except Exception as exc:
                logger.warning("Unreadable membership %s: %s", membership_path, exc)
        return sorted({org.org_id: org for org in organizations}.values(), key=lambda org: org.name)

    async def _pg_list_organizations_for_user(self, user_id: str) -> List[Organization]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.list_organizations_for_user(conn, user_id)

    async def list_classes_for_user_async(
        self, user_id: str, org_id: Optional[str] = None
    ) -> List[CourseClass]:
        """List classes visible through active membership and class assignment."""
        if self._pg_enabled:
            return await _await_background(
                self._pg_list_classes_for_user(user_id, org_id)
            )

        active_memberships = {}
        for membership_path in self.members_dir.glob("*.json"):
            try:
                with open(membership_path, "r", encoding="utf-8") as f:
                    membership = OrgMembership.model_validate(json.load(f))
                if membership.user_id == user_id and membership.is_active:
                    active_memberships[membership.org_id] = membership.role
            except Exception as exc:
                logger.warning("Unreadable membership %s: %s", membership_path, exc)
        if org_id is not None:
            active_memberships = {
                key: value for key, value in active_memberships.items() if key == org_id
            }

        classes = []
        for class_path in self.classes_dir.glob("*.json"):
            try:
                with open(class_path, "r", encoding="utf-8") as f:
                    course_class = CourseClass.model_validate(json.load(f))
                role = active_memberships.get(course_class.org_id)
                if role == UserRole.ADMIN or (
                    role == UserRole.TEACHER and user_id in course_class.teacher_ids
                ):
                    classes.append(course_class)
            except Exception as exc:
                logger.warning("Unreadable class %s: %s", class_path, exc)
        return sorted(classes, key=lambda course_class: course_class.title)

    async def _pg_list_classes_for_user(
        self, user_id: str, org_id: Optional[str]
    ) -> List[CourseClass]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            classes = await self._repo.list_classes_for_user(conn, user_id, org_id)
            visible = []
            for course_class in classes:
                membership = await self._repo.get_membership(
                    conn, course_class.org_id, user_id
                )
                if not membership or not membership.is_active:
                    continue
                if membership.role == UserRole.ADMIN or (
                    membership.role == UserRole.TEACHER
                    and user_id in course_class.teacher_ids
                ):
                    visible.append(course_class)
            return visible

    def create_organization(self, name: str, domain: Optional[str] = None) -> Organization:
        org_id = f"org_{uuid.uuid4().hex[:8]}"

        if self._pg_enabled:
            org = _run_async(self._pg_create_organization(org_id, name, domain))
        else:
            org = Organization(
                org_id=org_id,
                name=name,
                domain=domain,
                created_at_iso=datetime.now(timezone.utc).isoformat(),
            )

        # Always write to JSON for backward compat with non-PG consumers.
        _atomic_write_json(
            self.orgs_dir / f"{org_id}.json",
            org.model_dump(mode="json"),
            self.orgs_dir,
        )
        return org

    async def _pg_create_organization(
        self, org_id: str, name: str, domain: Optional[str]
    ) -> Organization:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.create_organization(
                conn, org_id=org_id, name=name, domain=domain
            )

    def get_organization(self, org_id: str) -> Optional[Organization]:
        if self._pg_enabled:
            return _run_async(self._pg_get_organization(org_id))
        # JSON fallback
        p = self.orgs_dir / f"{org_id}.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return Organization.model_validate(json.load(f))

    async def _pg_get_organization(self, org_id: str) -> Optional[Organization]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.get_organization(conn, org_id)

    def list_organizations(self) -> List[Organization]:
        """List registered organizations. Only seeds demo data in dev/JSON mode."""
        if self._pg_enabled:
            orgs = _run_async(self._pg_list_organizations())
            return sorted(orgs, key=lambda o: o.name)

        # --- JSON mode (dev/test only) ---
        orgs = []
        for p in self.orgs_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    orgs.append(Organization.model_validate(json.load(f)))
            except Exception as exc:
                logger.warning("Unreadable organization %s: %s", p, exc)

        if not orgs:
            # Demo seed is safe in JSON-only (dev) mode only.
            org = self.create_organization(
                name="Apex Institute of Science & Technology",
                domain="apex.edu",
            )
            self.add_membership(org.org_id, "admin_sterling", UserRole.ADMIN)
            self.add_membership(org.org_id, "prof_vance", UserRole.TEACHER)
            self.add_membership(org.org_id, "student_alex", UserRole.LEARNER)
            self.add_membership(org.org_id, "student_jordan", UserRole.LEARNER)
            self.add_membership(org.org_id, "student_sam", UserRole.LEARNER)
            self.create_class(
                org_id=org.org_id,
                subject_id="doc_stud-share-sample_c_programs_daa-_lab_programs",
                title="CS301: Advanced Algorithms & System Paradigms",
                teacher_ids=["prof_vance"],
                creator_user_id="admin_sterling",
            )
            orgs.append(org)

        return sorted(orgs, key=lambda o: o.name)

    async def _pg_list_organizations(self) -> List[Organization]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.list_organizations(conn)

    # -----------------------------------------------------------------------
    # Memberships & RBAC
    # -----------------------------------------------------------------------

    def add_membership(self, org_id: str, user_id: str, role: UserRole) -> OrgMembership:
        mem_id = f"mem_{uuid.uuid4().hex[:8]}"

        if self._pg_enabled:
            mem = _run_async(self._pg_add_membership(mem_id, org_id, user_id, role))
        else:
            mem = OrgMembership(
                membership_id=mem_id,
                org_id=org_id,
                user_id=user_id,
                role=role,
                is_active=True,
            )

        # JSON projection for audit/fallback.
        _atomic_write_json(
            self.members_dir / f"{org_id}_{user_id}.json",
            mem.model_dump(mode="json"),
            self.members_dir,
        )
        return mem

    async def _pg_add_membership(
        self, mem_id: str, org_id: str, user_id: str, role: UserRole
    ) -> OrgMembership:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.create_membership(
                conn, membership_id=mem_id, org_id=org_id, user_id=user_id, role=role
            )

    def get_membership(self, org_id: str, user_id: str) -> Optional[OrgMembership]:
        if self._pg_enabled:
            return _run_async(self._pg_get_membership(org_id, user_id))
        # JSON fallback
        p = self.members_dir / f"{org_id}_{user_id}.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return OrgMembership.model_validate(json.load(f))

    async def _pg_get_membership(
        self, org_id: str, user_id: str
    ) -> Optional[OrgMembership]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.get_membership(conn, org_id, user_id)

    def require_role(
        self, org_id: str, user_id: str, allowed_roles: List[UserRole]
    ) -> OrgMembership:
        """Assert that user_id has an active membership with one of allowed_roles.

        The user_id must be a verified backend identity (from AuthenticatedUser.id
        or from a trusted fixture); it must NOT be taken directly from any
        client-supplied parameter.
        """
        mem = self.get_membership(org_id, user_id)
        if not mem or not mem.is_active:
            raise AuthorizationError(
                f"User '{user_id}' has no active membership in organization '{org_id}'",
                details={"org_id": org_id, "user_id": user_id},
            )
        if mem.role not in allowed_roles:
            raise AuthorizationError(
                f"User '{user_id}' with role '{mem.role}' lacks permission for this action",
                details={
                    "required_roles": [r.value for r in allowed_roles],
                    "actual_role": mem.role.value,
                },
            )
        return mem

    # -----------------------------------------------------------------------
    # Classes & Cohorts
    # -----------------------------------------------------------------------

    def create_class(
        self,
        org_id: str,
        subject_id: str,
        title: str,
        teacher_ids: List[str],
        creator_user_id: str,
        enrolled_learner_ids: Optional[List[str]] = None,
    ) -> CourseClass:
        # Authorization: only ADMIN or TEACHER in the org may create classes.
        creator = self.require_role(org_id, creator_user_id, [UserRole.ADMIN, UserRole.TEACHER])
        teacher_ids = list(dict.fromkeys(teacher_ids or []))
        if creator.role == UserRole.TEACHER and creator_user_id not in teacher_ids:
            teacher_ids.append(creator_user_id)
        for teacher_id in teacher_ids:
            self.require_role(org_id, teacher_id, [UserRole.TEACHER])
        roster = list(dict.fromkeys(enrolled_learner_ids or []))
        for learner_id in roster:
            self.require_role(org_id, learner_id, [UserRole.LEARNER])
            self._require_provisioned_learner(learner_id)

        class_id = f"cls_{uuid.uuid4().hex[:8]}"

        if self._pg_enabled:
            c = _run_async(
                self._pg_create_class(class_id, org_id, subject_id, title, teacher_ids, roster)
            )
        else:
            c = CourseClass(
                class_id=class_id,
                org_id=org_id,
                subject_id=subject_id,
                title=title,
                teacher_ids=teacher_ids,
                created_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            _atomic_write_json(
                self.classes_dir / f"{class_id}.json",
                c.model_dump(mode="json"),
                self.classes_dir,
            )
            # JSON enrollments
            for lid in roster:
                enr_id = f"enr_{class_id}_{lid}"
                enr = ClassEnrollment(
                    enrollment_id=enr_id,
                    class_id=class_id,
                    learner_id=lid,
                    enrolled_at_iso=datetime.now(timezone.utc).isoformat(),
                )
                _atomic_write_json(
                    self.enrollments_dir / f"{enr_id}.json",
                    enr.model_dump(mode="json"),
                    self.enrollments_dir,
                )

        # Always cross-sync to storage/classes so teacher_service reads work.
        self._sync_class_to_teacher_storage(class_id, subject_id, title, roster)
        return c

    async def _pg_create_class(
        self,
        class_id: str,
        org_id: str,
        subject_id: str,
        title: str,
        teacher_ids: List[str],
        roster: List[str],
    ) -> CourseClass:
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                c = await self._repo.create_class(
                    conn,
                    class_id=class_id,
                    org_id=org_id,
                    subject_id=subject_id,
                    title=title,
                    teacher_ids=teacher_ids,
                )
                for lid in roster:
                    enr_id = f"enr_{class_id}_{lid}"
                    await self._repo.enroll_learner(
                        conn,
                        enrollment_id=enr_id,
                        class_id=class_id,
                        learner_id=lid,
                    )
        return c

    @staticmethod
    def _sync_class_to_teacher_storage(
        class_id: str, subject_id: str, title: str, roster: List[str]
    ) -> None:
        """Maintain storage/classes projection for teacher_service compatibility."""
        native_dir = Path("storage/classes")
        native_dir.mkdir(parents=True, exist_ok=True)
        try:
            _atomic_write_json(
                native_dir / f"{class_id}.json",
                {
                    "class_id": class_id,
                    "subject_id": subject_id,
                    "class_name": title,
                    "enrolled_learner_ids": roster,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                native_dir,
            )
        except Exception as exc:
            logger.warning("Could not sync class %s to teacher storage: %s", class_id, exc)

    def get_class(self, class_id: str) -> Optional[CourseClass]:
        if self._pg_enabled:
            return _run_async(self._pg_get_class(class_id))
        # JSON fallback
        p = self.classes_dir / f"{class_id}.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return CourseClass.model_validate(json.load(f))

    async def _pg_get_class(self, class_id: str) -> Optional[CourseClass]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.get_class(conn, class_id)

    def list_classes(self, org_id: Optional[str] = None) -> List[CourseClass]:
        if self._pg_enabled:
            classes = _run_async(self._pg_list_classes(org_id))
            return sorted(classes, key=lambda c: c.title)

        # JSON fallback
        classes = []
        for p in self.classes_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    c = CourseClass.model_validate(json.load(f))
                    if org_id is None or c.org_id == org_id:
                        classes.append(c)
            except Exception as exc:
                logger.warning("Unreadable class %s: %s", p, exc)
        return sorted(classes, key=lambda c: c.title)

    async def _pg_list_classes(self, org_id: Optional[str]) -> List[CourseClass]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.list_classes(conn, org_id=org_id)

    def enroll_learner(
        self, class_id: str, learner_id: str, enroller_user_id: str
    ) -> ClassEnrollment:
        c = self.get_class(class_id)
        if not c:
            raise ValueError(f"Class '{class_id}' does not exist")
        # Require teacher or admin of the class's organization.
        enroller = self.require_role(c.org_id, enroller_user_id, [UserRole.ADMIN, UserRole.TEACHER])
        if enroller.role == UserRole.TEACHER and enroller_user_id not in c.teacher_ids:
            raise AuthorizationError("Teacher is not assigned to this class")
        self.require_role(c.org_id, learner_id, [UserRole.LEARNER])
        self._require_provisioned_learner(learner_id)

        enr_id = f"enr_{class_id}_{learner_id}"

        if self._pg_enabled:
            enr = _run_async(self._pg_enroll_learner(enr_id, class_id, learner_id))
        else:
            enr = ClassEnrollment(
                enrollment_id=enr_id,
                class_id=class_id,
                learner_id=learner_id,
                enrolled_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            _atomic_write_json(
                self.enrollments_dir / f"{enr_id}.json",
                enr.model_dump(mode="json"),
                self.enrollments_dir,
            )

        # Keep the teacher_service projection current.
        self._append_learner_to_teacher_storage(class_id, learner_id)
        return enr

    async def _pg_enroll_learner(
        self, enr_id: str, class_id: str, learner_id: str
    ) -> ClassEnrollment:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.enroll_learner(
                conn, enrollment_id=enr_id, class_id=class_id, learner_id=learner_id
            )

    @staticmethod
    def _append_learner_to_teacher_storage(class_id: str, learner_id: str) -> None:
        """Add learner to the teacher storage JSON projection."""
        native_path = Path("storage/classes") / f"{class_id}.json"
        if not native_path.exists():
            return
        try:
            with open(native_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            enrolled = data.get("enrolled_learner_ids", [])
            if learner_id not in enrolled:
                enrolled.append(learner_id)
                data["enrolled_learner_ids"] = enrolled
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                _atomic_write_json(native_path, data, native_path.parent)
        except Exception as exc:
            logger.warning(
                "Could not update teacher storage for class %s: %s", class_id, exc
            )

    def get_class_roster(self, class_id: str, caller_user_id: str) -> List[str]:
        """Return sorted learner IDs for a class after verifying caller authorization.

        ``caller_user_id`` MUST be the verified backend identity from
        ``AuthenticatedUser.id``; it is never trusted from client input.

        Cross-tenant isolation: the service fetches the class to discover its
        org_id, then enforces ADMIN/TEACHER membership in that org for the
        caller.  A caller with valid credentials in a different org cannot
        enumerate another org's roster by guessing class_id values.
        """
        c = self.get_class(class_id)
        if not c:
            raise ValueError(f"Class '{class_id}' does not exist")
        # Enforce role in the class's own organization.
        membership = self.require_role(c.org_id, caller_user_id, [UserRole.ADMIN, UserRole.TEACHER])
        if membership.role == UserRole.TEACHER and caller_user_id not in c.teacher_ids:
            raise AuthorizationError("Teacher is not assigned to this class")

        if self._pg_enabled:
            return _run_async(self._pg_get_class_roster(class_id))

        # JSON fallback
        learners = []
        pattern = f"enr_{class_id}_*.json"
        for p in self.enrollments_dir.glob(pattern):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    enr = json.load(f)
                    learners.append(enr.get("learner_id"))
            except Exception as exc:
                logger.warning("Unreadable enrollment %s: %s", p, exc)
        return sorted(list(set(learners)))

    async def _pg_get_class_roster(self, class_id: str) -> List[str]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.get_class_learner_ids(conn, class_id)

    def is_active_learner_enrolled(self, class_id: str, learner_id: str) -> bool:
        """Return whether a learner has an active role and enrollment in this class."""
        try:
            learner_id = validate_canonical_learner_id(learner_id)
            self._require_provisioned_learner(learner_id)
        except (TypeError, ValueError, AuthorizationError):
            return False
        course_class = self.get_class(class_id)
        if course_class is None:
            return False
        membership = self.get_membership(course_class.org_id, learner_id)
        if (
            membership is None
            or not membership.is_active
            or membership.role != UserRole.LEARNER
        ):
            return False
        if self._pg_enabled:
            return _run_async(self._pg_is_learner_enrolled(class_id, learner_id))

        enrollment_path = self.enrollments_dir / f"enr_{class_id}_{learner_id}.json"
        try:
            with enrollment_path.open("r", encoding="utf-8") as stream:
                enrollment = json.load(stream)
            return (
                enrollment.get("class_id") == class_id
                and enrollment.get("learner_id") == learner_id
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    async def _pg_is_learner_enrolled(self, class_id: str, learner_id: str) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.get_enrollment(conn, class_id, learner_id) is not None

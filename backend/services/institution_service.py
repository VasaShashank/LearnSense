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
from phase3.errors import AuthenticationError, AuthorizationError, LearnSenseError
from phase3.storage.learner_repository import LearnerStateRepository
from storage.id_validation import validate_canonical_learner_id
from backend.services import audit_log
from backend.services.audit_log import AuditLog
from backend.services.user_service import UserNotProvisionedError, UserService
from storage.atomic_replace import replace_atomically

logger = logging.getLogger(__name__)


class MembershipNotFoundError(LookupError):
    """No membership exists for this (organization, user)."""


class LastAdminError(RuntimeError):
    """The change would leave an organization without an active administrator."""


class DuplicateOrganizationError(RuntimeError):
    """An organization with this name (case-insensitive) already exists."""


class ClassNotFoundError(LookupError, ValueError):
    """No such class. Subclasses ValueError for backward compatibility."""

    def __init__(self, class_id: str):
        super().__init__(f"Class '{class_id}' does not exist")


class EnrollmentNotFoundError(LookupError):
    """The learner was never enrolled in this class."""


class InvalidAssignmentError(AuthorizationError):
    """Requested teachers are not active TEACHER members of the class's organization."""

    code = "INVALID_ASSIGNMENT"
    http_status = 400
    recoverable = False


_NO_ADMIN = "Only an active organization admin can manage memberships"
_FORBIDDEN = "You do not have permission to perform this operation."


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
        replace_atomically(tmp_name, path)
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
        user_service: Optional[UserService] = None,
    ):
        self.base_dir = Path(base_dir)
        self.learner_state_repo = learner_state_repo or LearnerStateRepository()
        self.orgs_dir = self.base_dir / "organizations"
        self.members_dir = self.base_dir / "memberships"
        self.classes_dir = self.base_dir / "classes"
        self.enrollments_dir = self.base_dir / "enrollments"
        # JSON mode has no row locks; serialize check-then-write membership changes
        # within this process. (PostgreSQL mode relies on row locks instead.)
        self._membership_lock = threading.Lock()

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
            from backend.repositories.platform_repository import AuditRepository, UserRepository
            self._repo = InstitutionRepository()
            self._audit_repo = AuditRepository()
            self._user_repo = UserRepository()
        else:
            self._repo = None
        # Users live beside the institutional store (storage/users by default).
        self.users = user_service or UserService(
            base_dir=str(self.base_dir.parent / "users"), pg_enabled=self._pg_enabled
        )
        self.audit = AuditLog(str(self.base_dir / "audit"), pg_enabled=self._pg_enabled)

    def _json_audit(self, **event) -> None:
        """JSON mode: append after the write succeeded (PostgreSQL writes in-transaction)."""
        self.audit.record(**event)

    def _require_provisioned_staff_json(self, user_id: str) -> None:
        try:
            validate_canonical_learner_id(user_id)
        except (TypeError, ValueError):
            raise UserNotProvisionedError(
                "Staff roles can only be granted to a signed-in LearnSense user."
            ) from None
        self.users.require_provisioned_staff_sync(user_id)

    async def _pg_require_provisioned_staff(self, conn, user_id: str) -> None:
        try:
            validate_canonical_learner_id(user_id)
        except (TypeError, ValueError):
            raise UserNotProvisionedError(
                "Staff roles can only be granted to a signed-in LearnSense user."
            ) from None
        record = await self._user_repo.get(conn, user_id)
        if record is None or record["status"] != "active":
            raise UserNotProvisionedError(
                "The user must sign in to LearnSense before they can be given this role."
            )

    def is_provisioned_learner(self, learner_id: str) -> bool:
        """Canonical Supabase UUID with trusted learner provenance (no exception)."""
        try:
            self._require_provisioned_learner(learner_id)
            return True
        except AuthorizationError:
            return False

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
            raise UserNotProvisionedError(
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

        name = (name or "").strip()
        if not name:
            raise ValueError("Organization name is required")
        if self._pg_enabled:
            org, membership = await _await_background(
                self._pg_create_organization_with_admin(
                    org_id, mem_id, name, domain, creator_user_id
                )
            )
        else:
            with self._membership_lock:
                if self._json_org_name_taken(name):
                    raise DuplicateOrganizationError(name)
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
            self._json_audit(
                actor_user_id=creator_user_id, org_id=org_id, action=audit_log.ORG_CREATED,
                target_type="organization", target_id=org_id, details={"name": name},
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
        import asyncpg

        pool = await self._pool()
        async with pool.acquire() as conn:
            try:
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
                    await self._audit_repo.insert(
                        conn, actor_user_id=creator_user_id, org_id=org_id,
                        action=audit_log.ORG_CREATED, target_type="organization",
                        target_id=org_id, details={"name": name},
                    )
            except asyncpg.UniqueViolationError as exc:
                if getattr(exc, "constraint_name", None) == "uq_organizations_name_ci":
                    raise DuplicateOrganizationError(name) from None
                raise
        return org, membership

    def _json_org_name_taken(self, name: str) -> bool:
        wanted = name.strip().lower()
        for path in self.orgs_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    if str(json.load(f).get("name", "")).strip().lower() == wanted:
                        return True
            except Exception as exc:
                logger.warning("Unreadable organization %s: %s", path, exc)
        return False

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
            with self._membership_lock:
                current = self.get_membership(org_id, acting_user_id)
                if not current or not current.is_active or current.role != UserRole.ADMIN:
                    raise AuthorizationError(_NO_ADMIN)
                target = self.get_membership(org_id, target_user_id)
                if (
                    target is not None
                    and target.is_active
                    and target.role == UserRole.ADMIN
                    and role != UserRole.ADMIN
                    and self._json_active_admin_count(org_id) <= 1
                ):
                    raise LastAdminError(org_id)
                if role == UserRole.LEARNER:
                    self._require_provisioned_learner(target_user_id)
                else:
                    self._require_provisioned_staff_json(target_user_id)
                action = self._membership_action(target, role)
                if action is None:
                    membership = target
                else:
                    membership = self.add_membership(org_id, target_user_id, role)
            if action is not None:
                self._json_audit(
                    actor_user_id=acting_user_id, org_id=org_id, action=action,
                    target_type="membership", target_id=target_user_id,
                    details=self._membership_details(target, role),
                )

        _atomic_write_json(
            self.members_dir / f"{org_id}_{target_user_id}.json",
            membership.model_dump(mode="json"),
            self.members_dir,
        )
        # A (re)activation or role change alters who is an active learner.
        await self._refresh_roster_projections(org_id)
        return membership

    @staticmethod
    def _membership_action(target: Optional[OrgMembership], role: UserRole) -> Optional[str]:
        """Audit action for an upsert, or None when nothing changes."""
        if target is None:
            return audit_log.MEMBERSHIP_CREATED
        if not target.is_active:
            return audit_log.MEMBERSHIP_REACTIVATED
        if target.role != role:
            return audit_log.MEMBERSHIP_ROLE_CHANGED
        return None

    @staticmethod
    def _membership_details(target: Optional[OrgMembership], role: UserRole) -> Dict[str, Any]:
        details: Dict[str, Any] = {"role": role.value}
        if target is not None:
            details["previous_role"] = target.role.value
            details["previously_active"] = target.is_active
        return details

    async def deactivate_membership_as_admin_async(
        self, org_id: str, acting_user_id: str, target_user_id: str
    ) -> tuple[OrgMembership, bool]:
        """Deactivate a membership; only an active org ADMIN may, and never the last one.

        Returns ``(membership, changed)``; ``changed`` is False when it was already
        inactive. The membership row, class enrollments and learner state are retained
        as history. Raises AuthorizationError, MembershipNotFoundError, LastAdminError.
        """
        if self._pg_enabled:
            membership, changed = await _await_background(
                self._pg_deactivate_membership(org_id, acting_user_id, target_user_id)
            )
        else:
            membership, changed = self._json_deactivate_membership(
                org_id, acting_user_id, target_user_id
            )
        if changed:
            _atomic_write_json(
                self.members_dir / f"{org_id}_{target_user_id}.json",
                membership.model_dump(mode="json"),
                self.members_dir,
            )
            await self._refresh_roster_projections(org_id)
        return membership, changed

    async def _pg_deactivate_membership(
        self, org_id: str, acting_user_id: str, target_user_id: str
    ) -> tuple[OrgMembership, bool]:
        """Authorize, protect the last admin, and deactivate in one transaction.

        Locking every active admin row (fixed order) first serializes concurrent
        admin changes in the org: a second transaction blocks until the first commits,
        then re-evaluates against the committed state, so two admins can never
        deactivate each other (or the last admin) at the same time.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                admins = await self._repo.lock_active_admins(conn, org_id)
                if acting_user_id not in {a.user_id for a in admins}:
                    raise AuthorizationError(_NO_ADMIN)
                target = await self._repo.get_membership(
                    conn, org_id, target_user_id, for_update=True
                )
                if target is None:
                    raise MembershipNotFoundError(org_id)
                if not target.is_active:
                    return target, False
                if target.role == UserRole.ADMIN and len(admins) <= 1:
                    raise LastAdminError(org_id)
                await self._repo.deactivate_membership(conn, org_id, target_user_id)
                await self._audit_repo.insert(
                    conn, actor_user_id=acting_user_id, org_id=org_id,
                    action=audit_log.MEMBERSHIP_DEACTIVATED, target_type="membership",
                    target_id=target_user_id, details={"role": target.role.value},
                )
                return target.model_copy(update={"is_active": False}), True

    def _json_active_admin_count(self, org_id: str) -> int:
        """Count active ADMIN memberships of an org (JSON mode)."""
        count = 0
        for path in self.members_dir.glob(f"{org_id}_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    member = OrgMembership.model_validate(json.load(f))
            except Exception as exc:
                logger.warning("Unreadable membership %s: %s", path, exc)
                continue
            if member.org_id == org_id and member.is_active and member.role == UserRole.ADMIN:
                count += 1
        return count

    def _json_deactivate_membership(
        self, org_id: str, acting_user_id: str, target_user_id: str
    ) -> tuple[OrgMembership, bool]:
        with self._membership_lock:
            acting = self.get_membership(org_id, acting_user_id)
            if not acting or not acting.is_active or acting.role != UserRole.ADMIN:
                raise AuthorizationError(_NO_ADMIN)
            target = self.get_membership(org_id, target_user_id)
            if target is None:
                raise MembershipNotFoundError(org_id)
            if not target.is_active:
                return target, False
            if target.role == UserRole.ADMIN and self._json_active_admin_count(org_id) <= 1:
                raise LastAdminError(org_id)
            inactive = target.model_copy(update={"is_active": False})
            _atomic_write_json(
                self.members_dir / f"{org_id}_{target_user_id}.json",
                inactive.model_dump(mode="json"),
                self.members_dir,
            )
        self._json_audit(
            actor_user_id=acting_user_id, org_id=org_id,
            action=audit_log.MEMBERSHIP_DEACTIVATED, target_type="membership",
            target_id=target_user_id, details={"role": target.role.value},
        )
        return inactive, True

    async def _refresh_roster_projections(self, org_id: str) -> None:
        """Rewrite each class's analytics projection from its ACTIVE roster.

        ``storage/classes`` feeds teacher analytics and is compared to the roster by
        the route layer, so it must follow membership changes. A failure here only
        logs: routes then fail closed (404) on the mismatch instead of leaking.
        """
        try:
            if self._pg_enabled:
                rosters = await _await_background(self._pg_active_rosters(org_id))
            else:
                rosters = {
                    c.class_id: self._json_active_roster(c.class_id)
                    for c in self.list_classes(org_id)
                }
            for class_id, roster in rosters.items():
                self._set_teacher_storage_roster(class_id, roster)
        except Exception as exc:
            logger.warning("Could not refresh roster projections for %s: %s", org_id, exc)

    async def _pg_active_rosters(self, org_id: str) -> Dict[str, List[str]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            classes = await self._repo.list_classes(conn, org_id=org_id)
            return {
                c.class_id: await self._repo.get_active_class_learner_ids(conn, c.class_id)
                for c in classes
            }

    def _json_active_roster(self, class_id: str) -> List[str]:
        """JSON-mode roster: enrolled learners with an active LEARNER membership."""
        course_class = self.get_class(class_id)
        if course_class is None:
            return []
        learners = set()
        for path in self.enrollments_dir.glob(f"enr_{class_id}_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    enrollment = json.load(f)
            except Exception as exc:
                logger.warning("Unreadable enrollment %s: %s", path, exc)
                continue
            if enrollment.get("status", "active") != "active":
                continue
            learner_id = enrollment.get("learner_id")
            membership = self.get_membership(course_class.org_id, learner_id)
            if (
                membership is not None
                and membership.is_active
                and membership.role == UserRole.LEARNER
            ):
                learners.add(learner_id)
        return sorted(learners)

    @staticmethod
    def _set_teacher_storage_roster(class_id: str, roster: List[str]) -> None:
        """Set the enrolled list of an existing storage/classes projection."""
        native_path = Path("storage/classes") / f"{class_id}.json"
        if not native_path.exists():
            return
        with open(native_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if sorted(data.get("enrolled_learner_ids", [])) == sorted(roster):
            return
        data["enrolled_learner_ids"] = list(roster)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(native_path, data, native_path.parent)

    async def _pg_add_membership_as_admin(
        self, mem_id: str, org_id: str, acting_user_id: str,
        target_user_id: str, role: UserRole
    ) -> OrgMembership:
        """Authorize and mutate membership under one transaction and row locks.

        Lock protocol (shared with ``_pg_deactivate_membership``; keep them identical
        to avoid deadlocks): first every active ADMIN row of the org in membership_id
        order, then the target row. A role change or reactivation therefore
        serializes with concurrent deactivations on the same admin set.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                admins = await self._repo.lock_active_admins(conn, org_id)
                if acting_user_id not in {a.user_id for a in admins}:
                    raise AuthorizationError(_NO_ADMIN)
                target = await self._repo.get_membership(
                    conn, org_id, target_user_id, for_update=True
                )
                if (
                    target is not None
                    and target.is_active
                    and target.role == UserRole.ADMIN
                    and role != UserRole.ADMIN
                    and len(admins) <= 1
                ):
                    raise LastAdminError(org_id)
                if role == UserRole.LEARNER:
                    self._require_provisioned_learner(target_user_id)
                else:
                    await self._pg_require_provisioned_staff(conn, target_user_id)
                action = self._membership_action(target, role)
                if action is None:
                    return target
                membership = await self._repo.create_membership(
                    conn, membership_id=mem_id, org_id=org_id,
                    user_id=target_user_id, role=role
                )
                await self._audit_repo.insert(
                    conn, actor_user_id=acting_user_id, org_id=org_id, action=action,
                    target_type="membership", target_id=target_user_id,
                    details=self._membership_details(target, role),
                )
                return membership

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
        # Messages carry no identifiers, roles or organization IDs (api-errors.md).
        if not mem or not mem.is_active or mem.role not in allowed_roles:
            raise AuthorizationError(_FORBIDDEN)
        return mem

    def _require_member_role(self, org_id: str, user_id: str, role: UserRole) -> None:
        """Validate a *subject* of an operation (not the caller): 400, never concealed."""
        mem = self.get_membership(org_id, user_id)
        if not mem or not mem.is_active or mem.role != role:
            raise InvalidAssignmentError(
                f"Every {role.value.lower()} must be an active {role.value} member of the class's organization."
            )

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
            self._require_member_role(org_id, teacher_id, UserRole.TEACHER)
        roster = list(dict.fromkeys(enrolled_learner_ids or []))
        for learner_id in roster:
            self._require_member_role(org_id, learner_id, UserRole.LEARNER)
            self._require_provisioned_learner(learner_id)

        class_id = f"cls_{uuid.uuid4().hex[:8]}"

        if self._pg_enabled:
            c = _run_async(
                self._pg_create_class(
                    class_id, org_id, subject_id, title, teacher_ids, roster, creator_user_id
                )
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
            self._json_audit(
                actor_user_id=creator_user_id, org_id=org_id, action=audit_log.CLASS_CREATED,
                target_type="class", target_id=class_id,
                details={"teacher_ids": teacher_ids, "enrolled_learner_ids": roster},
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
        creator_user_id: str,
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
                await self._audit_repo.insert(
                    conn, actor_user_id=creator_user_id, org_id=org_id,
                    action=audit_log.CLASS_CREATED, target_type="class", target_id=class_id,
                    details={"teacher_ids": teacher_ids, "enrolled_learner_ids": roster},
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
            raise ClassNotFoundError(class_id)
        # Require teacher or admin of the class's organization.
        enroller = self.require_role(c.org_id, enroller_user_id, [UserRole.ADMIN, UserRole.TEACHER])
        if enroller.role == UserRole.TEACHER and enroller_user_id not in c.teacher_ids:
            raise AuthorizationError("Teacher is not assigned to this class")
        self._require_member_role(c.org_id, learner_id, UserRole.LEARNER)
        self._require_provisioned_learner(learner_id)

        enr_id = f"enr_{class_id}_{learner_id}"

        if self._pg_enabled:
            enr = _run_async(
                self._pg_enroll_learner(enr_id, class_id, learner_id, c.org_id, enroller_user_id)
            )
        else:
            path = self.enrollments_dir / f"enr_{class_id}_{learner_id}.json"
            previous = self._json_read_enrollment(path)
            if previous is not None and previous.get("status", "active") == "active":
                enr = ClassEnrollment.model_validate(previous)
                action = None
            else:
                enr = ClassEnrollment(
                    enrollment_id=(previous or {}).get("enrollment_id", enr_id),
                    class_id=class_id,
                    learner_id=learner_id,
                    enrolled_at_iso=(previous or {}).get(
                        "enrolled_at_iso", datetime.now(timezone.utc).isoformat()
                    ),
                    status="active",
                )
                _atomic_write_json(path, enr.model_dump(mode="json"), self.enrollments_dir)
                action = (
                    audit_log.ENROLLMENT_REACTIVATED if previous else audit_log.ENROLLMENT_CREATED
                )
            if action:
                self._json_audit(
                    actor_user_id=enroller_user_id, org_id=c.org_id, action=action,
                    target_type="enrollment", target_id=f"{class_id}:{learner_id}",
                    details={"class_id": class_id, "learner_id": learner_id},
                )

        # Keep the teacher_service projection current.
        self._append_learner_to_teacher_storage(class_id, learner_id)
        return enr

    async def _pg_enroll_learner(
        self, enr_id: str, class_id: str, learner_id: str, org_id: str, actor_user_id: str
    ) -> ClassEnrollment:
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                previous = await self._repo.get_enrollment(
                    conn, class_id, learner_id, for_update=True
                )
                enrollment = await self._repo.enroll_learner(
                    conn, enrollment_id=enr_id, class_id=class_id, learner_id=learner_id
                )
                if previous is None or previous.status != "active":
                    await self._audit_repo.insert(
                        conn, actor_user_id=actor_user_id, org_id=org_id,
                        action=(
                            audit_log.ENROLLMENT_REACTIVATED if previous
                            else audit_log.ENROLLMENT_CREATED
                        ),
                        target_type="enrollment", target_id=f"{class_id}:{learner_id}",
                        details={"class_id": class_id, "learner_id": learner_id},
                    )
                return enrollment

    @staticmethod
    def _json_read_enrollment(path: Path) -> Optional[Dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            return None

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
            raise ClassNotFoundError(class_id)
        # Enforce role in the class's own organization.
        membership = self.require_role(c.org_id, caller_user_id, [UserRole.ADMIN, UserRole.TEACHER])
        if membership.role == UserRole.TEACHER and caller_user_id not in c.teacher_ids:
            raise AuthorizationError("Teacher is not assigned to this class")

        # Active roster only: enrollments of deactivated learners are retained as
        # history but excluded here.
        if self._pg_enabled:
            return _run_async(self._pg_get_class_roster(class_id))
        return self._json_active_roster(class_id)

    async def _pg_get_class_roster(self, class_id: str) -> List[str]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await self._repo.get_active_class_learner_ids(conn, class_id)

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
                and enrollment.get("status", "active") == "active"
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    async def _pg_is_learner_enrolled(self, class_id: str, learner_id: str) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            enrollment = await self._repo.get_enrollment(conn, class_id, learner_id)
            return enrollment is not None and enrollment.status == "active"

    # -----------------------------------------------------------------------
    # Class lifecycle: unenrollment and teacher reassignment
    # -----------------------------------------------------------------------

    async def unenroll_learner_async(
        self, class_id: str, learner_id: str, actor_user_id: str
    ) -> bool:
        """Soft-unenroll; ADMIN of the class's org or an assigned TEACHER.

        Returns True when the enrollment changed, False when already unenrolled
        (idempotent). Raises ClassNotFoundError, AuthorizationError,
        EnrollmentNotFoundError. History and learner data are retained.
        """
        if self._pg_enabled:
            changed, org_id = await _await_background(
                self._pg_unenroll(class_id, learner_id, actor_user_id)
            )
        else:
            with self._membership_lock:
                course_class = self.get_class(class_id)
                if course_class is None:
                    raise ClassNotFoundError(class_id)
                org_id = course_class.org_id
                actor = self.require_role(org_id, actor_user_id, [UserRole.ADMIN, UserRole.TEACHER])
                if actor.role == UserRole.TEACHER and actor_user_id not in course_class.teacher_ids:
                    raise AuthorizationError(_FORBIDDEN)
                path = self.enrollments_dir / f"enr_{class_id}_{learner_id}.json"
                enrollment = self._json_read_enrollment(path)
                if enrollment is None or enrollment.get("learner_id") != learner_id:
                    raise EnrollmentNotFoundError(class_id)
                changed = enrollment.get("status", "active") == "active"
                if changed:
                    enrollment.update(
                        status="unenrolled",
                        unenrolled_at=datetime.now(timezone.utc).isoformat(),
                        unenrolled_by=actor_user_id,
                    )
                    _atomic_write_json(path, enrollment, self.enrollments_dir)
            if changed:
                self._json_audit(
                    actor_user_id=actor_user_id, org_id=org_id,
                    action=audit_log.ENROLLMENT_REMOVED, target_type="enrollment",
                    target_id=f"{class_id}:{learner_id}",
                    details={"class_id": class_id, "learner_id": learner_id},
                )
        if changed:
            await self._refresh_roster_projections(org_id)
        return changed

    async def _pg_unenroll(self, class_id: str, learner_id: str, actor_user_id: str):
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                course_class = await self._repo.get_class(conn, class_id)
                if course_class is None:
                    raise ClassNotFoundError(class_id)
                actor = await self._repo.get_membership(conn, course_class.org_id, actor_user_id)
                if (
                    actor is None or not actor.is_active
                    or actor.role not in (UserRole.ADMIN, UserRole.TEACHER)
                    or (actor.role == UserRole.TEACHER and actor_user_id not in course_class.teacher_ids)
                ):
                    raise AuthorizationError(_FORBIDDEN)
                previous = await self._repo.unenroll_learner(
                    conn, class_id=class_id, learner_id=learner_id, actor_user_id=actor_user_id
                )
                if previous is None:
                    raise EnrollmentNotFoundError(class_id)
                changed = previous == "active"
                if changed:
                    await self._audit_repo.insert(
                        conn, actor_user_id=actor_user_id, org_id=course_class.org_id,
                        action=audit_log.ENROLLMENT_REMOVED, target_type="enrollment",
                        target_id=f"{class_id}:{learner_id}",
                        details={"class_id": class_id, "learner_id": learner_id},
                    )
                return changed, course_class.org_id

    async def set_class_teachers_async(
        self, class_id: str, teacher_ids: List[str], actor_user_id: str
    ) -> CourseClass:
        """Replace a class's teachers. Active org ADMIN only; each teacher must be an
        active TEACHER member of the class's organization."""
        teacher_ids = list(dict.fromkeys(teacher_ids))
        if self._pg_enabled:
            return await _await_background(
                self._pg_set_class_teachers(class_id, teacher_ids, actor_user_id)
            )
        with self._membership_lock:
            course_class = self.get_class(class_id)
            if course_class is None:
                raise ClassNotFoundError(class_id)
            self.require_role(course_class.org_id, actor_user_id, [UserRole.ADMIN])
            for teacher_id in teacher_ids:
                member = self.get_membership(course_class.org_id, teacher_id)
                if member is None or not member.is_active or member.role != UserRole.TEACHER:
                    raise InvalidAssignmentError(
                        "Every teacher must be an active TEACHER member of the class's organization."
                    )
            before = list(course_class.teacher_ids)
            updated = course_class.model_copy(update={"teacher_ids": teacher_ids})
            _atomic_write_json(
                self.classes_dir / f"{class_id}.json", updated.model_dump(mode="json"), self.classes_dir
            )
        self._json_audit(
            actor_user_id=actor_user_id, org_id=course_class.org_id,
            action=audit_log.CLASS_TEACHERS_UPDATED, target_type="class", target_id=class_id,
            details={"before": before, "after": teacher_ids},
        )
        return updated

    async def _pg_set_class_teachers(
        self, class_id: str, teacher_ids: List[str], actor_user_id: str
    ) -> CourseClass:
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                course_class = await self._repo.get_class(conn, class_id)
                if course_class is None:
                    raise ClassNotFoundError(class_id)
                # Same lock order as membership operations: admin rows, then the target.
                admins = await self._repo.lock_active_admins(conn, course_class.org_id)
                if actor_user_id not in {a.user_id for a in admins}:
                    raise AuthorizationError(_FORBIDDEN)
                course_class = await self._repo.get_class(conn, class_id, for_update=True)
                for teacher_id in teacher_ids:
                    member = await self._repo.get_membership(conn, course_class.org_id, teacher_id)
                    if member is None or not member.is_active or member.role != UserRole.TEACHER:
                        raise InvalidAssignmentError(
                            "Every teacher must be an active TEACHER member of the class's organization."
                        )
                await self._repo.set_class_teachers(conn, class_id, teacher_ids)
                await self._audit_repo.insert(
                    conn, actor_user_id=actor_user_id, org_id=course_class.org_id,
                    action=audit_log.CLASS_TEACHERS_UPDATED, target_type="class", target_id=class_id,
                    details={"before": course_class.teacher_ids, "after": teacher_ids},
                )
                return course_class.model_copy(update={"teacher_ids": teacher_ids})

    # -----------------------------------------------------------------------
    # Membership reads: current user and organization member list
    # -----------------------------------------------------------------------

    async def list_memberships_for_user_async(
        self, user_id: str, *, include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """[{membership_id, org_id, org_name, role, is_active}] for one user."""
        if self._pg_enabled:
            async def _query():
                pool = await self._pool()
                async with pool.acquire() as conn:
                    return await self._repo.list_memberships_for_user(
                        conn, user_id, include_inactive=include_inactive
                    )
            rows = await _await_background(_query())
        else:
            rows = []
            for path in self.members_dir.glob("*.json"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        membership = OrgMembership.model_validate(json.load(f))
                except Exception as exc:
                    logger.warning("Unreadable membership %s: %s", path, exc)
                    continue
                if membership.user_id != user_id or not (include_inactive or membership.is_active):
                    continue
                org = self.get_organization(membership.org_id)
                if org is not None:
                    rows.append({"membership": membership, "org_name": org.name})
            rows.sort(key=lambda r: (r["org_name"], r["membership"].org_id))
        return [
            {
                "membership_id": r["membership"].membership_id,
                "org_id": r["membership"].org_id,
                "org_name": r["org_name"],
                "role": r["membership"].role,
                "is_active": r["membership"].is_active,
            }
            for r in rows
        ]

    async def list_org_memberships_async(
        self, org_id: str, acting_user_id: str, *, limit: int, offset: int, include_inactive: bool
    ) -> tuple[List[OrgMembership], int]:
        """Paginated members of an organization ordered by user_id; active org ADMIN only."""
        if self._pg_enabled:
            async def _query():
                pool = await self._pool()
                async with pool.acquire() as conn:
                    actor = await self._repo.get_membership(conn, org_id, acting_user_id)
                    if actor is None or not actor.is_active or actor.role != UserRole.ADMIN:
                        raise AuthorizationError(_NO_ADMIN)
                    return await self._repo.list_org_memberships(
                        conn, org_id, limit=limit, offset=offset, include_inactive=include_inactive
                    )
            return await _await_background(_query())
        actor = self.get_membership(org_id, acting_user_id)
        if actor is None or not actor.is_active or actor.role != UserRole.ADMIN:
            raise AuthorizationError(_NO_ADMIN)
        members = []
        for path in self.members_dir.glob(f"{org_id}_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    membership = OrgMembership.model_validate(json.load(f))
            except Exception as exc:
                logger.warning("Unreadable membership %s: %s", path, exc)
                continue
            if membership.org_id == org_id and (include_inactive or membership.is_active):
                members.append(membership)
        members.sort(key=lambda m: (m.user_id, m.membership_id))
        return members[offset:offset + limit], len(members)

    # -----------------------------------------------------------------------
    # Account lifecycle: export of Person 1-owned identity records
    # -----------------------------------------------------------------------

    async def export_identity_records_async(self, user_id: str) -> Dict[str, Any]:
        """User record, memberships, enrollments and audit events acted by the user."""
        user = await self.users.get_user(user_id)
        memberships = await self.list_memberships_for_user_async(user_id, include_inactive=True)
        if self._pg_enabled:
            async def _query():
                pool = await self._pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT class_id, status, enrolled_at, unenrolled_at FROM class_enrollments "
                        "WHERE learner_id = $1 ORDER BY class_id",
                        user_id,
                    )
                    return [
                        {
                            "class_id": r["class_id"],
                            "status": r["status"],
                            "enrolled_at": r["enrolled_at"].isoformat() if r["enrolled_at"] else None,
                            "unenrolled_at": r["unenrolled_at"].isoformat() if r["unenrolled_at"] else None,
                        }
                        for r in rows
                    ]
            enrollments = await _await_background(_query())
        else:
            enrollments = []
            for path in sorted(self.enrollments_dir.glob("*.json")):
                record = self._json_read_enrollment(path)
                if record and record.get("learner_id") == user_id:
                    enrollments.append({
                        "class_id": record.get("class_id"),
                        "status": record.get("status", "active"),
                        "enrolled_at": record.get("enrolled_at_iso"),
                        "unenrolled_at": record.get("unenrolled_at"),
                    })
        events = await self.audit.list_events(actor_user_id=user_id, limit=1000)
        return {
            "user": user,
            "memberships": [{**m, "role": m["role"].value} for m in memberships],
            "enrollments": enrollments,
            "audit_events_as_actor": [_export_audit_event(e, user_id) for e in events],
        }


# Detail keys that never hold another person's identifier. Everything else
# (teacher_ids, enrolled_learner_ids, before/after lists, learner_id, reason, ...)
# is dropped from a personal export.
_EXPORT_SAFE_DETAIL_KEYS = frozenset({"name", "role", "previous_role", "previously_active", "class_id", "status"})
# target_type -> how the target names a user: whole ID, or "<class_id>:<learner_id>".
_USER_TARGET_TYPES = frozenset({"membership", "user"})


def _export_audit_event(event: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Project an audit event the caller performed onto data safe to give the caller.

    The caller keeps the record of *what they did* (action, time, organization,
    class, their own documents) but never receives other users' identifiers, even
    after their memberships were deactivated (S2).
    """
    target_type = event.get("target_type")
    target_id = event.get("target_id")
    redacted = False
    if target_type in _USER_TARGET_TYPES and target_id != user_id:
        target_id, redacted = None, True
    elif target_type == "enrollment" and isinstance(target_id, str) and ":" in target_id:
        class_id, learner_id = target_id.split(":", 1)
        if learner_id != user_id:
            target_id, redacted = class_id, True
    details = event.get("details") or {}
    safe_details = {k: v for k, v in details.items() if k in _EXPORT_SAFE_DETAIL_KEYS}
    if len(safe_details) != len(details):
        redacted = True
    return {
        "event_id": event.get("event_id"),
        "occurred_at": event.get("occurred_at"),
        "actor_user_id": user_id,
        "org_id": event.get("org_id"),
        "action": event.get("action"),
        "target_type": target_type,
        "target_id": target_id,
        "details": safe_details,
        "redacted": redacted,
    }

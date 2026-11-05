"""Local user records and account status (Person 1 user lifecycle).

Supabase Auth remains the credential authority. LearnSense keeps one record per
verified identity: email (informational copy), status, timestamps. A ``disabled``
status blocks every protected LearnSense API call (enforced once, in
``backend.auth.get_current_user``) without changing the Supabase account, the
user's organization memberships, or any learning data.

Organization membership deactivation is a different thing: it removes access to
one organization only (docs/contracts/identity-and-roles.md).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from phase3.errors import AuthorizationError, LearnSenseError
from storage.id_validation import validate_canonical_learner_id
from storage.atomic_replace import replace_atomically

USER_STATUSES = ("active", "disabled")


class AccountDisabledError(LearnSenseError):
    code = "ACCOUNT_DISABLED"
    http_status = 403
    recoverable = False


class UserNotProvisionedError(AuthorizationError):
    """Target identity is not a provisioned LearnSense user (never signed in)."""

    code = "USER_NOT_PROVISIONED"
    http_status = 404


class UserService:
    def __init__(self, base_dir: str = "storage/users", pg_enabled: Optional[bool] = None):
        from backend.db.pg_connection import is_pg_configured

        self.base_dir = Path(base_dir)
        self._pg_enabled = is_pg_configured() if pg_enabled is None else pg_enabled
        self._lock = threading.Lock()

    # -- JSON mode ----------------------------------------------------------

    def _path(self, user_id: str) -> Path:
        return self.base_dir / f"{validate_canonical_learner_id(user_id)}.json"

    def get_user_json(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            path = self._path(user_id)
        except (TypeError, ValueError):
            return None
        try:
            with path.open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            return None

    def _write_json(self, record: Dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2)
            replace_atomically(tmp, self._path(record["user_id"]))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- PostgreSQL helpers ---------------------------------------------------

    async def _pg(self, operation):
        from backend.db.pg_connection import get_pg_pool
        from backend.services.institution_service import _await_background

        async def _run():
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    return await operation(conn)

        return await _await_background(_run())

    # -- Public API -----------------------------------------------------------

    async def ensure_user(self, user_id: str, email: Optional[str]) -> Dict[str, Any]:
        """Idempotently provision the record for a verified identity; refresh last_seen."""
        user_id = validate_canonical_learner_id(user_id)
        if self._pg_enabled:
            from backend.repositories.platform_repository import UserRepository

            async def _op(conn):
                record, _created = await UserRepository().upsert_seen(conn, user_id, email)
                return record

            return await self._pg(_op)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            record = self.get_user_json(user_id) or {
                "user_id": user_id,
                "email": None,
                "status": "active",
                "status_reason": None,
                "created_at": now,
            }
            record["email"] = email or record.get("email")
            record["updated_at"] = now
            record["last_seen_at"] = now
            self._write_json(record)
            return record

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            user_id = validate_canonical_learner_id(user_id)
        except (TypeError, ValueError):
            return None
        if self._pg_enabled:
            from backend.repositories.platform_repository import UserRepository

            return await self._pg(lambda conn: UserRepository().get(conn, user_id))
        return self.get_user_json(user_id)

    async def is_disabled(self, user_id: str) -> bool:
        record = await self.get_user(user_id)
        return bool(record and record.get("status") == "disabled")

    async def set_status(
        self, user_id: str, status: str, *, reason: Optional[str], actor_user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Operator action (scripts/manage_users.py). Audited. Returns None if no record."""
        from backend.services import audit_log

        if status not in USER_STATUSES:
            raise ValueError(f"status must be one of {USER_STATUSES}")
        user_id = validate_canonical_learner_id(user_id)
        details = {"status": status, "reason": reason}
        if self._pg_enabled:
            from backend.repositories.platform_repository import AuditRepository, UserRepository

            async def _op(conn):
                record = await UserRepository().set_status(conn, user_id, status, reason)
                if record is not None:
                    await AuditRepository().insert(
                        conn, actor_user_id=actor_user_id, org_id=None,
                        action=audit_log.USER_STATUS_CHANGED, target_type="user",
                        target_id=user_id, details=details,
                    )
                return record

            return await self._pg(_op)
        with self._lock:
            record = self.get_user_json(user_id)
            if record is None:
                return None
            record.update(status=status, status_reason=reason,
                          updated_at=datetime.now(timezone.utc).isoformat())
            self._write_json(record)
        audit_log.AuditLog(str(self.base_dir.parent / "audit")).record(
            actor_user_id=actor_user_id, org_id=None, action=audit_log.USER_STATUS_CHANGED,
            target_type="user", target_id=user_id, details=details,
        )
        return record

    def require_provisioned_staff_sync(self, user_id: str) -> None:
        """JSON mode: staff grants need a canonical, provisioned, active user record."""
        record = self.get_user_json(user_id)
        if record is None or record.get("status") != "active":
            raise UserNotProvisionedError(
                "The user must sign in to LearnSense before they can be given this role."
            )


_default_service: Optional[UserService] = None
_default_lock = threading.Lock()


def get_user_service() -> UserService:
    """Process-wide service used by the authentication dependency."""
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = UserService()
        return _default_service


def reset_user_service_for_testing(service: Optional[UserService] = None) -> None:
    global _default_service
    with _default_lock:
        _default_service = service

"""Audit events for privileged institutional operations.

PostgreSQL mode: services insert events with ``AuditRepository`` *inside the same
transaction* as the operation, so an event exists if and only if the operation
committed. JSON (development) mode: events are appended to a JSONL file after the
operation succeeds. Denied or failed operations never produce events.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Action vocabulary (docs/contracts/identity-and-roles.md).
ORG_CREATED = "org.created"
MEMBERSHIP_CREATED = "membership.created"
MEMBERSHIP_ROLE_CHANGED = "membership.role_changed"
MEMBERSHIP_REACTIVATED = "membership.reactivated"
MEMBERSHIP_DEACTIVATED = "membership.deactivated"
CLASS_CREATED = "class.created"
ENROLLMENT_CREATED = "class.enrollment.created"
ENROLLMENT_REACTIVATED = "class.enrollment.reactivated"
ENROLLMENT_REMOVED = "class.enrollment.removed"
CLASS_TEACHERS_UPDATED = "class.teachers.updated"
SHARE_GRANTED = "document.share.granted"
SHARE_REVOKED = "document.share.revoked"
USER_STATUS_CHANGED = "user.status_changed"
INVITATION_CREATED = "org.invitation.created"
INVITATION_REVOKED = "org.invitation.revoked"
INVITATION_ACCEPTED = "org.invitation.accepted"
USER_PROFILE_UPDATED = "user.profile_updated"


class AuditLog:
    """JSON-mode audit store and PostgreSQL read access."""

    def __init__(self, base_dir: str, pg_enabled: bool = False):
        self.path = Path(base_dir) / "audit_events.jsonl"
        self._pg_enabled = pg_enabled
        self._lock = threading.Lock()

    def record(
        self,
        *,
        actor_user_id: str,
        org_id: Optional[str],
        action: str,
        target_type: str,
        target_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append one event (JSON mode only; PostgreSQL writes happen in-transaction)."""
        if self._pg_enabled:
            raise RuntimeError("In PostgreSQL mode audit events are written in-transaction")
        event = {
            "event_id": str(uuid.uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "actor_user_id": actor_user_id,
            "org_id": org_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    async def list_events(
        self,
        *,
        org_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if self._pg_enabled:
            from backend.db.pg_connection import get_pg_pool
            from backend.repositories.platform_repository import AuditRepository
            from backend.services.institution_service import _await_background

            async def _query():
                pool = await get_pg_pool()
                async with pool.acquire() as conn:
                    return await AuditRepository().list_events(
                        conn, org_id=org_id, actor_user_id=actor_user_id,
                        target_id=target_id, limit=limit,
                    )

            return await _await_background(_query())
        if not self.path.exists():
            return []
        events = []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if org_id is not None and event.get("org_id") != org_id:
                continue
            if actor_user_id is not None and event.get("actor_user_id") != actor_user_id:
                continue
            if target_id is not None and event.get("target_id") != target_id:
                continue
            events.append(event)
        events.sort(key=lambda e: e["occurred_at"], reverse=True)
        return events[:limit]

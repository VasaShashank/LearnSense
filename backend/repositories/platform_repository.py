"""PostgreSQL repositories for Person 1 platform records (migrations 003-005).

Like ``institution_repository``, every method takes an ``asyncpg`` connection so
the caller owns transaction boundaries. Nothing here commits or rolls back.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)


def _json(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

class AuditRepository:
    async def insert(
        self,
        conn: Any,
        *,
        actor_user_id: str,
        org_id: Optional[str],
        action: str,
        target_type: str,
        target_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = await conn.fetchrow(
            """
            INSERT INTO audit_events (actor_user_id, org_id, action, target_type, target_id, details)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING event_id, occurred_at, actor_user_id, org_id, action, target_type, target_id, details
            """,
            actor_user_id, org_id, action, target_type, target_id, json.dumps(details or {}),
        )
        return self._row(row)

    async def list_events(
        self,
        conn: Any,
        *,
        org_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT event_id, occurred_at, actor_user_id, org_id, action, target_type, target_id, details
            FROM audit_events
            WHERE ($1::text IS NULL OR org_id = $1)
              AND ($2::text IS NULL OR actor_user_id = $2)
              AND ($3::text IS NULL OR target_id = $3)
            ORDER BY occurred_at DESC, event_id
            LIMIT $4
            """,
            org_id, actor_user_id, target_id, limit,
        )
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: Any) -> Dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "occurred_at": _iso(row["occurred_at"]),
            "actor_user_id": row["actor_user_id"],
            "org_id": row["org_id"],
            "action": row["action"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "details": _json(row["details"]),
        }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserRepository:
    _COLUMNS = "user_id, email, status, status_reason, created_at, updated_at, last_seen_at"

    async def upsert_seen(self, conn: Any, user_id: str, email: Optional[str]) -> Tuple[Dict[str, Any], bool]:
        """Create the record or refresh email/last_seen_at. Returns (record, created)."""
        row = await conn.fetchrow(
            f"""
            INSERT INTO users (user_id, email, last_seen_at)
            VALUES ($1::uuid, $2, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET email = COALESCE(EXCLUDED.email, users.email),
                    last_seen_at = NOW(),
                    updated_at = NOW()
            RETURNING {self._COLUMNS}, (xmax = 0) AS inserted
            """,
            user_id, email,
        )
        return self._row(row), bool(row["inserted"])

    async def get(self, conn: Any, user_id: str, *, for_update: bool = False) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(
            f"SELECT {self._COLUMNS} FROM users WHERE user_id = $1::uuid"
            + (" FOR UPDATE" if for_update else ""),
            user_id,
        )
        return self._row(row) if row else None

    async def set_status(self, conn: Any, user_id: str, status: str, reason: Optional[str]) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(
            f"""
            UPDATE users SET status = $2, status_reason = $3, updated_at = NOW()
            WHERE user_id = $1::uuid
            RETURNING {self._COLUMNS}
            """,
            user_id, status, reason,
        )
        return self._row(row) if row else None

    @staticmethod
    def _row(row: Any) -> Dict[str, Any]:
        return {
            "user_id": str(row["user_id"]),
            "email": row["email"],
            "status": row["status"],
            "status_reason": row["status_reason"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "last_seen_at": _iso(row["last_seen_at"]),
        }


# ---------------------------------------------------------------------------
# Document ownership and shares
# ---------------------------------------------------------------------------

class DocumentAccessRepository:
    async def claim(self, conn: Any, document_id: str, owner_id: str, *, source: str = "app") -> str:
        """Insert ownership once. Returns the stored owner (existing owner wins)."""
        await conn.execute(
            """
            INSERT INTO document_owners (document_id, owner_id, source)
            VALUES ($1, $2, $3)
            ON CONFLICT (document_id) DO NOTHING
            """,
            document_id, owner_id, source,
        )
        return await conn.fetchval("SELECT owner_id FROM document_owners WHERE document_id = $1", document_id)

    async def get_owner(self, conn: Any, document_id: str) -> Optional[str]:
        return await conn.fetchval("SELECT owner_id FROM document_owners WHERE document_id = $1", document_id)

    async def list_owned(self, conn: Any, owner_id: str) -> List[str]:
        rows = await conn.fetch(
            "SELECT document_id FROM document_owners WHERE owner_id = $1 ORDER BY document_id", owner_id
        )
        return [r["document_id"] for r in rows]

    async def grant(
        self, conn: Any, *, document_id: str, class_id: str, owner_id: str, shared_by: str
    ) -> Tuple[Dict[str, Any], bool]:
        row = await conn.fetchrow(
            """
            INSERT INTO document_shares (document_id, class_id, owner_id, shared_by)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (document_id, class_id) DO NOTHING
            RETURNING document_id, class_id, owner_id, shared_by, created_at
            """,
            document_id, class_id, owner_id, shared_by,
        )
        if row is not None:
            return self._share(row), True
        existing = await conn.fetchrow(
            "SELECT document_id, class_id, owner_id, shared_by, created_at "
            "FROM document_shares WHERE document_id = $1 AND class_id = $2",
            document_id, class_id,
        )
        return self._share(existing), False

    async def revoke(self, conn: Any, *, document_id: str, class_id: str, owner_id: str) -> bool:
        result = await conn.execute(
            "DELETE FROM document_shares WHERE document_id = $1 AND class_id = $2 AND owner_id = $3",
            document_id, class_id, owner_id,
        )
        return result.endswith(" 1")

    async def list_for_document(self, conn: Any, document_id: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            "SELECT document_id, class_id, owner_id, shared_by, created_at "
            "FROM document_shares WHERE document_id = $1 ORDER BY class_id",
            document_id,
        )
        return [self._share(r) for r in rows]

    # Class-share access, driven by the learner's OWN active enrollments: only shares
    # of classes the learner is actively enrolled in are touched (indexes:
    # class_enrollments(learner_id), document_shares(class_id),
    # org_memberships(org_id, user_id)). Policy mirrors DocumentAccessService:
    # share owner == document owner, class exists, enrollment active, membership
    # active with role LEARNER.
    _SHARED_FOR_LEARNER = """
        SELECT s.document_id
        FROM class_enrollments AS e
        JOIN course_classes   AS c ON c.class_id = e.class_id
        JOIN org_memberships  AS m ON m.org_id = c.org_id AND m.user_id = e.learner_id
        JOIN document_shares  AS s ON s.class_id = e.class_id
        JOIN document_owners  AS o ON o.document_id = s.document_id AND o.owner_id = s.owner_id
        WHERE e.learner_id = $1 AND e.status = 'active'
          AND m.is_active = TRUE AND m.role = 'LEARNER'
    """

    async def owned_and_shared_document_ids(self, conn: Any, user_id: str) -> Tuple[List[str], List[str]]:
        """(owned, shared-via-active-class) document IDs in ONE round trip."""
        rows = await conn.fetch(
            "SELECT document_id, 'owned' AS via FROM document_owners WHERE owner_id = $1 "
            "UNION SELECT document_id, 'shared' AS via FROM (" + self._SHARED_FOR_LEARNER + ") AS shared",
            user_id,
        )
        owned = sorted({r["document_id"] for r in rows if r["via"] == "owned"})
        shared = sorted({r["document_id"] for r in rows if r["via"] == "shared"})
        return owned, shared

    async def learner_has_shared_access(self, conn: Any, document_id: str, user_id: str) -> bool:
        return bool(await conn.fetchval(
            "SELECT EXISTS (" + self._SHARED_FOR_LEARNER + " AND s.document_id = $2)",
            user_id, document_id,
        ))

    async def list_all(self, conn: Any) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            "SELECT document_id, class_id, owner_id, shared_by, created_at "
            "FROM document_shares ORDER BY document_id, class_id"
        )
        return [self._share(r) for r in rows]

    @staticmethod
    def _share(row: Any) -> Dict[str, Any]:
        return {
            "document_id": row["document_id"],
            "class_id": row["class_id"],
            "owner_id": row["owner_id"],
            "shared_by": row["shared_by"],
            "created_at": _iso(row["created_at"]),
        }


# ---------------------------------------------------------------------------
# Plans, quota limits, usage events
# ---------------------------------------------------------------------------

class UsageRepository:
    async def create_plan(self, conn: Any, plan_id: str, name: str) -> None:
        await conn.execute(
            "INSERT INTO plans (plan_id, name) VALUES ($1, $2) "
            "ON CONFLICT (plan_id) DO UPDATE SET name = EXCLUDED.name",
            plan_id, name,
        )

    async def set_limit(self, conn: Any, plan_id: str, dimension: str, period: str, limit_quantity: int) -> None:
        await conn.execute(
            """
            INSERT INTO quota_limits (plan_id, dimension, period, limit_quantity)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (plan_id, dimension, period) DO UPDATE SET limit_quantity = EXCLUDED.limit_quantity
            """,
            plan_id, dimension, period, limit_quantity,
        )

    async def assign_plan(self, conn: Any, org_id: str, plan_id: str, assigned_by: str) -> None:
        await conn.execute(
            """
            INSERT INTO org_plan_assignments (org_id, plan_id, assigned_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (org_id) DO UPDATE
                SET plan_id = EXCLUDED.plan_id, assigned_by = EXCLUDED.assigned_by, assigned_at = NOW()
            """,
            org_id, plan_id, assigned_by,
        )

    async def get_org_plan(self, conn: Any, org_id: str) -> Optional[str]:
        return await conn.fetchval("SELECT plan_id FROM org_plan_assignments WHERE org_id = $1", org_id)

    async def limits_for(self, conn: Any, plan_id: str, dimension: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            "SELECT period, limit_quantity FROM quota_limits WHERE plan_id = $1 AND dimension = $2 ORDER BY period",
            plan_id, dimension,
        )
        return [{"period": r["period"], "limit": int(r["limit_quantity"])} for r in rows]

    async def usage_since(self, conn: Any, org_id: str, dimension: str, since: Optional[datetime]) -> int:
        value = await conn.fetchval(
            """
            SELECT COALESCE(SUM(quantity), 0) FROM usage_events
            WHERE org_id = $1 AND dimension = $2 AND ($3::timestamptz IS NULL OR occurred_at >= $3)
            """,
            org_id, dimension, since,
        )
        return int(value)

    async def lock_quota_scope(self, conn: Any, org_id: str, dimension: str) -> None:
        """Transaction-scoped advisory lock serializing consumers of one (org, dimension)."""
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"quota:{org_id}:{dimension}")

    async def insert_event(
        self, conn: Any, *, org_id: Optional[str], user_id: str, dimension: str,
        quantity: int, source: str, request_id: str,
    ) -> Tuple[Dict[str, Any], bool]:
        row = await conn.fetchrow(
            """
            INSERT INTO usage_events (org_id, user_id, dimension, quantity, source, request_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (request_id) DO NOTHING
            RETURNING event_id, occurred_at, org_id, user_id, dimension, quantity, source, request_id
            """,
            org_id, user_id, dimension, quantity, source, request_id,
        )
        if row is not None:
            return self._event(row), True
        existing = await conn.fetchrow(
            "SELECT event_id, occurred_at, org_id, user_id, dimension, quantity, source, request_id "
            "FROM usage_events WHERE request_id = $1",
            request_id,
        )
        return self._event(existing), False

    @staticmethod
    def _event(row: Any) -> Dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "occurred_at": _iso(row["occurred_at"]),
            "org_id": row["org_id"],
            "user_id": row["user_id"],
            "dimension": row["dimension"],
            "quantity": int(row["quantity"]),
            "source": row["source"],
            "request_id": row["request_id"],
        }

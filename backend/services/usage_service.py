"""Usage events, plans and server-side quota enforcement (Person 1 foundation).

Person 5 owns the metering *dimensions*, where usage is recorded in ingestion/LLM
workflows, cost reports and dashboards. This module owns storage, attribution,
idempotency and enforcement. See docs/contracts/usage-and-quotas.md.

Semantics
---------
* Quotas are per organization and dimension, over a period: ``day`` and ``month``
  (UTC calendar boundaries) or ``total``.
* An organization with no plan assignment has no limits (documented no-plan state).
* Usage with ``org_id=None`` is attributed to the user only and is not quota-limited.
* ``record_usage`` is idempotent on ``request_id``; a replay returns the original
  event and never double-counts. Reusing a request_id for a *different* usage raises
  ``IdempotencyConflict``.
* ``consume`` = check + record atomically; it serializes concurrent consumers of the
  same (org, dimension), preventing overshoot. ``check_quota`` alone is advisory.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from phase3.errors import AuthorizationError, LearnSenseError

PERIODS = ("day", "month", "total")
_DIMENSION = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_PLAN_ID = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")
MAX_QUANTITY = 10**12


class QuotaExceeded(LearnSenseError):
    code = "QUOTA_EXCEEDED"
    http_status = 429
    recoverable = False


class InvalidUsageError(LearnSenseError):
    code = "INVALID_USAGE"
    http_status = 400
    recoverable = False


class IdempotencyConflict(LearnSenseError):
    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    recoverable = False


def period_bounds(period: str, now: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
    """(start, resets_at) in UTC; ``total`` has neither."""
    now = now.astimezone(timezone.utc)
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, datetime.fromordinal(start.toordinal() + 1).replace(tzinfo=timezone.utc)
    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        return start, nxt
    return None, None


def _validate(dimension: str, quantity: int, *, source: Optional[str] = None,
              request_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
    if not isinstance(dimension, str) or not _DIMENSION.match(dimension):
        raise InvalidUsageError("Invalid usage dimension.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 < quantity <= MAX_QUANTITY:
        raise InvalidUsageError("Usage quantity must be a positive integer.")
    if source is not None and (not isinstance(source, str) or not source.strip() or len(source) > 128):
        raise InvalidUsageError("Usage source is required.")
    if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200):
        raise InvalidUsageError("A request_id is required for idempotent usage recording.")
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        raise InvalidUsageError("Usage must be attributed to a user.")


def _same_usage(event: Dict[str, Any], org_id, user_id, dimension, quantity) -> bool:
    return (
        event["org_id"] == org_id and event["user_id"] == user_id
        and event["dimension"] == dimension and int(event["quantity"]) == quantity
    )


class UsageService:
    def __init__(
        self,
        base_dir: str = "storage/usage",
        *,
        membership_lookup: Optional[Callable[[str, str], Any]] = None,
        pg_enabled: Optional[bool] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        from backend.db.pg_connection import is_pg_configured

        self.base_dir = Path(base_dir)
        self._pg_enabled = is_pg_configured() if pg_enabled is None else pg_enabled
        self._membership_lookup = membership_lookup
        self._clock = clock
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ PG plumbing

    async def _pg(self, operation):
        from backend.db.pg_connection import get_pg_pool
        from backend.services.institution_service import _await_background

        async def _run():
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    return await operation(conn)

        return await _await_background(_run())

    @staticmethod
    async def _pg_require_member(conn, org_id: str, user_id: str) -> None:
        active = await conn.fetchval(
            "SELECT is_active FROM org_memberships WHERE org_id = $1 AND user_id = $2", org_id, user_id
        )
        if not active:
            raise AuthorizationError("Usage can only be attributed to an active member of the organization.")

    async def _pg_limits_status(self, conn, org_id: str, dimension: str, qty: int) -> List[Dict[str, Any]]:
        from backend.repositories.platform_repository import UsageRepository

        repo = UsageRepository()
        plan_id = await repo.get_org_plan(conn, org_id)
        if plan_id is None:
            return []
        now = self._clock()
        out = []
        for limit in await repo.limits_for(conn, plan_id, dimension):
            start, resets = period_bounds(limit["period"], now)
            used = await repo.usage_since(conn, org_id, dimension, start)
            out.append(self._limit_entry(limit, used, qty, resets))
        return out

    # ------------------------------------------------------------------ JSON plumbing

    def _json_state(self) -> Dict[str, Any]:
        path = self.base_dir / "plans.json"
        if not path.exists():
            return {"plans": {}, "limits": {}, "assignments": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _json_save_state(self, state: Dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.base_dir / "plans.json.tmp"
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.base_dir / "plans.json")

    def _json_events(self) -> List[Dict[str, Any]]:
        path = self.base_dir / "usage_events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _json_require_member(self, org_id: str, user_id: str) -> None:
        if self._membership_lookup is None:
            raise AuthorizationError("Organization membership cannot be verified.")
        membership = self._membership_lookup(org_id, user_id)
        if membership is None or not getattr(membership, "is_active", False):
            raise AuthorizationError("Usage can only be attributed to an active member of the organization.")

    def _json_limits_status(self, org_id: str, dimension: str, qty: int) -> List[Dict[str, Any]]:
        state = self._json_state()
        plan_id = state["assignments"].get(org_id)
        if plan_id is None:
            return []
        now = self._clock()
        events = [e for e in self._json_events() if e["org_id"] == org_id and e["dimension"] == dimension]
        out = []
        for period, limit in sorted(state["limits"].get(plan_id, {}).get(dimension, {}).items()):
            start, resets = period_bounds(period, now)
            used = sum(
                int(e["quantity"]) for e in events
                if start is None or datetime.fromisoformat(e["occurred_at"]) >= start
            )
            out.append(self._limit_entry({"period": period, "limit": int(limit)}, used, qty, resets))
        return out

    # ------------------------------------------------------------------ shared logic

    @staticmethod
    def _limit_entry(limit: Dict[str, Any], used: int, qty: int, resets: Optional[datetime]) -> Dict[str, Any]:
        return {
            "period": limit["period"],
            "limit": limit["limit"],
            "used": used,
            "requested": qty,
            "remaining": max(limit["limit"] - used, 0),
            "allowed": used + qty <= limit["limit"],
            "resets_at": resets.isoformat() if resets else None,
        }

    @staticmethod
    def _raise_if_exceeded(dimension: str, limits: List[Dict[str, Any]]) -> None:
        for entry in limits:
            if not entry["allowed"]:
                raise QuotaExceeded(
                    "Usage quota exceeded for this organization.",
                    details={"dimension": dimension, **{k: entry[k] for k in
                             ("period", "limit", "used", "requested", "resets_at")}},
                )

    # ------------------------------------------------------------------ public API

    async def check_quota(self, org_id: Optional[str], user_id: str, dimension: str, qty: int) -> Dict[str, Any]:
        """Advisory check. Raises QuotaExceeded; returns per-period status otherwise."""
        _validate(dimension, qty, user_id=user_id)
        if org_id is None:
            return {"dimension": dimension, "limits": []}
        if self._pg_enabled:
            async def _op(conn):
                await self._pg_require_member(conn, org_id, user_id)
                return await self._pg_limits_status(conn, org_id, dimension, qty)
            limits = await self._pg(_op)
        else:
            self._json_require_member(org_id, user_id)
            with self._lock:
                limits = self._json_limits_status(org_id, dimension, qty)
        self._raise_if_exceeded(dimension, limits)
        return {"dimension": dimension, "limits": limits}

    async def record_usage(
        self, org_id: Optional[str], user_id: str, dimension: str, quantity: int, source: str, request_id: str
    ) -> Dict[str, Any]:
        """Record attributable usage. Idempotent on request_id. No quota check."""
        return await self._record(org_id, user_id, dimension, quantity, source, request_id, enforce=False)

    async def consume(
        self, org_id: Optional[str], user_id: str, dimension: str, quantity: int, source: str, request_id: str
    ) -> Dict[str, Any]:
        """Atomically enforce quota and record usage. A replayed request_id is not re-checked."""
        return await self._record(org_id, user_id, dimension, quantity, source, request_id, enforce=True)

    async def _record(self, org_id, user_id, dimension, quantity, source, request_id, *, enforce: bool):
        _validate(dimension, quantity, source=source, request_id=request_id, user_id=user_id)
        if self._pg_enabled:
            from backend.repositories.platform_repository import UsageRepository

            async def _op(conn):
                repo = UsageRepository()
                existing = await conn.fetchrow(
                    "SELECT org_id, user_id, dimension, quantity FROM usage_events WHERE request_id = $1",
                    request_id,
                )
                if existing is not None:
                    if not _same_usage(dict(existing), org_id, user_id, dimension, quantity):
                        raise IdempotencyConflict("request_id was already used for different usage.")
                    event, _ = await repo.insert_event(
                        conn, org_id=org_id, user_id=user_id, dimension=dimension,
                        quantity=quantity, source=source, request_id=request_id,
                    )
                    return {"event": event, "created": False}
                if org_id is not None:
                    await self._pg_require_member(conn, org_id, user_id)
                    if enforce:
                        await repo.lock_quota_scope(conn, org_id, dimension)
                        self._raise_if_exceeded(
                            dimension, await self._pg_limits_status(conn, org_id, dimension, quantity)
                        )
                event, created = await repo.insert_event(
                    conn, org_id=org_id, user_id=user_id, dimension=dimension,
                    quantity=quantity, source=source, request_id=request_id,
                )
                if not created and not _same_usage(event, org_id, user_id, dimension, quantity):
                    raise IdempotencyConflict("request_id was already used for different usage.")
                return {"event": event, "created": created}

            return await self._pg(_op)

        with self._lock:
            for event in self._json_events():
                if event["request_id"] == request_id:
                    if not _same_usage(event, org_id, user_id, dimension, quantity):
                        raise IdempotencyConflict("request_id was already used for different usage.")
                    return {"event": event, "created": False}
            if org_id is not None:
                self._json_require_member(org_id, user_id)
                if enforce:
                    self._raise_if_exceeded(dimension, self._json_limits_status(org_id, dimension, quantity))
            event = {
                "event_id": str(uuid.uuid4()),
                "occurred_at": self._clock().isoformat(),
                "org_id": org_id, "user_id": user_id, "dimension": dimension,
                "quantity": quantity, "source": source, "request_id": request_id,
            }
            self.base_dir.mkdir(parents=True, exist_ok=True)
            with (self.base_dir / "usage_events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
            return {"event": event, "created": True}

    # ------------------------------------------------------------------ plan administration
    # Operator-level functions (no HTTP route): plan management UI/billing are not P1.

    async def create_plan(self, plan_id: str, name: str) -> None:
        if not _PLAN_ID.match(plan_id or ""):
            raise InvalidUsageError("Invalid plan_id.")
        if self._pg_enabled:
            from backend.repositories.platform_repository import UsageRepository
            await self._pg(lambda conn: UsageRepository().create_plan(conn, plan_id, name))
            return
        with self._lock:
            state = self._json_state()
            state["plans"][plan_id] = name
            self._json_save_state(state)

    async def set_quota_limit(self, plan_id: str, dimension: str, period: str, limit: int) -> None:
        if period not in PERIODS:
            raise InvalidUsageError("period must be day, month or total.")
        if not _DIMENSION.match(dimension or "") or isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise InvalidUsageError("Invalid quota limit.")
        if self._pg_enabled:
            from backend.repositories.platform_repository import UsageRepository
            await self._pg(lambda conn: UsageRepository().set_limit(conn, plan_id, dimension, period, limit))
            return
        with self._lock:
            state = self._json_state()
            if plan_id not in state["plans"]:
                raise InvalidUsageError("Unknown plan.")
            state["limits"].setdefault(plan_id, {}).setdefault(dimension, {})[period] = limit
            self._json_save_state(state)

    async def assign_plan(self, org_id: str, plan_id: str, *, assigned_by: str) -> None:
        if self._pg_enabled:
            from backend.repositories.platform_repository import UsageRepository
            await self._pg(lambda conn: UsageRepository().assign_plan(conn, org_id, plan_id, assigned_by))
            return
        with self._lock:
            state = self._json_state()
            if plan_id not in state["plans"]:
                raise InvalidUsageError("Unknown plan.")
            state["assignments"][org_id] = plan_id
            self._json_save_state(state)

    async def get_org_plan(self, org_id: str) -> Optional[str]:
        if self._pg_enabled:
            from backend.repositories.platform_repository import UsageRepository
            return await self._pg(lambda conn: UsageRepository().get_org_plan(conn, org_id))
        return self._json_state()["assignments"].get(org_id)


# ---------------------------------------------------------------------------
# Shared instance (the supported way to obtain the service)
# ---------------------------------------------------------------------------

DEFAULT_JSON_DIR = "storage/usage"
_default_service: Optional[UsageService] = None
_default_lock = threading.Lock()


def _api_membership_lookup(org_id: str, user_id: str):
    """JSON mode: verify membership through the API's InstitutionService instance.

    Resolved at call time (not import time) so the lookup always uses the same
    institution store the API serves, including in tests that replace it.
    """
    from backend.routes import api as api_module

    return api_module.institution_service.get_membership(org_id, user_id)


def get_usage_service() -> UsageService:
    """Process-wide UsageService.

    * PostgreSQL mode (DATABASE_URL configured): membership is verified in SQL and
      quota enforcement uses a transaction-scoped advisory lock per (org, dimension).
    * JSON mode (development/tests): membership is verified through
      ``InstitutionService.get_membership``; one shared instance means one shared
      process-local lock, so concurrent ``consume`` calls in this process serialize.
    """
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = UsageService(
                base_dir=DEFAULT_JSON_DIR, membership_lookup=_api_membership_lookup
            )
        return _default_service


def reset_usage_service_for_testing(service: Optional[UsageService] = None) -> None:
    global _default_service
    with _default_lock:
        _default_service = service

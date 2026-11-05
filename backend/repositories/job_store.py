"""Canonical job persistence (migration 006) — Person 1 foundation for Person 5.

This module stores job records and enforces the *allowed status transitions*.
It deliberately contains no worker execution, retry policy or cancellation
orchestration: those belong to Person 5 (docs/contracts/jobs.md).

Status vocabulary (Master Blueprint §5.3): queued, running, succeeded, failed,
cancelled. ``LEGACY_STATUS_MAP`` translates the statuses still produced by the
JSON-file job path (``storage/job_repository.py``) without changing its consumers.
"""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from backend.repositories.platform_repository import _iso, _json


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.CANCELLED})

# to_status -> statuses it may be entered from.
ALLOWED_TRANSITIONS: Dict[JobStatus, frozenset] = {
    JobStatus.RUNNING: frozenset({JobStatus.QUEUED}),
    JobStatus.SUCCEEDED: frozenset({JobStatus.RUNNING}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED, JobStatus.RUNNING}),
    JobStatus.CANCELLED: frozenset({JobStatus.QUEUED, JobStatus.RUNNING}),
    # Re-queue: an interrupted run, or a failed job with attempts remaining.
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.FAILED}),
}

LEGACY_STATUS_MAP: Dict[str, JobStatus] = {
    "queued": JobStatus.QUEUED,
    "processing": JobStatus.RUNNING,
    "done": JobStatus.SUCCEEDED,
    "error": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
}

MAX_ERROR_MESSAGE_LENGTH = 500


class JobTransitionError(ValueError):
    """The requested status change is not allowed from the job's current state."""


def to_canonical_status(legacy_status: str) -> JobStatus:
    try:
        return LEGACY_STATUS_MAP[legacy_status]
    except KeyError as exc:
        raise ValueError(f"Unknown legacy job status: {legacy_status!r}") from exc


def to_legacy_status(status: JobStatus) -> str:
    return {v: k for k, v in LEGACY_STATUS_MAP.items()}[JobStatus(status)]


_COLUMNS = (
    "job_id, kind, owner_id, org_id, document_id, status, progress_pct, stage, error_code, "
    "error_message, attempt, max_attempts, idempotency_key, pipeline_version, result, "
    "cancel_requested_at, created_at, updated_at, started_at, finished_at"
)


def _row(row: Any) -> Dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "kind": row["kind"],
        "owner_id": row["owner_id"],
        "org_id": row["org_id"],
        "document_id": row["document_id"],
        "status": row["status"],
        "progress_pct": int(row["progress_pct"]),
        "stage": row["stage"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "attempt": int(row["attempt"]),
        "max_attempts": int(row["max_attempts"]),
        "idempotency_key": row["idempotency_key"],
        "pipeline_version": row["pipeline_version"],
        "result": _json(row["result"]) if row["result"] is not None else None,
        "cancel_requested_at": _iso(row["cancel_requested_at"]),
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "started_at": _iso(row["started_at"]),
        "finished_at": _iso(row["finished_at"]),
    }


class JobStore:
    """Repository over ``jobs``; every method takes a connection (caller owns transactions)."""

    async def create(
        self,
        conn: Any,
        *,
        kind: str,
        owner_id: str,
        org_id: Optional[str] = None,
        document_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        max_attempts: int = 1,
        pipeline_version: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """Create a queued job. With an idempotency key, a repeat returns the original."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        row = await conn.fetchrow(
            f"""
            INSERT INTO jobs (job_id, kind, owner_id, org_id, document_id, idempotency_key,
                              max_attempts, pipeline_version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (owner_id, idempotency_key) DO NOTHING
            RETURNING {_COLUMNS}
            """,
            job_id or f"job_{uuid.uuid4().hex}", kind, owner_id, org_id, document_id,
            idempotency_key, max_attempts, pipeline_version,
        )
        if row is not None:
            return _row(row), True
        existing = await conn.fetchrow(
            f"SELECT {_COLUMNS} FROM jobs WHERE owner_id = $1 AND idempotency_key = $2",
            owner_id, idempotency_key,
        )
        return _row(existing), False

    async def get(
        self, conn: Any, job_id: str, *, owner_id: Optional[str] = None, for_update: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Owner-scoped when ``owner_id`` is given: another owner's job reads as missing."""
        row = await conn.fetchrow(
            f"SELECT {_COLUMNS} FROM jobs WHERE job_id = $1 AND ($2::text IS NULL OR owner_id = $2)"
            + (" FOR UPDATE" if for_update else ""),
            job_id, owner_id,
        )
        return _row(row) if row else None

    async def list_for_owner(
        self, conn: Any, owner_id: str, *, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT {_COLUMNS} FROM jobs WHERE owner_id = $1 "
            "ORDER BY created_at DESC, job_id LIMIT $2 OFFSET $3",
            owner_id, limit, offset,
        )
        return [_row(r) for r in rows]

    async def transition(
        self,
        conn: Any,
        job_id: str,
        to_status: JobStatus,
        *,
        stage: Optional[str] = None,
        progress_pct: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Apply one allowed status change atomically (row lock). Raises JobTransitionError."""
        to_status = JobStatus(to_status)
        current = await self.get(conn, job_id, for_update=True)
        if current is None:
            raise LookupError(job_id)
        from_status = JobStatus(current["status"])
        if from_status not in ALLOWED_TRANSITIONS[to_status]:
            raise JobTransitionError(f"{from_status.value} -> {to_status.value} is not allowed")
        if (
            to_status == JobStatus.QUEUED
            and from_status == JobStatus.FAILED
            and current["attempt"] >= current["max_attempts"]
        ):
            raise JobTransitionError("No attempts remaining")
        if progress_pct is not None and not 0 <= progress_pct <= 100:
            raise ValueError("progress_pct must be between 0 and 100")
        if error_message is not None:
            error_message = error_message[:MAX_ERROR_MESSAGE_LENGTH]
        row = await conn.fetchrow(
            f"""
            UPDATE jobs SET
                status = $2,
                stage = COALESCE($3, stage),
                progress_pct = COALESCE($4, CASE WHEN $2 = 'succeeded' THEN 100 ELSE progress_pct END),
                error_code = CASE WHEN $2 IN ('failed') THEN $5 WHEN $2 = 'queued' THEN NULL ELSE error_code END,
                error_message = CASE WHEN $2 IN ('failed') THEN $6 WHEN $2 = 'queued' THEN NULL ELSE error_message END,
                result = COALESCE($7::jsonb, result),
                attempt = CASE WHEN $2 = 'running' THEN attempt + 1 ELSE attempt END,
                started_at = CASE WHEN $2 = 'running' THEN NOW() ELSE started_at END,
                finished_at = CASE WHEN $2 IN ('succeeded', 'failed', 'cancelled') THEN NOW()
                                   WHEN $2 = 'queued' THEN NULL ELSE finished_at END,
                updated_at = NOW()
            WHERE job_id = $1
            RETURNING {_COLUMNS}
            """,
            job_id, to_status.value, stage, progress_pct, error_code, error_message,
            json.dumps(result) if result is not None else None,
        )
        return _row(row)

    async def update_progress(
        self, conn: Any, job_id: str, *, progress_pct: int, stage: Optional[str] = None
    ) -> Dict[str, Any]:
        """Progress is only recorded for running jobs."""
        if not 0 <= progress_pct <= 100:
            raise ValueError("progress_pct must be between 0 and 100")
        row = await conn.fetchrow(
            f"""
            UPDATE jobs SET progress_pct = $2, stage = COALESCE($3, stage), updated_at = NOW()
            WHERE job_id = $1 AND status = 'running'
            RETURNING {_COLUMNS}
            """,
            job_id, progress_pct, stage,
        )
        if row is None:
            raise JobTransitionError("Progress can only be updated while running")
        return _row(row)

    async def request_cancel(self, conn: Any, job_id: str, *, owner_id: str) -> Optional[Dict[str, Any]]:
        """Record a cancellation request (idempotent). Acting on it is the worker's job."""
        row = await conn.fetchrow(
            f"""
            UPDATE jobs SET cancel_requested_at = COALESCE(cancel_requested_at, NOW()), updated_at = NOW()
            WHERE job_id = $1 AND owner_id = $2
            RETURNING {_COLUMNS}
            """,
            job_id, owner_id,
        )
        return _row(row) if row else None

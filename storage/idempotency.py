"""
Durable Idempotency Store for LearnSense / TAPROOT Phase 5.
Persists processed request tokens and cached response payloads to SQLite so idempotency
guarantees survive application restarts and multi-worker execution.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional


class DurableIdempotencyTracker:
    """
    SQLite-backed idempotency tracker.
    Stores request tokens with their computed response payloads and expiration timestamps.
    """

    def __init__(self, db_path: str = "storage/idempotency.db", ttl_seconds: int = 86400):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    token TEXT PRIMARY KEY,
                    learner_id TEXT,
                    response_json TEXT,
                    created_at REAL,
                    expires_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_records(expires_at)"
            )
            conn.commit()

    def is_duplicate(self, token: str) -> bool:
        if not token:
            return False
        self._cleanup()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM idempotency_records WHERE token = ? AND expires_at > ?",
                (token, time.time()),
            ).fetchone()
            return row is not None

    def get_cached_response(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT response_json FROM idempotency_records WHERE token = ? AND expires_at > ?",
                (token, time.time()),
            ).fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    return None
            return None

    def mark_processed(
        self, token: str, learner_id: Optional[str] = None, response_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        if not token:
            return
        now = time.time()
        expires_at = now + self.ttl_seconds
        payload_str = json.dumps(response_payload) if response_payload is not None else None
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO idempotency_records (token, learner_id, response_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    response_json = excluded.response_json,
                    expires_at = excluded.expires_at
                """,
                (token, learner_id or "", payload_str, now, expires_at),
            )
            conn.commit()

    def _cleanup(self) -> None:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("DELETE FROM idempotency_records WHERE expires_at <= ?", (now,))
            conn.commit()

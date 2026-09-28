"""
SQLite Database Persistence Manager for Taproot Phase 1 Job Tracking and Caching.
Matches Section 22 and Section 24 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from schemas.document import ProcessingStatusEnum, WarningCodeEnum, WarningSeverityEnum


class DatabaseManager:
    def __init__(self, db_path: str = "storage/taproot.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """
        Open a connection, commit on success, and **always close it**.

        ``with sqlite3.connect(...) as conn`` only commits or rolls back the transaction -
        it leaves the file handle open until the garbage collector happens to run. On
        Windows that made ``shutil.rmtree`` of a test's temp directory fail with
        ``PermissionError: [WinError 32]`` nondeterministically, and leaked handles in
        the long-running API process.
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                cache_key TEXT UNIQUE,
                status TEXT NOT NULL,
                page_count INTEGER DEFAULT 0,
                processed_pages INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS page_states (
                document_id TEXT NOT NULL,
                page_index INTEGER NOT NULL,
                page_label TEXT NOT NULL,
                page_type TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (document_id, page_index),
                FOREIGN KEY (document_id) REFERENCES documents (document_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                page_index INTEGER,
                block_id TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents (document_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_documents_cache_key ON documents (cache_key);
            CREATE INDEX IF NOT EXISTS idx_warnings_doc ON warnings (document_id);
            """)

    def create_document_job(
        self,
        document_id: str,
        sha256: str,
        filename: str,
        size_bytes: int,
        cache_key: Optional[str] = None,
        status: str = "queued",
    ) -> Dict[str, Any]:
        """
        Register (or re-register) a document job.

        Upsert rather than plain INSERT: re-processing a document is a normal operation -
        the learner can upload a corrected file, or a test can rebuild a fixture - and a
        bare INSERT failed with ``UNIQUE constraint failed: documents.document_id``.
        Re-registering resets the progress columns, because the previous run's page
        counts and warnings describe the *old* content.
        """
        now = self._now_iso()
        with self._connection() as conn:
            # A cache key may still be held by a different document_id from an earlier
            # run. Release it first so the UNIQUE index does not reject this insert.
            if cache_key:
                conn.execute(
                    "UPDATE documents SET cache_key = NULL WHERE cache_key = ? AND document_id != ?",
                    (cache_key, document_id),
                )

            # Previous progress describes the old file, so drop it.
            conn.execute("DELETE FROM page_states WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM warnings WHERE document_id = ?", (document_id,))

            conn.execute(
                """
                INSERT INTO documents (
                    document_id, sha256, filename, size_bytes, cache_key, status,
                    page_count, processed_pages, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    sha256 = excluded.sha256,
                    filename = excluded.filename,
                    size_bytes = excluded.size_bytes,
                    cache_key = excluded.cache_key,
                    status = excluded.status,
                    page_count = 0,
                    processed_pages = 0,
                    updated_at = excluded.updated_at
                """,
                (document_id, sha256, filename, size_bytes, cache_key, status, now, now),
            )
        return self.get_document_job(document_id)

    def get_document_job(self, document_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,)).fetchone()
            if row:
                return dict(row)
            return None

    def find_cached_document(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE cache_key = ? AND status IN ('completed', 'completed_with_warnings')",
                (cache_key,),
            ).fetchone()
            if row:
                return dict(row)
            return None

    def update_document_status(
        self,
        document_id: str,
        status: str,
        page_count: Optional[int] = None,
        processed_pages: Optional[int] = None,
    ) -> None:
        now = self._now_iso()
        with self._connection() as conn:
            if page_count is not None and processed_pages is not None:
                conn.execute(
                    "UPDATE documents SET status = ?, page_count = ?, processed_pages = ?, updated_at = ? WHERE document_id = ?",
                    (status, page_count, processed_pages, now, document_id),
                )
            elif page_count is not None:
                conn.execute(
                    "UPDATE documents SET status = ?, page_count = ?, updated_at = ? WHERE document_id = ?",
                    (status, page_count, now, document_id),
                )
            elif processed_pages is not None:
                conn.execute(
                    "UPDATE documents SET status = ?, processed_pages = ?, updated_at = ? WHERE document_id = ?",
                    (status, processed_pages, now, document_id),
                )
            else:
                conn.execute(
                    "UPDATE documents SET status = ?, updated_at = ? WHERE document_id = ?",
                    (status, now, document_id),
                )

    def set_page_state(
        self,
        document_id: str,
        page_index: int,
        page_label: str,
        page_type: str,
        status: str,
    ) -> None:
        now = self._now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO page_states (document_id, page_index, page_label, page_type, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, page_index) DO UPDATE SET
                    page_label = excluded.page_label,
                    page_type = excluded.page_type,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (document_id, page_index, page_label, page_type, status, now),
            )

    def get_page_states(self, document_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM page_states WHERE document_id = ? ORDER BY page_index ASC", (document_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def add_warning(
        self,
        document_id: str,
        code: str,
        severity: str,
        message: str,
        page_index: Optional[int] = None,
        block_id: Optional[str] = None,
    ) -> None:
        now = self._now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO warnings (document_id, code, severity, page_index, block_id, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, code, severity, page_index, block_id, message, now),
            )

    def get_warnings(self, document_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM warnings WHERE document_id = ? ORDER BY id ASC", (document_id,)
            ).fetchall()
            return [dict(r) for r in rows]

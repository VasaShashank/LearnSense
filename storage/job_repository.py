"""
Durable Ingestion Job Repository for LearnSense / TAPROOT.
Persists upload and ingestion job state to disk atomically so progress,
timestamps, status and results survive server reloads and restarts.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from storage.id_validation import validate_storage_id

logger = logging.getLogger(__name__)


class JobRepository:
    def __init__(self, base_dir: str = "storage/jobs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}

    def get_path(self, job_id: str) -> Path:
        safe_id = validate_storage_id(job_id, name="job_id")
        path = (self.base_dir / f"{safe_id}.json").resolve()
        if not path.is_relative_to(self.base_dir.resolve()):
            raise ValueError("Invalid job_id")
        return path

    def get_cancel_event(self, job_id: str) -> threading.Event:
        with self._lock:
            if job_id not in self._cancel_events:
                self._cancel_events[job_id] = threading.Event()
            return self._cancel_events[job_id]

    def create_job(
        self, job_id: str, filename: str, owner_id: Optional[str] = None
    ) -> Dict[str, Any]:
        now = time.time()
        job = {
            "job_id": job_id,
            "owner_id": owner_id,
            "filename": filename,
            "status": "queued",
            "progress_pct": 5,
            "stage": "Job queued for processing",
            "created_at": now,
            "updated_at": now,
            "elapsed_seconds": 0.0,
            "result": None,
            "error": None,
            "cancelled": False,
        }
        self.save_job(job)
        return job

    def save_job(self, job: Dict[str, Any]) -> None:
        job_id = job.get("job_id")
        if not job_id:
            return
        path = self.get_path(job_id)
        job["updated_at"] = time.time()
        created = job.get("created_at") or job["updated_at"]
        job["elapsed_seconds"] = round(job["updated_at"] - created, 1)

        fd, tmp_name = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(job, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception as exc:
            logger.error("Failed to save job %s: %s", job_id, exc)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    def load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            path = self.get_path(job_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def load_owned_job(self, job_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Return a job only when persisted owner metadata matches exactly."""
        job = self.load_job(job_id)
        if not job or job.get("owner_id") != owner_id:
            return None
        return job

    def cancel_job(self, job_id: str, owner_id: Optional[str] = None) -> bool:
        # Route callers always supply the verified owner. owner_id=None remains
        # available for trusted internal maintenance and existing repository tests.
        job = self.load_job(job_id) if owner_id is None else self.load_owned_job(job_id, owner_id)
        if not job:
            return False
        with self._lock:
            if job_id in self._cancel_events:
                self._cancel_events[job_id].set()
        job["cancelled"] = True
        job["status"] = "cancelled"
        job["stage"] = "Ingestion cancelled by user"
        self.save_job(job)
        return True

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._cancel_events and self._cancel_events[job_id].is_set():
                return True
        job = self.load_job(job_id)
        return bool(job and job.get("cancelled", False))

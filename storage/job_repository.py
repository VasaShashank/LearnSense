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

logger = logging.getLogger(__name__)


class JobRepository:
    def __init__(self, base_dir: str = "storage/jobs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}

    def get_path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"

    def get_cancel_event(self, job_id: str) -> threading.Event:
        with self._lock:
            if job_id not in self._cancel_events:
                self._cancel_events[job_id] = threading.Event()
            return self._cancel_events[job_id]

    def create_job(self, job_id: str, filename: str) -> Dict[str, Any]:
        now = time.time()
        job = {
            "job_id": job_id,
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
        path = self.get_path(job_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def cancel_job(self, job_id: str) -> bool:
        job = self.load_job(job_id)
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

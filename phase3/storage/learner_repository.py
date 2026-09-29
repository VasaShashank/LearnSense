"""
Learner State Repository for Phase 3.
Persists learner states and knowledge tracing snapshots to disk atomically,
with thread-safe concurrency synchronization per learner ID.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional
from phase3.learner.models import LearnerState

_LEARNER_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_MUTEX = threading.Lock()


def get_learner_lock(learner_id: str) -> threading.RLock:
    """Get or create a reentrant lock for a specific learner to serialize concurrent mutations."""
    with _LOCKS_MUTEX:
        if learner_id not in _LEARNER_LOCKS:
            _LEARNER_LOCKS[learner_id] = threading.RLock()
        return _LEARNER_LOCKS[learner_id]


class LearnerStateRepository:
    def __init__(self, base_dir: str = "storage/learner_states"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, learner_id: str) -> Path:
        return self.base_dir / f"{learner_id}.json"

    def save_state(self, state: LearnerState) -> Path:
        """Write learner state atomically and flush to disk to ensure crash resilience."""
        path = self.get_path(state.learner_id)
        data = state.model_dump(mode="json")

        with get_learner_lock(state.learner_id):
            fd, tmp_name = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        return path

    def load_state(self, learner_id: str) -> Optional[LearnerState]:
        path = self.get_path(learner_id)
        with get_learner_lock(learner_id):
            if not path.exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return LearnerState.model_validate(data)
            except (json.JSONDecodeError, ValueError):
                return None

"""
Learner State Repository for Phase 3.
Persists learner states and knowledge tracing snapshots to disk.
"""

import json
from pathlib import Path
from typing import Optional
from phase3.learner.models import LearnerState


class LearnerStateRepository:
    def __init__(self, base_dir: str = "storage/learner_states"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, learner_id: str) -> Path:
        return self.base_dir / f"{learner_id}.json"

    def save_state(self, state: LearnerState) -> Path:
        path = self.get_path(state.learner_id)
        data = state.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def load_state(self, learner_id: str) -> Optional[LearnerState]:
        path = self.get_path(learner_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return LearnerState.model_validate(data)

"""
Interaction Logger for Phase 3 Adaptive Learning Engine.
Records structured learner interactions for analytics, KT, and future Phase 4 RL.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class InteractionRecord(BaseModel):
    interaction_id: str = Field(default_factory=lambda: f"int_{uuid.uuid4().hex[:12]}")
    learner_id: str
    session_id: str
    question_id: str
    concept_ids: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list)
    question_type: str
    difficulty: float = 0.5
    response: Any
    correctness: float  # 0.0 to 1.0
    score: float = 0.0
    time_taken_seconds: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pre_mastery: Dict[str, float] = Field(default_factory=dict)
    post_mastery: Dict[str, float] = Field(default_factory=dict)
    source: str = "GENERATED"  # SOURCE, GENERATED, VARIANT
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InteractionLogger:
    def __init__(self):
        self.logs: List[InteractionRecord] = []

    def log_interaction(self, record: InteractionRecord) -> InteractionRecord:
        self.logs.append(record)
        return record

    def get_learner_history(self, learner_id: str) -> List[InteractionRecord]:
        return [log for log in self.logs if log.learner_id == learner_id]

    def get_session_history(self, session_id: str) -> List[InteractionRecord]:
        return [log for log in self.logs if log.session_id == session_id]

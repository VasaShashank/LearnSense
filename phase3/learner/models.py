"""
Phase 3 Learner State Models.
Represents individual concept states, aggregated topic/chapter states, and overall learner progress.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ConceptState(BaseModel):
    concept_id: str
    mastery_probability: float = Field(default=0.3, ge=0.0, le=1.0)
    uncertainty: float = Field(default=0.5, ge=0.0, le=1.0)
    attempt_count: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    incorrect_count: int = Field(default=0, ge=0)
    recent_performance: List[bool] = Field(default_factory=list)  # Last N responses
    last_attempt: Optional[datetime] = None


class LearnerState(BaseModel):
    learner_id: str
    concept_states: Dict[str, ConceptState] = Field(default_factory=dict)
    topic_scores: Dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_concept_state(self, concept_id: str) -> ConceptState:
        if concept_id not in self.concept_states:
            self.concept_states[concept_id] = ConceptState(concept_id=concept_id)
        return self.concept_states[concept_id]

    def update_concept_state(self, concept_id: str, is_correct: float) -> ConceptState:
        state = self.get_concept_state(concept_id)
        state.attempt_count += 1
        if is_correct >= 0.8:
            state.correct_count += 1
            state.recent_performance.append(True)
        else:
            state.incorrect_count += 1
            state.recent_performance.append(False)

        if len(state.recent_performance) > 10:
            state.recent_performance = state.recent_performance[-10:]

        state.last_attempt = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        return state

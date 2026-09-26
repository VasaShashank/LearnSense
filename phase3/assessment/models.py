"""
Assessment Models for Phase 3 Main Chapter Assessment.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from phase3.question_bank.models import QuestionBankItem


class AssessmentStoppingReason(str, Enum):
    TARGET_REACHED = "target_reached"
    TIME_EXPIRED = "time_expired"
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"
    COVERAGE_UNMET = "coverage_unmet"
    ABORTED = "aborted"


class AssessmentConstraints(BaseModel):
    min_questions: int = 20
    max_questions: int = 25
    time_limit_seconds: float = 1800.0  # 30 minutes
    required_concept_ids: List[str] = Field(default_factory=list)
    required_skill_ids: List[str] = Field(default_factory=list)


class CandidateScore(BaseModel):
    question_id: str
    information_gain: float
    uncertainty_score: float
    coverage_score: float
    total_score: float

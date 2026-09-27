"""
Phase 4 Data Models.
Includes models for self-assessment, initial knowledge sessions, gap representation, and path planning.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SelfAssessmentStatus(str, Enum):
    KNOW = "KNOW"
    DONT_KNOW = "DONT_KNOW"
    UNANSWERED = "UNANSWERED"


class ConceptSelfAssessment(BaseModel):
    concept_id: str
    status: SelfAssessmentStatus = SelfAssessmentStatus.UNANSWERED
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeSufficiencyStatus(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INITIALIZED = "INITIALIZED"


class KnowledgeInitializationSession(BaseModel):
    session_id: str
    learner_id: str
    subject_id: str
    self_assessments: Dict[str, ConceptSelfAssessment] = Field(default_factory=dict)
    know_concept_ids: List[str] = Field(default_factory=list)
    dont_know_concept_ids: List[str] = Field(default_factory=list)
    unanswered_concept_ids: List[str] = Field(default_factory=list)
    diagnostic_session_id: Optional[str] = None
    diagnostic_completed: bool = False
    diagnostic_score: Optional[float] = None
    sufficiency_status: KnowledgeSufficiencyStatus = KnowledgeSufficiencyStatus.UNINITIALIZED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GapType(str, Enum):
    LOW_MASTERY = "LOW_MASTERY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    WEAK_PREREQUISITE = "WEAK_PREREQUISITE"
    HIGH_DOWNSTREAM_IMPACT = "HIGH_DOWNSTREAM_IMPACT"


class GapReason(BaseModel):
    gap_type: GapType
    description: str
    details: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeGap(BaseModel):
    gap_id: str
    concept_id: str
    concept_name: str
    gap_type: GapType
    priority_score: float = Field(ge=0.0, le=1.0)
    reasons: List[GapReason] = Field(default_factory=list)
    mastery_probability: float
    uncertainty: float
    downstream_impact_count: int = 0
    weak_prerequisite_ids: List[str] = Field(default_factory=list)


class LearningGoal(BaseModel):
    goal_id: str
    subject_id: str
    title: str
    target_concept_ids: List[str] = Field(default_factory=list)


class LearningTarget(BaseModel):
    target_id: str
    concept_id: str
    concept_name: str
    target_type: str = "CONCEPT_MASTERY"  # e.g., CONCEPT_MASTERY, PREREQUISITE_REMEDIATION
    reason: str


class ActivityType(str, Enum):
    EXPLANATION = "EXPLANATION"
    PRACTICE_QUESTION = "PRACTICE_QUESTION"
    MINI_QUIZ = "MINI_QUIZ"


class LearningActivity(BaseModel):
    activity_id: str
    target_id: str
    concept_id: str
    activity_type: ActivityType
    title: str
    content: Optional[Dict[str, Any]] = None


class LearningPathNode(BaseModel):
    node_id: str
    concept_id: str
    concept_name: str
    order: int
    is_foundational: bool = False
    is_prerequisite: bool = False
    estimated_mastery: float
    status: str = "PENDING"  # PENDING, IN_PROGRESS, COMPLETED


class LearningPath(BaseModel):
    path_id: str
    learner_id: str
    subject_id: str
    nodes: List[LearningPathNode] = Field(default_factory=list)
    target_concept_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

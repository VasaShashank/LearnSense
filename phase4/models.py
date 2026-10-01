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


class ConfidenceLevel(str, Enum):
    """Learner-reported confidence in a self-assessment judgment.

    Stored separately from perceived level AND from objective BKT evidence.
    HIGH maps to the CONFIDENT row of the confidence x competence matrix;
    MEDIUM/LOW map to UNSURE.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConceptSelfAssessment(BaseModel):
    concept_id: str
    status: SelfAssessmentStatus = SelfAssessmentStatus.UNANSWERED
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
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
    # Confidence is stored as a separate signal, never merged into mastery.
    confidences: Dict[str, ConfidenceLevel] = Field(default_factory=dict)
    # Ordered diagnostic coverage (KNOW + UNANSWERED prioritized by confidence).
    verify_concept_ids: List[str] = Field(default_factory=list)
    diagnostic_priorities: Dict[str, float] = Field(default_factory=dict)
    diagnostic_question_ids: List[str] = Field(default_factory=list)
    diagnostic_responses: Dict[str, Any] = Field(default_factory=dict)
    # Confidence x competence calibration per concept: CC | CI | UC | UI.
    calibration: Dict[str, str] = Field(default_factory=dict)
    confirmed_concept_ids: List[str] = Field(default_factory=list)
    contradicted_concept_ids: List[str] = Field(default_factory=list)
    # Prerequisite-aware verification hints produced at diagnostic submit time.
    prerequisite_verification: List[Dict[str, Any]] = Field(default_factory=list)
    diagnostic_session_id: Optional[str] = None
    diagnostic_completed: bool = False
    diagnostic_score: Optional[float] = None
    sufficiency_status: KnowledgeSufficiencyStatus = KnowledgeSufficiencyStatus.UNINITIALIZED
    # Durable per-answer audit trail. ``diagnostic_responses`` holds the
    # authoritative correctness the server computed for each question; this map
    # holds what the learner actually picked plus the concepts each answer fed.
    # Together they make a refresh-resumable assessment and make duplicate
    # submissions detectable (a question_id present here is never re-applied).
    diagnostic_answer_records: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Server-side cursor so the client never has to remember where it was.
    diagnostic_answered_count: int = 0
    # Set when question generation fails. A failure must surface as an error the
    # learner can retry, never as "verification completed".
    diagnostic_generation_error: Optional[str] = None
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
    FINAL_ASSESSMENT = "FINAL_ASSESSMENT"


class LearningActivity(BaseModel):
    activity_id: str
    target_id: str
    concept_id: str
    activity_type: ActivityType
    title: str
    content: Optional[Dict[str, Any]] = None


class FinalAssessmentSession(BaseModel):
    assessment_id: str
    learner_id: str
    subject_id: str
    question_ids: List[str] = Field(default_factory=list)
    concept_ids: List[str] = Field(default_factory=list)
    completed: bool = False
    score_pct: Optional[float] = None
    passed: Optional[bool] = None
    total_questions: int = 0
    correct_count: int = 0
    responses: Dict[str, Any] = Field(default_factory=dict)
    scores: Dict[str, float] = Field(default_factory=dict)
    concept_results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


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

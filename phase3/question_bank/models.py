"""
Question Bank Schema and Models for Phase 3.
Tracks Question Provenance (SOURCE, GENERATED, VARIANT) and course metadata.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QuestionSourceType(str, Enum):
    SOURCE = "SOURCE"        # Directly extracted from user material via Phase 2 AssessableItem
    GENERATED = "GENERATED"  # LLM-generated based on Phase 2 EKR course knowledge
    VARIANT = "VARIANT"      # LLM-generated variant of another question


class QuestionType(str, Enum):
    MCQ = "mcq"
    TRUE_FALSE = "true_false"
    NUMERICAL = "numerical"
    SHORT_ANSWER = "short_answer"


class QuestionValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    PENDING = "pending"


class QuestionBankItem(BaseModel):
    question_id: str = Field(default_factory=lambda: f"q_{uuid.uuid4().hex[:12]}")
    chapter_id: str = "ch_1"
    topic_ids: List[str] = Field(default_factory=list)
    concept_ids: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list)
    question_type: QuestionType = QuestionType.MCQ
    question_text: str
    options: Optional[List[str]] = None
    correct_answer: Any
    explanation: str = ""
    difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    expected_time_seconds: float = 60.0
    information_value: float = Field(default=1.0, ge=0.1, le=3.0)  # Discrimination factor
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)
    source_type: QuestionSourceType = QuestionSourceType.GENERATED
    source_item_id: Optional[str] = None
    validation_status: QuestionValidationStatus = QuestionValidationStatus.VALID
    exposure_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QuestionBank(BaseModel):
    document_id: str
    chapter_id: str
    questions: Dict[str, QuestionBankItem] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_question(self, item: QuestionBankItem) -> None:
        self.questions[item.question_id] = item
        self.updated_at = datetime.now(timezone.utc)

    def get_by_topic(self, topic_id: str) -> List[QuestionBankItem]:
        return [q for q in self.questions.values() if topic_id in q.topic_ids and q.validation_status == QuestionValidationStatus.VALID]

    def get_by_concept(self, concept_id: str) -> List[QuestionBankItem]:
        return [q for q in self.questions.values() if concept_id in q.concept_ids and q.validation_status == QuestionValidationStatus.VALID]

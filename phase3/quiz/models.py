"""
Quiz Schemas and Models for Phase 3.
"""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from phase3.question_bank.models import QuestionBankItem, QuestionType


class QuizQuestion(BaseModel):
    question_id: str = Field(default_factory=lambda: f"mq_{uuid.uuid4().hex[:12]}")
    question_type: QuestionType = QuestionType.MCQ
    question_text: str
    options: Optional[List[str]] = None
    correct_answer: Any
    explanation: str = ""
    concept_ids: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list)
    difficulty: float = 0.5
    expected_time_seconds: float = 60.0
    provenance: str = "GENERATED"


class DynamicMiniQuiz(BaseModel):
    quiz_id: str = Field(default_factory=lambda: f"quiz_{uuid.uuid4().hex[:12]}")
    learner_id: str
    topic_id: str
    questions: List[QuizQuestion] = Field(default_factory=list)
    target_question_count: int = 6

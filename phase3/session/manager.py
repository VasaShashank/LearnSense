"""
Session Models and Manager for Phase 3.
Supports mini_quiz and chapter_assessment explicit learning sessions.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionType(str, Enum):
    MINI_QUIZ = "mini_quiz"
    CHAPTER_ASSESSMENT = "chapter_assessment"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABORTED = "aborted"
    EXPIRED = "expired"


class LearningSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    learner_id: str
    document_id: str
    chapter_id: str = "ch_1"
    topic_id: Optional[str] = None
    session_type: SessionType = SessionType.MINI_QUIZ
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    status: SessionStatus = SessionStatus.ACTIVE
    current_question_index: int = 0
    question_ids: List[str] = Field(default_factory=list)
    responses: Dict[str, Any] = Field(default_factory=dict)
    scores: Dict[str, float] = Field(default_factory=dict)


class SessionManager:
    """Manages creation, tracking, and lifecycle of learning sessions."""

    def __init__(self):
        self.sessions: Dict[str, LearningSession] = {}

    def create_session(
        self,
        learner_id: str,
        document_id: str,
        session_type: SessionType,
        chapter_id: str = "ch_1",
        topic_id: Optional[str] = None,
        question_ids: Optional[List[str]] = None,
    ) -> LearningSession:
        sess = LearningSession(
            learner_id=learner_id,
            document_id=document_id,
            chapter_id=chapter_id,
            topic_id=topic_id,
            session_type=session_type,
            question_ids=question_ids or [],
        )
        self.sessions[sess.session_id] = sess
        return sess

    def get_session(self, session_id: str) -> Optional[LearningSession]:
        return self.sessions.get(session_id)

    def record_response(
        self, session_id: str, question_id: str, response: Any, score: float
    ) -> LearningSession:
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError(f"Session {session_id} not found.")

        sess.responses[question_id] = response
        sess.scores[question_id] = score
        sess.current_question_index += 1
        return sess

    def complete_session(self, session_id: str) -> LearningSession:
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError(f"Session {session_id} not found.")

        sess.status = SessionStatus.COMPLETED
        sess.end_time = datetime.now(timezone.utc)
        return sess

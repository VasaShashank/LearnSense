"""Phase 3 Tutoring Package — Socratic AI Teacher, Grounded Knowledge Base, and Anti-Leak Guardrails."""

from src.tutoring import (
    TutoringEngine,
    TutoringRequest,
    TutoringResponse,
    TutoringStep,
)
from src.teacher import (
    IndependentTeacherPlanner,
    CohortTeacherManager,
    DynamicTeachingPlan,
    CohortClassroomReport,
    LessonSegment,
)
from src.knowledge_base import (
    GroundedKnowledgeBase,
    GroundedConceptContent,
    ContentSnippet,
)

# Friendly alias for Socratic teacher planner
SocraticTeacher = IndependentTeacherPlanner

__all__ = [
    "TutoringEngine",
    "TutoringRequest",
    "TutoringResponse",
    "TutoringStep",
    "IndependentTeacherPlanner",
    "SocraticTeacher",
    "CohortTeacherManager",
    "DynamicTeachingPlan",
    "CohortClassroomReport",
    "LessonSegment",
    "GroundedKnowledgeBase",
    "GroundedConceptContent",
    "ContentSnippet",
]

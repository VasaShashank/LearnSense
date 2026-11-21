"""Phase 3 Quiz Package.

Exposes Person 3's authoritative MicroQuizEngine, dynamic mini quiz generators, and schemas.
"""

from phase3.quiz.models import (
    DynamicMiniQuiz,
    QuizQuestion,
)
from phase3.quiz.mini_quiz_generator import DynamicMiniQuizGenerator
from phase3.quiz.micro_quiz import (
    MicroQuizEngine,
    MicroQuizSession,
    MicroQuizItem,
    MicroQuizOption,
    QuestionEvaluationResult,
)

__all__ = [
    "DynamicMiniQuiz",
    "QuizQuestion",
    "DynamicMiniQuizGenerator",
    "MicroQuizEngine",
    "MicroQuizSession",
    "MicroQuizItem",
    "MicroQuizOption",
    "QuestionEvaluationResult",
]

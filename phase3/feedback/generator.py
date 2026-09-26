"""
Feedback Generator for Phase 3.
Generates structured feedback after response evaluation.
"""

from typing import List, Optional
from pydantic import BaseModel, Field
from phase3.evaluation.evaluator import EvaluationResult
from phase3.knowledge.phase2_adapter import LearningContext


class StructuredFeedback(BaseModel):
    is_correct: bool
    correctness_score: float
    user_response: str
    expected_answer: str
    explanation: str
    concept_names: List[str] = Field(default_factory=list)
    skill_statements: List[str] = Field(default_factory=list)
    guidance: str = ""


class FeedbackGenerator:
    """Constructs learner-facing feedback based on evaluation result and course context."""

    @staticmethod
    def generate_feedback(
        eval_result: EvaluationResult,
        explanation: str,
        concept_ids: List[str],
        skill_ids: List[str],
        context: LearningContext,
    ) -> StructuredFeedback:
        c_names = [
            context.concepts[c_id].canonical_name
            for c_id in concept_ids
            if c_id in context.concepts
        ]
        s_stmts = [
            context.skills[s_id].statement
            for s_id in skill_ids
            if s_id in context.skills
        ]

        if eval_result.is_correct:
            guidance = "Great job! You demonstrated mastery of this key concept."
        elif eval_result.correctness_score > 0.0:
            guidance = "You're close! Review the concept definitions and try again."
        else:
            guidance = f"Key concept to review: {', '.join(c_names) if c_names else 'Topic fundamental principles'}."

        return StructuredFeedback(
            is_correct=eval_result.is_correct,
            correctness_score=eval_result.correctness_score,
            user_response=str(eval_result.user_response),
            expected_answer=str(eval_result.expected_answer),
            explanation=explanation or eval_result.feedback_text,
            concept_names=c_names,
            skill_statements=s_stmts,
            guidance=guidance,
        )

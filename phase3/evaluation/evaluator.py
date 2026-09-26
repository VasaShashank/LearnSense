"""
Structured Answer Evaluation Engine for Phase 3.
Supports exact matching for MCQ and True/False, numerical tolerance, and short answer semantic matching.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    is_correct: bool
    correctness_score: float = Field(..., ge=0.0, le=1.0)
    user_response: Any
    expected_answer: Any
    feedback_text: str = ""
    confidence: float = 1.0


class AnswerEvaluator:
    """Evaluates learner responses across MCQ, True/False, Numerical, and Short Answer types."""

    @staticmethod
    def evaluate_mcq(user_response: Any, expected_answer: Any) -> EvaluationResult:
        is_corr = str(user_response).strip().lower() == str(expected_answer).strip().lower()
        score = 1.0 if is_corr else 0.0
        return EvaluationResult(
            is_correct=is_corr,
            correctness_score=score,
            user_response=user_response,
            expected_answer=expected_answer,
            feedback_text="Correct!" if is_corr else f"Incorrect. Expected option: {expected_answer}",
        )

    @staticmethod
    def evaluate_true_false(user_response: Any, expected_answer: Any) -> EvaluationResult:
        norm_user = str(user_response).strip().lower() in ["true", "t", "1", "yes"]
        norm_expected = str(expected_answer).strip().lower() in ["true", "t", "1", "yes"]
        is_corr = norm_user == norm_expected
        score = 1.0 if is_corr else 0.0
        return EvaluationResult(
            is_correct=is_corr,
            correctness_score=score,
            user_response=user_response,
            expected_answer=expected_answer,
            feedback_text="Correct!" if is_corr else f"Incorrect. Correct answer is {norm_expected}",
        )

    @staticmethod
    def evaluate_numerical(
        user_response: Any, expected_answer: Any, tolerance_percent: float = 0.02
    ) -> EvaluationResult:
        try:
            u_val = float(str(user_response).strip())
            e_val = float(str(expected_answer).strip())
            if e_val == 0:
                is_corr = abs(u_val) <= 1e-5
            else:
                rel_diff = abs(u_val - e_val) / abs(e_val)
                is_corr = rel_diff <= tolerance_percent
            score = 1.0 if is_corr else 0.0
            return EvaluationResult(
                is_correct=is_corr,
                correctness_score=score,
                user_response=user_response,
                expected_answer=expected_answer,
                feedback_text="Correct!" if is_corr else f"Incorrect. Expected numerical value within {tolerance_percent*100}% of {e_val}",
            )
        except (ValueError, TypeError):
            return EvaluationResult(
                is_correct=False,
                correctness_score=0.0,
                user_response=user_response,
                expected_answer=expected_answer,
                feedback_text="Invalid numerical input.",
            )

    @staticmethod
    def evaluate_short_answer(user_response: Any, expected_answer: Any) -> EvaluationResult:
        u_str = str(user_response).strip().lower()
        e_str = str(expected_answer).strip().lower()

        if u_str == e_str:
            return EvaluationResult(
                is_correct=True,
                correctness_score=1.0,
                user_response=user_response,
                expected_answer=expected_answer,
                feedback_text="Exact match!",
            )

        # Keyword / substring similarity heuristic
        e_words = set(e_str.split())
        u_words = set(u_str.split())
        if not e_words:
            overlap = 1.0
        else:
            overlap = len(e_words.intersection(u_words)) / len(e_words)

        is_corr = overlap >= 0.6
        return EvaluationResult(
            is_correct=is_corr,
            correctness_score=round(overlap, 2),
            user_response=user_response,
            expected_answer=expected_answer,
            feedback_text=f"Partially correct ({int(overlap*100)}% match)." if overlap > 0 else "Incorrect.",
        )

    def evaluate(
        self, question_type: str, user_response: Any, expected_answer: Any, **kwargs
    ) -> EvaluationResult:
        qtype = str(question_type).lower()
        if qtype in ["mcq", "multiple_choice"]:
            return self.evaluate_mcq(user_response, expected_answer)
        elif qtype in ["true_false", "tf"]:
            return self.evaluate_true_false(user_response, expected_answer)
        elif qtype in ["numerical", "number"]:
            return self.evaluate_numerical(user_response, expected_answer, kwargs.get("tolerance_percent", 0.02))
        else:
            return self.evaluate_short_answer(user_response, expected_answer)

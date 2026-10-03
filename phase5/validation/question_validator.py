"""
Question Validation and Alignment Engine for Taproot Phase 5.
Validates structural non-emptiness, concept alignment, answer/option consistency, source grounding, and difficulty sanity.
"""

from typing import List, Optional, Set, Tuple
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import QuestionBankItem, QuestionType
from phase3.question_bank.validator import QuestionBankValidator
from phase5.config.phase5_config import phase5_config
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class QuestionValidator:
    """Validates generated educational questions before presentation to students."""

    def __init__(self, base_validator: Optional[QuestionBankValidator] = None):
        self.base_validator = base_validator or QuestionBankValidator()

    def validate_question_item(
        self,
        item: QuestionBankItem,
        context: Optional[LearningContext] = None,
        target_concept_id: Optional[str] = None,
    ) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        q_id = item.question_id

        # 1. Reuse existing Phase 3 QuestionBankValidator if context is provided
        if context:
            is_valid, reasons = self.base_validator.validate_item(item, context)
            if not is_valid:
                for reason in reasons:
                    result.add_error(f"Phase 3 structural check failed: {reason}")

        # 2. Structural & Non-emptiness checks
        if not item.question_text or len(item.question_text.strip()) < 5:
            result.add_error("Question text is empty or shorter than 5 characters.")

        # 3. Target Concept Alignment check
        if target_concept_id:
            if target_concept_id not in item.concept_ids:
                result.add_error(
                    f"Question concept mismatch: target concept '{target_concept_id}' not found in question concept_ids {item.concept_ids}."
                )

        # 4. Answer Consistency & Multiple Choice Option checks
        if item.question_type == QuestionType.MCQ:
            if not item.options or len(item.options) < 2:
                result.add_error("MCQ question requires at least 2 distinct choices.")
            elif len(set(item.options)) < len(item.options):
                result.add_error("MCQ question options contain duplicate choices.")

            if item.correct_answer is None or item.correct_answer == "":
                result.add_error("MCQ question missing correct_answer designation.")
            elif isinstance(item.correct_answer, str) and item.options:
                valid_answers = list(item.options) + [chr(65 + i) for i in range(len(item.options))] + [str(i) for i in range(len(item.options))]
                if item.correct_answer not in valid_answers:
                    result.add_error(f"MCQ correct_answer '{item.correct_answer}' is not present in options or index labels.")

        elif item.question_type == QuestionType.TRUE_FALSE:
            if str(item.correct_answer).lower() not in ["true", "false", "1", "0", "t", "f"]:
                result.add_error(f"True/False question correct_answer '{item.correct_answer}' is not a valid boolean.")

        # 5. Difficulty Sanity check
        diff = getattr(item, "difficulty", None)
        if diff is not None and (diff < 0.0 or diff > 1.0):
            result.add_warning(f"Question difficulty {diff} is outside expected range [0.0, 1.0].")

        result.metadata["question_id"] = q_id
        result.metadata["concept_ids"] = item.concept_ids
        result.metadata["question_type"] = str(item.question_type)

        if not result.is_valid:
            result.recoverable = False
            result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
            result.suggested_action = "Reject invalid question with recorded validation errors."
            ValidationEventLogger.log_event(
                "question_validation_failed",
                "INVALID",
                f"Question '{q_id}' failed validation: {result.errors}",
                question_id=q_id,
            )
        else:
            ValidationEventLogger.log_event(
                "question_validation_passed",
                "VALID",
                f"Question '{q_id}' passed validation.",
                question_id=q_id,
            )

        return result

"""LearnSense Person 3 — Question Bank Integration Adapter.

Consumes question bank items owned by Person 2 (Content & Question Bank Owner):
- Validates question metadata against contracts/question_schema.json (Draft 2020-12).
- Enforces strict student safety: projects student-facing representations by stripping
  private answer keys, scoring rubrics, and server-only solution material.
- Supports deterministic question lookup and item metadata inspection for adaptive assessment.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set

from src.adaptive_assessment import AdaptiveAssessmentSelector, QuestionItem
from src.integration.contracts import validate_question


class QuestionBankAdapter:
    """Safe adapter for accessing question bank items and generating student projections."""

    SERVER_ONLY_FIELDS: Set[str] = {
        "answer_key",
        "correct_answer",
        "rubric",
        "scoring_guide",
        "solution_steps",
        "teacher_notes",
    }

    def __init__(self, assessment_selector: Optional[AdaptiveAssessmentSelector] = None) -> None:
        self._selector = assessment_selector or AdaptiveAssessmentSelector()

    def get_question_raw(self, question_id: str) -> Optional[QuestionItem]:
        """Internal accessor for question metadata including item parameters."""
        return self._selector.get_question(question_id)

    def get_question_safe_projection(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves question dictionary stripped of all private scoring and answer key fields.
        
        Guarantees:
        - Conforms to contracts/question_schema.json.
        - Zero answer key or rubric leakage.
        """
        q = self._selector.get_question(question_id)
        if not q:
            return None

        contract_dict = q.to_contract_dict()
        safe_dict = self.sanitize_question_for_student(contract_dict)

        # Validate against question schema
        is_valid, errors = validate_question(safe_dict)
        if not is_valid:
            raise ValueError(f"Question '{question_id}' failed schema validation: {errors}")
        return safe_dict

    @classmethod
    def sanitize_question_for_student(cls, question_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a student-safe projection by removing all server-only grading secrets."""
        cleaned = copy.deepcopy(question_dict)
        for secret_field in cls.SERVER_ONLY_FIELDS:
            cleaned.pop(secret_field, None)

        # If options exist, sanitize any is_correct flags
        if "options" in cleaned and isinstance(cleaned["options"], list):
            sanitized_options = []
            for opt in cleaned["options"]:
                if isinstance(opt, dict):
                    opt_copy = copy.deepcopy(opt)
                    opt_copy.pop("is_correct", None)
                    sanitized_options.append(opt_copy)
                else:
                    sanitized_options.append(opt)
            cleaned["options"] = sanitized_options

        return cleaned

    def get_questions_for_concept(
        self,
        concept_id: str,
        difficulty: Optional[str] = None,
    ) -> List[QuestionItem]:
        """Returns internal question items available for a concept."""
        return self._selector.get_questions_for_concept(concept_id, difficulty=difficulty)

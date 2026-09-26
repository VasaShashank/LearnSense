"""
Question Bank Validator and Deduplicator for Phase 3.
Ensures structural integrity, course grounding, quality, and semantic uniqueness.
"""

import hashlib
from typing import Dict, List, Tuple
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import QuestionBankItem, QuestionValidationStatus, QuestionType


class QuestionBankValidator:
    """Validates question structure, grounding in LearningContext, and quality."""

    @staticmethod
    def validate_item(item: QuestionBankItem, context: LearningContext) -> Tuple[bool, List[str]]:
        reasons = []

        # 1. Structural check
        if not item.question_text or len(item.question_text.strip()) < 5:
            reasons.append("Question text is too short or empty.")

        if item.question_type == QuestionType.MCQ:
            if not item.options or len(item.options) < 2:
                reasons.append("MCQ requires at least 2 options.")
            elif len(set(item.options)) < len(item.options):
                reasons.append("MCQ contains duplicate options.")

            if item.correct_answer is None:
                reasons.append("MCQ missing correct_answer.")

        elif item.question_type == QuestionType.TRUE_FALSE:
            if str(item.correct_answer).lower() not in ["true", "false", "1", "0"]:
                reasons.append("True/False question correct_answer must be boolean.")

        # 2. Course Grounding check
        valid_concepts = set(context.concepts.keys())
        for c_id in item.concept_ids:
            if c_id not in valid_concepts:
                reasons.append(f"Referenced concept_id '{c_id}' not found in course context.")

        valid_skills = set(context.skills.keys())
        for s_id in item.skill_ids:
            if s_id not in valid_skills:
                reasons.append(f"Referenced skill_id '{s_id}' not found in course context.")

        is_valid = len(reasons) == 0
        return is_valid, reasons


class QuestionBankDeduplicator:
    """Prevents exact and normalized semantic duplicates in question banks."""

    @staticmethod
    def compute_fingerprint(question_text: str) -> str:
        norm = "".join(c.lower() for c in question_text if c.isalnum())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    @classmethod
    def deduplicate(cls, items: List[QuestionBankItem]) -> List[QuestionBankItem]:
        seen_fingerprints = set()
        unique_items = []
        for item in items:
            fp = cls.compute_fingerprint(item.question_text)
            if fp not in seen_fingerprints:
                seen_fingerprints.add(fp)
                unique_items.append(item)
        return unique_items

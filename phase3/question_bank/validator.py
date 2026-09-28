"""
Question Bank Validator and Deduplicator for Phase 3.
Ensures structural integrity, course grounding, source grounding, quality, and semantic uniqueness.
"""

import hashlib
import re
from typing import Dict, List, Set, Tuple

from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import QuestionBankItem, QuestionValidationStatus, QuestionType

# Placeholder wording that must never survive into a learner's session. The builder
# refuses to emit these, and the validator rejects any bank that somehow contains them.
_PLACEHOLDER_PATTERNS = (
    "see detailed solution",
    "generated question",
    "extracted directly from",
    "general topic principles",
    "lorem ipsum",
    "todo",
    "tbd",
    "placeholder",
    "example text",
    "topic 1",
    "concept 1",
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


def _content_words(text: str) -> Set[str]:
    """Content words of a string, used to judge whether it overlaps the evidence."""
    return {w for w in _normalize(text).split() if len(w) > 3}


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

            if item.correct_answer is None or not str(item.correct_answer).strip():
                reasons.append("MCQ missing correct_answer.")
            elif item.options and str(item.correct_answer) not in item.options:
                reasons.append("correct_answer does not exactly match one of the options.")

        elif item.question_type == QuestionType.TRUE_FALSE:
            if str(item.correct_answer).lower() not in ["true", "false", "1", "0"]:
                reasons.append("True/False question correct_answer must be boolean.")

        # 2. No placeholder or filler content
        haystack = " ".join(
            [item.question_text, item.explanation or "", str(item.correct_answer or "")]
            + list(item.options or [])
        ).lower()
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern in haystack:
                reasons.append(f"Contains placeholder text ({pattern!r}).")
                break

        # 3. Course grounding check
        valid_concepts = set(context.concepts.keys())
        for c_id in item.concept_ids:
            if c_id not in valid_concepts:
                reasons.append(f"Referenced concept_id '{c_id}' not found in course context.")
        if not item.concept_ids:
            reasons.append("Question is not attached to any concept in the document.")

        valid_skills = set(context.skills.keys())
        for s_id in item.skill_ids:
            if s_id not in valid_skills:
                reasons.append(f"Referenced skill_id '{s_id}' not found in course context.")

        # 4. Source grounding check - the important one.
        #    A question is only trustworthy if it points at real passages of the
        #    learner's own material and shares real vocabulary with them.
        if not item.source_citations:
            reasons.append("Question has no source citation, so it is not grounded in the material.")
        else:
            for citation in item.source_citations:
                if not citation.block_id:
                    reasons.append("A source citation is missing its block_id.")
                if not citation.quote or len(citation.quote.strip()) < 10:
                    reasons.append("A source citation has no real quote from the material.")
                if citation.document_id != context.document_id:
                    reasons.append(
                        f"Citation points at document {citation.document_id!r}, "
                        f"not {context.document_id!r}."
                    )

            question_words = _content_words(item.question_text) | _content_words(
                str(item.correct_answer or "")
            )
            evidence_words: Set[str] = set()
            for citation in item.source_citations:
                evidence_words |= _content_words(citation.quote)
            if question_words and evidence_words:
                overlap = len(question_words & evidence_words) / len(question_words)
                if overlap < 0.20:
                    reasons.append(
                        "Question shares almost no vocabulary with its cited passage "
                        f"({overlap:.0%} overlap), so it is likely not answerable from it."
                    )

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

    @staticmethod
    def prune_invalid(items: List[QuestionBankItem]) -> List[QuestionBankItem]:
        """Mark every ungrounded item INVALID so it can never be served."""
        pruned: List[QuestionBankItem] = []
        for item in items:
            if not item.is_grounded:
                item.validation_status = QuestionValidationStatus.INVALID
            pruned.append(item)
        return pruned

"""
Adaptive Chapter Assessment Loop and Stopping Mechanics for Phase 3.
Manages 20-25 item adaptive assessment sessions with Information Gain selection.
"""

from typing import Dict, List, Optional, Set
from phase3.assessment.information_gain import InformationGainPolicy
from phase3.assessment.models import AssessmentConstraints, AssessmentStoppingReason
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionValidationStatus


class ChapterAssessmentEngine:
    """Manages adaptive chapter assessment loop adhering to constraints and Information Gain policy."""

    def __init__(
        self,
        constraints: Optional[AssessmentConstraints] = None,
        policy: Optional[InformationGainPolicy] = None,
    ):
        self.constraints = constraints or AssessmentConstraints()
        self.policy = policy or InformationGainPolicy()

    def get_eligible_candidates(
        self, bank: QuestionBank, asked_ids: Set[str]
    ) -> List[QuestionBankItem]:
        return [
            q for q_id, q in bank.questions.items()
            if q_id not in asked_ids and (
                q.validation_status == QuestionValidationStatus.VALID or str(q.validation_status) == "valid"
            )
        ]

    def select_next_question(
        self,
        bank: QuestionBank,
        learner_state: LearnerState,
        asked_ids: Set[str],
        elapsed_time_seconds: float = 0.0,
    ) -> QuestionBankItem:
        candidates = self.get_eligible_candidates(bank, asked_ids)
        if not candidates:
            raise ValueError("No candidates available in question bank.")

        return self.policy.select_next_question(candidates, learner_state, asked_ids)

    def should_stop(
        self,
        asked_count: int,
        elapsed_time_seconds: float,
        bank: QuestionBank,
        asked_ids: Set[str],
    ) -> tuple[bool, Optional[AssessmentStoppingReason]]:
        if asked_count >= self.constraints.max_questions:
            return True, AssessmentStoppingReason.TARGET_REACHED

        if elapsed_time_seconds >= self.constraints.time_limit_seconds:
            return True, AssessmentStoppingReason.TIME_EXPIRED

        candidates = self.get_eligible_candidates(bank, asked_ids)
        if not candidates:
            if asked_count >= self.constraints.min_questions:
                return True, AssessmentStoppingReason.TARGET_REACHED
            else:
                return True, AssessmentStoppingReason.INSUFFICIENT_CANDIDATES

        return False, None

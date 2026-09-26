"""
Information Gain and Adaptive Policy Abstractions for Phase 3.
Implements AdaptiveAssessmentPolicy interface and InformationGainPolicy.
"""

from typing import List, Protocol, Set
from phase3.assessment.models import CandidateScore
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBankItem


class AdaptiveAssessmentPolicy(Protocol):
    def select_next_question(
        self,
        candidates: List[QuestionBankItem],
        learner_state: LearnerState,
        asked_question_ids: Set[str],
    ) -> QuestionBankItem: ...


class InformationGainPolicy:
    """
    Selects questions based on Information Gain (uncertainty reduction & discrimination).
    Information Gain = learner uncertainty on concepts * item information value * concept coverage bonus.
    """

    @staticmethod
    def calculate_information_gain(
        question: QuestionBankItem,
        learner_state: LearnerState,
    ) -> CandidateScore:
        if not question.concept_ids:
            avg_uncertainty = 0.5
        else:
            uncertainties = [
                learner_state.get_concept_state(c_id).uncertainty
                for c_id in question.concept_ids
            ]
            avg_uncertainty = sum(uncertainties) / len(uncertainties)

        # IG approximation: Uncertainty * Item Discrimination (information_value)
        info_gain = avg_uncertainty * question.information_value

        # Diversity / coverage score bonus
        coverage_score = 1.0 / (1.0 + question.exposure_count)

        total_score = (info_gain * 0.7) + (coverage_score * 0.3)

        return CandidateScore(
            question_id=question.question_id,
            information_gain=round(info_gain, 4),
            uncertainty_score=round(avg_uncertainty, 4),
            coverage_score=round(coverage_score, 4),
            total_score=round(total_score, 4),
        )

    def select_next_question(
        self,
        candidates: List[QuestionBankItem],
        learner_state: LearnerState,
        asked_question_ids: Set[str],
    ) -> QuestionBankItem:
        eligible = [q for q in candidates if q.question_id not in asked_question_ids]
        if not eligible:
            raise ValueError("No eligible candidate questions remaining.")

        scored = []
        for q in eligible:
            cand_score = self.calculate_information_gain(q, learner_state)
            scored.append((cand_score.total_score, q))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

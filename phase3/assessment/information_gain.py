"""
Information Gain and Adaptive Policy Abstractions for Phase 3.
Implements AdaptiveAssessmentPolicy interface and InformationGainPolicy
grounded in Shannon Entropy and Expected Information Gain per Section 25.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Protocol, Sequence, Set, Tuple
from phase3.assessment.models import CandidateScore
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBankItem


def binary_entropy(p: float) -> float:
    """Computes Shannon binary entropy H(p) = -p log2(p) - (1-p) log2(1-p)."""
    p = max(1e-7, min(1.0 - 1e-7, p))
    return - (p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


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
    Computes Shannon Information Gain: IG(Q) = H_prior - E[H_posterior].
    """

    @staticmethod
    def calculate_information_gain(
        question: QuestionBankItem,
        learner_state: LearnerState,
        guess_prob: float = 0.25,
        slip_prob: float = 0.10,
    ) -> CandidateScore:
        if not question.concept_ids:
            avg_uncertainty = 0.5
            p_prior = 0.5
        else:
            uncertainties = [
                learner_state.get_concept_state(c_id).uncertainty
                for c_id in question.concept_ids
            ]
            masteries = [
                learner_state.get_concept_state(c_id).mastery_probability
                for c_id in question.concept_ids
            ]
            avg_uncertainty = sum(uncertainties) / len(uncertainties)
            p_prior = sum(masteries) / len(masteries)

        # Prior Shannon binary entropy of learner mastery
        h_prior = binary_entropy(p_prior)

        # Item discrimination factor (scaled by question information_value)
        discrim = max(0.1, min(2.0, getattr(question, "information_value", 1.0) or 1.0))
        effective_slip = max(0.02, min(0.40, slip_prob / discrim))
        effective_guess = max(0.05, min(0.45, guess_prob / discrim))

        # Predicted probability of correct response: P(correct) = p * (1 - s) + (1 - p) * g
        p_c_given_l = 1.0 - effective_slip
        p_c_given_not_l = effective_guess
        p_obs_correct = p_prior * p_c_given_l + (1.0 - p_prior) * p_c_given_not_l
        p_obs_incorrect = 1.0 - p_obs_correct

        # Posteriors via Bayes rule
        p_post_correct = (p_prior * p_c_given_l) / max(1e-7, p_obs_correct)
        p_post_incorrect = (p_prior * effective_slip) / max(1e-7, p_obs_incorrect)

        # Expected posterior entropy
        h_post_correct = binary_entropy(p_post_correct)
        h_post_incorrect = binary_entropy(p_post_incorrect)
        expected_h_post = p_obs_correct * h_post_correct + p_obs_incorrect * h_post_incorrect

        # Shannon Information Gain
        info_gain = max(0.0, h_prior - expected_h_post)

        # Coverage / freshness score bonus
        exposure = getattr(question, "exposure_count", 0)
        coverage_score = 1.0 / (1.0 + exposure)

        # Weighted total score incorporating uncertainty and IG
        total_score = (info_gain * 0.5) + (avg_uncertainty * 0.3) + (coverage_score * 0.2)

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

        # Deterministic sort: score descending, then question_id ascending
        scored.sort(key=lambda x: (-x[0], x[1].question_id))
        return scored[0][1]

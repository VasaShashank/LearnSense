"""
Knowledge Sufficiency Checker.
Determines whether sufficient evidence exists for a learner's subject knowledge state.
"""

from phase3.learner.models import LearnerState
from phase4.config import phase4_config
from phase4.models import KnowledgeSufficiencyStatus


class KnowledgeSufficiencyChecker:
    """Evaluates learner state against evidence threshold requirements."""

    def __init__(self, config=None):
        self.config = config or phase4_config

    def check_sufficiency(
        self,
        learner_state: LearnerState,
        subject_concept_ids: list[str],
    ) -> KnowledgeSufficiencyStatus:
        """
        Determines if the subject learner state is UNINITIALIZED, INSUFFICIENT_EVIDENCE, or INITIALIZED.
        """
        if not subject_concept_ids:
            return KnowledgeSufficiencyStatus.UNINITIALIZED

        observed_concepts = 0
        total_attempts = 0

        for c_id in subject_concept_ids:
            if c_id in learner_state.concept_states:
                c_state = learner_state.concept_states[c_id]
                if c_state.attempt_count > 0:
                    observed_concepts += 1
                    total_attempts += c_state.attempt_count

        if observed_concepts == 0 or total_attempts == 0:
            return KnowledgeSufficiencyStatus.UNINITIALIZED

        if total_attempts < self.config.MIN_EVIDENCE_COUNT:
            return KnowledgeSufficiencyStatus.INSUFFICIENT_EVIDENCE

        return KnowledgeSufficiencyStatus.INITIALIZED

"""
Knowledge Tracing Engine for Phase 3.
Provides deterministic, testable Bayesian Knowledge Tracing (BKT) / update mechanics.
"""

from typing import Dict, List, Optional
from phase3.learner.models import ConceptState, LearnerState


class KnowledgeTracer:
    """
    Deterministic Knowledge Tracing model based on BKT principles.
    Parameters:
    - p_init: initial mastery probability (default 0.3)
    - p_transit (P(T)): probability of transitioning from unlearned to learned state
    - p_slip (P(S)): probability of slipping (making a mistake despite knowing concept)
    - p_guess (P(G)): probability of guessing correctly despite not knowing concept
    """

    def __init__(
        self,
        p_init: float = 0.3,
        p_transit: float = 0.15,
        p_slip: float = 0.1,
        p_guess: float = 0.25,
    ):
        self.p_init = p_init
        self.p_transit = p_transit
        self.p_slip = p_slip
        self.p_guess = p_guess

    def initialize_learner(self, learner_id: str, concept_ids: List[str]) -> LearnerState:
        state = LearnerState(learner_id=learner_id)
        for c_id in concept_ids:
            state.concept_states[c_id] = ConceptState(
                concept_id=c_id,
                mastery_probability=self.p_init,
                uncertainty=0.5,
            )
        return state

    def update(
        self,
        learner_state: LearnerState,
        concept_ids: List[str],
        correctness: float,  # 0.0 to 1.0 (1.0 = fully correct, 0.0 = incorrect)
    ) -> Dict[str, float]:
        """
        Updates learner's concept mastery values post-response using Bayesian update.
        Returns a map of {concept_id: new_mastery_probability}.
        """
        updated_masteries = {}

        for c_id in concept_ids:
            c_state = learner_state.get_concept_state(c_id)
            p_prev = c_state.mastery_probability

            # Posterior update based on evidence (correct vs incorrect)
            if correctness >= 0.5:
                # Correct response evidence
                p_obs_given_known = 1.0 - self.p_slip
                p_obs_given_unknown = self.p_guess
            else:
                # Incorrect response evidence
                p_obs_given_known = self.p_slip
                p_obs_given_unknown = 1.0 - self.p_guess

            p_obs = (p_prev * p_obs_given_known) + ((1.0 - p_prev) * p_obs_given_unknown)
            if p_obs == 0:
                p_posterior = p_prev
            else:
                p_posterior = (p_prev * p_obs_given_known) / p_obs

            # Transition step: P(L_t) = P(L_{t|obs}) + (1 - P(L_{t|obs})) * P(T)
            p_next = p_posterior + (1.0 - p_posterior) * self.p_transit

            # Bound probability to [0.01, 0.99] to prevent extreme lock-in
            p_next = max(0.01, min(0.99, p_next))

            # Update uncertainty: U = 2 * |0.5 - P_mastery| inverted (high near 0.5, low near 0 or 1)
            uncertainty = 1.0 - 2.0 * abs(0.5 - p_next)

            # Apply update to state
            c_state.mastery_probability = round(p_next, 4)
            c_state.uncertainty = round(uncertainty, 4)
            learner_state.update_concept_state(c_id, correctness)

            updated_masteries[c_id] = c_state.mastery_probability

        return updated_masteries

    def get_mastery(self, learner_state: LearnerState, concept_id: str) -> float:
        return learner_state.get_concept_state(concept_id).mastery_probability

    def get_state(self, learner_state: LearnerState, concept_id: str) -> ConceptState:
        return learner_state.get_concept_state(concept_id)

"""
Knowledge Tracing Engine for Phase 3.
Provides deterministic, testable Bayesian Knowledge Tracing (BKT) / update mechanics.

Design invariants:
  - BKT posterior is computed BEFORE the transition step.
  - Mastery is bounded to [0.01, 0.99] to prevent deterministic lock-in.
  - Uncertainty = 1 - 2*|0.5 - mastery|  (peaks at mastery=0.5, zero at extremes).
  - Diagnostic confidence reflects evidence CONSISTENCY, not mastery. It rises
    when recent_performance is homogeneous and falls when it's mixed.
  - update() calls LearnerState.update_concept_state() for bookkeeping (attempt/
    correct/incorrect counts, recent_performance) but THEN applies its own BKT
    mastery/uncertainty/confidence values. This avoids the old double-write bug.
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

    def initialize_concept_state(self, concept_id: str) -> ConceptState:
        return ConceptState(
            concept_id=concept_id,
            mastery_probability=self.p_init,
            uncertainty=0.85,
            confidence=0.5,
        )

    def initialize_learner(self, learner_id: str, concept_ids: List[str]) -> LearnerState:
        state = LearnerState(learner_id=learner_id)
        for c_id in concept_ids:
            state.concept_states[c_id] = self.initialize_concept_state(c_id)
        return state

    def update(
        self,
        learner_state: LearnerState,
        concept_ids: List[str],
        correctness: float,  # 0.0 to 1.0 (1.0 = fully correct, 0.0 = incorrect)
        reported_confidence: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Updates learner's concept mastery values post-response using Bayesian update.

        Steps per concept:
          1. Record the attempt in LearnerState bookkeeping (counts, recent_performance)
          2. Compute BKT posterior from the PRIOR mastery
          3. Apply transition step
          4. Compute uncertainty from the new mastery
          5. Compute diagnostic confidence from recent_performance consistency
          6. Write final values back to ConceptState

        Returns a map of {concept_id: new_mastery_probability}.
        """
        updated_masteries = {}

        for c_id in concept_ids:
            c_state = learner_state.get_concept_state(c_id)
            p_prev = c_state.mastery_probability

            # --- 1. Bookkeeping: update counts and recent_performance ---
            learner_state.update_concept_state(c_id, correctness, reported_confidence)

            # --- 2. BKT Posterior ---
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

            # --- 3. Transition step: P(L_t) = P(L_{t|obs}) + (1 - P(L_{t|obs})) * P(T) ---
            p_next = p_posterior + (1.0 - p_posterior) * self.p_transit

            # Bound probability to [0.01, 0.99] to prevent extreme lock-in
            p_next = max(0.01, min(0.99, p_next))

            # --- 4. Uncertainty: Evidence-based model per Section 20 ---
            uncertainty = self._compute_evidence_based_uncertainty(c_state, p_next)

            # --- 5. Diagnostic confidence from recent_performance consistency ---
            diagnostic_confidence = self._compute_diagnostic_confidence(c_state)

            # --- 6. Write final computed values OVER bookkeeping values ---
            c_state.mastery_probability = round(p_next, 4)
            c_state.uncertainty = round(max(0.0, min(1.0, uncertainty)), 4)
            c_state.confidence = round(diagnostic_confidence, 4)

            updated_masteries[c_id] = c_state.mastery_probability

        return updated_masteries

    @staticmethod
    def _compute_evidence_based_uncertainty(c_state: ConceptState, p_next: float) -> float:
        """
        Evidence-based uncertainty adhering to Section 20 of TAPROOT master specification:
        Must NOT be simply f(mastery).
        Uses:
          - observation count (attempt_count / len(recent_performance))
          - response consistency (homogeneous responses reduce uncertainty faster)
          - mastery spread (posterior Bernoulli variance 4 * p * (1 - p))
          - recency weighting

        Distinguishes:
          - low mastery + high certainty (multiple consistent wrong responses -> low mastery, LOW uncertainty / HIGH certainty)
          - moderate mastery + high uncertainty (few or mixed observations near 0.5 -> HIGH uncertainty)
        """
        rp = c_state.recent_performance
        n = len(rp)
        if n == 0:
            return 0.85

        p_correct = sum(rp) / n
        volatility = 1.0 - 2.0 * abs(0.5 - p_correct)

        evidence_weight = 1.0 / (1.0 + 0.35 * n)
        posterior_spread = 4.0 * p_next * (1.0 - p_next)

        u = (0.45 * evidence_weight) + (0.35 * volatility * (1.0 - 0.5 * (1.0 - evidence_weight))) + (0.20 * posterior_spread)
        return round(max(0.01, min(0.99, u)), 4)

    @staticmethod
    def _compute_diagnostic_confidence(c_state: ConceptState) -> float:
        """
        Diagnostic confidence reflects how CONSISTENT recent evidence is.

        - If recent_performance is all True or all False => confidence ~ 0.9-0.95
        - If recent_performance is mixed (half-half)   => confidence ~ 0.3-0.5
        - With few attempts (< 3)                      => confidence stays low (0.3-0.5)

        This is intentionally separate from mastery_probability.
        A learner who consistently gets things wrong has HIGH diagnostic confidence
        (we are confident they don't know it) and LOW mastery.
        """
        rp = c_state.recent_performance
        n = len(rp)
        if n == 0:
            return 0.5  # No evidence yet

        # Proportion correct
        p_correct = sum(rp) / n

        # Consistency = how far from 0.5 the proportion is (0=maximally mixed, 0.5=all same)
        consistency = abs(p_correct - 0.5) * 2.0  # Range [0, 1]

        # Scale by evidence quantity (more evidence = more confident)
        evidence_weight = min(1.0, n / 5.0)  # Saturates at 5 attempts

        # Base confidence + consistency bonus scaled by evidence
        confidence = 0.3 + (0.65 * consistency * evidence_weight)
        return max(0.0, min(1.0, confidence))

    def get_mastery(self, learner_state: LearnerState, concept_id: str) -> float:
        return learner_state.get_concept_state(concept_id).mastery_probability

    def get_uncertainty(self, learner_state: LearnerState, concept_id: str) -> float:
        return learner_state.get_concept_state(concept_id).uncertainty

    def get_diagnostic_confidence(self, learner_state: LearnerState, concept_id: str) -> float:
        return learner_state.get_concept_state(concept_id).confidence

    def get_state(self, learner_state: LearnerState, concept_id: str) -> ConceptState:
        return learner_state.get_concept_state(concept_id)

    def identify_weak_concepts(
        self,
        learner_state: LearnerState,
        mastery_threshold: float = 0.4,
        min_attempts: int = 2,
    ) -> List[str]:
        """
        Returns concept IDs where mastery is below threshold AND we have
        enough evidence (attempts >= min_attempts) to be confident.
        """
        weak = []
        for c_id, c_state in learner_state.concept_states.items():
            if c_state.attempt_count >= min_attempts and c_state.mastery_probability < mastery_threshold:
                weak.append(c_id)
        return sorted(weak)

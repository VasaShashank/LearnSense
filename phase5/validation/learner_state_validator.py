"""
Learner State Validator and Response Idempotency Tracker for Taproot Phase 5.
Validates student response payloads, learner state bounds, history consistency, and prevents duplicate KT updates.
"""

from typing import Dict, List, Optional, Set
import time
from phase3.learner.models import ConceptState, LearnerState
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class IdempotencyTracker:
    """Tracks processed request/attempt IDs to enforce response submission idempotency."""

    def __init__(self, ttl_seconds: int = 86400):
        self._processed_tokens: Set[str] = set()
        self._token_timestamps: Dict[str, float] = {}
        self.ttl_seconds = ttl_seconds

    def is_duplicate(self, token: str) -> bool:
        self._cleanup()
        return token in self._processed_tokens

    def mark_processed(self, token: str):
        self._processed_tokens.add(token)
        self._token_timestamps[token] = time.time()

    def _cleanup(self):
        now = time.time()
        expired = [t for t, ts in self._token_timestamps.items() if now - ts > self.ttl_seconds]
        for t in expired:
            self._processed_tokens.discard(t)
            del self._token_timestamps[t]


class LearnerStateValidator:
    """Validates learner state integrity, response submissions, and KT update boundary bounds."""

    def __init__(self, idempotency_tracker: Optional[IdempotencyTracker] = None):
        self.idempotency = idempotency_tracker or IdempotencyTracker()

    def validate_response_submission(
        self,
        learner_id: str,
        concept_ids: List[str],
        correctness: float,
        request_id: Optional[str] = None,
        valid_subject_concepts: Optional[Set[str]] = None,
    ) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)

        # 1. Idempotency Check
        if request_id:
            if self.idempotency.is_duplicate(request_id):
                result.add_warning(f"Duplicate response submission detected for request_id '{request_id}'. KT update skipped.")
                result.metadata["duplicate_submission"] = True
                result.suggested_action = "Return existing result without reapplying KT state mutation."
                ValidationEventLogger.log_event(
                    "duplicate_response_detected",
                    "WARNING",
                    f"Duplicate activity submission with request_id '{request_id}'.",
                    learner_id=learner_id,
                )
                return result

        # 2. Correctness score range [0.0, 1.0]
        if correctness < 0.0 or correctness > 1.0:
            result.add_error(f"Response correctness score {correctness} is outside valid range [0.0, 1.0].")

        # 3. Concept reference validity
        if not concept_ids:
            result.add_error("Response submission does not reference any concept_ids.")
        elif valid_subject_concepts:
            for c_id in concept_ids:
                if c_id not in valid_subject_concepts:
                    result.add_error(f"Referenced concept_id '{c_id}' does not exist in current subject graph.")

        if not result.is_valid:
            result.recoverable = False
            result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
            ValidationEventLogger.log_event(
                "response_validation_failed",
                "INVALID",
                f"Response validation failed for learner '{learner_id}': {result.errors}",
                learner_id=learner_id,
            )

        return result

    def validate_learner_state(self, learner_state: LearnerState) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)

        if not learner_state.learner_id:
            result.add_error("LearnerState missing learner_id.")

        if not learner_state.concept_states:
            result.add_warning("LearnerState contains zero tracked concepts.")

        for c_id, c_state in learner_state.concept_states.items():
            if c_state.mastery_probability < 0.0 or c_state.mastery_probability > 1.0:
                result.add_error(f"ConceptState '{c_id}' mastery_probability {c_state.mastery_probability} outside [0.0, 1.0].")

            if c_state.attempts < 0:
                result.add_error(f"ConceptState '{c_id}' attempts count is negative: {c_state.attempts}.")

        return result

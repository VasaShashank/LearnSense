"""LearnSense Person 3 — Integration Event Handlers and Dispatcher.

Handles incoming learning events from message queues, HTTP webhooks, and direct service calls:
- Deduplicates retry transmissions idempotently.
- Detects conflicting attempt payloads and raises explicit validation errors.
- Dispatches attempt events to knowledge tracing, misconception tracking, retention modeling, and transfer verification.
- Enforces strict learner-scoped data isolation.
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.bkt import LearnerConceptState
from src.confidence import ConfidenceTracker
from src.integration.assessment_adapter import AssessmentAdapter, IngestedAttemptEvent
from src.misconceptions import MisconceptionRecord, MisconceptionTracker
from src.retention import PersonalizedRetentionModel, RetentionRecord
from src.state import LearnerStateService
from src.storage import ConfidenceRecord, LearnerStateStore
from src.transfer import MasteryTransferVerifier, TransferRecord


@dataclass
class AttemptDispatchOutcome:
    """Consolidated outcome of dispatching an attempt event across all learner modeling sub-services."""
    attempt_id: str
    learner_id: str
    concept_id: str
    question_id: str
    is_duplicate: bool
    is_correct: bool
    p_pred: float
    prior_mastery: float
    posterior_mastery: float
    updated_state: LearnerConceptState
    misconception_record: Optional[MisconceptionRecord] = None
    retention_record: Optional[RetentionRecord] = None
    transfer_record: Optional[TransferRecord] = None
    confidence_record: Optional[ConfidenceRecord] = None
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "learner_id": self.learner_id,
            "concept_id": self.concept_id,
            "question_id": self.question_id,
            "is_duplicate": self.is_duplicate,
            "is_correct": self.is_correct,
            "p_pred": round(self.p_pred, 5),
            "prior_mastery": round(self.prior_mastery, 5),
            "posterior_mastery": round(self.posterior_mastery, 5),
            "misconception": self.misconception_record.to_dict() if self.misconception_record else None,
            "retention": self.retention_record.to_dict() if self.retention_record else None,
            "transfer": self.transfer_record.to_dict() if self.transfer_record else None,
            "confidence": self.confidence_record.to_dict() if self.confidence_record else None,
            "timestamp": self.timestamp,
        }


class AttemptEventDispatcher:
    """Coordinates atomic attempt ingestion and dispatches side-effect-free updates to all modeling sub-services."""

    def __init__(
        self,
        state_service: LearnerStateService,
        assessment_adapter: Optional[AssessmentAdapter] = None,
        misconception_tracker: Optional[MisconceptionTracker] = None,
        retention_model: Optional[PersonalizedRetentionModel] = None,
        transfer_verifier: Optional[MasteryTransferVerifier] = None,
        confidence_tracker: Optional[ConfidenceTracker] = None,
    ) -> None:
        self.state_service = state_service
        self.assessment_adapter = assessment_adapter or AssessmentAdapter()
        self.store = state_service.store
        self.misconception_tracker = misconception_tracker or MisconceptionTracker(store=self.store)
        self.retention_model = retention_model or PersonalizedRetentionModel(store=self.store)
        self.transfer_verifier = transfer_verifier or MasteryTransferVerifier(store=self.store)
        self.confidence_tracker = confidence_tracker or ConfidenceTracker(store=self.store)

    def dispatch_attempt(
        self,
        raw_attempt_payload: Dict[str, Any],
        fallback_concept_id: Optional[str] = None,
    ) -> AttemptDispatchOutcome:
        """Processes an attempt event through the complete model dispatch pipeline.
        
        Guarantees:
        1. Predict before update: P(correct) is evaluated against prior state before mutation.
        2. Idempotency: Duplicate attempts return original state without applying BKT or retention twice.
        3. Conflict detection: Conflicting payloads with same attempt_id raise ValueError.
        4. Sub-service dispatch: Misconception, retention, and transfer models are updated in tandem.
        """
        # 1. Ingest & Validate via Assessment Adapter
        event = self.assessment_adapter.ingest_attempt(
            raw_attempt_payload,
            fallback_concept_id=fallback_concept_id,
        )

        lid = event.learner_id
        cid = event.concept_id
        aid = event.attempt_id
        now_iso = event.submitted_at

        # 2. Check Idempotency and Capture Prior State
        is_already_done = self.state_service.is_attempt_processed(lid, aid)
        current_state = self.state_service.get_or_initialize_state(lid, cid)
        prior_mastery = current_state.mastery_probability

        # 3. Process Bayesian State Update
        updated_state, p_pred, was_new = self.state_service.process_attempt(
            learner_id=lid,
            concept_id=cid,
            attempt_id=aid,
            is_correct=event.is_correct,
            question_id=event.question_id,
            submitted_at=now_iso,
            scoring_source=event.scoring_source,
        )
        posterior_mastery = updated_state.mastery_probability

        # If duplicate attempt, return immediately with cached dispatch state
        if not was_new:
            return AttemptDispatchOutcome(
                attempt_id=aid,
                learner_id=lid,
                concept_id=cid,
                question_id=event.question_id,
                is_duplicate=True,
                is_correct=event.is_correct,
                p_pred=p_pred,
                prior_mastery=prior_mastery,
                posterior_mastery=posterior_mastery,
                updated_state=updated_state,
                timestamp=now_iso,
            )

        # 4. Dispatch Misconception Analysis
        misc_rec = self.misconception_tracker.analyze_attempt(
            learner_id=lid,
            concept_id=cid,
            attempt_id=aid,
            question_id=event.question_id,
            is_correct=event.is_correct,
            work_steps=event.work_steps,
            learner_mastery=posterior_mastery,
            submitted_at=now_iso,
        )

        # 5. Dispatch Retention Model Update
        ret_rec = self.retention_model.record_review_attempt(
            learner_id=lid,
            concept_id=cid,
            attempt_id=aid,
            is_correct=event.is_correct,
            mastery_probability=posterior_mastery,
            submitted_at=now_iso,
        )

        # 6. Dispatch Transfer Verification
        transfer_rec = self.transfer_verifier.record_attempt_transfer(
            learner_id=lid,
            concept_id=cid,
            question_id=event.question_id,
            attempt_id=aid,
            is_correct=event.is_correct,
            is_multi_concept=False,
            submitted_at=now_iso,
        )

        # 7. Dispatch Confidence Recording
        conf_rec = None
        if event.reported_confidence is not None:
            conf_rec = self.confidence_tracker.record_attempt_confidence(
                learner_id=lid,
                attempt_id=aid,
                concept_id=cid,
                question_id=event.question_id,
                is_correct=event.is_correct,
                raw_confidence=event.reported_confidence,
                submitted_at=now_iso,
            )

        return AttemptDispatchOutcome(
            attempt_id=aid,
            learner_id=lid,
            concept_id=cid,
            question_id=event.question_id,
            is_duplicate=False,
            is_correct=event.is_correct,
            p_pred=p_pred,
            prior_mastery=prior_mastery,
            posterior_mastery=posterior_mastery,
            updated_state=updated_state,
            misconception_record=misc_rec,
            retention_record=ret_rec,
            transfer_record=transfer_rec,
            confidence_record=conf_rec,
            timestamp=now_iso,
        )


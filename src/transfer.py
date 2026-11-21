"""LearnSense Person 3 — Mastery and Transfer Verification Engine.

Distinguishes superficial familiar-item memorization from robust, transferable mastery:
- Evaluates whether learner can solve unseen question variants testing the concept.
- Distinguishes immediate practice from delayed recall (>= 24 hours).
- Tracks transfer categories: familiar_repeat, unseen_near, unseen_distant.
- Determines transfer verification status:
  * untested: no unseen transfer items attempted.
  * emerging_transfer: initial success on an unseen transfer item.
  * verified_transfer: confirmed mastery across multiple distinct unseen items and delayed recall.
  * transfer_failed: struggling on transfer items despite apparent practice familiarity.
- Persists transfer evidence through LearnerStateStore.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from src.storage import LearnerStateStore, TransferRecord


class TransferType(str, Enum):
    FAMILIAR_REPEAT = "familiar_repeat"
    UNSEEN_NEAR = "unseen_near"
    UNSEEN_DISTANT = "unseen_distant"


class TransferStatus(str, Enum):
    UNTESTED = "untested"
    EMERGING_TRANSFER = "emerging_transfer"
    VERIFIED_TRANSFER = "verified_transfer"
    TRANSFER_FAILED = "transfer_failed"


@dataclass
class TransferEvaluationResult:
    """Summary of transfer verification evidence for a learner and concept."""
    learner_id: str
    concept_id: str
    status: TransferStatus
    unseen_attempts_count: int
    unseen_correct_count: int
    delayed_recall_count: int
    delayed_recall_correct: int
    transfer_accuracy: float
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "concept_id": self.concept_id,
            "status": self.status.value,
            "unseen_attempts_count": self.unseen_attempts_count,
            "unseen_correct_count": self.unseen_correct_count,
            "delayed_recall_count": self.delayed_recall_count,
            "delayed_recall_correct": self.delayed_recall_correct,
            "transfer_accuracy": round(self.transfer_accuracy, 4),
            "explanation": self.explanation,
        }


class MasteryTransferVerifier:
    """Tracks, evaluates, and verifies concept mastery transfer and delayed retention."""

    DELAYED_RECALL_THRESHOLD_HOURS = 24.0

    def __init__(self, store: Optional[LearnerStateStore] = None) -> None:
        self.store = store

    def _parse_iso(self, ts: str) -> datetime.datetime:
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc)

    def record_attempt_transfer(
        self,
        learner_id: str,
        concept_id: str,
        question_id: str,
        attempt_id: str,
        is_correct: bool,
        is_multi_concept: bool = False,
        submitted_at: Optional[str] = None,
    ) -> TransferRecord:
        """Categorizes and persists an attempt as familiar practice or unseen transfer.
        
        Guarantees:
        - Inspects prior attempts for learner to determine whether question_id is unseen.
        - Calculates elapsed time from prior concept attempt to flag delayed recall.
        - Persists in SQLite store.
        """
        now_dt = self._parse_iso(submitted_at) if submitted_at else datetime.datetime.now(datetime.timezone.utc)
        now_iso = now_dt.isoformat()

        prior_evidence = self.store.get_transfer_evidence(learner_id, concept_id) if self.store else []
        seen_questions: Set[str] = {r.question_id for r in prior_evidence}

        # Check if question has been attempted before by this learner
        if question_id in seen_questions:
            transfer_type = TransferType.FAMILIAR_REPEAT.value
        elif is_multi_concept:
            transfer_type = TransferType.UNSEEN_DISTANT.value
        else:
            transfer_type = TransferType.UNSEEN_NEAR.value

        # Check delayed recall (>= 24 hours since last attempt on this concept)
        is_delayed = False
        if prior_evidence:
            last_attempt = prior_evidence[-1]
            last_dt = self._parse_iso(last_attempt.submitted_at)
            hours_elapsed = max(0.0, (now_dt - last_dt).total_seconds() / 3600.0)
            if hours_elapsed >= self.DELAYED_RECALL_THRESHOLD_HOURS:
                is_delayed = True

        rec = TransferRecord(
            learner_id=learner_id,
            attempt_id=attempt_id,
            concept_id=concept_id,
            question_id=question_id,
            transfer_type=transfer_type,
            is_delayed_recall=is_delayed,
            is_correct=is_correct,
            submitted_at=now_iso,
        )
        if self.store:
            self.store.save_transfer_evidence(rec)
        return rec

    def evaluate_transfer(
        self,
        learner_id: str,
        concept_id: str,
    ) -> TransferEvaluationResult:
        """Evaluates overall transfer verification status for a concept."""
        evidence = self.store.get_transfer_evidence(learner_id, concept_id) if self.store else []

        unseen = [
            r for r in evidence
            if r.transfer_type in {TransferType.UNSEEN_NEAR.value, TransferType.UNSEEN_DISTANT.value}
        ]
        unseen_count = len(unseen)
        unseen_correct = sum(1 for r in unseen if r.is_correct)

        delayed = [r for r in evidence if r.is_delayed_recall]
        delayed_count = len(delayed)
        delayed_correct = sum(1 for r in delayed if r.is_correct)

        acc = (unseen_correct / unseen_count) if unseen_count > 0 else 0.0

        if unseen_count == 0:
            status = TransferStatus.UNTESTED
            explanation = "No unseen transfer items attempted yet. Mastery is untested beyond familiar practice."
        elif unseen_correct >= 2 and delayed_correct >= 1 and acc >= 0.70:
            status = TransferStatus.VERIFIED_TRANSFER
            explanation = (
                f"Mastery transfer verified: successfully solved {unseen_correct}/{unseen_count} unseen questions, "
                f"including delayed recall verification ({delayed_correct}/{delayed_count})."
            )
        elif unseen_correct >= 1 and acc >= 0.50:
            status = TransferStatus.EMERGING_TRANSFER
            explanation = (
                f"Emerging transfer: successfully solved {unseen_correct}/{unseen_count} unseen questions. "
                "Further transfer practice and delayed recall needed for verification."
            )
        else:
            status = TransferStatus.TRANSFER_FAILED
            explanation = (
                f"Transfer struggling: low accuracy ({unseen_correct}/{unseen_count}) on unseen transfer items "
                "despite prior exposure. Foundational reinforcement recommended."
            )

        return TransferEvaluationResult(
            learner_id=learner_id,
            concept_id=concept_id,
            status=status,
            unseen_attempts_count=unseen_count,
            unseen_correct_count=unseen_correct,
            delayed_recall_count=delayed_count,
            delayed_recall_correct=delayed_correct,
            transfer_accuracy=acc,
            explanation=explanation,
        )

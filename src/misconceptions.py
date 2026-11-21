"""LearnSense Person 3 — Persistent Misconception Tracking and Remediation Engine.

Provides structured, evidence-grounded tracking of learner misconceptions:
- Conservative, deterministic diagnosis distinguishing careless errors from conceptual deficits.
- Multi-attempt evidence accumulation with idempotent recurrence tracking.
- Remediation assignment and resolution verification upon demonstrated subsequent mastery.
- Durable persistence isolated per learner.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from src.storage import LearnerStateStore, MisconceptionRecord


class MisconceptionCategory(str, Enum):
    FORMULA_MISAPPLICATION = "formula_misapplication"
    SIGN_OR_DIRECTION_ERROR = "sign_or_direction_error"
    INVERSE_RELATION_CONFUSION = "inverse_relation_confusion"
    PREREQUISITE_DEFICIT = "prerequisite_deficit"
    UNITS_OR_DIMENSION_ERROR = "units_or_dimension_error"
    CARELESS_SLIP = "careless_slip"
    UNCLASSIFIED = "unclassified"


class MisconceptionStatus(str, Enum):
    SUSPECTED = "suspected"
    RECURRING = "recurring"
    IMPROVING = "improving"
    RESOLVED = "resolved"
    NEEDS_REASSESSMENT = "needs_reassessment"


# Canonical misconception definitions per concept domain
KNOWN_CONCEPT_MISCONCEPTIONS: Dict[str, List[Dict[str, Any]]] = {
    "PHY_KIN": [
        {
            "category": MisconceptionCategory.SIGN_OR_DIRECTION_ERROR,
            "pattern": r"(acceleration.*positive.*downward|sign.*error|g\s*=\s*\+\s*9\.8.*upward)",
            "description": "Confusion between acceleration due to gravity sign convention and coordinate axes.",
            "remediation": "Review coordinate convention in kinematics: designate upward as positive and g as negative.",
        },
        {
            "category": MisconceptionCategory.FORMULA_MISAPPLICATION,
            "pattern": r"(v\s*=\s*u\s*\+\s*at.*variable|constant\s*acceleration.*inapplicable)",
            "description": "Applying constant-acceleration kinematic equations to non-uniform acceleration scenarios.",
            "remediation": "Review calculus-based definitions v = dx/dt and a = dv/dt when acceleration is time-dependent.",
        },
    ],
    "PHY_NLM": [
        {
            "category": MisconceptionCategory.INVERSE_RELATION_CONFUSION,
            "pattern": r"(action\s*reaction.*cancel|internal.*forces|third\s*law.*same\s*body)",
            "description": "Believing Newton's third law action-reaction pairs act on the same body and cancel out.",
            "remediation": "Draw separate free-body diagrams for interacting bodies; action-reaction pairs act on different objects.",
        },
        {
            "category": MisconceptionCategory.FORMULA_MISAPPLICATION,
            "pattern": r"(f\s*=\s*ma.*pseudo|inertial.*frame.*violation)",
            "description": "Applying Newton's second law in non-inertial frames without fictitious/pseudo forces.",
            "remediation": "Identify frame of reference first: in accelerating frames, introduce pseudo force F_pseudo = -m*a_frame.",
        },
    ],
    "PHY_WPE": [
        {
            "category": MisconceptionCategory.SIGN_OR_DIRECTION_ERROR,
            "pattern": r"(work.*friction.*positive|work.*done.*negative.*potential)",
            "description": "Misunderstanding work-energy theorem signs for dissipative forces.",
            "remediation": "Work done by friction opposes displacement, doing negative work on the system.",
        },
    ],
}


class MisconceptionTracker:
    """Manages detection, recurrence, persistence, and remediation of learner misconceptions."""

    def __init__(self, store: Optional[LearnerStateStore] = None) -> None:
        self.store = store

    def _generate_misconception_id(self, learner_id: str, concept_id: str, category: str) -> str:
        key = f"{learner_id}:{concept_id}:{category}"
        return f"MISC_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12].upper()}"

    def analyze_attempt(
        self,
        learner_id: str,
        concept_id: str,
        attempt_id: str,
        question_id: str,
        is_correct: bool,
        work_steps: Optional[List[Any]] = None,
        learner_mastery: float = 0.5,
        submitted_at: Optional[str] = None,
    ) -> Optional[MisconceptionRecord]:
        """Analyzes an attempt to detect, update, or remediate misconceptions.
        
        Conservative policy:
        - If attempt is correct: evaluates existing misconceptions on this concept for improvement/resolution.
        - If attempt is incorrect:
          * If student has high mastery (>0.85) and no work step error pattern -> categorized as careless slip, low confidence.
          * If work steps reveal known misconception pattern -> categorized with high confidence.
          * If no work steps and low mastery -> unclassified deficit.
        """
        now_iso = submitted_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        existing_records = self.get_misconceptions(learner_id, concept_id)

        # -------------------------------------------------------------
        # 1. Correct Attempt -> Check for Resolution / Improvement
        # -------------------------------------------------------------
        if is_correct:
            for rec in existing_records:
                if rec.status in {MisconceptionStatus.SUSPECTED, MisconceptionStatus.RECURRING, MisconceptionStatus.IMPROVING}:
                    # Add positive evidence
                    rec.evidence_history.append({
                        "attempt_id": attempt_id,
                        "question_id": question_id,
                        "outcome": 1,
                        "timestamp": now_iso,
                        "note": "Demonstrated correct understanding",
                    })
                    rec.last_observed_at = now_iso

                    # Count recent consecutive correct attempts following remediation
                    recent_correct = 0
                    for ev in reversed(rec.evidence_history):
                        if ev.get("outcome") == 1:
                            recent_correct += 1
                        else:
                            break

                    if recent_correct >= 2:
                        rec.status = MisconceptionStatus.RESOLVED.value
                        rec.confidence = max(0.1, rec.confidence * 0.4)
                    elif recent_correct == 1:
                        rec.status = MisconceptionStatus.IMPROVING.value
                        rec.confidence = max(0.2, rec.confidence * 0.7)

                    if self.store:
                        self.store.save_misconception(rec)
                    return rec
            return None

        # -------------------------------------------------------------
        # 2. Incorrect Attempt -> Detect or Recur
        # -------------------------------------------------------------
        work_texts: List[str] = []
        if work_steps:
            for ws in work_steps:
                if isinstance(ws, dict):
                    work_texts.append(str(ws.get("text", "")).lower())
                else:
                    work_texts.append(str(ws).lower())
        full_work = " ".join(work_texts)

        detected_category = MisconceptionCategory.UNCLASSIFIED
        description = "Unclassified performance deficit."
        remediation = "Review the core governing laws and definitions for this concept."
        confidence = 0.50

        # Pattern match known domain misconceptions
        known_list = KNOWN_CONCEPT_MISCONCEPTIONS.get(concept_id, [])
        matched_known = False
        for known in known_list:
            if re.search(known["pattern"], full_work, re.IGNORECASE):
                detected_category = known["category"]
                description = known["description"]
                remediation = known["remediation"]
                confidence = 0.85
                matched_known = True
                break

        if not matched_known:
            if learner_mastery >= 0.80 and len(full_work) < 15:
                detected_category = MisconceptionCategory.CARELESS_SLIP
                description = "Isolated mistake likely due to computational slip or time pressure rather than conceptual deficit."
                remediation = "Re-check arithmetic and sign conventions before finalizing response."
                confidence = 0.35
            elif "prerequisite" in full_work or "unfamiliar" in full_work:
                detected_category = MisconceptionCategory.PREREQUISITE_DEFICIT
                description = "Struggling due to foundational gaps in concept prerequisites."
                remediation = "Step back to review prerequisite foundational concepts."
                confidence = 0.75

        # Check if this misconception is already tracked
        misc_id = self._generate_misconception_id(learner_id, concept_id, detected_category.value)
        existing = None
        if self.store:
            existing = self.store.get_misconception(learner_id, misc_id)

        if existing:
            # Check idempotency: if attempt_id is already in supporting attempts, do not double-count
            if attempt_id in existing.supporting_attempt_ids:
                return existing

            existing.supporting_attempt_ids.append(attempt_id)
            existing.last_observed_at = now_iso
            existing.recurrence_count += 1
            existing.evidence_history.append({
                "attempt_id": attempt_id,
                "question_id": question_id,
                "outcome": 0,
                "timestamp": now_iso,
                "note": f"Recurrence observed in {question_id}",
            })

            # Upgrade status
            if existing.status == MisconceptionStatus.RESOLVED.value:
                # Contradictory evidence: reopen!
                existing.status = MisconceptionStatus.NEEDS_REASSESSMENT.value
                existing.confidence = min(0.95, existing.confidence + 0.3)
            elif existing.recurrence_count >= 2:
                existing.status = MisconceptionStatus.RECURRING.value
                existing.confidence = min(0.95, existing.confidence + 0.15)
            else:
                existing.status = MisconceptionStatus.SUSPECTED.value

            if self.store:
                self.store.save_misconception(existing)
            return existing

        # Create new record
        new_record = MisconceptionRecord(
            misconception_id=misc_id,
            learner_id=learner_id,
            concept_id=concept_id,
            category=detected_category.value,
            description=description,
            confidence=confidence,
            first_observed_at=now_iso,
            last_observed_at=now_iso,
            recurrence_count=1,
            status=MisconceptionStatus.SUSPECTED.value,
            remediation_action=remediation,
            supporting_attempt_ids=[attempt_id],
            evidence_history=[{
                "attempt_id": attempt_id,
                "question_id": question_id,
                "outcome": 0,
                "timestamp": now_iso,
                "note": f"Initial observation from {question_id}",
            }],
        )

        if self.store:
            self.store.save_misconception(new_record)
        return new_record

    def get_misconceptions(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
        active_only: bool = False,
    ) -> List[MisconceptionRecord]:
        """Retrieves misconceptions for a learner, optionally filtered by concept or active status."""
        if not self.store:
            return []
        records = self.store.get_learner_misconceptions(learner_id, concept_id)
        if active_only:
            return [
                r for r in records
                if r.status in {
                    MisconceptionStatus.SUSPECTED.value,
                    MisconceptionStatus.RECURRING.value,
                    MisconceptionStatus.NEEDS_REASSESSMENT.value,
                }
            ]
        return records

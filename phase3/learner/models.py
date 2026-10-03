"""
Phase 3 Learner State Models.
Represents individual concept states, evidence-based uncertainty, separate learner confidence,
persistent misconception states, and overall progress.
Matches Sections 19, 20, 21, and 22 of TAPROOT master specification.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class MisconceptionStatusEnum(str, Enum):
    SUSPECTED = "suspected"
    SUPPORTED = "supported"
    RESOLVED = "resolved"


class MisconceptionRecord(BaseModel):
    """
    Persistent learner misconception state adhering to Section 22 schema.
    A single wrong answer does NOT produce a supported misconception.
    """
    misconception_id: str
    learner_id: str
    concept_id: str
    description: str
    evidence_refs: List[str] = Field(default_factory=list)
    first_detected: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_detected: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    frequency: int = Field(default=1, ge=1)
    status: MisconceptionStatusEnum = MisconceptionStatusEnum.SUSPECTED


class ConceptState(BaseModel):
    concept_id: str
    mastery_probability: float = Field(default=0.3, ge=0.0, le=1.0)
    uncertainty: float = Field(default=0.85, ge=0.0, le=1.0)  # Evidence-based uncertainty
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)   # Diagnostic confidence (separate from mastery)
    attempt_count: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    incorrect_count: int = Field(default=0, ge=0)
    recent_performance: List[bool] = Field(default_factory=list)  # Last N responses
    last_attempt: Optional[datetime] = None


class LearnerState(BaseModel):
    learner_id: str
    concept_states: Dict[str, ConceptState] = Field(default_factory=dict)
    misconceptions: Dict[str, MisconceptionRecord] = Field(default_factory=dict)
    topic_scores: Dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_concept_state(self, concept_id: str) -> ConceptState:
        if concept_id not in self.concept_states:
            self.concept_states[concept_id] = ConceptState(concept_id=concept_id)
        return self.concept_states[concept_id]

    def update_concept_state(
        self,
        concept_id: str,
        is_correct: float,
        reported_confidence: Optional[float] = None,
    ) -> ConceptState:
        """
        Bookkeeping-only update: increments attempt/correct/incorrect counts
        and appends to recent_performance.

        NOTE: This method does NOT update mastery_probability, uncertainty, or
        diagnostic confidence. Those are computed by KnowledgeTracer.update()
        and written back separately to prevent double-write bugs.
        """
        state = self.get_concept_state(concept_id)
        state.attempt_count += 1
        if is_correct >= 0.8:
            state.correct_count += 1
            state.recent_performance.append(True)
        else:
            state.incorrect_count += 1
            state.recent_performance.append(False)

        if len(state.recent_performance) > 10:
            state.recent_performance = state.recent_performance[-10:]

        # Only update confidence if explicitly reported by the learner
        # (self-reported confidence, distinct from diagnostic confidence)
        if reported_confidence is not None:
            state.confidence = max(0.0, min(1.0, float(reported_confidence)))

        state.last_attempt = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        return state

    def record_misconception(
        self,
        concept_id: str,
        description: str,
        evidence_ref: str,
        initial_confidence: float = 0.4,
    ) -> MisconceptionRecord:
        """
        Records or updates a misconception.
        Rule: A single wrong answer produces a SUSPECTED misconception.
        Repeated evidence (frequency >= 2 or confidence >= 0.65) elevates status to SUPPORTED.
        Uses deterministic SHA-based key for stability across sessions.
        """
        # Formulate deterministic key from concept_id and normalized description
        norm_desc = " ".join(description.lower().split())
        hash_input = f"{concept_id}:{norm_desc}"
        desc_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:10]
        misc_key = f"misc_{concept_id}_{desc_hash}"

        now = datetime.now(timezone.utc)
        if misc_key in self.misconceptions:
            rec = self.misconceptions[misc_key]
            rec.frequency += 1
            rec.last_detected = now
            if evidence_ref and evidence_ref not in rec.evidence_refs:
                rec.evidence_refs.append(evidence_ref)
            # Increase confidence with repeated evidence
            rec.confidence = min(0.98, rec.confidence + 0.25)
            # Section 22 rule: repeated evidence transitions status to SUPPORTED
            if rec.frequency >= 2 or rec.confidence >= 0.65:
                rec.status = MisconceptionStatusEnum.SUPPORTED
        else:
            rec = MisconceptionRecord(
                misconception_id=misc_key,
                learner_id=self.learner_id,
                concept_id=concept_id,
                description=description,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                first_detected=now,
                last_detected=now,
                confidence=max(0.1, min(0.5, initial_confidence)),
                frequency=1,
                status=MisconceptionStatusEnum.SUSPECTED,  # Never supported on single event
            )
            self.misconceptions[misc_key] = rec

        self.updated_at = now
        return rec

    def resolve_misconception(self, misconception_id: str) -> Optional[MisconceptionRecord]:
        """Marks a misconception as resolved after successful remediation."""
        rec = self.misconceptions.get(misconception_id)
        if rec:
            rec.status = MisconceptionStatusEnum.RESOLVED
            rec.last_detected = datetime.now(timezone.utc)
            self.updated_at = datetime.now(timezone.utc)
        return rec

    def get_active_misconceptions(
        self,
        concept_id: Optional[str] = None,
    ) -> List[MisconceptionRecord]:
        """
        Returns all non-RESOLVED misconceptions, optionally filtered by concept_id.
        Useful for adaptive feedback and remediation targeting.
        """
        results = []
        for rec in self.misconceptions.values():
            if rec.status == MisconceptionStatusEnum.RESOLVED:
                continue
            if concept_id and rec.concept_id != concept_id:
                continue
            results.append(rec)
        return results

    def get_supported_misconceptions(
        self,
        concept_id: Optional[str] = None,
    ) -> List[MisconceptionRecord]:
        """
        Returns only SUPPORTED misconceptions — those with sufficient evidence.
        These should drive remediation content selection.
        """
        return [
            rec for rec in self.get_active_misconceptions(concept_id)
            if rec.status == MisconceptionStatusEnum.SUPPORTED
        ]

    def get_mastery_summary(self) -> Dict[str, Dict[str, float]]:
        """
        Returns a summary dict keyed by concept_id with mastery, uncertainty,
        confidence, and attempt count for observability / diagnostics.
        """
        summary = {}
        for c_id, c_state in self.concept_states.items():
            summary[c_id] = {
                "mastery": c_state.mastery_probability,
                "uncertainty": c_state.uncertainty,
                "confidence": c_state.confidence,
                "attempts": float(c_state.attempt_count),
            }
        return summary

    def get_weakest_concepts(self, n: int = 3) -> List[Tuple[str, float]]:
        """
        Returns the N concepts with lowest mastery (that have at least 1 attempt).
        Used by mini-quiz targeting and remediation.
        """
        attempted = [
            (c_id, c_state.mastery_probability)
            for c_id, c_state in self.concept_states.items()
            if c_state.attempt_count > 0
        ]
        attempted.sort(key=lambda x: x[1])
        return attempted[:n]

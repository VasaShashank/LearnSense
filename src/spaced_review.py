"""LearnSense Person 3 — Spaced Repetition and Review Scheduling Engine.

Computes pedagogically grounded review intervals and due statuses based on:
- Actual longitudinal interaction timestamps and evidence counts.
- Current estimated concept mastery probability.
- Error streaks and demonstrated prerequisite gaps.
- Explicit distinction between unassessed concepts and overdue review concepts.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from src.bkt import LearnerConceptState


@dataclass(frozen=True)
class ConceptReviewStatus:
    """Evaluation of spaced review status for a single learner-concept pair."""
    concept_id: str
    status: str  # 'unassessed' | 'scheduled' | 'due' | 'overdue'
    is_review_due: bool
    urgency: float  # [0.0, 1.0] priority weight
    days_since_last_evidence: Optional[float]
    recommended_interval_days: float
    next_review_due_iso: Optional[str]
    rationale: str

    def to_dict(self) -> Dict[str, Union[str, float, bool, None]]:
        return {
            "concept_id": self.concept_id,
            "status": self.status,
            "is_review_due": self.is_review_due,
            "urgency": round(self.urgency, 4),
            "days_since_last_evidence": (
                round(self.days_since_last_evidence, 2)
                if self.days_since_last_evidence is not None
                else None
            ),
            "recommended_interval_days": round(self.recommended_interval_days, 2),
            "next_review_due_iso": self.next_review_due_iso,
            "rationale": self.rationale,
        }


class SpacedReviewScheduler:
    """Spaced Repetition and Retention Review Scheduler.
    
    Determines optimal concept revisit intervals using modified half-life
    repetition spacing modulated by Bayesian mastery probability.
    """

    def __init__(
        self,
        base_interval_days: float = 1.0,
        repetition_multiplier: float = 1.8,
        max_interval_days: float = 30.0,
        overdue_grace_days: float = 2.0,
    ) -> None:
        self.base_interval_days = base_interval_days
        self.repetition_multiplier = repetition_multiplier
        self.max_interval_days = max_interval_days
        self.overdue_grace_days = overdue_grace_days

    def compute_review_interval(
        self,
        mastery_probability: float,
        evidence_count: int,
        consecutive_errors: int = 0,
    ) -> float:
        """Calculates review interval in days.
        
        High mastery and repeated successful practice lengthen the interval exponentially.
        Consecutive errors or weak mastery collapse the interval back to minimum.
        """
        if evidence_count <= 0:
            return self.base_interval_days

        if consecutive_errors > 0 or mastery_probability < 0.50:
            # Collapse interval for immediate reinforcement
            return max(0.5, self.base_interval_days * 0.5)

        # Scale interval: I = base * (multiplier ^ min(evidence, 5)) * (mastery / 0.5)
        power = min(float(evidence_count), 5.0)
        mastery_factor = max(0.5, min(2.0, mastery_probability / 0.50))
        interval = self.base_interval_days * (self.repetition_multiplier ** power) * mastery_factor
        return min(self.max_interval_days, max(0.5, interval))

    def evaluate_concept_review(
        self,
        state: LearnerConceptState,
        as_of_time: Optional[Union[str, datetime.datetime]] = None,
    ) -> ConceptReviewStatus:
        """Evaluates whether a concept is due or overdue for spaced review.
        
        Rules:
        - An unassessed concept (evidence_count == 0) is NEVER classified as 'due' or 'overdue'.
        - If last_evidence_at is missing, falls back to 'unassessed' or 'scheduled' safely.
        - Calculates elapsed time accurately from timestamp.
        """
        cid = state.concept_id

        # 1. Unassessed concepts are never overdue
        if state.evidence_count == 0 or state.last_evidence_at is None:
            return ConceptReviewStatus(
                concept_id=cid,
                status="unassessed",
                is_review_due=False,
                urgency=0.0,
                days_since_last_evidence=None,
                recommended_interval_days=self.base_interval_days,
                next_review_due_iso=None,
                rationale="Concept is unassessed. Foundational learning or initial assessment required before review scheduling.",
            )

        # 2. Parse timestamps
        try:
            last_dt = datetime.datetime.fromisoformat(state.last_evidence_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            last_dt = datetime.datetime.now(datetime.timezone.utc)

        if as_of_time is None:
            now_dt = datetime.datetime.now(datetime.timezone.utc)
        elif isinstance(as_of_time, str):
            now_dt = datetime.datetime.fromisoformat(as_of_time.replace("Z", "+00:00"))
        else:
            now_dt = as_of_time
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)

        # 3. Calculate interval and due date
        consecutive_errors = state.metadata.get("consecutive_errors", 0)
        interval_days = self.compute_review_interval(
            mastery_probability=state.mastery_probability,
            evidence_count=state.evidence_count,
            consecutive_errors=consecutive_errors,
        )

        due_dt = last_dt + datetime.timedelta(days=interval_days)
        next_review_iso = due_dt.isoformat()

        elapsed_seconds = (now_dt - last_dt).total_seconds()
        elapsed_days = max(0.0, elapsed_seconds / 86400.0)

        # 4. Determine status and urgency
        if elapsed_days < interval_days:
            # Still within retention window
            urgency = max(0.0, (elapsed_days / interval_days) * 0.40)
            return ConceptReviewStatus(
                concept_id=cid,
                status="scheduled",
                is_review_due=False,
                urgency=urgency,
                days_since_last_evidence=elapsed_days,
                recommended_interval_days=interval_days,
                next_review_due_iso=next_review_iso,
                rationale=f"Review scheduled in {interval_days - elapsed_days:.1f} days.",
            )
        elif elapsed_days <= interval_days + self.overdue_grace_days:
            # Due for review
            urgency = 0.60 + min(0.20, (elapsed_days - interval_days) / self.overdue_grace_days * 0.20)
            return ConceptReviewStatus(
                concept_id=cid,
                status="due",
                is_review_due=True,
                urgency=urgency,
                days_since_last_evidence=elapsed_days,
                recommended_interval_days=interval_days,
                next_review_due_iso=next_review_iso,
                rationale=f"Concept review is due (interval of {interval_days:.1f} days elapsed {elapsed_days:.1f} days ago).",
            )
        else:
            # Overdue
            urgency = min(1.0, 0.85 + (elapsed_days - interval_days - self.overdue_grace_days) * 0.05)
            return ConceptReviewStatus(
                concept_id=cid,
                status="overdue",
                is_review_due=True,
                urgency=urgency,
                days_since_last_evidence=elapsed_days,
                recommended_interval_days=interval_days,
                next_review_due_iso=next_review_iso,
                rationale=f"Concept review is overdue by {elapsed_days - interval_days:.1f} days.",
            )

    def find_concepts_due_for_review(
        self,
        states: Dict[str, LearnerConceptState],
        as_of_time: Optional[Union[str, datetime.datetime]] = None,
    ) -> List[ConceptReviewStatus]:
        """Returns all concepts currently due or overdue for review, sorted by urgency descending."""
        due_list: List[ConceptReviewStatus] = []
        for state in states.values():
            rev = self.evaluate_concept_review(state, as_of_time=as_of_time)
            if rev.is_review_due:
                due_list.append(rev)

        # Sort by urgency descending, then concept_id alphabetically
        due_list.sort(key=lambda r: (-r.urgency, r.concept_id))
        return due_list

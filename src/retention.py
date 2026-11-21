"""LearnSense Person 3 — Personalized Retention Model and Dynamic Spaced Review.

Extends the half-life spaced-review scheduler with a personalized memory retention model:
- Explicit retention probability model R(Δt) = 2^(-Δt / S) based on memory stability S (half-life).
- Evidence-driven stability updates: successful delayed recall expands stability, while failure contracts it.
- Clear separation between skill mastery P(L_t) and temporal retention R(t).
- Durable persistence per learner and concept.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.spaced_review import SpacedReviewScheduler
from src.storage import LearnerStateStore, RetentionRecord


# Default initial stability by base mastery tier
DEFAULT_STABILITY_DAYS = {
    "low": 2.0,       # P(L) < 0.50
    "developing": 4.0, # 0.50 <= P(L) < 0.85
    "mastered": 7.0,   # P(L) >= 0.85
}
MIN_STABILITY_DAYS = 1.0
MAX_STABILITY_DAYS = 60.0
DEFAULT_RETENTION_THRESHOLD = 0.70  # Concept is due for review when R(t) < 0.70


class PersonalizedRetentionModel:
    """Calculates and updates per-learner, per-concept memory retention and review schedules."""

    def __init__(
        self,
        store: Optional[LearnerStateStore] = None,
        retention_threshold: float = DEFAULT_RETENTION_THRESHOLD,
    ) -> None:
        self.store = store
        self.retention_threshold = retention_threshold
        self.baseline_scheduler = SpacedReviewScheduler()

    def _parse_iso(self, ts: str) -> datetime.datetime:
        ts_clean = ts.replace("Z", "+00:00")
        try:
            return datetime.datetime.fromisoformat(ts_clean)
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc)

    def estimate_retention(
        self,
        learner_id: str,
        concept_id: str,
        as_of_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Estimates current retrieval probability R(t) = 2^(-Δt / S) for a learner and concept.
        
        Returns:
            Dictionary with recall_probability, half_life_days, days_elapsed, is_due, and explanation.
        """
        now_dt = self._parse_iso(as_of_time) if as_of_time else datetime.datetime.now(datetime.timezone.utc)
        record = self.store.get_retention(learner_id, concept_id) if self.store else None

        if not record:
            # Concept has never been reviewed / unassessed
            return {
                "learner_id": learner_id,
                "concept_id": concept_id,
                "recall_probability": 1.0,
                "half_life_days": 0.0,
                "days_elapsed": 0.0,
                "is_due": False,
                "review_count": 0,
                "status": "unassessed",
                "explanation": "No prior review history; retention model inactive until initial mastery.",
            }

        last_review_dt = self._parse_iso(record.last_review_at)
        days_elapsed = max(0.0, (now_dt - last_review_dt).total_seconds() / 86400.0)
        s = max(MIN_STABILITY_DAYS, record.half_life_days)

        # Exponential decay: R = 2^(-Δt / S)
        recall_prob = math.pow(2.0, -days_elapsed / s)
        recall_prob = max(0.01, min(1.0, recall_prob))
        is_due = recall_prob <= self.retention_threshold

        explanation = (
            f"Estimated recall probability is {recall_prob:.1%} after {days_elapsed:.1f} days "
            f"(stability half-life: {s:.1f} days). "
            + ("Review is DUE to prevent forgetting." if is_due else "Memory retention is currently stable.")
        )

        return {
            "learner_id": learner_id,
            "concept_id": concept_id,
            "recall_probability": round(recall_prob, 4),
            "half_life_days": round(s, 2),
            "days_elapsed": round(days_elapsed, 2),
            "is_due": is_due,
            "review_count": record.review_count,
            "consecutive_successes": record.consecutive_successes,
            "status": "overdue" if is_due else "stable",
            "explanation": explanation,
        }

    def record_review_attempt(
        self,
        learner_id: str,
        concept_id: str,
        attempt_id: str,
        is_correct: bool,
        mastery_probability: float,
        submitted_at: Optional[str] = None,
    ) -> RetentionRecord:
        """Updates stability and retention parameters upon observing a reviewed attempt.
        
        Guarantees:
        - Exactly-once update (idempotent per attempt_id).
        - Successful review expands stability proportional to elapsed interval.
        - Failed review contracts stability.
        - Persisted in storage.
        """
        now_dt = self._parse_iso(submitted_at) if submitted_at else datetime.datetime.now(datetime.timezone.utc)
        now_iso = now_dt.isoformat()
        record = self.store.get_retention(learner_id, concept_id) if self.store else None

        if not record:
            # Initialize retention record based on initial mastery
            if mastery_probability >= 0.85:
                init_stability = DEFAULT_STABILITY_DAYS["mastered"]
            elif mastery_probability >= 0.50:
                init_stability = DEFAULT_STABILITY_DAYS["developing"]
            else:
                init_stability = DEFAULT_STABILITY_DAYS["low"]

            record = RetentionRecord(
                learner_id=learner_id,
                concept_id=concept_id,
                half_life_days=init_stability,
                last_review_at=now_iso,
                review_count=1,
                consecutive_successes=1 if is_correct else 0,
                last_recall_probability=1.0 if is_correct else 0.5,
                updated_at=now_iso,
                history=[{
                    "attempt_id": attempt_id,
                    "outcome": 1 if is_correct else 0,
                    "submitted_at": now_iso,
                    "stability_after": init_stability,
                }],
            )
            if self.store:
                self.store.save_retention(record)
            return record

        # Idempotency check: if attempt_id is already in history, return without double-updating
        for h in record.history:
            if h.get("attempt_id") == attempt_id:
                return record

        last_dt = self._parse_iso(record.last_review_at)
        days_elapsed = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
        old_s = record.half_life_days

        if is_correct:
            # Expanding retrieval: reward longer intervals successfully recalled
            # Factor: 1.0 + 0.5 * sqrt(interval / S)
            interval_ratio = min(3.0, days_elapsed / max(0.5, old_s))
            expansion_factor = 1.0 + 0.4 * math.sqrt(max(0.1, interval_ratio))
            new_s = min(MAX_STABILITY_DAYS, old_s * expansion_factor)
            consec = record.consecutive_successes + 1
        else:
            # Forgetting event: contract stability
            new_s = max(MIN_STABILITY_DAYS, old_s * 0.55)
            consec = 0

        # Calculate recall prob before update
        est_recall = math.pow(2.0, -days_elapsed / old_s) if old_s > 0 else 0.5

        record.half_life_days = round(new_s, 2)
        record.last_review_at = now_iso
        record.review_count += 1
        record.consecutive_successes = consec
        record.last_recall_probability = round(est_recall, 4)
        record.updated_at = now_iso
        record.history.append({
            "attempt_id": attempt_id,
            "outcome": 1 if is_correct else 0,
            "submitted_at": now_iso,
            "days_elapsed": round(days_elapsed, 2),
            "stability_after": record.half_life_days,
        })

        if self.store:
            self.store.save_retention(record)
        return record

    def get_overdue_concepts(
        self,
        learner_id: str,
        as_of_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Returns all concepts that have fallen below the retention threshold, sorted by urgency."""
        if not self.store:
            return []
        all_recs = self.store.get_all_retention(learner_id)
        overdue_list = []
        for r in all_recs:
            est = self.estimate_retention(learner_id, r.concept_id, as_of_time)
            if est["is_due"]:
                overdue_list.append(est)

        # Sort by lowest recall probability (most urgent)
        overdue_list.sort(key=lambda x: x["recall_probability"])
        return overdue_list

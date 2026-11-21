"""LearnSense Person 3 — Student-Reported Confidence-Aware Personalization.

Integrates subjective self-reported confidence ratings into the personalization system as a
supplementary metacognitive signal, strictly respecting non-negotiable pedagogical boundaries:
1. Latent mastery separation: BKT Bayesian updates continue to use objective correctness and canonical parameters;
   self-reported confidence does NOT alter P(L_t) updates.
2. Metacognitive calibration: Identifies calibration quadrants:
   - High Confidence + Correct: well_calibrated_mastery
   - High Confidence + Incorrect: high_confidence_error (blindspots, conceptual traps)
   - Low Confidence + Correct: low_confidence_correct (impostor uncertainty, lucky guesses)
   - Low Confidence + Incorrect: well_calibrated_uncertainty (metacognitive accuracy of knowledge gap)
3. Proportionality guardrail: Isolated ratings do not trigger definitive psychological diagnoses;
   recurrent discrepancy patterns (>= 2 occurrences) guide cautious pedagogical support.
4. Priority integrity: Confidence signals never override critical prerequisite remediation (Priority 90)
   or overdue spaced reviews (Priority 80).
5. Idempotent and learner-isolated storage backed by durable SQLite.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from src.storage import ConfidenceRecord, LearnerStateStore, SQLiteStateStore


HIGH_CONFIDENCE_THRESHOLD = 0.70
LOW_CONFIDENCE_THRESHOLD = 0.40


def normalize_confidence(value: Any) -> Optional[float]:
    """Normalizes and validates student-reported confidence rating.
    
    Supported formats:
    - None / missing -> returns None safely (backward compatibility).
    - Float / int in [0.0, 1.0] -> validated directly.
    - Int in [1, 5] -> linearly scaled to (val - 1.0) / 4.0 in [0.0, 1.0].
    
    Raises:
        ValueError: If value is non-numeric or outside permitted ranges.
    """
    if value is None:
        return None

    if isinstance(value, str):
        val_str = value.strip()
        if not val_str:
            return None
        try:
            numeric_val = float(val_str)
        except ValueError:
            raise ValueError(f"Invalid confidence value '{value}': must be numeric or null.")
    elif isinstance(value, (int, float)):
        numeric_val = float(value)
    else:
        raise ValueError(f"Invalid confidence type '{type(value).__name__}': must be numeric or null.")

    if 0.0 <= numeric_val <= 1.0:
        return round(numeric_val, 4)
    # Check if 1-5 scale was used
    if 1.0 < numeric_val <= 5.0 and float(numeric_val).is_integer():
        normalized = (numeric_val - 1.0) / 4.0
        return round(normalized, 4)

    raise ValueError(f"Confidence value {numeric_val} out of bounds: must be in [0.0, 1.0] or integer 1-5.")


def classify_calibration_quadrant(confidence_score: float, is_correct: bool) -> str:
    """Classifies single attempt into a metacognitive calibration quadrant."""
    conf = float(confidence_score)
    if conf >= HIGH_CONFIDENCE_THRESHOLD:
        return "well_calibrated_mastery" if is_correct else "high_confidence_error"
    elif conf <= LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence_correct" if is_correct else "well_calibrated_uncertainty"
    else:
        return "intermediate_calibration"


@dataclass
class ConfidenceCalibrationProfile:
    """Longitudinal metacognitive calibration summary for a learner."""
    learner_id: str
    concept_id: Optional[str]
    total_ratings: int
    mean_confidence: float
    overall_accuracy: float
    accuracy_at_high_confidence: Optional[float]
    accuracy_at_low_confidence: Optional[float]
    high_confidence_error_count: int
    low_confidence_correct_count: int
    recurrent_high_confidence_errors: bool
    recurrent_low_confidence_correct: bool
    calibration_bias: float  # mean_confidence - overall_accuracy (positive = overconfident, negative = underconfident)
    brier_score: float
    status: str  # 'insufficient_evidence', 'calibrated'
    pedagogical_guidance: Optional[str] = None
    recent_quadrants: List[str] = field(default_factory=list)
    created_at: str = ""
    disclaimer: str = (
        "Self-reported confidence is a subjective metacognitive signal. "
        "It supplements but never replaces objective assessment or BKT latent mastery."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfidenceTracker:
    """Coordinates recording and analysis of student-reported confidence."""

    def __init__(self, store: Optional[LearnerStateStore] = None) -> None:
        self.store = store or SQLiteStateStore()

    def record_attempt_confidence(
        self,
        learner_id: str,
        attempt_id: str,
        concept_id: str,
        question_id: str,
        is_correct: bool,
        raw_confidence: Any,
        submitted_at: Optional[str] = None,
    ) -> Optional[ConfidenceRecord]:
        """Safely normalizes, classifies, and durably persists student-reported confidence.
        
        If confidence is omitted, returns None without side effects.
        """
        conf_val = normalize_confidence(raw_confidence)
        if conf_val is None:
            return None

        lid = str(learner_id).strip()
        aid = str(attempt_id).strip()
        cid = str(concept_id).strip()
        qid = str(question_id).strip()
        now_iso = submitted_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

        quadrant = classify_calibration_quadrant(conf_val, is_correct)
        rec = ConfidenceRecord(
            learner_id=lid,
            attempt_id=aid,
            concept_id=cid,
            question_id=qid,
            is_correct=is_correct,
            confidence_score=conf_val,
            calibration_quadrant=quadrant,
            submitted_at=now_iso,
        )
        self.store.save_confidence_record(rec)
        return rec

    def get_confidence_records(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
    ) -> List[ConfidenceRecord]:
        """Retrieves raw confidence records strictly scoped to learner."""
        return self.store.get_confidence_records(str(learner_id).strip(), concept_id=concept_id)

    def evaluate_calibration_profile(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
    ) -> ConfidenceCalibrationProfile:
        """Evaluates longitudinal metacognitive calibration for a learner."""
        lid = str(learner_id).strip()
        records = self.get_confidence_records(lid, concept_id=concept_id)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not records:
            return ConfidenceCalibrationProfile(
                learner_id=lid,
                concept_id=concept_id,
                total_ratings=0,
                mean_confidence=0.0,
                overall_accuracy=0.0,
                accuracy_at_high_confidence=None,
                accuracy_at_low_confidence=None,
                high_confidence_error_count=0,
                low_confidence_correct_count=0,
                recurrent_high_confidence_errors=False,
                recurrent_low_confidence_correct=False,
                calibration_bias=0.0,
                brier_score=0.0,
                status="insufficient_evidence",
                pedagogical_guidance="No self-reported confidence data available.",
                recent_quadrants=[],
                created_at=now_iso,
            )

        total = len(records)
        sum_conf = sum(r.confidence_score for r in records)
        mean_conf = round(sum_conf / total, 4)

        correct_count = sum(1 for r in records if r.is_correct)
        overall_acc = round(correct_count / total, 4)

        high_conf_recs = [r for r in records if r.confidence_score >= HIGH_CONFIDENCE_THRESHOLD]
        low_conf_recs = [r for r in records if r.confidence_score <= LOW_CONFIDENCE_THRESHOLD]

        acc_high = round(sum(1 for r in high_conf_recs if r.is_correct) / len(high_conf_recs), 4) if high_conf_recs else None
        acc_low = round(sum(1 for r in low_conf_recs if r.is_correct) / len(low_conf_recs), 4) if low_conf_recs else None

        high_conf_errors = sum(1 for r in records if r.calibration_quadrant == "high_confidence_error")
        low_conf_corrects = sum(1 for r in records if r.calibration_quadrant == "low_confidence_correct")

        # Brier score: MSE between confidence rating and outcome {0, 1}
        brier = round(sum((r.confidence_score - (1.0 if r.is_correct else 0.0)) ** 2 for r in records) / total, 4)
        bias = round(mean_conf - overall_acc, 4)

        # Recurrent patterns require at least 2 occurrences
        recurrent_hc_err = high_conf_errors >= 2
        recurrent_lc_corr = low_conf_corrects >= 2

        # Cautious pedagogical guidance
        guidance = None
        if recurrent_hc_err and bias > 0.15:
            guidance = (
                "Observed repeated high-confidence errors. Recommend diagnostic reflection, "
                "identifying potential misconception traps or careless execution errors before reattempt."
            )
            status = "calibrated" if total >= 3 else "preliminary_pattern"
        elif recurrent_lc_corr and bias < -0.15:
            guidance = (
                "Observed repeated correct responses with low reported confidence. "
                "Recommend supportive reinforcement and validation to build metacognitive self-trust."
            )
            status = "calibrated" if total >= 3 else "preliminary_pattern"
        elif total < 3:
            status = "insufficient_evidence"
            guidance = "Preliminary confidence tracking; insufficient volume for calibration profile."
        else:
            status = "calibrated"
            if abs(bias) <= 0.15:
                guidance = "Well-calibrated metacognitive self-assessment between subjective confidence and objective outcomes."
            else:
                guidance = "Slight calibration divergence; maintain standard adaptive practice."


        recent_quads = [r.calibration_quadrant for r in records[-5:]]

        return ConfidenceCalibrationProfile(
            learner_id=lid,
            concept_id=concept_id,
            total_ratings=total,
            mean_confidence=mean_conf,
            overall_accuracy=overall_acc,
            accuracy_at_high_confidence=acc_high,
            accuracy_at_low_confidence=acc_low,
            high_confidence_error_count=high_conf_errors,
            low_confidence_correct_count=low_conf_corrects,
            recurrent_high_confidence_errors=recurrent_hc_err,
            recurrent_low_confidence_correct=recurrent_lc_corr,
            calibration_bias=bias,
            brier_score=brier,
            status=status,
            pedagogical_guidance=guidance,
            recent_quadrants=recent_quads,
            created_at=now_iso,
        )

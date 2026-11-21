"""LearnSense Person 3 — Mastery Uncertainty Engine.

Calculates evidence strength, epistemic uncertainty, and qualitative mastery tiers:
- Distinguishes unassessed (zero evidence) from weak (confirmed low mastery).
- Classifies mastery into five explainable categories:
  * unassessed: no qualifying assessment evidence (N = 0).
  * weak: confirmed low mastery (N >= 2, P(L) < 0.50).
  * developing: emerging or inconsistent mastery (N >= 1, 0.50 <= P(L) < 0.85).
  * well_supported: high mastery confirmed by sufficient evidence (N >= 3, P(L) >= 0.85).
  * uncertain: conflicting responses, sparse evidence, or stale history.
- Computes calibrated uncertainty index U in [0.0, 1.0].
- Generates human-readable pedagogical explanations.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.bkt import LearnerConceptState


class MasteryClassification(str, Enum):
    UNASSESSED = "unassessed"
    WEAK = "weak"
    DEVELOPING = "developing"
    WELL_SUPPORTED = "well_supported"
    UNCERTAIN = "uncertain"


@dataclass
class MasteryUncertaintyEvaluation:
    """Detailed evaluation of mastery belief uncertainty and evidence strength."""
    learner_id: str
    concept_id: str
    mastery_probability: float
    evidence_count: int
    classification: MasteryClassification
    uncertainty_index: float  # [0.0, 1.0], where 1.0 is maximum uncertainty
    contract_status: str       # "unassessed", "provisional", "estimated", "needs_review"
    is_stale: bool
    is_conflicting: bool
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "concept_id": self.concept_id,
            "mastery_probability": round(self.mastery_probability, 4),
            "evidence_count": self.evidence_count,
            "classification": self.classification.value,
            "uncertainty_index": round(self.uncertainty_index, 4),
            "contract_status": self.contract_status,
            "is_stale": self.is_stale,
            "is_conflicting": self.is_conflicting,
            "explanation": self.explanation,
        }


class MasteryUncertaintyEvaluator:
    """Evaluates the evidential certainty of a learner's mastery state."""

    STALENESS_THRESHOLD_DAYS = 14.0

    @classmethod
    def evaluate_state(
        cls,
        state: LearnerConceptState,
        as_of_time: Optional[str] = None,
        recent_outcomes: Optional[List[int]] = None,
    ) -> MasteryUncertaintyEvaluation:
        """Evaluates state uncertainty, classification, and explanation."""
        n = state.evidence_count
        p = state.mastery_probability

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if as_of_time:
            try:
                now_dt = datetime.datetime.fromisoformat(as_of_time.replace("Z", "+00:00"))
            except Exception:
                pass

        # Check staleness
        is_stale = False
        days_since_evidence = 0.0
        if state.last_evidence_at:
            try:
                last_dt = datetime.datetime.fromisoformat(state.last_evidence_at.replace("Z", "+00:00"))
                days_since_evidence = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
                if days_since_evidence > cls.STALENESS_THRESHOLD_DAYS and n > 0:
                    is_stale = True
            except Exception:
                pass

        # Check conflicting responses (e.g. mixed 1s and 0s in recent attempts)
        is_conflicting = False
        if recent_outcomes and len(recent_outcomes) >= 2:
            has_success = any(x == 1 for x in recent_outcomes)
            has_failure = any(x == 0 for x in recent_outcomes)
            if has_success and has_failure:
                is_conflicting = True

        # Compute uncertainty index U in [0.0, 1.0]
        if n == 0:
            uncertainty_index = 1.0
            classification = MasteryClassification.UNASSESSED
            contract_status = "unassessed"
            explanation = "No assessment evidence observed for this concept. Mastery is unassessed."
        else:
            # Variance component: 4 * p * (1 - p) in [0, 1]
            variance_factor = 4.0 * p * (1.0 - p)
            # Sample size confidence: exponential decay of uncertainty with N
            sample_size_factor = math.exp(-n / 3.0)
            # Base uncertainty combines belief variance and evidence volume
            base_u = 0.5 * variance_factor + 0.5 * sample_size_factor

            # Penalties
            if is_conflicting:
                base_u = min(1.0, base_u + 0.25)
            if is_stale:
                base_u = min(1.0, base_u + 0.20)

            uncertainty_index = max(0.05, min(1.0, base_u))

            # Classification logic
            if is_conflicting and n >= 2:
                classification = MasteryClassification.UNCERTAIN
                contract_status = "needs_review"
                explanation = f"Conflicting response pattern observed across {n} attempts. Reassessment is recommended."
            elif is_stale:
                classification = MasteryClassification.UNCERTAIN
                contract_status = "needs_review"
                explanation = f"Assessment evidence is stale ({days_since_evidence:.1f} days elapsed). Reassessment recommended to confirm retention."
            elif n < 2:
                classification = MasteryClassification.DEVELOPING
                contract_status = "provisional"
                explanation = f"Sparse evidence ({n} attempt). Mastery estimate is provisional."
            elif p < 0.50:
                classification = MasteryClassification.WEAK
                contract_status = "estimated"
                explanation = f"Sufficient evidence ({n} attempts) indicates low mastery ({p:.1%}). Prerequisite remediation or review needed."
            elif p >= 0.85 and n >= 3 and not is_conflicting:
                classification = MasteryClassification.WELL_SUPPORTED
                contract_status = "estimated"
                explanation = f"High mastery ({p:.1%}) is well-supported by {n} consistent attempts."
            else:
                classification = MasteryClassification.DEVELOPING
                contract_status = "estimated"
                explanation = f"Concept mastery is developing ({p:.1%}) with {n} attempts recorded."

        return MasteryUncertaintyEvaluation(
            learner_id=state.learner_id,
            concept_id=state.concept_id,
            mastery_probability=p,
            evidence_count=n,
            classification=classification,
            uncertainty_index=uncertainty_index,
            contract_status=contract_status,
            is_stale=is_stale,
            is_conflicting=is_conflicting,
            explanation=explanation,
        )

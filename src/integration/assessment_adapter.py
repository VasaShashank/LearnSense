"""LearnSense Person 3 — Assessment Service Integration Adapter.

Consumes scored assessment attempt events from Person 4 (Assessment Service):
- Validates incoming events strictly against contracts/attempt_schema.json (Draft 2020-12).
- Enforces trusted server scoring rules: accepts only scoring_status == "scored".
- Rejects unscored, pending, or untrusted scoring sources.
- Normalizes student work steps into canonical structured step objects.
- Guards against client-supplied correctness claims.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from src.ingestion import is_attempt_trusted_and_scored
from src.integration.contracts import validate_attempt


@dataclass(frozen=True)
class IngestedAttemptEvent:
    """Validated, normalized attempt event ready for Bayesian knowledge tracing."""
    attempt_id: str
    learner_id: str
    question_id: str
    concept_id: str
    is_correct: bool
    score: float
    max_score: float
    scoring_source: str
    submitted_at: str
    work_steps: List[Dict[str, Any]] = field(default_factory=list)
    reported_confidence: Optional[float] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "learner_id": self.learner_id,
            "question_id": self.question_id,
            "concept_id": self.concept_id,
            "is_correct": self.is_correct,
            "score": self.score,
            "max_score": self.max_score,
            "scoring_source": self.scoring_source,
            "submitted_at": self.submitted_at,
            "reported_confidence": self.reported_confidence,
            "work_steps": list(self.work_steps),
        }


class AssessmentAdapter:
    """Thin, deterministic adapter for ingesting attempts from the Assessment Service."""

    def __init__(self, default_concept_id: str = "PHY_KIN") -> None:
        self.default_concept_id = default_concept_id

    def ingest_attempt(
        self,
        attempt_payload: Dict[str, Any],
        fallback_concept_id: Optional[str] = None,
    ) -> IngestedAttemptEvent:
        import copy
        payload = copy.deepcopy(attempt_payload)
        raw_work = payload.get("response", {}).get("work_steps")
        if raw_work and isinstance(raw_work, list):
            norm_steps = []
            for idx, ws in enumerate(raw_work):
                if isinstance(ws, dict):
                    norm_steps.append(ws)
                else:
                    norm_steps.append({"step_index": idx + 1, "text": str(ws)})
            payload["response"]["work_steps"] = norm_steps

        # 1. Validate Draft 2020-12 Schema
        is_valid_schema, errors = validate_attempt(payload)
        if not is_valid_schema:
            err_str = "; ".join(errors[:3])
            raise ValueError(f"Assessment event schema validation failed: {err_str}")

        # 2. Enforce Trusted Server Scoring
        is_eligible, is_correct, reason = is_attempt_trusted_and_scored(payload)
        if not is_eligible or is_correct is None:
            raise ValueError(f"Assessment attempt rejected: {reason}")

        attempt_id = str(attempt_payload.get("attempt_id") or attempt_payload.get("idempotency_key", "")).strip()
        learner_id = str(attempt_payload.get("learner_id", "")).strip()
        question_id = str(attempt_payload.get("question_id", "Q_UNKNOWN")).strip()
        submitted_at = str(attempt_payload.get("submitted_at", datetime.datetime.now(datetime.timezone.utc).isoformat()))

        # Resolve primary concept
        concept_id = fallback_concept_id
        if not concept_id:
            concept_id = attempt_payload.get("context", {}).get("concept_id")
        if not concept_id:
            concept_id = self.default_concept_id

        outcome = attempt_payload.get("outcome", {})
        score = float(outcome.get("score") if outcome.get("score") is not None else (1.0 if is_correct else 0.0))
        max_score = float(outcome.get("max_score") if outcome.get("max_score") is not None else 1.0)
        scoring_source = str(outcome.get("scoring_source", "server_key"))

        # Normalize work steps
        raw_response = attempt_payload.get("response", {})
        raw_work = raw_response.get("work_steps", [])
        normalized_work_steps: List[Dict[str, Any]] = []
        for idx, step in enumerate(raw_work):
            if isinstance(step, dict):
                normalized_work_steps.append({
                    "step_index": int(step.get("step_index", idx + 1)),
                    "text": str(step.get("text", "")),
                })
            else:
                normalized_work_steps.append({
                    "step_index": idx + 1,
                    "text": str(step),
                })

        # Extract reported confidence if supplied
        from src.confidence import normalize_confidence
        raw_conf = (
            attempt_payload.get("context", {}).get("reported_confidence")
            if isinstance(attempt_payload.get("context"), dict)
            else None
        )
        if raw_conf is None and isinstance(attempt_payload.get("response"), dict):
            raw_conf = attempt_payload.get("response", {}).get("reported_confidence")
        if raw_conf is None:
            raw_conf = attempt_payload.get("reported_confidence")
        norm_conf = normalize_confidence(raw_conf)

        return IngestedAttemptEvent(
            attempt_id=attempt_id,
            learner_id=learner_id,
            question_id=question_id,
            concept_id=concept_id,
            is_correct=is_correct,
            score=score,
            max_score=max_score,
            scoring_source=scoring_source,
            submitted_at=submitted_at,
            work_steps=normalized_work_steps,
            reported_confidence=norm_conf,
            raw_payload=attempt_payload,
        )


"""LearnSense Person 3 — Attempt Processing and Personalization Pipeline.

Executes the closed-loop adaptive learning cycle:
    Attempt Ingested
       │
       ▼
    Trusted Scoring Validation (Draft 2020-12 & Fail-Closed Idempotency)
       │
       ▼
    Pre-Outcome Prediction P(correct)
       │
       ▼
    Bayes Update & Longitudinal State Transition
       │
       ▼
    Spaced Review & Prerequisite Graph Evaluation
       │
       ▼
    Adaptive Assessment / Activity Recommendation
       │
       ▼
    Source-Grounded Tutoring Feedback (When Requested or Needed)
"""

from __future__ import annotations

import copy
import datetime
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.adaptive_assessment import AdaptiveAssessmentSelector
from src.ingestion import is_attempt_trusted_and_scored, validate_json_attempt
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.recommendation import RecommendationEngine, RecommendationItem
from src.spaced_review import SpacedReviewScheduler
from src.state import LearnerConceptState, LearnerStateService
from src.tutoring import TutoringEngine, TutoringRequest, TutoringResponse


@dataclass
class PipelineProcessingResult:
    """Full auditable result of processing an attempt through the personalization pipeline."""
    attempt_id: str
    learner_id: str
    question_id: str
    concept_id: str
    is_correct: bool
    is_duplicate: bool
    p_pred_prior: float
    prior_mastery: float
    posterior_mastery: float
    updated_state: LearnerConceptState
    next_recommendation: RecommendationItem
    tutoring_response: Optional[TutoringResponse] = None
    processing_timestamp: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "learner_id": self.learner_id,
            "question_id": self.question_id,
            "concept_id": self.concept_id,
            "is_correct": self.is_correct,
            "is_duplicate": self.is_duplicate,
            "was_new": not self.is_duplicate,
            "p_pred_prior": round(self.p_pred_prior, 5),
            "prior_mastery": round(self.prior_mastery, 5),
            "posterior_mastery": round(self.posterior_mastery, 5),
            "updated_state": self.updated_state.to_contract_payload({
                "name": "akt_concept_mastery_head",
                "version": "1.0",
                "parameters_id": "akt_multitask_confirmatory_v1",
                "extensions": ["causal_attention", "dedicated_mastery_head", "attempt_pipeline"],
            }),
            "next_recommendation": self.next_recommendation.to_contract_payload(),
            "tutoring_response": self.tutoring_response.to_contract_payload() if self.tutoring_response else None,
            "processing_timestamp": self.processing_timestamp,
            "errors": list(self.errors),
        }


class PersonalizationPipeline:
    """Integrated Closed-Loop Personalization and Learning Pipeline."""

    def __init__(
        self,
        state_service: Optional[LearnerStateService] = None,
        recommendation_engine: Optional[RecommendationEngine] = None,
        tutoring_engine: Optional[TutoringEngine] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.state_service = state_service or LearnerStateService(knowledge_graph=self.knowledge_graph)
        self.recommendation_engine = recommendation_engine or RecommendationEngine(knowledge_graph=self.knowledge_graph)
        self.tutoring_engine = tutoring_engine or TutoringEngine(knowledge_graph=self.knowledge_graph)

    def process_attempt_event(
        self,
        attempt_obj: Dict[str, Any],
        primary_concept_id: Optional[str] = None,
        provide_tutoring_feedback: bool = True,
    ) -> PipelineProcessingResult:
        """Processes an attempt event dictionary conforming to contracts/attempt_schema.json.
        
        Guarantees:
        - Rejects unverified, unscored, or schema-invalid attempts.
        - Idempotent: duplicate attempts do not mutate state or double-count.
        - Predict-before-update: pre-outcome prediction generated prior to update.
        - Exactly-once Bayesian state update.
        - Generates subsequent recommendation and diagnostic tutoring feedback.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Validate Schema and Scoring Trust
        is_eligible, is_correct_opt, reason = is_attempt_trusted_and_scored(attempt_obj)
        if not is_eligible or is_correct_opt is None:
            raise ValueError(f"Attempt rejected by pipeline gate: {reason}")

        attempt_id = str(attempt_obj.get("attempt_id") or attempt_obj.get("idempotency_key", "")).strip()
        learner_id = str(attempt_obj.get("learner_id", "")).strip()
        question_id = str(attempt_obj.get("question_id", "Q_UNKNOWN")).strip()
        submitted_at = str(attempt_obj.get("submitted_at") or now_iso)
        scoring_source = str(attempt_obj.get("outcome", {}).get("scoring_source", "server_key"))

        # Resolve primary concept
        cid = primary_concept_id
        if not cid:
            # Check context or question metadata
            cid = attempt_obj.get("context", {}).get("concept_id")
        if not cid:
            # Lookup in question bank
            q_item = self.recommendation_engine.assessment_selector.get_question(question_id)
            if q_item:
                cid = q_item.primary_concept_id
        if not cid:
            cid = "PHY_KIN"  # Canonical fallback

        # 2. Check Idempotency and Predict Before Update
        is_already_done = self.state_service.is_attempt_processed(learner_id, attempt_id)
        current_state = self.state_service.get_or_initialize_state(learner_id, cid)
        prior_mastery = current_state.mastery_probability

        # 3. Process attempt through State Service
        updated_state, p_pred, was_new = self.state_service.process_attempt(
            learner_id=learner_id,
            concept_id=cid,
            attempt_id=attempt_id,
            is_correct=is_correct_opt,
            question_id=question_id,
            submitted_at=submitted_at,
            scoring_source=scoring_source,
        )

        posterior_mastery = updated_state.mastery_probability

        # 4. Generate Next Recommendation
        next_rec = self.recommendation_engine.recommend_next_activity(
            learner_id=learner_id,
            state_service=self.state_service,
            focus_concept_id=cid,
            as_of_time=submitted_at,
        )

        # 5. Generate Tutoring Feedback if requested
        tutor_resp = None
        if provide_tutoring_feedback:
                raw_resp = attempt_obj.get("response", {})
                context = {
                    "is_correct": is_correct_opt,
                    "submitted_answer": str(raw_resp.get("value", "")),
                    "work_steps": list(raw_resp.get("work_steps", [])),
                    "has_work_steps": bool(raw_resp.get("work_steps")),
                }
                tutor_req = TutoringRequest(
                    request_id=f"TREQ_{uuid.uuid4().hex[:10]}",
                    learner_id=learner_id,
                    intent="check_work" if is_correct_opt else "review_mistake",
                    message=f"Attempt {attempt_id} for question {question_id}.",
                    concept_ids=[cid],
                    question_id=question_id,
                    attempt_id=attempt_id,
                    created_at=now_iso,
                    context=context,
                )
                tutor_resp = self.tutoring_engine.deliver_tutoring(tutor_req, state_service=self.state_service)

        return PipelineProcessingResult(
            attempt_id=attempt_id,
            learner_id=learner_id,
            question_id=question_id,
            concept_id=cid,
            is_correct=is_correct_opt,
            is_duplicate=not was_new,
            p_pred_prior=p_pred,
            prior_mastery=prior_mastery,
            posterior_mastery=posterior_mastery,
            updated_state=updated_state,
            next_recommendation=next_rec,
            tutoring_response=tutor_resp,
            processing_timestamp=now_iso,
            errors=[],
        )

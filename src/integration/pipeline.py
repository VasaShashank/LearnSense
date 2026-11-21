"""LearnSense Person 3 — End-to-End Integrated Learning Pipeline.

Executes the complete closed-loop adaptive learning cycle across all integrated components:
    Question Selection / Presentation
            │
            ▼
    Trusted Assessment Ingestion & Validation
            │
            ▼
    Pre-Outcome Prediction P(correct)
            │
            ▼
    Atomic Bayesian Knowledge Tracing Update
            │
            ▼
    Persistent Misconception Tracking & Recurrence
            │
            ▼
    Personalized Memory Retention Scheduling
            │
            ▼
    Mastery Transfer Verification
            │
            ▼
    Unified Explainable Recommendation
            │
            ▼
    Source-Grounded Pedagogical Tutoring Feedback
            │
            ▼
    Auditable Closed-Loop Pipeline Result
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from src.adaptive_assessment import AdaptiveAssessmentSelector
from src.bkt import LearnerConceptState
from src.confidence import ConfidenceTracker
from src.integration.assessment_adapter import AssessmentAdapter
from src.integration.event_handlers import AttemptDispatchOutcome, AttemptEventDispatcher
from src.integration.knowledge_graph_adapter import KnowledgeGraphAdapter
from src.integration.question_bank_adapter import QuestionBankAdapter
from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.misconceptions import MisconceptionTracker
from src.recommendation import RecommendationEngine, RecommendationItem
from src.retention import PersonalizedRetentionModel
from src.state import LearnerStateService
from src.storage import LearnerStateStore
from src.transfer import MasteryTransferVerifier
from src.tutoring import TutoringEngine, TutoringRequest, TutoringResponse
from src.uncertainty import MasteryUncertaintyEvaluator


@dataclass
class EndToEndPipelineResult:
    """Consolidated, auditable artifact representing the complete execution of the learning loop."""
    attempt_id: str
    learner_id: str
    question_id: str
    concept_id: str
    is_correct: bool
    is_duplicate: bool
    p_pred_prior: float
    prior_mastery: float
    posterior_mastery: float
    updated_state: Dict[str, Any]
    uncertainty_evaluation: Dict[str, Any]
    next_recommendation: Dict[str, Any]
    tutoring_response: Optional[Dict[str, Any]] = None
    misconception_record: Optional[Dict[str, Any]] = None
    retention_estimate: Optional[Dict[str, Any]] = None
    transfer_status: Optional[Dict[str, Any]] = None
    confidence_record: Optional[Dict[str, Any]] = None
    confidence_profile: Optional[Dict[str, Any]] = None
    execution_timestamp: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IntegratedLearningLoopPipeline:
    """Master orchestrator wiring all Person 3 components into an end-to-end adaptive learning loop."""

    def __init__(
        self,
        state_service: Optional[LearnerStateService] = None,
        store: Optional[LearnerStateStore] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.store = store or (state_service.store if state_service else None)

        self.state_service = state_service or LearnerStateService(
            knowledge_graph=self.knowledge_graph,
            store=self.store,
        )
        self.kg_adapter = KnowledgeGraphAdapter(graph=self.knowledge_graph)
        self.assessment_selector = AdaptiveAssessmentSelector(knowledge_graph=self.knowledge_graph)
        self.question_bank_adapter = QuestionBankAdapter(assessment_selector=self.assessment_selector)
        self.assessment_adapter = AssessmentAdapter()

        self.misconception_tracker = MisconceptionTracker(store=self.store)
        self.retention_model = PersonalizedRetentionModel(store=self.store)
        self.transfer_verifier = MasteryTransferVerifier(store=self.store)
        self.confidence_tracker = ConfidenceTracker(store=self.store)

        self.dispatcher = AttemptEventDispatcher(
            state_service=self.state_service,
            assessment_adapter=self.assessment_adapter,
            misconception_tracker=self.misconception_tracker,
            retention_model=self.retention_model,
            transfer_verifier=self.transfer_verifier,
            confidence_tracker=self.confidence_tracker,
        )

        self.recommendation_engine = RecommendationEngine(
            knowledge_graph=self.knowledge_graph,
            assessment_selector=self.assessment_selector,
            knowledge_base=self.knowledge_base,
            misconception_tracker=self.misconception_tracker,
            retention_model=self.retention_model,
            transfer_verifier=self.transfer_verifier,
        )

        self.tutoring_engine = TutoringEngine(
            knowledge_base=self.knowledge_base,
            knowledge_graph=self.knowledge_graph,
        )

    def run_learning_cycle(
        self,
        attempt_payload: Dict[str, Any],
        fallback_concept_id: Optional[str] = None,
        provide_tutoring_feedback: bool = True,
    ) -> EndToEndPipelineResult:
        """Executes the closed-loop learning cycle for a scored attempt event.
        
        Guarantees:
        - Predict-before-update invariant preserved.
        - Exactly-once transactional update; idempotent on retries.
        - Misconception, retention, and transfer models updated.
        - Next pedagogical recommendation generated with transparent rationale.
        - Source-grounded tutoring generated without answer key leakage.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Step 1: Dispatch attempt atomically across knowledge tracing & sub-services
        dispatch_outcome = self.dispatcher.dispatch_attempt(
            raw_attempt_payload=attempt_payload,
            fallback_concept_id=fallback_concept_id,
        )

        lid = dispatch_outcome.learner_id
        cid = dispatch_outcome.concept_id
        aid = dispatch_outcome.attempt_id
        qid = dispatch_outcome.question_id
        is_correct = dispatch_outcome.is_correct

        # Step 2: Evaluate Uncertainty on Updated State
        uncertainty_eval = MasteryUncertaintyEvaluator.evaluate_state(
            state=dispatch_outcome.updated_state,
            as_of_time=now_iso,
            recent_outcomes=[1 if is_correct else 0],
        )

        # Step 3: Estimate Current Memory Retention
        retention_est = self.retention_model.estimate_retention(lid, cid, as_of_time=now_iso)

        # Step 4: Evaluate Transfer Verification
        transfer_eval = self.transfer_verifier.evaluate_transfer(lid, cid)

        # Step 5: Generate Next Pedagogical Recommendation
        rec_item = self.recommendation_engine.recommend_next_activity(
            learner_id=lid,
            state_service=self.state_service,
            focus_concept_id=cid,
            as_of_time=now_iso,
        )
        rec_contract = rec_item.to_contract_payload()

        # Step 6: Generate Sourced Tutoring Dialogue / Feedback
        tutoring_contract = None
        if provide_tutoring_feedback:
            raw_resp = attempt_payload.get("response", {})
            tutor_req = TutoringRequest(
                request_id=f"TREQ_{uuid.uuid4().hex[:10]}",
                learner_id=lid,
                intent="check_work" if is_correct else "review_mistake",
                message=f"Attempt {aid} on question {qid}.",
                concept_ids=[cid],
                question_id=qid,
                attempt_id=aid,
                created_at=now_iso,
                context={
                    "is_correct": is_correct,
                    "submitted_answer": str(raw_resp.get("value", "")),
                    "work_steps": list(raw_resp.get("work_steps", [])),
                    "has_work_steps": bool(raw_resp.get("work_steps")),
                },
            )
            tutor_resp = self.tutoring_engine.deliver_tutoring(tutor_req, state_service=self.state_service)
            tutoring_contract = tutor_resp.to_contract_payload()

        # Step 7: Format contract-compliant learner state payload
        conf_profile = self.confidence_tracker.evaluate_calibration_profile(lid, concept_id=cid)
        state_contract = self.state_service.serialize_state_to_contract(dispatch_outcome.updated_state)
        # Enrich metadata with uncertainty, retention, transfer, and confidence summaries
        state_contract["metadata"]["uncertainty"] = uncertainty_eval.to_dict()
        state_contract["metadata"]["retention"] = retention_est
        state_contract["metadata"]["transfer"] = transfer_eval.to_dict()
        state_contract["metadata"]["confidence"] = conf_profile.to_dict()

        return EndToEndPipelineResult(
            attempt_id=aid,
            learner_id=lid,
            question_id=qid,
            concept_id=cid,
            is_correct=is_correct,
            is_duplicate=dispatch_outcome.is_duplicate,
            p_pred_prior=dispatch_outcome.p_pred,
            prior_mastery=dispatch_outcome.prior_mastery,
            posterior_mastery=dispatch_outcome.posterior_mastery,
            updated_state=state_contract,
            uncertainty_evaluation=uncertainty_eval.to_dict(),
            next_recommendation=rec_contract,
            tutoring_response=tutoring_contract,
            misconception_record=dispatch_outcome.misconception_record.to_dict() if dispatch_outcome.misconception_record else None,
            retention_estimate=retention_est,
            transfer_status=transfer_eval.to_dict(),
            confidence_record=dispatch_outcome.confidence_record.to_dict() if dispatch_outcome.confidence_record else None,
            confidence_profile=conf_profile.to_dict(),
            execution_timestamp=now_iso,
            errors=[],
        )


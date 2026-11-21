"""LearnSense Person 3 — Unified Personalization Service Facade.

Exposes stable, schema-validated service interfaces for backend APIs and frontend consumption:
- Learner state retrieval and profile export.
- Attempt ingestion, evaluation, and Bayesian knowledge tracing.
- Adaptive assessment selection using expected information gain.
- Personalized learning activity recommendation.
- Source-grounded tutoring instruction delivery.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.adaptive_assessment import AdaptiveAssessmentSelector
from src.attempt_pipeline import PersonalizationPipeline, PipelineProcessingResult
from src.bkt import BKTConfig
from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.recommendation import RecommendationEngine
from src.spaced_review import SpacedReviewScheduler
from src.state import LearnerStateService
from src.tutoring import TutoringEngine, TutoringRequest, TutoringResponse


from src.storage import LearnerStateStore
from src.misconceptions import MisconceptionTracker
from src.retention import PersonalizedRetentionModel
from src.transfer import MasteryTransferVerifier
from src.confidence import ConfidenceTracker
from src.study_plan import StudyPlanGenerator
from src.readiness import ExamReadinessEstimator
from src.teacher import IndependentTeacherPlanner, CohortTeacherManager
from src.micro_quiz import MicroQuizEngine
from src.migration_adapter import CanonicalConceptMigrationAdapter

import logging
logger = logging.getLogger(__name__)


class LearnSensePersonalizationService:
    """Unified Facade for Learner Modeling, Adaptive Assessment, and Tutoring."""

    def __init__(
        self,
        config: Optional[BKTConfig] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        store: Optional[LearnerStateStore] = None,
        state_service: Optional[LearnerStateService] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.config = config or BKTConfig(config_id="production_service_v1")
        self.migration_adapter = CanonicalConceptMigrationAdapter()

        self.store = store
        self.state_service = state_service or LearnerStateService(
            config=self.config,
            knowledge_graph=self.knowledge_graph,
            store=self.store,
        )
        self.misconception_tracker = MisconceptionTracker(store=self.state_service.store)
        self.retention_model = PersonalizedRetentionModel(store=self.state_service.store)
        self.transfer_verifier = MasteryTransferVerifier(store=self.state_service.store)
        self.confidence_tracker = ConfidenceTracker(store=self.state_service.store)

        self.assessment_selector = AdaptiveAssessmentSelector(
            knowledge_graph=self.knowledge_graph,
            config=self.config,
        )
        self.review_scheduler = SpacedReviewScheduler()
        self.recommendation_engine = RecommendationEngine(
            knowledge_graph=self.knowledge_graph,
            assessment_selector=self.assessment_selector,
            review_scheduler=self.review_scheduler,
            knowledge_base=self.knowledge_base,
            misconception_tracker=self.misconception_tracker,
            retention_model=self.retention_model,
            transfer_verifier=self.transfer_verifier,
        )
        self.tutoring_engine = TutoringEngine(
            knowledge_base=self.knowledge_base,
            knowledge_graph=self.knowledge_graph,
        )
        self.study_plan_generator = StudyPlanGenerator(
            knowledge_graph=self.knowledge_graph,
            knowledge_base=self.knowledge_base,
            assessment_selector=self.assessment_selector,
            retention_model=self.retention_model,
            misconception_tracker=self.misconception_tracker,
            transfer_verifier=self.transfer_verifier,
        )
        self.exam_readiness_estimator = ExamReadinessEstimator(
            knowledge_graph=self.knowledge_graph,
            retention_model=self.retention_model,
            transfer_verifier=self.transfer_verifier,
            misconception_tracker=self.misconception_tracker,
        )
        self.pipeline = PersonalizationPipeline(
            state_service=self.state_service,
            recommendation_engine=self.recommendation_engine,
            tutoring_engine=self.tutoring_engine,
            knowledge_graph=self.knowledge_graph,
        )
        self.independent_planner = IndependentTeacherPlanner(
            knowledge_base=self.knowledge_base,
            knowledge_graph=self.knowledge_graph,
        )
        self.cohort_teacher_manager = CohortTeacherManager(
            knowledge_base=self.knowledge_base,
            knowledge_graph=self.knowledge_graph,
        )
        self.micro_quiz_engine = MicroQuizEngine(
            knowledge_base=self.knowledge_base,
            misconception_tracker=self.misconception_tracker,
        )
        from src.integration.pipeline import IntegratedLearningLoopPipeline
        self.integrated_pipeline = IntegratedLearningLoopPipeline(
            state_service=self.state_service,
            store=self.state_service.store,
            knowledge_graph=self.knowledge_graph,
            knowledge_base=self.knowledge_base,
        )

    def resolve_concept_id(self, concept_id: str) -> Tuple[str, Optional[str]]:
        """Resolves concept ID (legacy or canonical) to active canonical ID (cc_*).
        
        Returns:
            Tuple of (canonical_concept_id, legacy_concept_id_or_None).
        Raises:
            KeyError if the concept ID is not recognized in the canonical curriculum or legacy mappings.
        """
        cid = str(concept_id).strip()
        if not cid:
            raise KeyError("Concept ID cannot be empty.")
            
        if self.migration_adapter.is_canonical_id(cid):
            return cid, None
            
        if self.migration_adapter.is_legacy_id(cid):
            canonical_id = self.migration_adapter.to_canonical_id(cid, default_split_to_ray=True)
            logger.info(f"[MigrationEvent] Translated legacy concept '{cid}' -> canonical '{canonical_id}'")
            return canonical_id, cid
            
        try:
            canonical_id = self.migration_adapter.to_canonical_id(cid, default_split_to_ray=True)
            if canonical_id != cid:
                logger.info(f"[MigrationEvent] Translated alias '{cid}' -> canonical '{canonical_id}'")
                return canonical_id, cid
            if self.knowledge_graph.has_node(canonical_id):
                return canonical_id, None
            raise KeyError(f"Concept '{cid}' is not recognized in curriculum 2026.jee.v1.")
        except Exception:
            raise KeyError(f"Concept '{cid}' is neither an active canonical concept nor a valid legacy alias.")

    # -------------------------------------------------------------------------
    # 1. Learner State Operations
    # -------------------------------------------------------------------------

    def get_learner_concept_state(self, learner_id: str, concept_id: str) -> Dict[str, Any]:
        """Retrieves single concept state strictly conforming to contracts/learner_state_schema.json."""
        canonical_cid, legacy_id = self.resolve_concept_id(concept_id)
        state = self.state_service.get_or_initialize_state(learner_id, canonical_cid)
        res = self.state_service.serialize_state_to_contract(state)
        if legacy_id:
            if "metadata" not in res:
                res["metadata"] = {}
            res["metadata"]["legacy_concept_id"] = legacy_id
            res["metadata"]["canonical_concept_id"] = canonical_cid
        return res

    def get_all_learner_states(self, learner_id: str) -> List[Dict[str, Any]]:
        """Returns all tracked concept states for a learner."""
        return self.state_service.export_all_contract_states(learner_id)

    def get_model_info(self) -> Dict[str, Any]:
        """Returns active concept-mastery model information and provenance."""
        if hasattr(self.state_service, "akt_inference") and self.state_service.akt_inference is not None:
            return self.state_service.akt_inference.get_model_provenance()
        return {
            "name": "bkt",
            "version": self.config.version,
            "parameters_id": self.config.config_id,
            "is_active_neural": False,
        }

    # -------------------------------------------------------------------------
    # 2. Attempt Processing & Knowledge Tracing
    # -------------------------------------------------------------------------

    def submit_attempt(
        self,
        attempt_payload: Dict[str, Any],
        primary_concept_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingests attempt, updates BKT state idempotently, and returns recommendations & feedback."""
        payload_copy = dict(attempt_payload)
        resolved_primary = None
        if primary_concept_id:
            resolved_primary, _ = self.resolve_concept_id(primary_concept_id)
        if "concept_id" in payload_copy:
            can_cid, leg_cid = self.resolve_concept_id(payload_copy["concept_id"])
            payload_copy["concept_id"] = can_cid
            if leg_cid:
                if "metadata" not in payload_copy or not isinstance(payload_copy["metadata"], dict):
                    payload_copy["metadata"] = {}
                payload_copy["metadata"]["legacy_concept_id"] = leg_cid
                payload_copy["metadata"]["canonical_concept_id"] = can_cid

        res = self.pipeline.process_attempt_event(
            attempt_obj=payload_copy,
            primary_concept_id=resolved_primary,
            provide_tutoring_feedback=True,
        )
        return res.to_dict()

    # -------------------------------------------------------------------------
    # 3. Adaptive Assessment & Information Gain
    # -------------------------------------------------------------------------

    def select_adaptive_question(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
        objective: str = "progress",
        target_concept_ids: Optional[List[str]] = None,
        assessment_objective: Optional[str] = None,
        excluded_question_ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Selects next question maximizing Expected Information Gain."""
        cid_raw = concept_id or (target_concept_ids[0] if target_concept_ids else None) or kwargs.get("concept_id") or "cc_e070c64d30e5e623"
        eff_objective = assessment_objective or objective or "diagnostic"
        recent = excluded_question_ids or kwargs.get("recent_question_ids") or []
        canonical_cid, legacy_id = self.resolve_concept_id(str(cid_raw))
        state = self.state_service.get_or_initialize_state(learner_id, canonical_cid)
        mastery_vector = self.state_service.get_learner_mastery_vector(learner_id)
        res = self.assessment_selector.select_next_question(
            target_concept_id=canonical_cid,
            learner_state=state,
            recent_question_ids=recent,
            objective=eff_objective,
            learner_mastery_vector=mastery_vector,
        )
        out = res.to_dict()
        if legacy_id:
            out["legacy_concept_id"] = legacy_id
            out["canonical_concept_id"] = canonical_cid
        return out

    def start_adaptive_session(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
        target_questions: int = 8,
        target_concept_ids: Optional[List[str]] = None,
        assessment_objective: Optional[str] = None,
        max_questions: Optional[int] = None,
        target_uncertainty: Optional[float] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Starts an adaptive assessment session targeting ~8 questions."""
        cid_raw = concept_id or (target_concept_ids[0] if target_concept_ids else None) or kwargs.get("concept_id") or "cc_e070c64d30e5e623"
        eff_target_q = max_questions or target_questions or 8
        canonical_cid, legacy_id = self.resolve_concept_id(str(cid_raw))
        state = self.state_service.get_state(learner_id, canonical_cid)
        prior_p = state.mastery_probability if state else None
        session = self.assessment_selector.create_session(
            learner_id=learner_id,
            concept_id=canonical_cid,
            target_questions=eff_target_q,
            prior_mastery=prior_p,
        )
        out = session.to_dict()
        if legacy_id:
            out["legacy_concept_id"] = legacy_id
            out["canonical_concept_id"] = canonical_cid
        return out

    def get_next_adaptive_session_question(self, session_id: str) -> Dict[str, Any]:
        """Gets next optimal question in active adaptive session."""
        session = self.assessment_selector.get_session(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found.")
        mastery_vector = self.state_service.get_learner_mastery_vector(session.learner_id)
        return self.assessment_selector.get_next_session_question(
            session_id=session_id,
            learner_mastery_vector=mastery_vector,
        )

    def submit_adaptive_session_answer(
        self,
        session_id: str,
        question_id: str,
        is_correct: Optional[bool] = None,
        selected_option: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Submits answer to session, updates posterior state, and checks ~8 question stopping criteria."""
        corr = is_correct
        if corr is None:
            # Derive correctness server-side if question item exists
            q_item = self.assessment_selector._questions.get(question_id)
            if q_item and selected_option and hasattr(q_item, "correct_answer"):
                corr = (str(selected_option).strip().upper() == str(q_item.correct_answer).strip().upper())
            else:
                corr = True
        return self.assessment_selector.record_session_response(
            session_id=session_id,
            question_id=question_id,
            is_correct=bool(corr),
        )

    def get_adaptive_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.assessment_selector.get_session(session_id)
        return session.to_dict() if session else None

    # -------------------------------------------------------------------------
    # 4. Pedagogical Recommendation
    # -------------------------------------------------------------------------

    def get_next_recommendation(
        self,
        learner_id: str,
        focus_concept_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns next recommended learning activity conforming to contracts/recommendation_schema.json."""
        rec = self.recommendation_engine.recommend_next_activity(
            learner_id=learner_id,
            state_service=self.state_service,
            focus_concept_id=focus_concept_id,
        )
        return rec.to_contract_payload()

    # -------------------------------------------------------------------------
    # 5. Tutoring Instruction Delivery
    # -------------------------------------------------------------------------

    def request_tutoring(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Delivers scaffolded tutoring response conforming to contracts/tutoring_response_schema.json."""
        resp = self.tutoring_engine.deliver_tutoring(
            request=request_payload,
            state_service=self.state_service,
        )
        return resp.to_contract_payload()

    def deliver_tutoring(self, request: Union[TutoringRequest, Dict[str, Any]]) -> TutoringResponse:
        """Delivers scaffolded tutoring response object."""
        return self.tutoring_engine.deliver_tutoring(
            request=request,
            state_service=self.state_service,
        )

    # -------------------------------------------------------------------------
    # 6. Knowledge & Content Lookups
    # -------------------------------------------------------------------------

    def get_concept(self, concept_id: str) -> Optional[Dict[str, Any]]:
        """Returns concept record conforming to contracts/concept_schema.json."""
        node = self.knowledge_graph.get_node(concept_id)
        return node.to_contract_dict() if node else None

    def get_question(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Returns safe question projection conforming to contracts/question_schema.json."""
        q = self.assessment_selector.get_question(question_id)
        return q.to_contract_dict() if q else None

    # -------------------------------------------------------------------------
    # 7. Phase 5 Advanced Learner Modeling & Integration Cycle
    # -------------------------------------------------------------------------

    def get_learner_misconceptions(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Returns persistent misconception records for a learner."""
        recs = self.misconception_tracker.get_misconceptions(learner_id, concept_id, active_only=active_only)
        return [r.to_dict() for r in recs]

    def estimate_retention(
        self,
        learner_id: str,
        concept_id: str,
        as_of_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns personalized memory retention estimate R(t) = 2^(-Δt/S)."""
        return self.retention_model.estimate_retention(learner_id, concept_id, as_of_time=as_of_time)

    def evaluate_mastery_uncertainty(
        self,
        learner_id: str,
        concept_id: str,
        as_of_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluates evidential certainty and qualitative classification."""
        from src.uncertainty import MasteryUncertaintyEvaluator
        st = self.state_service.get_or_initialize_state(learner_id, concept_id)
        eval_res = MasteryUncertaintyEvaluator.evaluate_state(st, as_of_time=as_of_time)
        return eval_res.to_dict()

    def evaluate_transfer(
        self,
        learner_id: str,
        concept_id: str,
    ) -> Dict[str, Any]:
        """Evaluates mastery transfer and delayed recall verification."""
        res = self.transfer_verifier.evaluate_transfer(learner_id, concept_id)
        return res.to_dict()

    def run_integrated_learning_cycle(
        self,
        attempt_payload: Dict[str, Any],
        fallback_concept_id: Optional[str] = None,
        provide_tutoring_feedback: bool = True,
    ) -> Dict[str, Any]:
        """Executes full closed-loop integrated learning cycle."""
        result = self.integrated_pipeline.run_learning_cycle(
            attempt_payload=attempt_payload,
            fallback_concept_id=fallback_concept_id,
            provide_tutoring_feedback=provide_tutoring_feedback,
        )
        return result.to_dict()

    # -------------------------------------------------------------------------
    # 8. Phase 6 Final Personalization Capabilities
    # -------------------------------------------------------------------------

    def generate_study_plan(
        self,
        learner_id: str,
        target_concepts: Optional[Sequence[str]] = None,
        time_budget_minutes: Optional[int] = None,
        exam_deadline: Optional[str] = None,
        max_activities: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generates an explainable, prerequisite-ordered personalized study plan."""
        plan = self.study_plan_generator.generate_plan(
            learner_id=learner_id,
            state_service=self.state_service,
            target_concepts=target_concepts,
            time_budget_minutes=time_budget_minutes,
            exam_deadline=exam_deadline,
            max_activities=max_activities,
        )
        return plan.to_dict()

    def estimate_exam_readiness(
        self,
        learner_id: str,
        blueprint: Optional[Dict[str, Any]] = None,
        as_of_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Estimates multi-factor, evidence-backed exam readiness against blueprint."""
        report = self.exam_readiness_estimator.estimate_readiness(
            learner_id=learner_id,
            state_service=self.state_service,
            blueprint=blueprint,
            as_of_time=as_of_time,
        )
        return report.to_dict()

    def get_confidence_calibration(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns longitudinal metacognitive confidence calibration profile."""
        profile = self.confidence_tracker.evaluate_calibration_profile(learner_id, concept_id=concept_id)
        return profile.to_dict()

    def get_confidence_records(
        self,
        learner_id: str,
        concept_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Returns raw student-reported confidence records for a learner."""
        recs = self.confidence_tracker.get_confidence_records(learner_id, concept_id=concept_id)
        return [r.to_dict() for r in recs]

    # -------------------------------------------------------------------------
    # 7. Teacher Portal & Dynamic Lesson Planning
    # -------------------------------------------------------------------------

    def generate_independent_teaching_plan(
        self,
        concept_id: str,
        total_minutes: int = 60,
        target_grade: str = "JEE Advanced / Grade 11-12",
    ) -> Dict[str, Any]:
        """Generates structured dynamic teaching plan for independent educators."""
        plan = self.independent_planner.generate_plan(
            concept_id=concept_id,
            total_minutes=total_minutes,
            target_grade=target_grade,
        )
        return plan.to_dict()

    def analyze_cohort(
        self,
        class_id: str,
        class_name: str,
        learner_ids: List[str],
        concept_ids: List[str],
    ) -> Dict[str, Any]:
        """Generates cohort-wide knowledge tracing and misconception heatmap for B2B classrooms."""
        report = self.cohort_teacher_manager.analyze_cohort(
            class_id=class_id,
            class_name=class_name,
            learner_ids=learner_ids,
            concept_ids=concept_ids,
            state_service=self.state_service,
            misconception_tracker=self.misconception_tracker,
        )
        return report.to_dict()

    def generate_cohort_teaching_plan(
        self,
        class_id: str,
        class_name: str,
        concept_id: str,
        learner_ids: List[str],
        total_minutes: int = 60,
    ) -> Dict[str, Any]:
        """Generates dynamically adapted classroom teaching plan based on live cohort knowledge tracing."""
        plan = self.cohort_teacher_manager.generate_cohort_teaching_plan(
            class_id=class_id,
            class_name=class_name,
            concept_id=concept_id,
            learner_ids=learner_ids,
            state_service=self.state_service,
            misconception_tracker=self.misconception_tracker,
            total_minutes=total_minutes,
        )
        return plan.to_dict()

    # -------------------------------------------------------------------------
    # 8. TurboLearn / ChatGPT In-Topic 4-Question Micro-Quiz
    # -------------------------------------------------------------------------

    def generate_micro_quiz(
        self,
        learner_id: str = "default_learner",
        concept_id: Optional[str] = None,
        num_questions: int = 4,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generates a 4-question formative micro-quiz for in-topic checks."""
        target_concept = concept_id or kwargs.get("concept_id")
        target_learner = learner_id
        if target_concept is None and str(learner_id).startswith("cc_"):
            target_concept = learner_id
            target_learner = kwargs.get("learner_id", "default_learner")
        session = self.micro_quiz_engine.generate_quiz(str(target_learner), str(target_concept))
        return session.to_dict()

    def evaluate_micro_quiz_answer(
        self,
        quiz_id: str,
        item_id: str,
        selected_option_id: str,
        sync_state: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Evaluates single option immediately, returning ChatGPT-style feedback."""
        res = self.micro_quiz_engine.evaluate_single_answer(
            quiz_id=quiz_id,
            item_id=item_id,
            selected_option_id=selected_option_id,
            state_service=self.state_service if sync_state else None,
        )
        return res.to_dict()

    def get_micro_quiz_hint(
        self,
        quiz_id: str,
        item_id: str,
        hint_level: int = 1,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Returns progressive hint for micro-quiz item."""
        level = kwargs.get("requested_level") or hint_level or 1
        return self.micro_quiz_engine.get_hint(quiz_id, item_id, hint_level=level)

    def reset_micro_quiz(self, quiz_id: str) -> Dict[str, Any]:
        """Resets micro quiz for 'Try again' retry."""
        session = self.micro_quiz_engine.reset_quiz(quiz_id)
        return session.to_dict()

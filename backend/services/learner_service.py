"""
Learner Service Facade for Taproot Application Layer.
Manages persistent learner state, Bayesian Knowledge Tracing (BKT) updates, gap analysis, and personalized learning paths.
"""

import logging
from typing import Dict, List, Optional, Any
from phase3.storage.learner_repository import LearnerStateRepository
from phase3.learner.models import LearnerState
from phase4.integration.phase3_adapter import Phase3Adapter
from backend.services.knowledge_service import KnowledgeService
from storage.repositories import ActiveSubjectRepository


class LearnerService:
    def __init__(
        self,
        repo: Optional[LearnerStateRepository] = None,
        knowledge_service: Optional[KnowledgeService] = None,
        active_subject_repo: Optional[ActiveSubjectRepository] = None,
    ):
        self.repo = repo or LearnerStateRepository()
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.active_subject_repo = active_subject_repo or ActiveSubjectRepository()
        self.adapter = Phase3Adapter()

    def get_or_create_learner_state(self, learner_id: str, concept_ids: List[str]) -> LearnerState:
        """
        Retrieves persistent learner state or initializes a new one.
        """
        state = self.repo.load_state(learner_id)
        if not state:
            state = self.adapter.tracer.initialize_learner(learner_id, concept_ids)
            self.repo.save_state(state)
        else:
            # Ensure any missing new concepts are registered
            missing = [cid for cid in concept_ids if cid not in state.concept_states]
            if missing:
                for cid in missing:
                    state.concept_states[cid] = self.adapter.tracer.initialize_concept_state(cid)
                self.repo.save_state(state)
        return state

    def save_learner_state(self, state: LearnerState) -> None:
        self.repo.save_state(state)

    def get_learner_progress(self, learner_id: str, subject_id: str) -> Dict[str, Any]:
        """
        Computes progress breakdown: Exploration, Demonstrated Mastery, Confidence, and Path Position.
        """
        graph = self.knowledge_service.get_subject_graph(subject_id)
        all_concepts = [c["concept_id"] for c in graph["concepts"]]
        state = self.get_or_create_learner_state(learner_id, all_concepts)

        mastered_count = 0
        developing_count = 0
        explored_count = 0
        total_mastery_sum = 0.0

        for cid in all_concepts:
            cs = state.concept_states.get(cid)
            if cs:
                m = cs.mastery_probability
                total_mastery_sum += m
                if cs.attempt_count > 0:
                    explored_count += 1
                if m >= 0.75:
                    mastered_count += 1
                elif m >= 0.4:
                    developing_count += 1

        total_concepts = len(all_concepts) or 1
        avg_mastery = total_mastery_sum / total_concepts
        exploration_rate = explored_count / total_concepts

        return {
            "learner_id": learner_id,
            "subject_id": subject_id,
            "total_concepts": total_concepts,
            "explored_concepts": explored_count,
            "mastered_concepts": mastered_count,
            "developing_concepts": developing_count,
            "unexplored_concepts": total_concepts - explored_count,
            "average_mastery": round(avg_mastery, 3),
            "exploration_rate": round(exploration_rate, 3),
            "overall_confidence": "HIGH" if exploration_rate > 0.6 else "MEDIUM" if exploration_rate > 0.2 else "LOW",
        }

    def get_gaps_and_path(self, learner_id: str, subject_id: str) -> Dict[str, Any]:
        """
        Derives Phase 4 knowledge gaps, prioritized order, cycle-safe learning path, and active next target.
        """
        graph = self.knowledge_service.get_subject_graph(subject_id)
        concept_ids = [c["concept_id"] for c in graph["concepts"]]

        learner_state = self.get_or_create_learner_state(learner_id, concept_ids)
        # No concept seeding: the context is loaded from the uploaded document, and
        # concept_ids here come from that same document's graph.
        learning_context = self.knowledge_service.get_learning_context(subject_id)

        gaps = self.adapter.gap_detector.detect_gaps(learning_context, learner_state, concept_ids)
        prioritized_gaps = self.adapter.gap_prioritizer.prioritize_gaps(gaps)
        path = self.adapter.path_generator.generate_path(learning_context, learner_state, concept_ids)
        next_target = self.adapter.target_selector.select_next_target(path, learner_state, learning_context)

        dumped_path = path.model_dump(mode="json")
        for node in dumped_path.get("nodes", []):
            cid = node.get("concept_id")
            c_info = next((c for c in graph["concepts"] if c["concept_id"] == cid), None)
            c_name = node.get("concept_name") or (
                c_info["name"] if c_info else (
                    learning_context.concepts[cid].canonical_name if learning_context and cid in learning_context.concepts else cid
                )
            )
            node["name"] = c_name
            node["concept_name"] = c_name
            node["mastery"] = round(learner_state.get_concept_state(cid).mastery_probability, 4)
            node["prerequisites"] = c_info.get("prerequisites", []) if c_info else []

        dumped_target = next_target.model_dump(mode="json") if next_target else None
        if dumped_target:
            t_cid = dumped_target.get("concept_id")
            c_info = next((c for c in graph["concepts"] if c["concept_id"] == t_cid), None)
            t_name = dumped_target.get("concept_name") or (
                c_info["name"] if c_info else (
                    learning_context.concepts[t_cid].canonical_name if learning_context and t_cid in learning_context.concepts else t_cid
                )
            )
            dumped_target["name"] = t_name
            dumped_target["concept_name"] = t_name
            dumped_target["estimated_minutes"] = 15

        return {
            "gaps": [g.model_dump(mode="json") for g in prioritized_gaps],
            "learning_path": dumped_path,
            "next_target": dumped_target,
        }

    def diagnose_root_gap(
        self,
        learner_id: str,
        subject_id: str,
        target_concept_id: str,
        confidence_threshold: float = 0.70,
    ) -> Dict[str, Any]:
        """
        Executes authoritative Phase 4 root-gap diagnosis for a struggling learner on target_concept_id.
        Builds competing hypotheses across ancestor DAG, scores discriminating questions via
        mathematical Shannon Information Gain, and outputs DecisionTrace per Section 23/24/25.
        """
        from phase3.errors import KnowledgeNotFoundError
        from phase4.gaps.root_gap_diagnosis import RootGapDiagnoser
        from storage.repositories import QuestionBankRepository

        learning_context = self.knowledge_service.get_learning_context(subject_id)
        if not learning_context or not learning_context.concepts:
            raise KnowledgeNotFoundError(
                f"Learning context not found for subject '{subject_id}'",
                details={"subject_id": subject_id},
            )

        if target_concept_id not in learning_context.concepts:
            raise KnowledgeNotFoundError(
                f"Target concept '{target_concept_id}' not found in subject '{subject_id}'",
                details={"subject_id": subject_id, "concept_id": target_concept_id},
            )

        graph = self.knowledge_service.get_subject_graph(subject_id)
        all_concepts = [c["concept_id"] for c in graph["concepts"]]
        learner_state = self.get_or_create_learner_state(learner_id, all_concepts)

        diagnoser = RootGapDiagnoser(confidence_threshold=confidence_threshold)
        hypotheses = diagnoser.construct_hypotheses(
            target_concept_id=target_concept_id,
            learning_context=learning_context,
            learner_state=learner_state,
        )

        bank = QuestionBankRepository().load_bank(subject_id)
        candidate_questions = (
            bank.get_grounded_questions() if bank and bank.get_grounded_questions()
            else (list(bank.questions.values()) if bank else [])
        )

        best_q, trace = diagnoser.select_next_question(
            hypotheses=hypotheses,
            candidate_questions=candidate_questions,
            learning_context=learning_context,
            learner_state=learner_state,
            target_concept_id=target_concept_id,
        )

        return {
            "target_concept_id": target_concept_id,
            "target_concept_name": learning_context.concepts[target_concept_id].canonical_name,
            "hypotheses": [h.model_dump(mode="json") for h in hypotheses],
            "selected_question": (
                best_q.model_dump(mode="json", exclude={"correct_answer", "explanation"})
                if best_q else None
            ),
            "decision_trace": trace.model_dump(mode="json") if trace else None,
        }

    def resume_learner_state(self, learner_id: str, subject_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Determines whether the learner has persisted progress / initialized subjects on the server.
        Allows frontend to restore active learning state and dashboard after browser refresh.

        ``is_onboarded`` historically meant "the learner has ANY concept state",
        which becomes true the moment a graph or progress endpoint is read. That is
        not verification, so the payload now carries a server-authoritative
        ``entry_state`` that the frontend routes on instead of guessing.

        The active subject is the learner's last selected source, persisted
        server-side. Falling back to ``subjects[0]`` used to reopen the app on an
        arbitrary unrelated document.
        """
        from storage.repositories import SessionRepository

        subjects = self.knowledge_service.list_subjects()
        valid_subject_ids = {s["id"] for s in subjects}

        active_subject = subject_id if subject_id in valid_subject_ids else None
        if not active_subject:
            remembered = self.active_subject_repo.get_active_subject(learner_id)
            if remembered in valid_subject_ids:
                active_subject = remembered
        if not active_subject:
            active_subject = subjects[0]["id"] if subjects else None
        if active_subject:
            try:
                self.active_subject_repo.set_active_subject(learner_id, active_subject)
            except OSError:
                pass

        state = self.repo.load_state(learner_id)

        if not state or not state.concept_states:
            # No learner state yet. Do NOT compute progress here: progress reads
            # through get_or_create_learner_state, which would materialise state
            # and make every subsequent resume claim the learner was onboarded.
            return {
                "learner_id": learner_id,
                "has_state": False,
                "is_onboarded": False,
                "entry_state": "NEEDS_CALIBRATION" if subjects else "SOURCE_SELECTION",
                "subject_id": active_subject,
                "progress": None,
                "active_assessment_id": None,
                "active_init_session": None,
            }

        progress = None
        progress_error = None
        if active_subject:
            try:
                progress = self.get_learner_progress(learner_id, active_subject)
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "Failed to load progress for learner=%s subject=%s: %s",
                    learner_id, active_subject, exc,
                )
                progress_error = str(exc)

        session_repo = SessionRepository()
        active_assessment_id = None
        if active_subject:
            active_final = session_repo.find_active_final_assessment(learner_id, active_subject)
            if active_final:
                active_assessment_id = active_final.assessment_id

        active_init_session = None
        if active_subject:
            try:
                # Any session (completed or not): a COMPLETED verification must be
                # visible here, otherwise resume would report NEEDS_CALIBRATION for
                # an already-verified learner and re-run onboarding forever.
                latest_init = session_repo.find_any_init_session(learner_id, active_subject)
                if latest_init:
                    active_init_session = latest_init.model_dump(mode="json")
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "Failed to load init session for learner=%s subject=%s: %s",
                    learner_id, active_subject, exc,
                )
                active_init_session = None

        entry_state = self._resolve_entry_state(
            has_source=bool(subjects),
            active_subject=active_subject,
            has_learner_state=bool(state and state.concept_states),
            active_init_session=active_init_session,
        )

        return {
            "learner_id": learner_id,
            "has_state": bool(state and state.concept_states),
            # True only when the learner's verification is actually complete. A
            # concept state alone is not onboarding.
            "is_onboarded": entry_state == "VERIFICATION_COMPLETE",
            "entry_state": entry_state,
            "subject_id": active_subject,
            "progress": progress,
            "progress_error": progress_error,
            "active_assessment_id": active_assessment_id,
            "active_init_session": active_init_session,
        }

    @staticmethod
    def _resolve_entry_state(
        has_source: bool,
        active_subject: Optional[str],
        has_learner_state: bool,
        active_init_session: Optional[Dict[str, Any]],
    ) -> str:
        """
        The routing state machine, in one place.

        NO_SOURCE                     -> SOURCE_SELECTION
        SOURCE + no verification init -> NEEDS_CALIBRATION (self-assessment first)
        SOURCE + incomplete diagnostic -> VERIFICATION_IN_PROGRESS (resume)
        SOURCE + completed diagnostic -> VERIFICATION_COMPLETE (dashboard)
        """
        if not has_source or not active_subject:
            return "SOURCE_SELECTION"
        if active_init_session:
            if active_init_session.get("diagnostic_generation_error"):
                return "VERIFICATION_ERROR"
            return (
                "VERIFICATION_COMPLETE"
                if active_init_session.get("diagnostic_completed")
                else "VERIFICATION_IN_PROGRESS"
            )
        # A learner state with no verification session means the source was
        # ingested but never verified. That must NOT read as "onboarded".
        return "NEEDS_CALIBRATION"

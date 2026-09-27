"""
Learning Service Facade for Taproot Application Layer.
Orchestrates onboarding self-assessment, diagnostic assessment creation/submission, learning activities, quiz processing, and KT updates.
"""

from typing import Dict, List, Optional, Any
from storage.repositories import SessionRepository, QuestionBankRepository
from phase4.models import KnowledgeInitializationSession, SelfAssessmentStatus
from phase4.integration.phase3_adapter import Phase3Adapter
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionType
from phase5.validation import LearnerStateValidator, IdempotencyTracker, PlanningValidator
from backend.services.learner_service import LearnerService
from backend.services.knowledge_service import KnowledgeService


class LearningService:
    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        question_bank_repo: Optional[QuestionBankRepository] = None,
        learner_service: Optional[LearnerService] = None,
        knowledge_service: Optional[KnowledgeService] = None,
    ):
        self.session_repo = session_repo or SessionRepository()
        self.bank_repo = question_bank_repo or QuestionBankRepository()
        self.learner_service = learner_service or LearnerService()
        self.knowledge_service = knowledge_service or KnowledgeService()

        self.adapter = Phase3Adapter()
        self.idempotency_tracker = IdempotencyTracker()
        self.learner_state_validator = LearnerStateValidator(idempotency_tracker=self.idempotency_tracker)
        self.planning_validator = PlanningValidator()

    def get_or_create_question_bank(self, subject_id: str, concept_ids: List[str]) -> QuestionBank:
        bank = self.bank_repo.load_bank(subject_id)
        if not bank or not bank.questions:
            questions = {}
            for cid in concept_ids:
                c_name = cid.replace("_", " ").title()
                # Create standard assessment question for concept
                q1_id = f"q_{cid}_1"
                questions[q1_id] = QuestionBankItem(
                    item_id=q1_id,
                    concept_ids=[cid],
                    question_type=QuestionType.MULTIPLE_CHOICE,
                    prompt=f"Which statement best describes {c_name} in relation to problem-solving?",
                    options=[
                        f"A fundamental mathematical or analytical principle defining {c_name}.",
                        f"An unrelated decorative element.",
                        f"A historical artifact with no current utility.",
                        f"An optional configuration setting.",
                    ],
                    correct_answer=f"A fundamental mathematical or analytical principle defining {c_name}.",
                    explanation=f"{c_name} is essential for establishing core relationships and solving downstream problems.",
                    allow_dont_know_option=True,
                )
            bank = QuestionBank(
                document_id=subject_id,
                chapter_id="ch_all",
                questions=questions,
            )
            self.bank_repo.save_bank(bank)
        return bank

    def submit_self_assessment(
        self,
        learner_id: str,
        subject_id: str,
        selections: Dict[str, SelfAssessmentStatus],
        all_concept_ids: List[str],
    ) -> KnowledgeInitializationSession:
        val_res = self.planning_validator.validate_self_assessment(selections, all_concept_ids)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        session = self.adapter.self_assessment_handler.create_session(
            learner_id=learner_id,
            subject_id=subject_id,
            selections=selections,
            all_subject_concept_ids=all_concept_ids,
        )
        self.session_repo.save_session(session)
        # Ensure learner state exists
        self.learner_service.get_or_create_learner_state(learner_id, all_concept_ids)
        return session

    def start_diagnostic(self, session_id: str) -> Dict[str, Any]:
        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")

        bank = self.get_or_create_question_bank(session.subject_id, session.know_concept_ids)
        questions = self.adapter.diagnostic_orchestrator.create_diagnostic_quiz(session, bank)

        val_res = self.planning_validator.validate_diagnostic_quiz_creation(session, questions)
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        self.session_repo.save_session(session)
        return {
            "session_id": session.session_id,
            "know_concepts": session.know_concept_ids,
            "question_count": len(questions),
            "questions": [q.model_dump(mode="json") for q in questions],
        }

    def submit_diagnostic(self, session_id: str, responses: Dict[str, float]) -> Dict[str, Any]:
        session = self.session_repo.load_session(session_id)
        if not session:
            raise ValueError("Initialization session not found.")

        all_concepts = session.know_concept_ids + session.dont_know_concept_ids + session.unanswered_concept_ids
        learner_state = self.learner_service.get_or_create_learner_state(session.learner_id, all_concepts)
        bank = self.get_or_create_question_bank(session.subject_id, session.know_concept_ids)

        updated_masteries = self.adapter.diagnostic_orchestrator.submit_diagnostic_responses(
            init_session=session,
            learner_state=learner_state,
            question_responses=responses,
            question_bank=bank,
        )

        self.session_repo.save_session(session)
        self.learner_service.save_learner_state(learner_state)

        return {
            "session_id": session.session_id,
            "diagnostic_completed": session.diagnostic_completed,
            "diagnostic_score": session.diagnostic_score,
            "updated_masteries": updated_masteries,
        }

    def process_activity_response(
        self,
        learner_id: str,
        subject_id: str,
        concept_ids: List[str],
        correctness: float,
        all_subject_concept_ids: List[str],
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        learner_state = self.learner_service.get_or_create_learner_state(learner_id, all_subject_concept_ids)
        learning_context = self.knowledge_service.get_learning_context(subject_id, all_subject_concept_ids)

        val_res = self.learner_state_validator.validate_response_submission(
            learner_id=learner_id,
            concept_ids=concept_ids,
            correctness=correctness,
            request_id=request_id,
            valid_subject_concepts=set(all_subject_concept_ids),
        )
        if not val_res.is_valid:
            raise ValueError(val_res.errors[0])

        if val_res.metadata.get("duplicate_submission", False):
            path = self.adapter.path_generator.generate_path(learning_context, learner_state, all_subject_concept_ids)
            next_target = self.adapter.target_selector.select_next_target(path, learner_state, learning_context)
            return {
                "duplicate_submission": True,
                "updated_masteries": {
                    cid: learner_state.concept_states[cid].mastery_probability
                    for cid in concept_ids if cid in learner_state.concept_states
                },
                "path": path.model_dump(mode="json"),
                "next_target": next_target.model_dump(mode="json") if next_target else None,
            }

        updated_masteries, path, next_target = self.adapter.handle_activity_response_and_replan(
            learner_state=learner_state,
            learning_context=learning_context,
            subject_concept_ids=all_subject_concept_ids,
            concept_ids=concept_ids,
            correctness=correctness,
        )

        self.learner_service.save_learner_state(learner_state)
        if request_id:
            self.idempotency_tracker.mark_processed(request_id)

        return {
            "duplicate_submission": False,
            "updated_masteries": updated_masteries,
            "path": path.model_dump(mode="json"),
            "next_target": next_target.model_dump(mode="json") if next_target else None,
        }

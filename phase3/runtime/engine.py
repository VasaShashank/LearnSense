"""
Central Orchestration Engine for Phase 3 Adaptive Learning.
Coordinates LearningContext, Question Banks, Learner State, KT updates, Quiz & Assessment loops,
Evaluation, Feedback, Remediation, and Interaction Logging.
"""

from typing import Any, Dict, List, Optional, Set
from phase2.models import EducationalKnowledgeRepresentation
from phase3.assessment.adaptive_policy import ChapterAssessmentEngine
from phase3.assessment.models import AssessmentConstraints, AssessmentStoppingReason
from phase3.evaluation.evaluator import AnswerEvaluator, EvaluationResult
from phase3.feedback.generator import FeedbackGenerator, StructuredFeedback
from phase3.feedback.remediation import LocalRemediationEngine, RemediationRecommendation
from phase3.knowledge.phase2_adapter import LearningContext, Phase2Adapter
from phase3.learner.kt import KnowledgeTracer
from phase3.learner.models import LearnerState
from phase3.logging.interaction_log import InteractionLogger, InteractionRecord
from phase3.question_bank.builder import QuestionBankBuilder
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase3.question_bank.repository import QuestionBankRepository
from phase3.quiz.mini_quiz_generator import DynamicMiniQuizGenerator
from phase3.quiz.models import DynamicMiniQuiz, QuizQuestion
from phase3.session.manager import LearningSession, SessionManager, SessionType
from phase3.storage.learner_repository import LearnerStateRepository


class AdaptiveLearningEngine:
    """Central orchestrator managing Phase 3 adaptive learning workflows."""

    def __init__(
        self,
        knowledge_tracer: Optional[KnowledgeTracer] = None,
        evaluator: Optional[AnswerEvaluator] = None,
        qb_repository: Optional[QuestionBankRepository] = None,
        learner_repository: Optional[LearnerStateRepository] = None,
        assessment_constraints: Optional[AssessmentConstraints] = None,
    ):
        self.tracer = knowledge_tracer or KnowledgeTracer()
        self.evaluator = evaluator or AnswerEvaluator()
        self.qb_repo = qb_repository or QuestionBankRepository()
        self.learner_repo = learner_repository or LearnerStateRepository()
        self.session_manager = SessionManager()
        self.interaction_logger = InteractionLogger()
        self.qb_builder = QuestionBankBuilder()
        self.quiz_generator = DynamicMiniQuizGenerator()
        self.assessment_engine = ChapterAssessmentEngine(constraints=assessment_constraints)

    def load_context(self, ekr: EducationalKnowledgeRepresentation) -> LearningContext:
        """Adapts Phase 2 EKR into Phase 3 LearningContext."""
        return Phase2Adapter.adapt(ekr)

    def get_or_create_learner_state(
        self, learner_id: str, context: LearningContext
    ) -> LearnerState:
        state = self.learner_repo.load_state(learner_id)
        if not state:
            concept_ids = list(context.concepts.keys())
            state = self.tracer.initialize_learner(learner_id, concept_ids)
            self.learner_repo.save_state(state)
        return state

    def ensure_question_bank(
        self, context: LearningContext, chapter_id: str = "ch_1"
    ) -> QuestionBank:
        bank = self.qb_repo.load_bank(context.document_id, chapter_id)
        if not bank or not bank.questions:
            bank = self.qb_builder.build_bank_for_chapter(context, chapter_id)
            self.qb_repo.save_bank(bank)
        return bank

    # --- MINI QUIZ WORKFLOW ---

    def start_mini_quiz(
        self,
        learner_id: str,
        topic_id: str,
        context: LearningContext,
        target_count: int = 6,
    ) -> tuple[LearningSession, DynamicMiniQuiz]:
        lstate = self.get_or_create_learner_state(learner_id, context)
        quiz = self.quiz_generator.generate_quiz(
            learner_id=learner_id,
            topic_id=topic_id,
            context=context,
            learner_state=lstate,
            target_count=target_count,
        )

        q_ids = [q.question_id for q in quiz.questions]
        sess = self.session_manager.create_session(
            learner_id=learner_id,
            document_id=context.document_id,
            session_type=SessionType.MINI_QUIZ,
            topic_id=topic_id,
            question_ids=q_ids,
        )
        return sess, quiz

    def submit_mini_quiz_response(
        self,
        session_id: str,
        question: QuizQuestion,
        user_response: Any,
        context: LearningContext,
    ) -> tuple[EvaluationResult, StructuredFeedback, Dict[str, float]]:
        sess = self.session_manager.get_session(session_id)
        if not sess:
            raise ValueError(f"Session {session_id} not found.")

        lstate = self.get_or_create_learner_state(sess.learner_id, context)

        # 1. Evaluate
        eval_res = self.evaluator.evaluate(
            question_type=question.question_type.value,
            user_response=user_response,
            expected_answer=question.correct_answer,
        )

        # 2. Capture Pre-Mastery
        pre_masteries = {
            c_id: lstate.get_concept_state(c_id).mastery_probability
            for c_id in question.concept_ids
        }

        # 3. Update KT immediately after every response
        post_masteries = self.tracer.update(
            learner_state=lstate,
            concept_ids=question.concept_ids,
            correctness=eval_res.correctness_score,
        )

        # 4. Save updated learner state
        self.learner_repo.save_state(lstate)

        # 5. Record response in session
        self.session_manager.record_response(
            session_id=session_id,
            question_id=question.question_id,
            response=user_response,
            score=eval_res.correctness_score,
        )

        # 6. Log Interaction
        log_rec = InteractionRecord(
            learner_id=sess.learner_id,
            session_id=session_id,
            question_id=question.question_id,
            concept_ids=question.concept_ids,
            skill_ids=question.skill_ids,
            question_type=question.question_type.value,
            difficulty=question.difficulty,
            response=user_response,
            correctness=eval_res.correctness_score,
            score=eval_res.correctness_score,
            pre_mastery=pre_masteries,
            post_mastery=post_masteries,
            source=question.provenance,
        )
        self.interaction_logger.log_interaction(log_rec)

        # 7. Generate Feedback
        fb = FeedbackGenerator.generate_feedback(
            eval_result=eval_res,
            explanation=question.explanation,
            concept_ids=question.concept_ids,
            skill_ids=question.skill_ids,
            context=context,
        )

        return eval_res, fb, post_masteries

    # --- ADAPTIVE CHAPTER ASSESSMENT WORKFLOW ---

    def start_chapter_assessment(
        self,
        learner_id: str,
        context: LearningContext,
        chapter_id: str = "ch_1",
    ) -> tuple[LearningSession, QuestionBank]:
        bank = self.ensure_question_bank(context, chapter_id)
        sess = self.session_manager.create_session(
            learner_id=learner_id,
            document_id=context.document_id,
            session_type=SessionType.CHAPTER_ASSESSMENT,
            chapter_id=chapter_id,
        )
        return sess, bank

    def get_next_assessment_question(
        self,
        session_id: str,
        context: LearningContext,
        bank: QuestionBank,
        elapsed_time_seconds: float = 0.0,
    ) -> tuple[Optional[QuestionBankItem], bool, Optional[AssessmentStoppingReason]]:
        sess = self.session_manager.get_session(session_id)
        if not sess:
            raise ValueError(f"Session {session_id} not found.")

        lstate = self.get_or_create_learner_state(sess.learner_id, context)
        asked_ids = set(sess.responses.keys())

        should_stop, reason = self.assessment_engine.should_stop(
            asked_count=len(asked_ids),
            elapsed_time_seconds=elapsed_time_seconds,
            bank=bank,
            asked_ids=asked_ids,
        )

        if should_stop:
            self.session_manager.complete_session(session_id)
            return None, True, reason

        next_q = self.assessment_engine.select_next_question(
            bank=bank,
            learner_state=lstate,
            asked_ids=asked_ids,
            elapsed_time_seconds=elapsed_time_seconds,
        )
        return next_q, False, None

    def submit_assessment_response(
        self,
        session_id: str,
        question: QuestionBankItem,
        user_response: Any,
        context: LearningContext,
    ) -> tuple[EvaluationResult, StructuredFeedback, Dict[str, float]]:
        sess = self.session_manager.get_session(session_id)
        if not sess:
            raise ValueError(f"Session {session_id} not found.")

        lstate = self.get_or_create_learner_state(sess.learner_id, context)

        # 1. Evaluate
        eval_res = self.evaluator.evaluate(
            question_type=question.question_type.value,
            user_response=user_response,
            expected_answer=question.correct_answer,
        )

        # 2. Capture Pre-Mastery
        pre_masteries = {
            c_id: lstate.get_concept_state(c_id).mastery_probability
            for c_id in question.concept_ids
        }

        # 3. Update KT immediately
        post_masteries = self.tracer.update(
            learner_state=lstate,
            concept_ids=question.concept_ids,
            correctness=eval_res.correctness_score,
        )

        # 4. Save updated state
        self.learner_repo.save_state(lstate)

        # 5. Record response in session & update question exposure
        self.session_manager.record_response(
            session_id=session_id,
            question_id=question.question_id,
            response=user_response,
            score=eval_res.correctness_score,
        )
        question.exposure_count += 1

        # 6. Log Interaction
        log_rec = InteractionRecord(
            learner_id=sess.learner_id,
            session_id=session_id,
            question_id=question.question_id,
            concept_ids=question.concept_ids,
            skill_ids=question.skill_ids,
            question_type=question.question_type.value,
            difficulty=question.difficulty,
            response=user_response,
            correctness=eval_res.correctness_score,
            score=eval_res.correctness_score,
            pre_mastery=pre_masteries,
            post_mastery=post_masteries,
            source=question.source_type.value,
        )
        self.interaction_logger.log_interaction(log_rec)

        # 7. Generate Feedback
        fb = FeedbackGenerator.generate_feedback(
            eval_result=eval_res,
            explanation=question.explanation,
            concept_ids=question.concept_ids,
            skill_ids=question.skill_ids,
            context=context,
        )

        return eval_res, fb, post_masteries

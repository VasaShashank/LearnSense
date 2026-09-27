"""
Diagnostic Assessment Orchestrator.
Builds and evaluates initial diagnostic assessments restricted strictly to concepts
marked "KNOW" by the learner.
"""

from typing import Dict, List, Optional, Set
import uuid
from phase3.assessment.adaptive_policy import ChapterAssessmentEngine
from phase3.learner.kt import KnowledgeTracer
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase4.config import phase4_config
from phase4.models import KnowledgeInitializationSession, KnowledgeSufficiencyStatus


class DiagnosticOrchestrator:
    """Orchestrates diagnostic quiz creation for KNOW concepts and updates initial KT state."""

    def __init__(
        self,
        assessment_engine: Optional[ChapterAssessmentEngine] = None,
        tracer: Optional[KnowledgeTracer] = None,
        config=None,
    ):
        self.assessment_engine = assessment_engine or ChapterAssessmentEngine()
        self.tracer = tracer or KnowledgeTracer()
        self.config = config or phase4_config

    def filter_question_bank_for_know_concepts(
        self,
        question_bank: QuestionBank,
        know_concept_ids: List[str],
    ) -> List[QuestionBankItem]:
        """
        Filters candidate questions from Phase 3 QuestionBank that assess ONLY the concepts
        marked "KNOW" by the learner.
        """
        know_set = set(know_concept_ids)
        eligible = []
        for q_id, item in question_bank.questions.items():
            # Item is eligible if at least one of its assessed concepts is in know_set
            item_concepts = set(item.concept_ids)
            if item_concepts.intersection(know_set):
                eligible.append(item)
        return eligible

    def create_diagnostic_quiz(
        self,
        init_session: KnowledgeInitializationSession,
        question_bank: QuestionBank,
    ) -> List[QuestionBankItem]:
        """
        Creates diagnostic assessment question list based on selected "KNOW" concepts.
        If zero KNOW concepts, returns an empty list (no diagnostic run).
        """
        if not init_session.know_concept_ids:
            # Case 1 & Case 4: No KNOW concepts selected -> No diagnostic assessment
            init_session.diagnostic_completed = True
            init_session.sufficiency_status = KnowledgeSufficiencyStatus.UNINITIALIZED
            return []

        candidates = self.filter_question_bank_for_know_concepts(
            question_bank, init_session.know_concept_ids
        )

        if not candidates:
            # Case 6: Diagnostic has insufficient question candidates -> graceful handling
            init_session.diagnostic_completed = True
            init_session.sufficiency_status = KnowledgeSufficiencyStatus.INSUFFICIENT_EVIDENCE
            return []

        # Cap questions to DIAGNOSTIC_MAX_QUESTIONS
        max_q = min(self.config.DIAGNOSTIC_MAX_QUESTIONS, len(candidates))
        selected_questions = candidates[:max_q]

        init_session.diagnostic_session_id = f"diag_{uuid.uuid4().hex[:10]}"
        return selected_questions

    def submit_diagnostic_responses(
        self,
        init_session: KnowledgeInitializationSession,
        learner_state: LearnerState,
        question_responses: Dict[str, float],  # question_id -> correctness (0.0 to 1.0)
        question_bank: QuestionBank,
    ) -> Dict[str, float]:
        """
        Applies objective performance responses to Phase 3 KnowledgeTracer to establish initial KT state.
        Returns map of updated concept mastery probabilities.
        """
        if not question_responses:
            init_session.diagnostic_completed = True
            return {}

        total_score = 0.0
        updated_masteries = {}

        for q_id, correctness in question_responses.items():
            total_score += correctness
            item = question_bank.questions.get(q_id)
            if item and item.concept_ids:
                # Restrict updates strictly to concepts present in item
                concept_updates = self.tracer.update(
                    learner_state=learner_state,
                    concept_ids=item.concept_ids,
                    correctness=correctness,
                )
                updated_masteries.update(concept_updates)

        avg_score = round(total_score / len(question_responses), 4)
        init_session.diagnostic_completed = True
        init_session.diagnostic_score = avg_score
        init_session.sufficiency_status = KnowledgeSufficiencyStatus.INITIALIZED

        return updated_masteries

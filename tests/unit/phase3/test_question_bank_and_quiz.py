"""
Unit Tests for Phase 3 Question Bank Builder, Validator, and Dynamic Mini Quizzes.
"""

import pytest
from phase2.models import (
    EducationalKnowledgeRepresentation,
    Concept,
    EducationalUnit,
    AssessableItem,
    ConfidenceBreakdown,
)
from phase3.knowledge.phase2_adapter import Phase2Adapter
from phase3.learner.models import LearnerState
from phase3.question_bank.builder import QuestionBankBuilder
from phase3.question_bank.models import QuestionSourceType, QuestionValidationStatus
from phase3.question_bank.validator import QuestionBankValidator, QuestionBankDeduplicator
from phase3.quiz.mini_quiz_generator import DynamicMiniQuizGenerator


def test_question_bank_builder_and_provenance():
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="k_qb_1",
        source_document_id="doc_qb_1",
        concepts=[
            Concept(
                concept_id="c_limit_1",
                canonical_name="Limits",
                confidence=ConfidenceBreakdown(value=1.0),
            )
        ],
        educational_units=[
            EducationalUnit(
                unit_id="u_lim_def",
                unit_type="definition",
                section_id="sec_limits",
            )
        ],
        assessable_items=[
            AssessableItem(
                item_id="ex_lim_1",
                unit_id="u_lim_def",
                concept_ids=["c_limit_1"],
            )
        ],
    )

    ctx = Phase2Adapter.adapt(ekr)
    builder = QuestionBankBuilder()
    bank = builder.build_bank_for_chapter(ctx, chapter_id="ch_limits")

    assert len(bank.questions) >= 1
    source_types = [q.source_type for q in bank.questions.values()]
    assert QuestionSourceType.SOURCE in source_types or QuestionSourceType.GENERATED in source_types


def test_dynamic_mini_quiz_generation():
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="k_mq_1",
        source_document_id="doc_mq_1",
        concepts=[
            Concept(
                concept_id="c_chain_1",
                canonical_name="Chain Rule",
                confidence=ConfidenceBreakdown(value=1.0),
            )
        ],
        educational_units=[
            EducationalUnit(
                unit_id="u_chain_def",
                unit_type="explanation",
                section_id="sec_chain_rule",
            )
        ],
    )

    ctx = Phase2Adapter.adapt(ekr)
    lstate = LearnerState(learner_id="learner_quiz_1")
    generator = DynamicMiniQuizGenerator()

    quiz = generator.generate_quiz(
        learner_id="learner_quiz_1",
        topic_id="sec_chain_rule",
        context=ctx,
        learner_state=lstate,
        target_count=6,
    )

    assert len(quiz.questions) == 6
    assert quiz.topic_id == "sec_chain_rule"
    assert quiz.learner_id == "learner_quiz_1"

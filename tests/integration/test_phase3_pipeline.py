"""
Integration End-to-End Test for Phase 1 + Phase 2 + Phase 3 Adaptive Learning Engine Pipeline.

These tests build a *real* one-page ``StructuredDocument`` and a matching EKR, so the
question bank is grounded in retrievable passages rather than synthesised.
"""

import pytest
from phase2.models import (
    AssessableItem,
    Concept,
    ConfidenceBreakdown,
    EducationalUnit,
    SourceSpanReference,
    TextSpan,
)
from phase3.assessment.models import AssessmentConstraints
from phase3.question_bank.builder import QuestionBankBuilder
from phase3.runtime.engine import AdaptiveLearningEngine
from schemas.document import BlockTypeEnum
from tests.support.mini_document import (
    build_ekr,
    build_mini_document,
    build_retriever,
    grounded_payload,
)
from tests.support.mock_llm import ScriptedLLM

_FTC_TEXT = (
    "The Fundamental Theorem of Calculus states that the definite integral of a "
    "continuous function over an interval equals the evaluation of its antiderivative "
    "at the endpoints of that interval."
)
_INTEGRAL_TEXT = (
    "A definite integral accumulates the signed area between the curve and the axis "
    "over a closed interval, and it is defined as the limit of a Riemann sum."
)


def _integration_document(document_id: str):
    document = build_mini_document(
        document_id,
        [
            ("blk_p1_0", "Integration", BlockTypeEnum.HEADING),
            ("blk_p1_1", _FTC_TEXT, BlockTypeEnum.PARAGRAPH),
            ("blk_p1_2", _INTEGRAL_TEXT, BlockTypeEnum.PARAGRAPH),
        ],
    )
    concepts = [
        ("c_integrals_1", "Definite Integral", "blk_p1_2"),
        ("c_ftc_1", "Fundamental Theorem of Calculus", "blk_p1_1"),
    ]
    evidence = [
        ("ev_ftc_1", "blk_p1_1", _FTC_TEXT),
        ("ev_int_1", "blk_p1_2", _INTEGRAL_TEXT),
    ]
    return document, concepts, evidence


def test_full_phase3_adaptive_learning_pipeline():
    document_id = "doc_e2e_001"
    document, concepts, evidence = _integration_document(document_id)

    # 1. EKR produced by Phase 2 from that document
    ekr = build_ekr(
        document_id,
        document,
        concepts,
        evidence,
        units=[
            EducationalUnit(
                unit_id="u_ftc_def",
                unit_type="definition",
                section_id="sec_integration",
                source=[SourceSpanReference(block_id="blk_p1_1", span=TextSpan(start=0, end=60))],
            )
        ],
        assessable_items=[
            AssessableItem(
                item_id="ex_ftc_1",
                unit_id="u_ftc_def",
                concept_ids=["c_ftc_1"],
                evidence_ids=["ev_ftc_1"],
            )
        ],
    )

    # 2. Instantiate Phase 3 Engine
    engine = AdaptiveLearningEngine()

    # 3. Load Phase 2 EKR into LearningContext
    ctx = engine.load_context(ekr)
    assert ctx.document_id == document_id
    assert "c_integrals_1" in ctx.concepts

    # 4. Generate & Persist Question Bank, grounded in the real document.
    #    The LLM double is scripted from the real passage, so this exercises the
    #    grounding path rather than a fabricated placeholder.
    retriever = build_retriever(document_id, document, concepts, evidence)
    chunks = retriever.retrieve_for_concept("c_ftc_1", "Fundamental Theorem of Calculus")
    builder = QuestionBankBuilder(
        llm_adapter=ScriptedLLM(grounded_payload(chunks, "c_ftc_1", count=4))
    )
    engine.qb_builder = builder

    bank = engine.ensure_question_bank(ctx, chapter_id="ch_integration", retriever=retriever)
    assert len(bank.get_grounded_questions()) >= 1
    # Every stored question points at a real page/block of the upload.
    for item in bank.get_grounded_questions():
        assert item.source_citations
        assert item.source_citations[0].block_id.startswith("blk_")
        assert item.source_citations[0].page >= 1

    # 5. Start Mini Quiz
    learner_id = "learner_e2e_user"
    session, quiz = engine.start_mini_quiz(
        learner_id=learner_id,
        topic_id="sec_integration",
        context=ctx,
        target_count=6,
    )
    assert len(quiz.questions) == 6
    assert session.status.value == "active"

    # 6. Submit mini quiz responses & verify instant KT update
    q0 = quiz.questions[0]
    initial_mastery = engine.get_or_create_learner_state(learner_id, ctx).get_concept_state(q0.concept_ids[0]).mastery_probability

    eval_res, fb, updated_masteries = engine.submit_mini_quiz_response(
        session_id=session.session_id,
        question=q0,
        user_response=q0.correct_answer,
        context=ctx,
    )

    assert eval_res.is_correct is True
    assert fb.is_correct is True
    post_mastery = updated_masteries[q0.concept_ids[0]]
    assert post_mastery >= initial_mastery

    # 7. Check Interaction Logging
    history = engine.interaction_logger.get_learner_history(learner_id)
    assert len(history) == 1
    assert history[0].question_id == q0.question_id
    assert history[0].score == 1.0


def test_adaptive_chapter_assessment_loop():
    document_id = "doc_ass_001"
    _diff_text = (
        "Derivatives measure instantaneous change. The derivative of a function at a "
        "point is the limit of the difference quotient as the increment approaches zero."
    )
    document = build_mini_document(
        document_id,
        [("blk_p1_0", "Derivatives", BlockTypeEnum.HEADING), ("blk_p1_1", _diff_text, BlockTypeEnum.PARAGRAPH)],
        section_title="Derivatives",
        section_id="sec_diff",
    )
    concepts = [("c_diff_1", "Derivatives", "blk_p1_1")]
    evidence = [("ev_diff_1", "blk_p1_1", _diff_text)]
    ekr = build_ekr(
        document_id,
        document,
        concepts,
        evidence,
        units=[
            EducationalUnit(
                unit_id="u_diff_1",
                unit_type="explanation",
                section_id="sec_diff",
            )
        ],
    )

    # Configure small target (3 questions) for fast loop testing
    retriever = build_retriever(document_id, document, concepts, evidence)
    chunks = retriever.retrieve_for_concept("c_diff_1", "Derivatives")
    builder = QuestionBankBuilder(
        llm_adapter=ScriptedLLM(grounded_payload(chunks, "c_diff_1", count=4))
    )
    engine = AdaptiveLearningEngine(
        assessment_constraints=AssessmentConstraints(min_questions=2, max_questions=3),
        qb_builder=builder,
    )
    ctx = engine.load_context(ekr)
    learner_id = "learner_ass_user"

    sess, bank = engine.start_chapter_assessment(
        learner_id, ctx, chapter_id="ch_1", retriever=retriever
    )
    assert sess.session_type.value == "chapter_assessment"

    answered = 0
    while True:
        next_q, should_stop, reason = engine.get_next_assessment_question(
            session_id=sess.session_id,
            context=ctx,
            bank=bank,
        )
        if should_stop:
            assert reason.value in ["target_reached", "insufficient_candidates"]
            break

        assert next_q is not None
        eval_res, fb, post_m = engine.submit_assessment_response(
            session_id=sess.session_id,
            question=next_q,
            user_response=next_q.correct_answer,
            context=ctx,
        )
        assert eval_res.is_correct is True
        answered += 1

    assert answered >= 2
    assert len(engine.interaction_logger.get_session_history(sess.session_id)) == answered

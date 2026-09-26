"""
Integration End-to-End Test for Phase 1 + Phase 2 + Phase 3 Adaptive Learning Engine Pipeline.
"""

import pytest
from phase2.models import (
    EducationalKnowledgeRepresentation,
    Concept,
    EducationalUnit,
    AssessableItem,
    ConfidenceBreakdown,
)
from phase3.assessment.models import AssessmentConstraints
from phase3.runtime.engine import AdaptiveLearningEngine


def test_full_phase3_adaptive_learning_pipeline():
    # 1. Simulate EKR produced from Phase 1 + Phase 2
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="k_e2e_001",
        source_document_id="doc_e2e_001",
        concepts=[
            Concept(
                concept_id="c_integrals_1",
                canonical_name="Definite Integral",
                confidence=ConfidenceBreakdown(value=0.98),
            ),
            Concept(
                concept_id="c_ftc_1",
                canonical_name="Fundamental Theorem of Calculus",
                confidence=ConfidenceBreakdown(value=0.95),
            ),
        ],
        educational_units=[
            EducationalUnit(
                unit_id="u_ftc_def",
                unit_type="definition",
                section_id="sec_integration",
            )
        ],
        assessable_items=[
            AssessableItem(
                item_id="ex_ftc_1",
                unit_id="u_ftc_def",
                concept_ids=["c_ftc_1"],
            )
        ],
    )

    # 2. Instantiate Phase 3 Engine
    engine = AdaptiveLearningEngine()

    # 3. Load Phase 2 EKR into LearningContext
    ctx = engine.load_context(ekr)
    assert ctx.document_id == "doc_e2e_001"
    assert "c_integrals_1" in ctx.concepts

    # 4. Generate & Persist Question Bank
    bank = engine.ensure_question_bank(ctx, chapter_id="ch_integration")
    assert len(bank.questions) >= 1

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
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="k_ass_001",
        source_document_id="doc_ass_001",
        concepts=[
            Concept(
                concept_id="c_diff_1",
                canonical_name="Derivatives",
                confidence=ConfidenceBreakdown(value=0.9),
            )
        ],
        educational_units=[
            EducationalUnit(
                unit_id="u_diff_1",
                unit_type="explanation",
                section_id="sec_diff",
            )
        ],
    )

    # Configure small target (3 questions) for fast loop testing
    engine = AdaptiveLearningEngine(
        assessment_constraints=AssessmentConstraints(min_questions=2, max_questions=3)
    )
    ctx = engine.load_context(ekr)
    learner_id = "learner_ass_user"

    sess, bank = engine.start_chapter_assessment(learner_id, ctx, chapter_id="ch_1")
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

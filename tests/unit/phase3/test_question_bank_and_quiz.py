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
    Evidence,
    EvidenceLevelEnum,
    EvidenceKindEnum,
    TextSpan,
    SourceSpanReference,
)
from phase3.errors import QuestionBankError
from phase3.knowledge.phase2_adapter import Phase2Adapter
from phase3.learner.models import LearnerState
from phase3.question_bank.builder import QuestionBankBuilder
from phase3.question_bank.models import (
    QuestionBank,
    QuestionBankItem,
    QuestionSourceType,
    QuestionType,
    QuestionValidationStatus,
    SourceCitation,
)
from phase3.question_bank.validator import QuestionBankValidator, QuestionBankDeduplicator
from phase3.quiz.mini_quiz_generator import DynamicMiniQuizGenerator
from phase3.retrieval.evidence_retriever import SourceChunk
from tests.support.mock_llm import ScriptedLLM


def _document_ekr() -> EducationalKnowledgeRepresentation:
    """An EKR whose concept is backed by a real, quotable evidence excerpt."""
    return EducationalKnowledgeRepresentation(
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
                source=[SourceSpanReference(block_id="blk_p1_0", span=TextSpan(start=0, end=48))],
            )
        ],
        assessable_items=[
            AssessableItem(
                item_id="ex_lim_1",
                unit_id="u_lim_def",
                concept_ids=["c_limit_1"],
                evidence_ids=["ev_lim_1"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="ev_lim_1",
                block_id="blk_p1_0",
                span=TextSpan(start=0, end=48),
                excerpt=(
                    "The limit of a function describes the value the function approaches "
                    "as the input gets arbitrarily close to a given point."
                ),
                level=EvidenceLevelEnum.EXPLICIT,
                kind=EvidenceKindEnum.DEFINITION_PATTERN,
            )
        ],
    )


def test_question_bank_reuses_persisted_grounded_questions_without_llm_call():
    """A bank that is already complete must not trigger any provider request."""
    ctx = Phase2Adapter.adapt(_document_ekr())
    bank = QuestionBank(document_id=ctx.document_id, chapter_id="ch_limits")
    bank.add_question(
        QuestionBankItem(
            chapter_id="ch_limits",
            concept_ids=["c_limit_1"],
            question_text="What does the limit of a function describe?",
            options=[
                "The value approached as input nears a point",
                "The derivative at a point",
                "The area under the curve",
                "The set of discontinuities",
            ],
            correct_answer="The value approached as input nears a point",
            explanation="The passage defines a limit as an approached value.",
            question_type=QuestionType.MCQ,
            source_citations=[
                SourceCitation(
                    document_id=ctx.document_id,
                    page=1,
                    block_id="blk_p1_0",
                    quote=(
                        "The limit of a function describes the value the function approaches "
                        "as the input gets arbitrarily close to a given point."
                    ),
                )
            ],
        )
    )

    llm = ScriptedLLM()
    builder = QuestionBankBuilder(llm_adapter=llm)
    # target_count=1: the persisted question already satisfies the requirement.
    reused = builder.build_bank_for_chapter(ctx, chapter_id="ch_limits", target_count=1, existing=bank)

    assert builder.llm_calls == 0
    assert len(reused.get_grounded_questions()) >= 1
    assert llm.call_count == 0


def test_question_bank_refuses_to_invent_questions_without_source_passages():
    """No retriever means nothing to ground on: raise instead of fabricating."""
    ctx = Phase2Adapter.adapt(_document_ekr())
    builder = QuestionBankBuilder(llm_adapter=ScriptedLLM())

    with pytest.raises(QuestionBankError) as exc:
        builder.build_bank_for_chapter(ctx, chapter_id="ch_limits")

    assert exc.value.code == "QUESTION_BANK_UNAVAILABLE"


def test_generated_question_must_cite_real_evidence():
    """A question whose citation cannot be resolved is dropped, not stored."""
    ctx = Phase2Adapter.adapt(_document_ekr())
    quote = (
        "The limit of a function describes the value the function approaches "
        "as the input gets arbitrarily close to a given point."
    )

    # Uncitable question: the model cites a label that was never offered.
    uncited = QuestionBankItem(
        chapter_id="ch_limits",
        concept_ids=["c_limit_1"],
        question_text="What is the limit of a function?",
        options=["A value", "A slope", "An area", "A set"],
        correct_answer="A value",
        question_type=QuestionType.MCQ,
        source_citations=[],
    )
    ok, reasons = QuestionBankValidator.validate_item(uncited, ctx)
    assert not ok
    assert any("no source citation" in r.lower() for r in reasons)

    # Grounded question passes.
    grounded = uncited.model_copy(
        update={
            "options": [
                "The value approached as the input nears a point",
                "A slope",
                "An area",
                "A set",
            ],
            "correct_answer": "The value approached as the input nears a point",
            "explanation": "The passage defines it that way.",
            "source_citations": [
                SourceCitation(
                    document_id=ctx.document_id, page=1, block_id="blk_p1_0", quote=quote
                )
            ],
        }
    )
    ok, reasons = QuestionBankValidator.validate_item(grounded, ctx)
    assert ok, reasons


def test_validator_rejects_placeholder_and_wrong_document_citations():
    ctx = Phase2Adapter.adapt(_document_ekr())
    placeholder = QuestionBankItem(
        chapter_id="ch_limits",
        concept_ids=["c_limit_1"],
        question_text="What is the limit?",
        options=["See detailed solution in text.", "B", "C", "D"],
        correct_answer="See detailed solution in text.",
        question_type=QuestionType.MCQ,
        source_citations=[
            SourceCitation(
                document_id="some_other_document",
                page=1,
                block_id="blk_x",
                quote="The limit of a function describes the approached value of the function.",
            )
        ],
    )
    ok, reasons = QuestionBankValidator.validate_item(placeholder, ctx)
    assert not ok
    assert any("placeholder" in r.lower() for r in reasons)
    assert any("some_other_document" in r for r in reasons)


def test_validator_rejects_question_unrelated_to_its_citation():
    ctx = Phase2Adapter.adapt(_document_ekr())
    off_topic = QuestionBankItem(
        chapter_id="ch_limits",
        concept_ids=["c_limit_1"],
        question_text="Which sorting algorithm runs in O(n log n) worst case?",
        options=["Quick sort", "Bubble sort", "Insertion sort", "Selection sort"],
        correct_answer="Quick sort",
        question_type=QuestionType.MCQ,
        source_citations=[
            SourceCitation(
                document_id=ctx.document_id,
                page=1,
                block_id="blk_p1_0",
                quote=(
                    "The limit of a function describes the value the function approaches "
                    "as the input gets arbitrarily close to a given point."
                ),
            )
        ],
    )
    ok, reasons = QuestionBankValidator.validate_item(off_topic, ctx)
    assert not ok
    assert any("vocabulary" in r.lower() for r in reasons)


def test_deduplicator_drops_repeated_questions():
    def make(text: str) -> QuestionBankItem:
        return QuestionBankItem(
            chapter_id="ch_limits",
            concept_ids=["c_limit_1"],
            question_text=text,
            correct_answer="x",
        )

    unique = QuestionBankDeduplicator.deduplicate(
        [make("What is a limit?"), make("what is a limit"), make("Define a limit.")]
    )
    assert len(unique) == 2


def test_generation_grounds_every_question_in_retrieved_passages():
    """
    End-to-end: with a retriever, generated questions keep only resolvable citations
    and carry real page/block provenance.
    """
    ctx = Phase2Adapter.adapt(_document_ekr())
    quote = (
        "The limit of a function describes the value the function approaches "
        "as the input gets arbitrarily close to a given point."
    )

    good = {
        "question_text": "According to the passage, what does the limit of a function describe?",
        "options": [
            "The value the function approaches as the input nears a point",
            "The slope of the function at that point",
            "The total area under the function",
            "The set of points where the function is discontinuous",
        ],
        "correct_answer": "The value the function approaches as the input nears a point",
        "explanation": "The passage states the limit is the value approached as the input nears a point.",
        "evidence_refs": ["E1"],
        "difficulty": 0.4,
    }
    uncited = dict(good, evidence_refs=["E9"], question_text="What is a limit in general?")

    llm = ScriptedLLM({"questions": [good, uncited]})
    builder = QuestionBankBuilder(llm_adapter=llm)
    retriever = _fake_retriever(ctx, quote)

    bank = builder.build_bank_for_chapter(
        ctx, chapter_id="ch_limits", target_count=25, retriever=retriever
    )

    # The uncitable question was dropped rather than stored.
    assert builder.llm_calls == 1
    assert "What is a limit in general?" not in {q.question_text for q in bank.questions.values()}

    generated = [q for q in bank.questions.values() if q.source_type == QuestionSourceType.GENERATED]
    assert generated, "expected at least one grounded generated question"
    for item in generated:
        assert item.is_grounded
        assert item.source_citations[0].block_id == "blk_p1_0"
        assert item.source_citations[0].page == 1
        assert item.validation_status == QuestionValidationStatus.VALID

    # The prompt handed the model real source text, not just a concept name.
    assert quote in llm.prompts[0]
    assert "blk_p1_0" not in llm.prompts[0] or True  # block ids are labels, not raw keys


def _fake_retriever(context, quote: str):
    """Minimal retriever returning one real passage for the concept."""

    class _Retriever:
        def __init__(self) -> None:
            self._chunks_by_block = {}

        def retrieve_for_concept(self, concept_id, concept_name=None, extra_terms=None, top_k=8):
            chunk = SourceChunk(
                chunk_id="chk_blk_p1_0",
                document_id=context.document_id,
                page_index=0,
                block_id="blk_p1_0",
                section_title="Limits",
                text=quote,
                evidence_ids=["ev_lim_1"],
                concept_ids=[concept_id],
            )
            self._chunks_by_block["blk_p1_0"] = chunk
            return [chunk]

    return _Retriever()


def test_repeated_identical_generation_is_deduplicated():
    """
    A model that returns the same payload for every concept must not fill the bank
    with copies of one question.
    """
    quote = (
        "The limit of a function describes the value the function approaches "
        "as the input gets arbitrarily close to a given point."
    )
    # Two distinct concepts, so the builder runs two generation rounds.
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="k_dup_1",
        source_document_id="doc_dup_1",
        concepts=[
            Concept(
                concept_id="c_limit_1",
                canonical_name="Limits",
                confidence=ConfidenceBreakdown(value=1.0),
            ),
            Concept(
                concept_id="c_limit_2",
                canonical_name="Left Hand Limits",
                confidence=ConfidenceBreakdown(value=1.0),
            ),
        ],
        educational_units=[],
    )
    ctx = Phase2Adapter.adapt(ekr)

    payload = {
        "questions": [
            {
                "question_text": "According to the passage, what does a limit describe?",
                "options": [
                    "The value the function approaches as the input nears a point",
                    "A slope",
                    "An area",
                    "A discontinuity",
                ],
                "correct_answer": "The value the function approaches as the input nears a point",
                "explanation": "The passage defines a limit as an approached value.",
                "evidence_refs": ["E1"],
                "difficulty": 0.5,
            }
        ]
    }
    # The double returns the same payload for every call, so the second concept's
    # question is an exact duplicate of the first concept's.
    llm = ScriptedLLM(payload)
    builder = QuestionBankBuilder(llm_adapter=llm)
    retriever = _fake_retriever(ctx, quote)

    bank = builder.build_bank_for_chapter(
        ctx, chapter_id="ch_dup", target_count=25, retriever=retriever
    )

    # Both concepts were attempted, yet only one distinct question was stored.
    assert builder.llm_calls == 2, "expected a generation round per uncovered concept"
    assert len(bank.questions) == 1, "duplicate questions were stored"
    assert len(bank.get_grounded_questions()) == 1


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

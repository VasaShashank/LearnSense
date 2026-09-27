"""
Unit tests for Phase 5 Validation, Recovery, and Idempotency engines.
"""

import pytest
import pymupdf as fitz
from phase2.models import Concept, ConfidenceBreakdown, Relationship, RelationshipTypeEnum, EvidenceLevelEnum
from phase3.knowledge.phase2_adapter import ConceptView, LearningContext, PrerequisiteLink
from phase3.learner.models import ConceptState, LearnerState
from phase3.question_bank.models import QuestionBankItem, QuestionType
from phase4.models import KnowledgeInitializationSession, LearningPath, LearningPathNode, SelfAssessmentStatus
from phase5.config.phase5_config import Phase5Config, phase5_config
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.validation import (
    ExtractionValidator,
    IdempotencyTracker,
    InputValidator,
    KnowledgeGraphValidator,
    LearnerStateValidator,
    NLPValidator,
    PlanningValidator,
    QuestionValidator,
)
from schemas.document import BlockContent, DocumentBlock, DocumentPage, SourceMetadata, StructuredDocument, DocumentMetadata, ProcessingStatusEnum


def _make_valid_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello World PDF Content")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_input_validator():
    validator = InputValidator(max_file_size_bytes=10000, max_page_count=5)

    valid_pdf_bytes = _make_valid_pdf_bytes()
    res = validator.validate_file(valid_pdf_bytes, "test.pdf")
    assert res.is_valid is True

    # Non-PDF extension
    res_txt = validator.validate_file(valid_pdf_bytes, "test.txt")
    assert res_txt.is_valid is False
    assert "Unsupported file type" in res_txt.errors[0]

    # Oversized PDF
    res_large = validator.validate_file(b"%PDF-" + b"0" * 20000, "large.pdf")
    assert res_large.is_valid is False
    assert "exceeds configured limit" in res_large.errors[0]

    # Empty / corrupted PDF
    res_empty = validator.validate_file(b"123", "empty.pdf")
    assert res_empty.is_valid is False


def test_extraction_validator():
    validator = ExtractionValidator(min_text_length=20)

    # Structured Document with text
    doc = StructuredDocument(
        document_id="doc_123",
        source=SourceMetadata(sha256="abc", filename="f.pdf", size_bytes=100),
        metadata=DocumentMetadata(page_count=1, title={"value": "T"}, processing_status=ProcessingStatusEnum.COMPLETED),
        pages=[
            DocumentPage(
                page_index=0,
                page_label="1",
                width=100,
                height=100,
                blocks=[
                    DocumentBlock(
                        block_id="b1",
                        type="paragraph",
                        role="body",
                        bbox=[0, 0, 10, 10],
                        content=BlockContent(text="This is a valid extracted text line with sufficient length.", text_raw="text"),
                        reading_order=0,
                        extraction_method="native",
                    )
                ],
            )
        ],
    )

    res = validator.validate_structured_document(doc)
    assert res.is_valid is True
    assert res.metadata["total_text_length"] > 20

    # Zero text yield
    doc.pages[0].blocks[0].content.text = ""
    res_zero = validator.validate_structured_document(doc)
    assert res_zero.is_valid is False
    assert "zero usable text" in res_zero.errors[0]


def test_nlp_validator():
    validator = NLPValidator(confidence_threshold=0.7)

    c1 = Concept(
        concept_id="c1",
        canonical_name="Velocity",
        confidence=ConfidenceBreakdown(value=0.9),
    )
    c2 = Concept(
        concept_id="c2",
        canonical_name="Acceleration",
        confidence=ConfidenceBreakdown(value=0.5),  # low confidence
    )

    res_c = validator.validate_concepts([c1, c2])
    assert res_c.is_valid is True
    assert res_c.metadata["low_confidence_concepts"] == 1
    assert res_c.status == ValidationStatus.WARNING

    # Relationship checks
    rel1 = Relationship(
        relationship_id="r1",
        source="c1",
        target="c2",
        type=RelationshipTypeEnum.PREREQUISITE_OF,
        evidence_level=EvidenceLevelEnum.EXPLICIT,
        confidence=ConfidenceBreakdown(value=0.9),
    )
    rel_self = Relationship(
        relationship_id="r2",
        source="c1",
        target="c1",  # self ref
        type=RelationshipTypeEnum.PREREQUISITE_OF,
        evidence_level=EvidenceLevelEnum.EXPLICIT,
        confidence=ConfidenceBreakdown(value=0.9),
    )

    res_r = validator.validate_relationships([rel1, rel_self], valid_concept_ids={"c1", "c2"})
    assert res_r.is_valid is False
    assert "Self-referencing relationship" in res_r.errors[0]


def test_knowledge_graph_validator_and_cycle_breaking():
    validator = KnowledgeGraphValidator()

    ctx = LearningContext(document_id="d1", knowledge_document_id="k1")
    ctx.concepts["c1"] = ConceptView(concept_id="c1", canonical_name="C1", type="concept")
    ctx.concepts["c2"] = ConceptView(concept_id="c2", canonical_name="C2", type="concept")
    ctx.concepts["c3"] = ConceptView(concept_id="c3", canonical_name="C3", type="concept")

    # Create cycle c1 -> c2 -> c3 -> c1
    ctx.prerequisites = [
        PrerequisiteLink(source_concept_id="c1", target_concept_id="c2", confidence=1.0),
        PrerequisiteLink(source_concept_id="c2", target_concept_id="c3", confidence=1.0),
        PrerequisiteLink(source_concept_id="c3", target_concept_id="c1", confidence=1.0),
    ]

    res = validator.validate_learning_context(ctx)
    assert res.metadata["cycles_count"] == 1

    # Sanitize and break cycle
    sanitized_ctx = validator.sanitize_and_break_cycles(ctx)
    res_clean = validator.validate_learning_context(sanitized_ctx)
    assert res_clean.metadata["cycles_count"] == 0


def test_question_validator():
    validator = QuestionValidator()

    q_item = QuestionBankItem(
        question_id="q1",
        concept_ids=["c1"],
        skill_ids=[],
        question_type=QuestionType.MCQ,
        question_text="What is the derivative of position with respect to time?",
        options=["Velocity", "Acceleration", "Force"],
        correct_answer="Velocity",
    )

    res = validator.validate_question_item(q_item, target_concept_id="c1")
    assert res.is_valid is True

    # Mismatched target concept
    res_mismatch = validator.validate_question_item(q_item, target_concept_id="c_other")
    assert res_mismatch.is_valid is False
    assert "Question concept mismatch" in res_mismatch.errors[0]


def test_learner_state_and_idempotency():
    tracker = IdempotencyTracker()
    validator = LearnerStateValidator(idempotency_tracker=tracker)

    # First submission
    res1 = validator.validate_response_submission(
        learner_id="l1",
        concept_ids=["c1"],
        correctness=1.0,
        request_id="req_001",
        valid_subject_concepts={"c1"},
    )
    assert res1.is_valid is True
    tracker.mark_processed("req_001")

    # Duplicate submission
    res2 = validator.validate_response_submission(
        learner_id="l1",
        concept_ids=["c1"],
        correctness=1.0,
        request_id="req_001",
        valid_subject_concepts={"c1"},
    )
    assert res2.metadata.get("duplicate_submission") is True


def test_planning_validator():
    validator = PlanningValidator()

    session = KnowledgeInitializationSession(
        session_id="sess_100",
        learner_id="l1",
        subject_id="s1",
        know_concept_ids=["c1"],
        dont_know_concept_ids=["c2"],
        unanswered_concept_ids=[],
    )

    # Diagnostic question matching KNOW concept
    valid_q = [{"question_id": "q1", "concept_ids": ["c1"]}]
    res1 = validator.validate_diagnostic_quiz_creation(session, valid_q)
    assert res1.is_valid is True

    # Invalid question introducing DON'T KNOW concept
    invalid_q = [{"question_id": "q2", "concept_ids": ["c2"]}]
    res2 = validator.validate_diagnostic_quiz_creation(session, invalid_q)
    assert res2.is_valid is False
    assert "was NOT reported as KNOW" in res2.errors[0]

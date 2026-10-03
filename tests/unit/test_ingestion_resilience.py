"""
Unit tests for Ingestion and OCR resilience in LearnSense.
Verifies:
1. Tesseract adapter safe error handling and availability detection.
2. Graceful degradation when image bytes are corrupted.
3. Automatic evidence grounding recovery on sparse documents in KnowledgeBuildService.
"""

import pytest
from adapters.tesseract_adapter import TesseractOCRAdapter
from backend.services.knowledge_build_service import KnowledgeBuildService
from phase3.knowledge.phase2_adapter import ConceptView, LearningContext
from phase3.errors import KnowledgeBuildError
from schemas.document import (
    BlockContent,
    BlockTypeEnum,
    DocumentBlock,
    DocumentPage,
    ExtractionMethodEnum,
    StructuredDocument,
    SourceMetadata,
    DocumentMetadata,
    TitleMetadata,
    TitleSourceEnum,
    ProcessingStatusEnum,
)


class TestTesseractResilience:
    def test_tesseract_adapter_corrupted_image_handling(self):
        adapter = TesseractOCRAdapter()
        # Invalid / corrupted bytes should return empty list without raising unhandled exceptions
        results = adapter.ocr_image(b"invalid_non_image_bytes")
        assert results == []

    def test_tesseract_availability_check(self):
        adapter = TesseractOCRAdapter()
        is_avail = adapter.is_available()
        assert isinstance(is_avail, bool)


class TestGroundingResilience:
    def test_assert_grounded_recovers_unlinked_concepts(self):
        # Create a structured document with text blocks
        block1 = DocumentBlock(
            block_id="blk_001",
            type=BlockTypeEnum.PARAGRAPH,
            role="body",
            bbox=[0.0, 0.0, 100.0, 100.0],
            content=BlockContent(text="Gradient Descent is an optimization algorithm used to minimize loss.", text_raw="Gradient Descent is an optimization algorithm used to minimize loss."),
            reading_order=1,
            extraction_method=ExtractionMethodEnum.NATIVE,
        )
        page1 = DocumentPage(
            page_index=0,
            page_label="1",
            width=612.0,
            height=792.0,
            blocks=[block1],
        )
        doc = StructuredDocument(
            document_id="doc_resilience_01",
            source=SourceMetadata(sha256="abc", filename="resilience.pdf", size_bytes=100),
            metadata=DocumentMetadata(
                page_count=1,
                title=TitleMetadata(value="Resilience Test", source=TitleSourceEnum.INFERRED),
                processing_status=ProcessingStatusEnum.COMPLETED,
            ),
            pages=[page1],
        )

        # Context has a concept but without prior explicit evidence binding
        concept = ConceptView(
            concept_id="c_grad_desc",
            canonical_name="Gradient Descent",
            type="concept",
            description="",
            evidence_ids=[],
        )
        context = LearningContext(
            document_id="doc_resilience_01",
            knowledge_document_id="kdoc_01",
            concepts={"c_grad_desc": concept},
        )

        # KnowledgeBuildService._assert_grounded should automatically resolve evidence from block1
        KnowledgeBuildService._assert_grounded(context, doc)

        assert len(context.concepts_with_evidence()) == 1
        assert len(context.concepts["c_grad_desc"].evidence_ids) > 0
        assert "blk_001" in context.concepts["c_grad_desc"].block_ids
        assert context.concepts["c_grad_desc"].description != ""

    def test_assert_grounded_raises_on_genuinely_empty_context(self):
        page1 = DocumentPage(
            page_index=0,
            page_label="1",
            width=612.0,
            height=792.0,
            blocks=[],
        )
        doc = StructuredDocument(
            document_id="doc_resilience_02",
            source=SourceMetadata(sha256="abc", filename="empty.pdf", size_bytes=100),
            metadata=DocumentMetadata(
                page_count=1,
                title=TitleMetadata(value="Empty Doc", source=TitleSourceEnum.INFERRED),
                processing_status=ProcessingStatusEnum.COMPLETED,
            ),
            pages=[page1],
        )
        context = LearningContext(
            document_id="doc_resilience_02",
            knowledge_document_id="kdoc_02",
            concepts={},
        )

        with pytest.raises(KnowledgeBuildError):
            KnowledgeBuildService._assert_grounded(context, doc)

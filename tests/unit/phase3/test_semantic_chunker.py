"""
Unit tests for SemanticChunker in LearnSense Phase 3.
Verifies:
1. Aggregation of small blocks under common headings/sections.
2. Boundary splitting on section changes and headings.
3. Provenance tracking: block_ids, page_indices, and evidence_ids.
"""

import pytest
from phase3.retrieval.semantic_chunker import SemanticChunker, SemanticChunk
from schemas.document import (
    BlockContent,
    BlockTypeEnum,
    DocumentBlock,
    DocumentPage,
    ExtractionMethodEnum,
    SectionNode,
    StructuredDocument,
    SourceMetadata,
    DocumentMetadata,
    TitleMetadata,
    TitleSourceEnum,
    ProcessingStatusEnum,
)
from phase2.models import EducationalKnowledgeRepresentation, Concept, Evidence, EvidenceLevelEnum, EvidenceKindEnum, TextSpan, ConfidenceBreakdown


class TestSemanticChunker:
    @pytest.fixture
    def sample_document(self):
        outline = [
            SectionNode(section_id="sec_01", title="Introduction to Vectors", level=1, page_start=1),
            SectionNode(section_id="sec_02", title="Vector Operations", level=1, page_start=2),
        ]
        page1_blocks = [
            DocumentBlock(
                block_id="b1",
                type=BlockTypeEnum.HEADING,
                role="heading_l1",
                section_id="sec_01",
                bbox=[0, 0, 100, 20],
                content=BlockContent(text="Introduction to Vectors", text_raw="Introduction to Vectors"),
                reading_order=1,
                extraction_method=ExtractionMethodEnum.NATIVE,
            ),
            DocumentBlock(
                block_id="b2",
                type=BlockTypeEnum.PARAGRAPH,
                role="body",
                section_id="sec_01",
                bbox=[0, 25, 100, 60],
                content=BlockContent(text="A vector is an object that has both magnitude and direction.", text_raw="A vector is an object that has both magnitude and direction."),
                reading_order=2,
                extraction_method=ExtractionMethodEnum.NATIVE,
            ),
            DocumentBlock(
                block_id="b3",
                type=BlockTypeEnum.PARAGRAPH,
                role="body",
                section_id="sec_01",
                bbox=[0, 65, 100, 100],
                content=BlockContent(text="Vectors are commonly represented as arrows in Euclidean space.", text_raw="Vectors are commonly represented as arrows in Euclidean space."),
                reading_order=3,
                extraction_method=ExtractionMethodEnum.NATIVE,
            ),
        ]
        page2_blocks = [
            DocumentBlock(
                block_id="b4",
                type=BlockTypeEnum.HEADING,
                role="heading_l1",
                section_id="sec_02",
                bbox=[0, 0, 100, 20],
                content=BlockContent(text="Vector Operations", text_raw="Vector Operations"),
                reading_order=1,
                extraction_method=ExtractionMethodEnum.NATIVE,
            ),
            DocumentBlock(
                block_id="b5",
                type=BlockTypeEnum.PARAGRAPH,
                role="body",
                section_id="sec_02",
                bbox=[0, 25, 100, 60],
                content=BlockContent(text="Vector addition is performed component-wise: (u1+v1, u2+v2).", text_raw="Vector addition is performed component-wise: (u1+v1, u2+v2)."),
                reading_order=2,
                extraction_method=ExtractionMethodEnum.NATIVE,
            ),
        ]
        pages = [
            DocumentPage(page_index=0, page_label="1", width=612, height=792, blocks=page1_blocks),
            DocumentPage(page_index=1, page_label="2", width=612, height=792, blocks=page2_blocks),
        ]
        return StructuredDocument(
            document_id="doc_vec_01",
            source=SourceMetadata(sha256="123", filename="vectors.pdf", size_bytes=200),
            metadata=DocumentMetadata(
                page_count=2,
                title=TitleMetadata(value="Vectors", source=TitleSourceEnum.INFERRED),
                processing_status=ProcessingStatusEnum.COMPLETED,
            ),
            outline=outline,
            pages=pages,
        )

    def test_chunker_merges_blocks_under_same_section(self, sample_document):
        chunker = SemanticChunker(min_chunk_tokens=20, max_chunk_tokens=300)
        chunks = chunker.chunk_document(sample_document)

        # Should produce distinct chunks separated by section / heading
        assert len(chunks) == 2
        sec1_chunk = chunks[0]
        assert "b1" in sec1_chunk.block_ids
        assert "b2" in sec1_chunk.block_ids
        assert "b3" in sec1_chunk.block_ids
        assert "magnitude and direction" in sec1_chunk.text
        assert sec1_chunk.section_title == "Introduction to Vectors"
        assert sec1_chunk.primary_page == 0

        sec2_chunk = chunks[1]
        assert "b4" in sec2_chunk.block_ids
        assert "b5" in sec2_chunk.block_ids
        assert sec2_chunk.section_title == "Vector Operations"
        assert sec2_chunk.primary_page == 1

    def test_chunk_citation_payload(self, sample_document):
        chunker = SemanticChunker()
        chunks = chunker.chunk_document(sample_document)
        citation = chunks[0].citation()

        assert citation["document_id"] == "doc_vec_01"
        assert citation["page"] == 1
        assert "b1" in citation["block_ids"]
        assert citation["section"] == "Introduction to Vectors"
        assert "magnitude" in citation["quote"]

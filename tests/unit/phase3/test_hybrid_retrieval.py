"""
Unit tests for Hybrid Evidence Retrieval (BM25 + Dense Vectors + Graph Traversal + RRF).
Verifies:
1. VectorSimilarityIndex sublinear TF-IDF cosine similarity.
2. KnowledgeGraphRetriever multi-hop neighbor traversal and prerequisite discovery.
3. HybridRetriever Reciprocal Rank Fusion combining lexical, dense, and graph ranks.
4. EvidenceRetriever end-to-end integration and citation provenance.
"""

import pytest
from phase3.retrieval.hybrid_retriever import (
    HybridRetriever,
    KnowledgeGraphRetriever,
    VectorSimilarityIndex,
    tokenize,
)
from phase3.retrieval.evidence_retriever import EvidenceRetriever
from phase3.retrieval.semantic_chunker import SemanticChunk
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
from phase2.models import (
    EducationalKnowledgeRepresentation,
    Concept,
    Relationship,
    RelationshipTypeEnum,
    Evidence,
    EvidenceLevelEnum,
    EvidenceKindEnum,
    TextSpan,
    ConfidenceBreakdown,
    ConceptMention,
)


@pytest.fixture
def test_ekr_and_doc():
    outline = [
        SectionNode(section_id="sec_01", title="Neural Network Basics", level=1, page_start=1),
        SectionNode(section_id="sec_02", title="Backpropagation Algorithm", level=1, page_start=2),
    ]

    block1 = DocumentBlock(
        block_id="blk_01",
        type=BlockTypeEnum.PARAGRAPH,
        role="body",
        section_id="sec_01",
        bbox=[0, 0, 100, 50],
        content=BlockContent(
            text="An artificial neural network consists of interconnected nodes or artificial neurons.",
            text_raw="An artificial neural network consists of interconnected nodes or artificial neurons.",
        ),
        reading_order=1,
        extraction_method=ExtractionMethodEnum.NATIVE,
    )
    block2 = DocumentBlock(
        block_id="blk_02",
        type=BlockTypeEnum.PARAGRAPH,
        role="body",
        section_id="sec_02",
        bbox=[0, 0, 100, 50],
        content=BlockContent(
            text="Backpropagation calculates the gradient of the loss function with respect to weights using the chain rule.",
            text_raw="Backpropagation calculates the gradient of the loss function with respect to weights using the chain rule.",
        ),
        reading_order=2,
        extraction_method=ExtractionMethodEnum.NATIVE,
    )

    pages = [
        DocumentPage(page_index=0, page_label="1", width=612, height=792, blocks=[block1]),
        DocumentPage(page_index=1, page_label="2", width=612, height=792, blocks=[block2]),
    ]

    doc = StructuredDocument(
        document_id="doc_nn_01",
        source=SourceMetadata(sha256="abc", filename="nn.pdf", size_bytes=200),
        metadata=DocumentMetadata(
            page_count=2,
            title=TitleMetadata(value="Neural Networks", source=TitleSourceEnum.INFERRED),
            processing_status=ProcessingStatusEnum.COMPLETED,
        ),
        outline=outline,
        pages=pages,
    )

    ev1 = Evidence(
        evidence_id="ev_01",
        block_id="blk_01",
        span=TextSpan(start=0, end=40),
        excerpt="An artificial neural network consists of interconnected nodes",
        level=EvidenceLevelEnum.EXPLICIT,
        kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
    )
    ev2 = Evidence(
        evidence_id="ev_02",
        block_id="blk_02",
        span=TextSpan(start=0, end=50),
        excerpt="Backpropagation calculates the gradient of the loss function",
        level=EvidenceLevelEnum.EXPLICIT,
        kind=EvidenceKindEnum.EXPLICIT_STATEMENT,
    )

    c1 = Concept(
        concept_id="c_nn",
        canonical_name="Neural Network",
        confidence=ConfidenceBreakdown(value=0.95),
        evidence_ids=["ev_01"],
    )
    c2 = Concept(
        concept_id="c_backprop",
        canonical_name="Backpropagation",
        confidence=ConfidenceBreakdown(value=0.95),
        evidence_ids=["ev_02"],
    )

    rel = Relationship(
        relationship_id="rel_01",
        source="c_nn",
        type=RelationshipTypeEnum.PREREQUISITE_OF,
        target="c_backprop",
        evidence_level=EvidenceLevelEnum.EXPLICIT,
        confidence=ConfidenceBreakdown(value=0.9),
    )

    m1 = ConceptMention(
        mention_id="m_01",
        concept_id="c_nn",
        block_id="blk_01",
        span=TextSpan(start=3, end=27),
        surface_form="artificial neural network",
    )
    m2 = ConceptMention(
        mention_id="m_02",
        concept_id="c_backprop",
        block_id="blk_02",
        span=TextSpan(start=0, end=15),
        surface_form="Backpropagation",
    )

    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="kdoc_nn_01",
        source_document_id="doc_nn_01",
        concepts=[c1, c2],
        relationships=[rel],
        mentions=[m1, m2],
        evidence=[ev1, ev2],
    )

    return doc, ekr


class TestVectorSimilarityIndex:
    def test_vector_similarity_search(self):
        index = VectorSimilarityIndex()
        chunk1 = SemanticChunk(
            chunk_id="chk_1",
            document_id="d1",
            text="Gradient descent optimizes parameters iteratively.",
            block_ids=["b1"],
        )
        chunk2 = SemanticChunk(
            chunk_id="chk_2",
            document_id="d1",
            text="Photosynthesis converts sunlight into glucose and oxygen.",
            block_ids=["b2"],
        )
        index.add(chunk1)
        index.add(chunk2)
        index.finalize()

        hits = index.search("iterative parameter optimization")
        assert len(hits) > 0
        assert hits[0][0] == 0  # chunk 1 is top hit


class TestKnowledgeGraphRetriever:
    def test_graph_neighbor_expansion(self, test_ekr_and_doc):
        doc, ekr = test_ekr_and_doc
        kg_retriever = KnowledgeGraphRetriever(ekr)

        # Querying backpropagation should identify its prerequisite (c_nn -> blk_01)
        scores = kg_retriever.traverse_neighbors(["Backpropagation"])
        assert "blk_02" in scores  # direct concept
        assert "blk_01" in scores  # 1-hop prerequisite neighbor
        assert scores["blk_02"] > scores["blk_01"]


class TestHybridRetrieverAndEvidenceRetriever:
    def test_hybrid_search_fusion(self, test_ekr_and_doc):
        doc, ekr = test_ekr_and_doc
        retriever = HybridRetriever(doc, ekr)

        results = retriever.search_hybrid("gradient chain rule loss function")
        assert len(results) > 0
        assert "blk_02" in results[0].block_ids
        assert results[0].score > 0.0

    def test_evidence_retriever_concept_and_text_retrieval(self, test_ekr_and_doc):
        doc, ekr = test_ekr_and_doc
        evidence_retriever = EvidenceRetriever(doc, ekr)

        # Retrieve for concept
        chunks = evidence_retriever.retrieve_for_concept("c_backprop")
        assert len(chunks) > 0
        assert "blk_02" == chunks[0].block_id
        citation = chunks[0].citation()
        assert citation["page"] == 2
        assert "gradient" in citation["quote"].lower()

        # Retrieve by text
        text_chunks = evidence_retriever.retrieve_by_text("neurons connected nodes")
        assert len(text_chunks) > 0
        assert text_chunks[0].block_id == "blk_01"

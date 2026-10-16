"""
Unit tests for Relationship Extraction in Phase 2.
Verifies Section 16 of TAPROOT:
- Support for:
  - X requires Y
  - Y is prerequisite for X
  - X depends on Y
  - X builds on Y
  - X relies on Y
  - To understand X, students should know Y
- Negation and hedging detection
- Directed cycle prevention
- Grounded evidence and confidence metadata
"""

import pytest
from phase2.models import (
    Concept,
    ConfidenceBreakdown,
    Evidence,
    EvidenceKindEnum,
    EvidenceLevelEnum,
    RelationshipTypeEnum,
    TextSpan,
)
from phase2.pipeline.stage1_normalize import NormalizedDocumentContext
from phase2.pipeline.stage4_candidates import Stage4ExtractionResult
from phase2.pipeline.stage7_relationships import (
    detect_negation_or_hedging,
    has_directed_path,
    run_stage7_relationship_extraction,
)
from schemas.document import (
    BlockContent,
    BlockTypeEnum,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    ExtractionMethodEnum,
    ProcessingStatusEnum,
    SourceMetadata,
    StructuredDocument,
    TitleMetadata,
    TitleSourceEnum,
)


class TestRelationshipExtractionComplete:
    @pytest.fixture
    def test_context_and_concepts(self):
        doc_id = "doc_test_rel"
        c1 = Concept(
            concept_id="c_diff",
            canonical_name="Differentiation",
            confidence=ConfidenceBreakdown(value=0.95),
            evidence_ids=["ev_1"],
        )
        c2 = Concept(
            concept_id="c_integ",
            canonical_name="Integration",
            confidence=ConfidenceBreakdown(value=0.95),
            evidence_ids=["ev_2"],
        )
        c3 = Concept(
            concept_id="c_ode",
            canonical_name="Differential Equations",
            confidence=ConfidenceBreakdown(value=0.95),
            evidence_ids=["ev_3"],
        )
        return doc_id, [c1, c2, c3]

    def _run_with_text(self, text: str, concepts: list, doc_id: str):
        ev1 = Evidence(
            evidence_id="ev_1", block_id="b1", span=TextSpan(start=0, end=len(concepts[0].canonical_name)),
            excerpt=concepts[0].canonical_name, level=EvidenceLevelEnum.EXPLICIT, kind=EvidenceKindEnum.EXPLICIT_STATEMENT
        )
        ev2 = Evidence(
            evidence_id="ev_2", block_id="b1", span=TextSpan(start=0, end=len(concepts[1].canonical_name)),
            excerpt=concepts[1].canonical_name, level=EvidenceLevelEnum.EXPLICIT, kind=EvidenceKindEnum.EXPLICIT_STATEMENT
        )
        candidates = Stage4ExtractionResult()
        candidates.evidence = [ev1, ev2]

        block = DocumentBlock(
            block_id="b1",
            type=BlockTypeEnum.PARAGRAPH,
            role="body",
            bbox=[0, 0, 100, 100],
            content=BlockContent(text=text, text_raw=text),
            reading_order=1,
            extraction_method=ExtractionMethodEnum.NATIVE,
        )
        page = DocumentPage(page_index=0, page_label="1", width=612, height=792, blocks=[block])
        doc = StructuredDocument(
            document_id=doc_id,
            source=SourceMetadata(sha256="abc", filename="doc.pdf", size_bytes=100),
            metadata=DocumentMetadata(
                page_count=1,
                title=TitleMetadata(value="Rel Test", source=TitleSourceEnum.INFERRED),
                processing_status=ProcessingStatusEnum.COMPLETED,
            ),
            pages=[page],
        )
        norm_doc = NormalizedDocumentContext(doc)
        return run_stage7_relationship_extraction(norm_doc, concepts, candidates)

    def test_pattern_x_requires_y(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        # "Integration requires Differentiation." -> Differentiation (source) -> Integration (target)
        text = "Integration requires Differentiation as a foundational mathematical tool."
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 1
        assert rels[0].source == "c_diff"
        assert rels[0].target == "c_integ"
        assert rels[0].type == RelationshipTypeEnum.PREREQUISITE_OF

    def test_pattern_y_is_prerequisite_for_x(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        # "Differentiation is a prerequisite for Integration." -> Differentiation (source) -> Integration (target)
        text = "Differentiation is a prerequisite for Integration in elementary calculus."
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 1
        assert rels[0].source == "c_diff"
        assert rels[0].target == "c_integ"

    def test_pattern_x_depends_on_y(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        # "Integration depends on Differentiation." -> Differentiation (source) -> Integration (target)
        text = "Integration depends on Differentiation principles."
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 1
        assert rels[0].source == "c_diff"
        assert rels[0].target == "c_integ"

    def test_pattern_x_builds_on_y(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        # "Integration builds on Differentiation." -> Differentiation (source) -> Integration (target)
        text = "Integration builds on Differentiation extensively throughout this chapter."
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 1
        assert rels[0].source == "c_diff"
        assert rels[0].target == "c_integ"

    def test_pattern_x_relies_on_y(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        # "Integration relies on Differentiation." -> Differentiation (source) -> Integration (target)
        text = "Integration relies on Differentiation techniques."
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 1
        assert rels[0].source == "c_diff"
        assert rels[0].target == "c_integ"

    def test_pattern_to_understand_x_know_y(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        # "To understand Integration, students should know Differentiation." -> Differentiation (source) -> Integration (target)
        text = "To understand Integration, students should know Differentiation thoroughly."
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 1
        assert rels[0].source == "c_diff"
        assert rels[0].target == "c_integ"

    def test_negation_hedging_filtered(self, test_context_and_concepts):
        doc_id, concepts = test_context_and_concepts
        text = "Integration does not require Differentiation in this specific discrete context."
        assert detect_negation_or_hedging(text) is True
        rels = self._run_with_text(text, concepts, doc_id)
        assert len(rels) == 0  # Negated dependency must not be extracted!

    def test_cycle_prevention(self):
        adj = {"c1": {"c2"}, "c2": {"c3"}}
        # c1 -> c2 -> c3. Does c3 reach c1? No.
        assert not has_directed_path(adj, "c3", "c1")
        # Adding c3 -> c1 would create cycle.
        adj["c3"] = {"c1"}
        assert has_directed_path(adj, "c3", "c1")

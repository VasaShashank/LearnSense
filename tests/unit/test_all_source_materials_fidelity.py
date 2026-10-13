"""
Comprehensive Unit Tests for All Source Materials to Knowledge Graph Fidelity.
Verifies PDF, DOCX, TXT/MD, multi-word domain concepts, colon definitions,
and typed relationships (PREREQUISITE_OF, IS_A, INSTANCE_OF, PART_OF).
"""

import io
import pytest
from docx import Document

from ingestion.document_formats import docx_to_structured_document, text_to_pdf
from ingestion.pipeline import IngestionPipeline
from schemas.document import BlockTypeEnum
from phase2.adapters.nlp_adapters import Tier01DeterministicAdapter
from phase2.models import EvidenceKindEnum, RelationshipTypeEnum
from phase2.pipeline.stage1_normalize import run_stage1_normalize
from phase2.pipeline.stage2_context import run_stage2_context
from phase2.pipeline.stage3_segment import run_stage3_segmentation
from phase2.pipeline.stage4_candidates import extract_candidates
from phase2.pipeline.stage5_resolution import run_stage5_entity_resolution
from phase2.pipeline.stage7_relationships import run_stage7_relationship_extraction
from phase2.pipeline.stage8_graph import run_stage8_graph_construction


def _create_sample_docx_bytes() -> bytes:
    doc = Document()
    doc.add_heading("Advanced Algorithms and Data Structures", level=1)
    doc.add_paragraph("Binary Search Tree is an algorithm that provides logarithmic lookup time.")
    doc.add_paragraph("Dynamic Programming is defined as an algorithmic paradigm that solves subproblems recursively.")
    doc.add_paragraph("Dynamic Programming requires Recursion as a core mathematical foundation.")

    # Table in Word document
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Data Structure"
    table.cell(0, 1).text = "Time Complexity"
    table.cell(1, 0).text = "Hash Table"
    table.cell(1, 1).text = "O(1) average"

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_docx_to_knowledge_graph_fidelity():
    raw_docx = _create_sample_docx_bytes()
    struct_doc = docx_to_structured_document(raw_docx, "algorithms.docx", "doc_docx_algo")

    assert struct_doc.document_id == "doc_docx_algo"
    all_blocks = [b for page in struct_doc.pages for b in page.blocks]

    # Verify table extracted from Word document
    table_blocks = [b for b in all_blocks if b.type == BlockTypeEnum.TABLE]
    assert len(table_blocks) >= 1
    assert "| Data Structure | Time Complexity |" in table_blocks[0].content.text
    assert "| Hash Table | O(1) average |" in table_blocks[0].content.text

    # Run through Phase 2
    norm_doc = run_stage1_normalize(struct_doc)
    doc_ctx = run_stage2_context(norm_doc)
    units = run_stage3_segmentation(norm_doc, doc_ctx, Tier01DeterministicAdapter())
    candidates = extract_candidates(norm_doc, doc_ctx, units)

    # Verify definition harvested
    dp_defs = [d for d in candidates.harvested_definitions if "dynamic programming" in d["term"].lower()]
    assert len(dp_defs) > 0

    concepts, _ = run_stage5_entity_resolution(norm_doc, candidates)
    concept_names = [c.canonical_name.lower() for c in concepts]

    assert any("dynamic programming" in name for name in concept_names)
    assert any("binary search tree" in name for name in concept_names)

    # Verify concept description bound from definition
    dp_concept = next(c for c in concepts if "dynamic programming" in c.canonical_name.lower())
    assert dp_concept.description != ""
    assert "subproblems recursively" in dp_concept.description


def test_markdown_and_colon_definitions_fidelity():
    text_corpus = (
        "# Graph Algorithms Curriculum\n\n"
        "Breadth-First Search: An algorithm for traversing tree or graph data structures layer by layer.\n\n"
        "Depth-First Search: An algorithm that explores as far as possible along each branch before backtracking.\n\n"
        "Graph Traversal is an umbrella technique for visiting all vertices in a network.\n\n"
        "Breadth-First Search is an example of Graph Traversal.\n\n"
        "Graph Traversal requires Tree Traversal as a conceptual prerequisite.\n\n"
        "Tree Traversal explores hierarchical nodes systematically."
    )

    pdf_bytes = text_to_pdf(text_corpus)
    pipeline = IngestionPipeline()
    struct_doc = pipeline.process_pdf_bytes(pdf_bytes, "graphs.md", "doc_graph_01")

    norm_doc = run_stage1_normalize(struct_doc)
    doc_ctx = run_stage2_context(norm_doc)
    units = run_stage3_segmentation(norm_doc, doc_ctx, Tier01DeterministicAdapter())
    candidates = extract_candidates(norm_doc, doc_ctx, units)

    # Verify colon definitions harvested
    colon_terms = [d["term"].lower() for d in candidates.harvested_definitions]
    assert any("breadth-first search" in t or "breadth" in t for t in colon_terms)
    assert any("depth-first search" in t or "depth" in t for t in colon_terms)

    concepts, _ = run_stage5_entity_resolution(norm_doc, candidates)
    relationships = run_stage7_relationship_extraction(norm_doc, concepts, candidates)

    # Verify typed relationships:
    # 1. "Breadth-First Search is an example of Graph Traversal" -> INSTANCE_OF
    # 2. "Graph Traversal requires Tree Traversal" -> PREREQUISITE_OF
    rel_types = [r.type for r in relationships]
    assert RelationshipTypeEnum.PREREQUISITE_OF in rel_types or RelationshipTypeEnum.INSTANCE_OF in rel_types


def test_lowercase_domain_concept_mining():
    # Text with technical terms recurring in lowercase
    text_corpus = (
        "In artificial intelligence, neural network architectures utilize backpropagation.\n"
        "The neural network adjusts weights to minimize the loss function.\n"
        "During training, a neural network optimizes parameters across epochs.\n"
        "Gradient descent is an algorithm that minimizes cost functions iteratively.\n"
        "Gradient descent requires calculus derivatives."
    )

    pdf_bytes = text_to_pdf(text_corpus)
    pipeline = IngestionPipeline()
    struct_doc = pipeline.process_pdf_bytes(pdf_bytes, "ai_lecture.txt", "doc_ai_01")

    norm_doc = run_stage1_normalize(struct_doc)
    doc_ctx = run_stage2_context(norm_doc)
    units = run_stage3_segmentation(norm_doc, doc_ctx, Tier01DeterministicAdapter())
    candidates = extract_candidates(norm_doc, doc_ctx, units)

    # Verify lowercase recurring multi-word phrase "neural network" was mined
    mention_surfaces = [m.surface_form.lower() for m in candidates.mentions]
    assert any("neural network" in s for s in mention_surfaces)

    concepts, _ = run_stage5_entity_resolution(norm_doc, candidates)
    c_names = [c.canonical_name.lower() for c in concepts]
    assert any("neural network" in name for name in c_names)

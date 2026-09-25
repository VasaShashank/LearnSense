"""
Unit tests for Milestone M2 (Stages 4-6: candidates, entity resolution, object assembly).
"""

import json
import pytest
from schemas.document import StructuredDocument
from phase2.pipeline.stage1_normalize import run_stage1_normalize
from phase2.pipeline.stage2_context import run_stage2_context
from phase2.pipeline.stage3_segment import run_stage3_segmentation
from phase2.pipeline.stage4_candidates import extract_candidates
from phase2.pipeline.stage5_resolution import run_stage5_entity_resolution
from phase2.pipeline.stage6_assembly import run_stage6_object_assembly
from phase2.adapters.nlp_adapters import Tier01DeterministicAdapter


def test_m2_textbook_candidates_and_resolution():
    with open("tests/fixtures/phase2/textbook.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    norm_doc = run_stage1_normalize(doc)
    doc_ctx = run_stage2_context(norm_doc)
    nlp_adapter = Tier01DeterministicAdapter()

    units = run_stage3_segmentation(norm_doc, doc_ctx, nlp_adapter)
    candidates = extract_candidates(norm_doc, doc_ctx, units)

    assert len(candidates.mentions) > 0
    assert len(candidates.skills) > 0  # Learning objective extracted

    concepts, merge_records = run_stage5_entity_resolution(norm_doc, candidates)
    assert len(concepts) > 0

    items = run_stage6_object_assembly(norm_doc, units, concepts, candidates)
    assert isinstance(items, list)


def test_m2_acronym_resolution():
    with open("tests/fixtures/phase2/duplicate_concepts.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    norm_doc = run_stage1_normalize(doc)
    doc_ctx = run_stage2_context(norm_doc)
    nlp_adapter = Tier01DeterministicAdapter()

    units = run_stage3_segmentation(norm_doc, doc_ctx, nlp_adapter)
    candidates = extract_candidates(norm_doc, doc_ctx, units)
    concepts, merge_records = run_stage5_entity_resolution(norm_doc, candidates)

    canonical_names = [c.canonical_name for c in concepts]
    assert "Artificial Intelligence" in canonical_names

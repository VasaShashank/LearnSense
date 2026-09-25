"""
Unit tests for Milestone M3 (Stages 7-8: relationships, graph construction, trusted view, grounding, cycle detection).
"""

import json
import pytest
from schemas.document import StructuredDocument
from phase2.pipeline.runner import Phase2PipelineRunner
from phase2.pipeline.stage8_graph import detect_scc_tarjan, aggregate_confidence_noisy_or


def test_m3_prerequisite_extraction_and_trusted_view():
    with open("tests/fixtures/phase2/textbook.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = StructuredDocument.model_validate(data)
    runner = Phase2PipelineRunner()
    ekr = runner.process(doc)

    assert len(ekr.relationships) > 0
    rel = ekr.relationships[0]
    assert rel.type.value == "prerequisite_of"
    assert rel.relationship_id in ekr.views.trusted["relationship_ids"]


def test_tarjan_cycle_detection():
    nodes = {"c_1", "c_2", "c_3", "c_4"}
    edges = [("c_1", "c_2"), ("c_2", "c_3"), ("c_3", "c_1"), ("c_3", "c_4")]
    sccs = detect_scc_tarjan(nodes, edges)

    assert len(sccs) == 1
    assert sccs[0] == {"c_1", "c_2", "c_3"}


def test_noisy_or_combination():
    conf = aggregate_confidence_noisy_or([0.5, 0.5])
    assert conf == 0.75

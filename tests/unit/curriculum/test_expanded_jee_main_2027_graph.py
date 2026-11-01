"""
Comprehensive verification test for the expanded JEE Main 2027 Canonical Curriculum Graph.
"""

import json
from pathlib import Path
import pytest

from curriculum.graph import CurriculumGraphValidator, derive_topological_depth
from curriculum.learner_adapter import KnowledgeGraphAdapter
from curriculum.seed import load_spec, seed_curriculum
from curriculum.simulator import SimulatorBridge, load_simulator_concepts

SPEC_PATH = Path("curriculum/data/jee_curriculum_spec.json")
CROSSWALK_PATH = Path("curriculum/data/jee_main_2027_crosswalk.json")
SIMULATOR_CSV = Path("../References/learnsense_jee_simulator_v2/concepts.csv")


@pytest.fixture(scope="module")
def canonical_graph():
    spec = load_spec(SPEC_PATH)
    graph = seed_curriculum(spec)
    return graph


def test_concept_and_relationship_counts(canonical_graph):
    assert len(canonical_graph.concepts) == 89
    assert len(canonical_graph.relationships) == 91

    # Check subject breakdown
    physics_concepts = [c for c in canonical_graph.concepts.values() if c.subject.value == "physics"]
    chemistry_concepts = [c for c in canonical_graph.concepts.values() if c.subject.value == "chemistry"]
    math_concepts = [c for c in canonical_graph.concepts.values() if c.subject.value == "mathematics"]

    assert len(physics_concepts) == 36
    assert len(chemistry_concepts) == 31
    assert len(math_concepts) == 22


def test_graph_validation_zero_errors(canonical_graph):
    report = CurriculumGraphValidator().validate(canonical_graph)
    assert report.is_valid, f"Graph validation failed: {[i.message for i in report.issues if i.severity.value == 'error']}"
    assert report.error_count == 0


def test_topological_depth_derived_for_all_concepts(canonical_graph):
    depths = derive_topological_depth(canonical_graph)
    assert len(depths) == 89
    assert min(depths.values()) == 0
    assert max(depths.values()) >= 5


def test_simulator_62_concepts_backward_compatibility(canonical_graph):
    bridge = SimulatorBridge(canonical_graph)
    sim_concepts = load_simulator_concepts(SIMULATOR_CSV)
    assert len(sim_concepts) == 62

    entries = bridge.map_concepts(sim_concepts)
    mapped_entries = [e for e in entries if e.status.value == "mapped"]
    assert len(mapped_entries) == 62, "All 62 simulator concepts must map decisively 1-to-1"


def test_pruned_legacy_concepts_scope_classification(canonical_graph):
    pruned_keys = [
        "chemistry/physical_chemistry/states_of_matter",
        "chemistry/inorganic_chemistry/metallurgy",
        "chemistry/inorganic_chemistry/hydrogen_and_s_block",
    ]
    for key in pruned_keys:
        concept = next((c for c in canonical_graph.concepts.values() if c.stable_key == key), None)
        assert concept is not None, f"Legacy concept {key} must be preserved for simulator compatibility"
        assert "legacy_retained" in concept.tags
        assert "excluded_from_jee_main_2027" in concept.tags


def test_syllabus_crosswalk_completeness():
    assert CROSSWALK_PATH.exists()
    with open(CROSSWALK_PATH, "r", encoding="utf-8") as f:
        crosswalk = json.load(f)

    assert crosswalk["summary"]["total_syllabus_items"] == 135
    assert crosswalk["summary"]["mapped_items"] == 135
    assert crosswalk["summary"]["unmapped_items"] == 0
    assert crosswalk["summary"]["coverage_percentage"] == 100.0


def test_knowledge_graph_adapter_compatibility(canonical_graph):
    adapter = KnowledgeGraphAdapter(canonical_graph)
    assert len(adapter.concept_ids) == 87  # 87 active concepts (2 deprecated)
    assert len(canonical_graph.concepts) == 89

    # Test readiness evaluation on an expanded concept
    # Vernier calipers requires Units and Measurements
    calipers_id = next(c.concept_id for c in canonical_graph.concepts.values() if "vernier" in c.stable_key)
    is_ready, status_map, remediation = adapter.evaluate_prerequisite_readiness(calipers_id, {})
    # Since prerequisite has 0 mastery, it should not be ready
    assert is_ready is False
    assert len(status_map) > 0

"""Unit tests for src.knowledge_graph module."""

from pathlib import Path
import json
import pytest
from jsonschema import Draft202012Validator

from src.knowledge_graph import (
    ConceptNode,
    PrerequisiteGraph,
    SourceReference,
    load_knowledge_graph_from_csv,
)

CONTRACTS_DIR = next((d / "contracts" for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent / "contracts")


def test_load_knowledge_graph_from_csv():
    """Verify loading and validation of canonical concepts.csv."""
    kg = load_knowledge_graph_from_csv()
    assert len(kg) >= 60
    assert kg.contains("PHY_KIN")
    assert kg.contains("CHE_MOL")
    assert kg.contains("MAT_SET")
    # Verify no cycles in production graph
    assert len(kg.detect_cycles()) == 0
    # Verify no invalid references
    assert len(kg.find_invalid_prerequisite_references()) == 0


def test_concept_node_schema_compliance():
    """Verify ConceptNode serializes conforming to contracts/concept_schema.json."""
    schema_path = CONTRACTS_DIR / "concept_schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema)

    node = ConceptNode(
        concept_id="TEST_CON_01",
        name="Test Concept",
        description="A verified test concept.",
        subject="Physics",
        chapter_id="TEST_CH",
        tags=["physics", "test"],
        status="active",
        prerequisite_concept_ids=[],
        source_refs=[SourceReference(source_id="NCERT-PHY-1", locator="p. 10")],
    )

    payload = node.to_contract_dict()
    errors = list(validator.iter_errors(payload))
    assert len(errors) == 0, f"Schema validation errors: {[e.message for e in errors]}"


def test_prerequisite_relationships():
    """Verify direct and ancestor prerequisite resolution."""
    kg = load_knowledge_graph_from_csv()
    kin_id = kg._resolve_id("PHY_KIN")
    nlm_id = kg._resolve_id("PHY_NLM")
    wpe_id = kg._resolve_id("PHY_WPE")

    # PHY_KIN has no prerequisites (root)
    assert kg.get_direct_prerequisites("PHY_KIN") == []
    assert kg.get_all_ancestor_prerequisites("PHY_KIN") == set()

    # PHY_NLM requires PHY_KIN
    nlm_prereqs = kg.get_direct_prerequisites("PHY_NLM")
    assert kin_id in nlm_prereqs or "PHY_KIN" in nlm_prereqs

    # PHY_ROT requires PHY_NLM and PHY_WPE
    rot_prereqs = kg.get_direct_prerequisites("PHY_ROT")
    assert nlm_id in rot_prereqs or "PHY_NLM" in rot_prereqs
    assert wpe_id in rot_prereqs or "PHY_WPE" in rot_prereqs

    # Transitive ancestors of PHY_ROT must include PHY_KIN
    rot_ancestors = kg.get_all_ancestor_prerequisites("PHY_ROT")
    assert kin_id in rot_ancestors or "PHY_KIN" in rot_ancestors
    assert nlm_id in rot_ancestors or "PHY_NLM" in rot_ancestors
    assert wpe_id in rot_ancestors or "PHY_WPE" in rot_ancestors


def test_cycle_detection():
    """Verify cycle detection on synthetic cyclic graphs."""
    nodes = {
        "A": ConceptNode(concept_id="A", name="A", prerequisite_concept_ids=["C"]),
        "B": ConceptNode(concept_id="B", name="B", prerequisite_concept_ids=["A"]),
        "C": ConceptNode(concept_id="C", name="C", prerequisite_concept_ids=["B"]),
    }
    kg = PrerequisiteGraph()
    for n in nodes.values():
        kg.add_node(n)

    cycles = kg.detect_cycles()
    assert len(cycles) > 0
    with pytest.raises(ValueError, match="circular dependencies"):
        kg.validate_graph()


def test_missing_reference_detection():
    """Verify detection of broken references to non-existent concepts."""
    nodes = {
        "A": ConceptNode(concept_id="A", name="A", prerequisite_concept_ids=["NON_EXISTENT_NODE"]),
    }
    kg = PrerequisiteGraph()
    for n in nodes.values():
        kg.add_node(n)

    invalid = kg.find_invalid_prerequisite_references()
    assert len(invalid) == 1
    assert invalid[0] == ("A", "NON_EXISTENT_NODE")
    with pytest.raises(ValueError, match="broken references"):
        kg.validate_graph()


def test_topological_sort():
    """Verify topological curriculum ordering."""
    kg = load_knowledge_graph_from_csv()
    topo = kg.topological_sort()
    assert len(topo) == len(kg)

    # In topological sort, prerequisites must appear before their dependents
    kin_id = kg._resolve_id("PHY_KIN")
    nlm_id = kg._resolve_id("PHY_NLM")
    wpe_id = kg._resolve_id("PHY_WPE")
    rot_id = kg._resolve_id("PHY_ROT")

    kin_idx = topo.index(kin_id)
    nlm_idx = topo.index(nlm_id)
    wpe_idx = topo.index(wpe_id)
    rot_idx = topo.index(rot_id)

    assert kin_idx < nlm_idx
    assert nlm_idx < wpe_idx
    assert wpe_idx < rot_idx


def test_prerequisite_readiness_evaluation():
    """Verify readiness evaluation under satisfied, unsatisfied, and unknown prerequisite states."""
    kg = load_knowledge_graph_from_csv()
    kin_id = kg._resolve_id("PHY_KIN")

    # Root concept PHY_KIN: always ready
    is_ready, p_map, broken = kg.evaluate_prerequisite_readiness("PHY_KIN", {})
    assert is_ready is True
    assert broken == []

    # PHY_NLM requires PHY_KIN: unknown state
    is_ready, p_map, broken = kg.evaluate_prerequisite_readiness("PHY_NLM", {})
    assert is_ready is False
    assert p_map.get(kin_id) == "unknown" or p_map.get("PHY_KIN") == "unknown"
    assert kin_id in broken or "PHY_KIN" in broken

    # PHY_NLM with weak PHY_KIN (0.30 < 0.50): unsatisfied
    is_ready, p_map, broken = kg.evaluate_prerequisite_readiness("PHY_NLM", {"PHY_KIN": 0.30})
    assert is_ready is False
    assert p_map.get(kin_id) == "unsatisfied" or p_map.get("PHY_KIN") == "unsatisfied"
    assert kin_id in broken or "PHY_KIN" in broken

    # PHY_NLM with mastered PHY_KIN (0.85 >= 0.50): satisfied
    is_ready, p_map, broken = kg.evaluate_prerequisite_readiness("PHY_NLM", {"PHY_KIN": 0.85})
    assert is_ready is True
    assert p_map.get(kin_id) == "satisfied" or p_map.get("PHY_KIN") == "satisfied"
    assert broken == []


def test_remediation_sequence():
    """Verify ordered remediation sequence for broken foundational prerequisites."""
    kg = load_knowledge_graph_from_csv()
    kin_id = kg._resolve_id("PHY_KIN")
    nlm_id = kg._resolve_id("PHY_NLM")
    wpe_id = kg._resolve_id("PHY_WPE")

    # Target: PHY_ROT requires PHY_NLM and PHY_WPE, which require PHY_KIN
    # Learner has zero knowledge
    seq = kg.get_remediation_sequence("PHY_ROT", {})
    assert len(seq) >= 3
    # Foundational PHY_KIN must come before PHY_NLM, which comes before PHY_WPE
    kin_idx = seq.index(kin_id) if kin_id in seq else seq.index("PHY_KIN")
    nlm_idx = seq.index(nlm_id) if nlm_id in seq else seq.index("PHY_NLM")
    wpe_idx = seq.index(wpe_id) if wpe_id in seq else seq.index("PHY_WPE")
    assert kin_idx < nlm_idx
    assert nlm_idx < wpe_idx

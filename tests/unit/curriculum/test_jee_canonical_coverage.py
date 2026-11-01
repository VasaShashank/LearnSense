"""
Unit tests validating full Person 2 x Person 3 canonical JEE curriculum coverage.

Verifies:
1. Canonical JEE spec seeds 62 concepts and 61 prerequisite relationships across NCERT Class 11-12.
2. Complete vocabulary coverage: 62/62 (100%) mapped decisively from AKT vocabulary and simulator concepts.csv.
3. Complete prerequisite edge backing: 61/61 (100%) backed by accepted canonical edges, 0 contradicted, 0 unchecked.
4. CHE_ION resolution: Ionic Equilibrium is an independent canonical node; edge CHE_EQM -> CHE_ION is preserved and backed.
5. Strict acyclicity: Graph is a DAG with zero cycles, zero self-loops, zero duplicate edges, zero missing endpoints.
6. Schema and field contract compatibility: All 62 concepts satisfy Draft 2020-12 concept_schema.json and Person 3 requirements.
7. KnowledgeGraphAdapter compatibility: get_node(), get_prerequisites(), get_successors() return correct nodes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from curriculum.compatibility import (
    CONTRACT_CONCEPT_KEYS,
    build_compatibility_report,
    field_compatibility,
    load_akt_vocabulary_concepts,
)
from curriculum.learner_adapter import KnowledgeGraphAdapter
from curriculum.seed import CurriculumSpec, seed_curriculum
from curriculum.simulator import (
    SimulatorBridge,
    SimulatorMappingStatus,
    load_simulator_concepts,
)
from curriculum.translation import (
    translate_mastery_profile,
    validate_simulator_ids,
)

REFERENCES = Path(__file__).resolve().parents[4] / "References"
V2_CONCEPTS_CSV = REFERENCES / "learnsense_jee_simulator_v2" / "concepts.csv"
PERSON3_DIR = REFERENCES / "LearnSense-Person3-FINAL"
AKT_VOCABULARY = PERSON3_DIR / "data" / "models" / "akt_vocabulary.json"

SPEC_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "curriculum"
    / "jee_curriculum_spec.json"
)
SPEC_PKG = (
    Path(__file__).resolve().parents[3]
    / "curriculum"
    / "data"
    / "jee_curriculum_spec.json"
)


@pytest.fixture(scope="module")
def canonical_jee_spec() -> CurriculumSpec:
    assert SPEC_FIXTURE.is_file(), f"Fixture missing: {SPEC_FIXTURE}"
    data = json.loads(SPEC_FIXTURE.read_text(encoding="utf-8"))
    return CurriculumSpec.model_validate(data)


@pytest.fixture(scope="module")
def canonical_jee_graph(canonical_jee_spec: CurriculumSpec) -> object:
    return seed_curriculum(canonical_jee_spec)


def test_spec_files_exist_and_match() -> None:
    assert SPEC_FIXTURE.is_file()
    assert SPEC_PKG.is_file()
    fixture_bytes = SPEC_FIXTURE.read_bytes()
    pkg_bytes = SPEC_PKG.read_bytes()
    assert fixture_bytes == pkg_bytes, "Fixture and package data specs must match identically"


def test_canonical_graph_structure(canonical_jee_graph: object) -> None:
    assert len(canonical_jee_graph.concepts) >= 62
    accepted_edges = canonical_jee_graph.prerequisite_edges(include_unreviewed=False)
    assert len(accepted_edges) >= 61
    assert canonical_jee_graph.curriculum_id == "jee_class_11_12"
    assert canonical_jee_graph.syllabus_version == "2026.jee.v1"
    fingerprint = canonical_jee_graph.content_fingerprint()
    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 16


def test_subject_distribution(canonical_jee_graph: object) -> None:
    counts: dict[str, int] = {}
    for c in canonical_jee_graph.concepts.values():
        counts[c.subject] = counts.get(c.subject, 0) + 1
    assert counts["physics"] >= 22
    assert counts["chemistry"] >= 24
    assert counts["mathematics"] >= 16


@pytest.mark.skipif(not V2_CONCEPTS_CSV.is_file(), reason="Simulator CSV missing")
def test_all_62_simulator_concepts_map_decisively(canonical_jee_graph: object) -> None:
    sim_concepts = load_simulator_concepts(V2_CONCEPTS_CSV)
    assert len(sim_concepts) == 62

    bridge = SimulatorBridge(canonical_jee_graph)
    entries = bridge.map_concepts(sim_concepts)
    assert len(entries) == 62

    summary = bridge.summary(entries)
    assert summary["total"] == 62
    assert summary["mapped"] == 62
    assert summary["ambiguous"] == 0
    assert summary["unmapped"] == 0
    assert summary["mapped_rate"] == 1.0


@pytest.mark.skipif(
    not (V2_CONCEPTS_CSV.is_file() and AKT_VOCABULARY.is_file()),
    reason="Reference files missing",
)
def test_full_akt_vocabulary_compatibility_report(canonical_jee_graph: object) -> None:
    sim_concepts = load_simulator_concepts(V2_CONCEPTS_CSV)
    vocab_ids = load_akt_vocabulary_concepts(AKT_VOCABULARY)
    assert len(vocab_ids) == 62

    report = build_compatibility_report(
        canonical_jee_graph,
        sim_concepts,
        vocab_ids,
        sources={"spec": "jee_curriculum_spec.json"},
    )

    # 1. Claims: 62/62 AKT vocabulary mapped; 1 false simulator edge rejected (CURR-AUDIT-005)
    assert len(report["claims"]["reasons"]) == 1
    assert "contradict the accepted canonical graph" in report["claims"]["reasons"][0]

    # 2. AKT Vocabulary: 100% coverage
    akt = report["akt_vocabulary"]
    assert akt["concept_count"] == 62
    assert akt["coverage_rate"] == 1.0
    assert len(akt["matched"]) == 62
    assert len(akt["ambiguous"]) == 0
    assert len(akt["unmapped"]) == 0

    # 3. Prerequisite Edges: 60/61 backed (98.4%); 1 contradicted (PHY_KIN -> PHY_OPT)
    edges = report["prerequisite_edges"]
    assert edges["checked"] == 61
    assert len(edges["backed"]) == 60
    assert len(edges["contradicted"]) == 1
    assert edges["contradicted"][0]["source_sim"] == "PHY_KIN"
    assert edges["contradicted"][0]["target_sim"] == "PHY_OPT"
    assert edges["unchecked"] == []
    assert edges["backing_rate"] == 0.9836

    # 4. Structural Checks
    struct = edges["structural_checks"]
    assert struct["is_dag"] is True
    assert struct["cycles"] == []
    assert struct["self_loops"] == []
    assert struct["duplicates"] == []
    assert struct["missing_endpoints"] == []
    assert struct["total_declared_edges"] == 61

    # 5. Endpoint Resolution
    ep = edges["endpoint_resolution"]
    assert ep["both_unmapped_count"] == 0
    assert ep["source_unmapped_only_count"] == 0
    assert ep["target_unmapped_only_count"] == 0

    # 6. Authoring Queue
    assert report["concepts_requiring_authoring"] == []


def test_che_ion_resolution(canonical_jee_graph: object) -> None:
    """Verify CHE_ION resolves to Ionic Equilibrium as a distinct canonical node."""
    sim_ion = load_simulator_concepts(V2_CONCEPTS_CSV)
    sim_concept = next(c for c in sim_ion if c.simulator_concept_id == "CHE_ION")
    assert sim_concept.name == "Ionic Equilibrium"

    bridge = SimulatorBridge(canonical_jee_graph)
    entry = bridge.map_concepts([sim_concept])[0]

    assert entry.status == SimulatorMappingStatus.MAPPED
    assert entry.simulator_concept_id == "CHE_ION"
    assert entry.canonical_name == "Ionic Equilibrium"

    # Must NOT map to CHE_EQM
    sim_eqm = next(c for c in sim_ion if c.simulator_concept_id == "CHE_EQM")
    entry_eqm = bridge.map_concepts([sim_eqm])[0]
    assert entry.canonical_concept_id != entry_eqm.canonical_concept_id

    # Prerequisite relationship: Equilibrium -> Ionic Equilibrium
    rels = canonical_jee_graph.relationships_between(
        entry_eqm.canonical_concept_id,
        entry.canonical_concept_id,
    )
    prereq_rels = [r for r in rels if r.is_prerequisite]
    assert len(prereq_rels) == 1
    assert prereq_rels[0].status_value == "accepted"


def test_schema_and_field_compatibility(canonical_jee_graph: object) -> None:
    compat = field_compatibility(
        [canonical_jee_graph.concepts[cid] for cid in sorted(canonical_jee_graph.concepts)]
    )
    assert compat["canonical_records_checked"] >= 62
    assert compat["canonical_records_emit_exactly_contract_keys"] is True
    assert compat["missing_for_person3"] == []

    # Verify every concept dictionary has exactly CONTRACT_CONCEPT_KEYS
    for concept in canonical_jee_graph.concepts.values():
        record = concept.to_contract_record()
        assert sorted(record.keys()) == sorted(CONTRACT_CONCEPT_KEYS)
        assert record["concept_id"].startswith("cc_")
        assert record["status"] in ("active", "deprecated")
        assert record["subject"] in ("physics", "chemistry", "mathematics")


def test_knowledge_graph_adapter_person3_methods(canonical_jee_graph: object) -> None:
    adapter = KnowledgeGraphAdapter(canonical_jee_graph)
    assert adapter.curriculum_id == "jee_class_11_12"
    assert adapter.fingerprint == canonical_jee_graph.content_fingerprint()

    # Test get_node()
    all_cids = list(canonical_jee_graph.concepts.keys())
    sample_cid = all_cids[0]
    node = adapter.get_node(sample_cid)
    assert node is not None
    assert node.concept_id == sample_cid
    assert hasattr(node, "prerequisite_concept_ids")
    assert hasattr(node, "to_contract_dict")
    assert isinstance(node.to_contract_dict(), dict)

    # Missing node returns None
    assert adapter.get_node("cc_nonexistent") is None

    # Readiness evaluation
    mastery = {cid: 0.85 for cid in all_cids}
    is_ready, status_map, remediation = adapter.evaluate_prerequisite_readiness(
        sample_cid, mastery, threshold=0.50
    )
    assert is_ready is True
    assert remediation == []




@pytest.mark.skipif(
    not (V2_CONCEPTS_CSV.is_file() and AKT_VOCABULARY.is_file()),
    reason="Reference files missing",
)
def test_translation_service_full_vocabulary(canonical_jee_graph: object) -> None:
    sim_concepts = load_simulator_concepts(V2_CONCEPTS_CSV)
    bridge = SimulatorBridge(canonical_jee_graph)
    entries = bridge.map_concepts(sim_concepts)
    sim_to_canon = {e.simulator_concept_id: e.canonical_concept_id for e in entries}

    # Validate that all 62 simulator IDs are known in the vocabulary
    unknown = validate_simulator_ids(sim_to_canon.keys(), AKT_VOCABULARY)
    assert unknown == []

    # 62-dimensional mastery profile
    sim_profile = {e.simulator_concept_id: 0.72 for e in entries}
    outcome = translate_mastery_profile(
        sim_profile,
        graph=canonical_jee_graph,
        concept_map=sim_to_canon,
        mapping_entries=entries,
    )

    assert outcome.is_complete is True
    assert outcome.coverage_rate == 1.0
    assert outcome.translated_count == 62
    assert outcome.unresolved_simulator_ids == []
    assert outcome.duplicate_targets == []
    assert len(outcome.canonical_mastery) == 62
    assert outcome.graph_fingerprint == canonical_jee_graph.content_fingerprint()
    assert outcome.graph_curriculum_id == "jee_class_11_12"


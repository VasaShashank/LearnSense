"""
Canonical learner-graph adapter (Person 2 <-> Person 3 boundary).

Covers the query surface Person 3's learner model, readiness checks and
remediation sequencing call (``PrerequisiteGraph`` / ``KnowledgeGraphAdapter``
method names), loaded through Person 2's *real* interface (``CurriculumRepository``
/ ``CurriculumService``'s graph), plus the explicit-failure contract: no
canonical graph means an error, never a silent CSV/synthetic fallback.

Everything here uses synthetic fixtures for isolated testing.  Passing these
tests proves interface and direction compatibility; it is not evidence of
curriculum correctness (see docs/curriculum/PERSON3_INTEGRATION_ADDENDUM.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from curriculum.ids import generate_concept_id
from curriculum.learner_adapter import (
    CanonicalGraphUnavailableError,
    KnowledgeGraphAdapter,
)
from curriculum.models import (
    ConceptLifecycleStatus,
    ConceptRelationship,
    IdReference,
    RelationshipStatusEnum,
    RelationshipTypeEnum,
)
from curriculum.repository import CurriculumRepository
from curriculum.seed import CurriculumSpec, seed_curriculum


def concept_id_for(graph: Any, stable_key: str) -> str:
    """Canonical id of the concept seeded from ``stable_key``."""
    for concept in graph.concepts.values():
        if concept.stable_key == stable_key:
            return concept.concept_id
    raise AssertionError(f"no concept with stable_key '{stable_key}'")


@pytest.fixture
def pilot_adapter(pilot_graph) -> KnowledgeGraphAdapter:
    return KnowledgeGraphAdapter(pilot_graph)


# --------------------------------------------------------------- real interface
def test_adapter_loads_through_real_repository(pilot_graph, tmp_path: Path) -> None:
    repository = CurriculumRepository(base_dir=str(tmp_path / "store"))
    repository.save_graph(pilot_graph)

    adapter = KnowledgeGraphAdapter.from_repository(repository, "pilot_jee_v1")

    assert adapter.curriculum_id == "pilot_jee_v1"
    assert adapter.syllabus_version == pilot_graph.syllabus_version
    assert adapter.graph_fingerprint() == pilot_graph.content_fingerprint()
    assert len(adapter) == len(pilot_graph.concepts)
    assert adapter.concept_ids == sorted(pilot_graph.concepts)


def test_from_repository_missing_graph_is_explicit_error(tmp_path: Path) -> None:
    repository = CurriculumRepository(base_dir=str(tmp_path / "empty_store"))

    with pytest.raises(CanonicalGraphUnavailableError) as excinfo:
        KnowledgeGraphAdapter.from_repository(repository, "pilot_jee_v1")

    message = str(excinfo.value)
    assert "pilot_jee_v1" in message
    assert "seed" in message.lower()  # tells the operator the remedy
    # read-only: the failed load must not have created a store or graph file
    assert not (tmp_path / "empty_store").exists() or not any(
        (tmp_path / "empty_store").rglob("*.json")
    )


def test_constructor_rejects_non_canonical_graphs() -> None:
    for bogus in (None, {}, "storage/curriculum", object()):
        with pytest.raises(TypeError):
            KnowledgeGraphAdapter(bogus)  # type: ignore[arg-type]


def test_from_repository_requires_load_graph() -> None:
    with pytest.raises(TypeError):
        KnowledgeGraphAdapter.from_repository(object(), "pilot_jee_v1")  # type: ignore[arg-type]


# --------------------------------------------------------------- contract read
def test_get_concept_returns_contract_record(pilot_adapter, pilot_graph) -> None:
    target = concept_id_for(pilot_graph, "physics/kinematics/displacement")
    record = pilot_adapter.get_concept(target)

    assert record is not None
    assert sorted(record.keys()) == sorted(
        [
            "concept_id",
            "name",
            "description",
            "subject",
            "chapter_id",
            "tags",
            "status",
            "prerequisite_concept_ids",
            "source_refs",
            "metadata",
        ]
    )
    assert record["concept_id"] == target
    assert record["name"] == "Displacement"
    assert record["status"] == "active"


def test_get_concept_unknown_returns_none(pilot_adapter) -> None:
    assert pilot_adapter.get_concept("cc_does_not_exist") is None
    assert pilot_adapter.get_concept("") is None


def test_canonical_ids_stable_across_reseeds(tmp_path: Path) -> None:
    first = seed_curriculum(
        CurriculumSpec.model_validate(
            {
                "curriculum_id": "stable_check_v1",
                "concepts": [
                    {"stable_key": "physics/kinematics/x", "name": "X", "subject": "physics"}
                ],
            }
        )
    )
    second = seed_curriculum(
        CurriculumSpec.model_validate(
            {
                "curriculum_id": "stable_check_v1",
                "concepts": [
                    {
                        "stable_key": "physics/kinematics/x",
                        "name": "X (renamed)",
                        "subject": "physics",
                    }
                ],
            }
        )
    )
    expected = generate_concept_id("stable_check_v1", "physics/kinematics/x")
    assert KnowledgeGraphAdapter(first).concept_ids == [expected]
    assert KnowledgeGraphAdapter(second).concept_ids == [expected]


# ------------------------------------------------------------------- direction
def test_prerequisite_direction_matches_team_convention(pilot_adapter, pilot_graph) -> None:
    units = concept_id_for(pilot_graph, "physics/units/units-and-measurement")
    distance = concept_id_for(pilot_graph, "physics/kinematics/distance")
    displacement = concept_id_for(pilot_graph, "physics/kinematics/displacement")

    # A --prerequisite_of--> B  =>  get_direct_prerequisites(B) contains A
    assert pilot_adapter.get_direct_prerequisites(distance) == [units]
    assert pilot_adapter.get_direct_prerequisites(displacement) == [units]
    assert set(pilot_adapter.get_direct_dependents(units)) == {distance, displacement}
    assert pilot_adapter.get_prerequisites(distance) == [units]  # adapter alias
    assert set(pilot_adapter.get_dependents(units)) == {distance, displacement}


def test_transitive_closures(pilot_adapter, pilot_graph) -> None:
    units = concept_id_for(pilot_graph, "physics/units/units-and-measurement")
    displacement = concept_id_for(pilot_graph, "physics/kinematics/displacement")
    pt_graph = concept_id_for(pilot_graph, "physics/kinematics/position-time-graph")
    vt_graph = concept_id_for(pilot_graph, "physics/kinematics/velocity-time-graph")

    assert pilot_adapter.get_all_ancestor_prerequisites(vt_graph) == {
        units,
        displacement,
        pt_graph,
    }
    assert pilot_adapter.get_all_descendant_dependents(units) == {
        # 'distance' also depends on units but nothing depends on distance, so
        # it is a descendant of units, too.
        concept_id_for(pilot_graph, "physics/kinematics/distance"),
        displacement,
        pt_graph,
        vt_graph,
    }
    assert pilot_adapter.get_all_ancestor_prerequisites(units) == set()


def test_topological_order_respects_every_accepted_edge(pilot_adapter) -> None:
    order = pilot_adapter.get_all_concept_ids()
    assert order == pilot_adapter.topological_sort()
    position = {concept_id: index for index, concept_id in enumerate(order)}
    for concept_id in pilot_adapter.concept_ids:
        for prereq in pilot_adapter.get_direct_prerequisites(concept_id):
            assert position[prereq] < position[concept_id], (
                f"{prereq} must precede {concept_id}"
            )


def test_unknown_concept_raises_keyerror_like_person3(pilot_adapter) -> None:
    for call in (
        lambda: pilot_adapter.get_direct_prerequisites("cc_nope"),
        lambda: pilot_adapter.get_direct_dependents("cc_nope"),
        lambda: pilot_adapter.get_all_ancestor_prerequisites("cc_nope"),
        lambda: pilot_adapter.evaluate_prerequisite_readiness("cc_nope", {}),
        lambda: pilot_adapter.get_remediation_sequence("cc_nope", {}),
    ):
        with pytest.raises(KeyError):
            call()


# ------------------------------------------------------------------ readiness
def test_readiness_states_satisfied_unsatisfied_unknown(pilot_adapter, pilot_graph) -> None:
    units = concept_id_for(pilot_graph, "physics/units/units-and-measurement")
    distance = concept_id_for(pilot_graph, "physics/kinematics/displacement")

    ready, status_map, needed = pilot_adapter.evaluate_prerequisite_readiness(
        distance, {units: 0.9}
    )
    assert ready is True
    assert status_map == {units: "satisfied"}
    assert needed == []

    ready, status_map, needed = pilot_adapter.evaluate_prerequisite_readiness(
        distance, {units: 0.2}
    )
    assert ready is False
    assert status_map == {units: "unsatisfied"}
    assert needed == [units]

    ready, status_map, needed = pilot_adapter.evaluate_prerequisite_readiness(
        distance, {}
    )
    assert ready is False
    assert status_map == {units: "unknown"}
    assert needed == [units]


def test_readiness_root_concept_is_always_ready(pilot_adapter, pilot_graph) -> None:
    units = concept_id_for(pilot_graph, "physics/units/units-and-measurement")
    assert pilot_adapter.evaluate_prerequisite_readiness(units, {}) == (True, {}, [])


def test_remediation_sequence_is_topologically_ordered(pilot_adapter, pilot_graph) -> None:
    units = concept_id_for(pilot_graph, "physics/units/units-and-measurement")
    displacement = concept_id_for(pilot_graph, "physics/kinematics/displacement")
    pt_graph = concept_id_for(pilot_graph, "physics/kinematics/position-time-graph")
    vt_graph = concept_id_for(pilot_graph, "physics/kinematics/velocity-time-graph")

    sequence = pilot_adapter.get_remediation_sequence(vt_graph, {units: 0.9})
    assert sequence == [displacement, pt_graph]

    mastered = {units: 0.9, displacement: 0.9, pt_graph: 0.9}
    assert pilot_adapter.get_remediation_sequence(vt_graph, mastered) == []


# ------------------------------------------------- deprecated & historical ids
def test_deprecated_concept_leaves_traversal_but_stays_readable(pilot_graph) -> None:
    displacement = concept_id_for(pilot_graph, "physics/kinematics/displacement")
    pilot_graph.concepts[displacement].status = ConceptLifecycleStatus.DEPRECATED
    adapter = KnowledgeGraphAdapter(pilot_graph)

    assert displacement not in adapter.concept_ids
    assert adapter.contains(displacement) is False
    record = adapter.get_concept(displacement)
    assert record is not None and record["status"] == "deprecated"
    with pytest.raises(KeyError, match="deprecated"):
        adapter.get_direct_prerequisites(displacement)


def test_merged_id_resolves_forward_to_successor(pilot_graph) -> None:
    old_id = generate_concept_id(pilot_graph.curriculum_id, "physics/kinematics/legacy")
    successor = concept_id_for(pilot_graph, "physics/kinematics/distance")
    pilot_graph.concepts[old_id] = pilot_graph.concepts[successor].model_copy(
        update={"concept_id": old_id, "stable_key": "physics/kinematics/legacy"}
    )
    pilot_graph.concepts[old_id].status = ConceptLifecycleStatus.DEPRECATED
    pilot_graph.record_id_reference(
        IdReference(old_id=old_id, current_id=successor, relation="merged_into")
    )
    adapter = KnowledgeGraphAdapter(pilot_graph)

    assert adapter.resolve_concept_id(old_id) == successor
    assert adapter.contains(old_id) is True
    record = adapter.get_concept(old_id)
    assert record is not None
    assert record["concept_id"] == successor  # successor's record, not the tombstone's
    assert adapter.get_direct_prerequisites(old_id) == adapter.get_direct_prerequisites(
        successor
    )


def test_removed_id_resolves_to_nothing(pilot_graph) -> None:
    pilot_graph.record_id_reference(
        IdReference(old_id="cc_gone_123", relation="removed")
    )
    adapter = KnowledgeGraphAdapter(pilot_graph)

    assert adapter.resolve_concept_id("cc_gone_123") is None
    assert adapter.contains("cc_gone_123") is False
    assert adapter.get_concept("cc_gone_123") is None
    with pytest.raises(KeyError):
        adapter.get_direct_prerequisites("cc_gone_123")


# -------------------------------------------------------------- edge policies
def test_unreviewed_edges_excluded_by_default(tmp_path: Path) -> None:
    spec = CurriculumSpec.model_validate(
        {
            "curriculum_id": "edge_policy_v1",
            "concepts": [
                {"stable_key": "a", "name": "Alpha", "subject": "physics"},
                {"stable_key": "b", "name": "Beta", "subject": "physics"},
            ],
            "relationships": [
                {
                    "source_key": "a",
                    "target_key": "b",
                    "type": "prerequisite_of",
                    "status": "candidate",
                }
            ],
        }
    )
    graph = seed_curriculum(spec, validate=False)

    reviewed_only = KnowledgeGraphAdapter(graph)
    b_id = concept_id_for(graph, "b")
    a_id = concept_id_for(graph, "a")
    assert reviewed_only.get_direct_prerequisites(b_id) == []

    include_candidates = KnowledgeGraphAdapter(graph, accepted_only=False)
    assert include_candidates.get_direct_prerequisites(b_id) == [a_id]


def test_detect_cycles_on_valid_graph_is_empty(pilot_adapter) -> None:
    assert pilot_adapter.detect_cycles() == []
    assert pilot_adapter.validate_graph().is_valid is True
    assert pilot_adapter.find_invalid_prerequisite_references() == []


def test_detect_cycles_finds_constructed_cycle() -> None:
    spec = CurriculumSpec.model_validate(
        {
            "curriculum_id": "cycle_v1",
            "concepts": [
                {"stable_key": "a", "name": "Alpha", "subject": "physics"},
                {"stable_key": "b", "name": "Beta", "subject": "physics"},
            ],
        }
    )
    graph = seed_curriculum(spec)
    a_id = concept_id_for(graph, "a")
    b_id = concept_id_for(graph, "b")
    graph.add_relationship(
        ConceptRelationship.create(
            a_id,
            RelationshipTypeEnum.PREREQUISITE_OF,
            b_id,
            status=RelationshipStatusEnum.ACCEPTED,
        )
    )
    graph.add_relationship(
        ConceptRelationship.create(
            b_id,
            RelationshipTypeEnum.PREREQUISITE_OF,
            a_id,
            status=RelationshipStatusEnum.ACCEPTED,
        )
    )
    adapter = KnowledgeGraphAdapter(graph)

    cycles = adapter.detect_cycles()
    assert cycles, "a two-node cycle must be reported"
    assert any(set(cycle) == {a_id, b_id} for cycle in cycles)
    with pytest.raises(RuntimeError):
        adapter.topological_sort()


def test_find_invalid_prerequisite_references_reports_dangling_ids(pilot_graph) -> None:
    target = concept_id_for(pilot_graph, "physics/kinematics/distance")
    pilot_graph.concepts[target].prerequisite_concept_ids.append("cc_ghost_999")
    adapter = KnowledgeGraphAdapter(pilot_graph)

    assert (target, "cc_ghost_999") in adapter.find_invalid_prerequisite_references()


# ------------------------------------------------------------------ read-only
def test_adapter_never_mutates_graph_or_store(pilot_graph, tmp_path: Path) -> None:
    repository = CurriculumRepository(base_dir=str(tmp_path / "store"))
    repository.save_graph(pilot_graph)
    adapter = KnowledgeGraphAdapter.from_repository(repository, "pilot_jee_v1")
    fingerprint_before = adapter.graph_fingerprint()
    store_before = sorted(
        path.relative_to(tmp_path / "store") for path in (tmp_path / "store").rglob("*")
    )

    for concept_id in adapter.concept_ids:
        adapter.get_concept(concept_id)
        adapter.get_direct_prerequisites(concept_id)
        adapter.get_direct_dependents(concept_id)
        adapter.get_all_ancestor_prerequisites(concept_id)
        adapter.get_all_descendant_dependents(concept_id)
        adapter.evaluate_prerequisite_readiness(concept_id, {concept_id: 0.7})
        adapter.get_remediation_sequence(concept_id, {})
    adapter.topological_sort()
    adapter.validate_graph()
    adapter.detect_cycles()
    adapter.find_invalid_prerequisite_references()

    assert adapter.graph_fingerprint() == fingerprint_before
    store_after = sorted(
        path.relative_to(tmp_path / "store") for path in (tmp_path / "store").rglob("*")
    )
    assert store_after == store_before


def test_graph_version_facts_differ_between_curricula(tmp_path: Path) -> None:
    repository = CurriculumRepository(base_dir=str(tmp_path / "store"))
    repository.save_graph(seed_curriculum(CurriculumSpec.model_validate(
        {"curriculum_id": "version_a", "concepts": [
            {"stable_key": "a", "name": "Alpha", "subject": "physics"}]}
    )))
    repository.save_graph(seed_curriculum(CurriculumSpec.model_validate(
        {"curriculum_id": "version_b", "concepts": [
            {"stable_key": "a", "name": "Alpha", "subject": "physics"}]}
    )))

    adapter_a = KnowledgeGraphAdapter.from_repository(repository, "version_a")
    adapter_b = KnowledgeGraphAdapter.from_repository(repository, "version_b")

    assert adapter_a.curriculum_id != adapter_b.curriculum_id
    assert adapter_a.graph_fingerprint() != adapter_b.graph_fingerprint()

def test_get_node_exposes_contract_record_for_person3_wrapping(pilot_adapter, pilot_graph) -> None:
    """Person 3's adapter calls ``self._graph.get_node(id).to_contract_dict()``."""
    target = concept_id_for(pilot_graph, "physics/kinematics/displacement")
    node = pilot_adapter.get_node(target)

    assert node is not None
    assert node.to_contract_dict() == pilot_adapter.get_concept(target)
    assert pilot_adapter.get_node("cc_does_not_exist") is None

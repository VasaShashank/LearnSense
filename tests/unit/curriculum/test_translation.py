"""
Mastery-profile translation tests (Person 2).
"""

from __future__ import annotations

import pytest

from curriculum.models import ConceptLifecycleStatus, IdReference
from curriculum.seed import CurriculumSpec, seed_curriculum
from curriculum.simulator import SimulatorBridge, SimulatorConcept, SimulatorMappingEntry, SimulatorMappingStatus
from curriculum.translation import (
    UnknownSimulatorIdError,
    index_to_simulator_id,
    mastery_profile_from_indexed_output,
    translate_mastery_profile,
    validate_simulator_ids,
)


def two_concept_graph():
    return seed_curriculum(
        CurriculumSpec.model_validate(
            {
                "curriculum_id": "trans_v1",
                "concepts": [
                    {"stable_key": "chem/equilibrium", "name": "Equilibrium", "subject": "chemistry"},
                    {
                        "stable_key": "chem/ionic-equilibrium",
                        "name": "Ionic Equilibrium",
                        "subject": "chemistry",
                        "prerequisites": ["chem/equilibrium"],
                    },
                ],
            }
        )
    )


def sim_concepts():
    return [
        SimulatorConcept.from_row(
            {
                "concept_id": "SIM_A",
                "concept_name": "Equilibrium",
                "subject": "Chemistry",
                "topic_group": "Physical Chemistry",
                "prerequisite_ids": "",
                "curriculum_status": "illustrative_pilot_graph_map_to_canonical_LearnSense_graph",
            }
        ),
        SimulatorConcept.from_row(
            {
                "concept_id": "SIM_B",
                "concept_name": "Ionic Equilibrium",
                "subject": "Chemistry",
                "topic_group": "Physical Chemistry",
                "prerequisite_ids": "SIM_A",
                "curriculum_status": "illustrative_pilot_graph_map_to_canonical_LearnSense_graph",
            }
        ),
    ]


def approved_map_and_entries():
    graph = two_concept_graph()
    bridge = SimulatorBridge(graph)
    entries = bridge.map_concepts(sim_concepts())
    return graph, bridge.resolve_map(entries), entries

def test_known_simulator_id_translates_and_preserves_value():
    graph, concept_map, entries = approved_map_and_entries()
    result = translate_mastery_profile(
        {"SIM_A": 0.85, "SIM_B": 0.4}, graph=graph, concept_map=concept_map, mapping_entries=entries
    )
    assert result.canonical_mastery == {concept_map["SIM_A"]: 0.85, concept_map["SIM_B"]: 0.4}
    assert result.translated_count == 2
    assert result.total_count == 2
    assert result.coverage_rate == 1.0
    assert result.is_complete is True
    assert result.unresolved_simulator_ids == []
    assert result.duplicate_targets == []
    assert result.original_profile == {"SIM_A": 0.85, "SIM_B": 0.4}
    assert result.graph_curriculum_id == graph.curriculum_id
    assert result.graph_fingerprint == graph.content_fingerprint()


def test_unknown_simulator_id_is_unresolved_not_dropped():
    graph, concept_map, entries = approved_map_and_entries()
    result = translate_mastery_profile(
        {"SIM_A": 0.85, "SIM_GHOST": 0.2}, graph=graph, concept_map=concept_map, mapping_entries=entries
    )
    assert result.translated_count == 1
    assert result.total_count == 2
    assert result.coverage_rate == 0.5
    assert result.is_complete is False
    assert result.unresolved_simulator_ids == ["SIM_GHOST"]
    assert any(e.status == "unmapped" and e.simulator_concept_id == "SIM_GHOST" for e in result.entries)
    assert result.original_profile["SIM_GHOST"] == 0.2
    assert len(result.canonical_mastery) == 1


def test_ambiguous_entry_is_not_translated():
    graph = two_concept_graph()

    ambiguous_entry = SimulatorMappingEntry(
        simulator_concept_id="SIM_AMB",
        simulator_name="Ambiguous Concept",
        status=SimulatorMappingStatus.AMBIGUOUS,
        reason="needs human decision",
    )
    result = translate_mastery_profile({"SIM_AMB": 0.6}, graph=graph, mapping_entries=[ambiguous_entry])
    assert result.canonical_mastery == {}
    assert result.unresolved_simulator_ids == ["SIM_AMB"]
    assert result.entries[0].status == "ambiguous"
    assert result.is_complete is False


def test_unmapped_entry_is_not_translated():
    graph = two_concept_graph()

    entry = SimulatorMappingEntry(
        simulator_concept_id="SIM_UNM",
        simulator_name="Unmapped Concept",
        status=SimulatorMappingStatus.UNMAPPED,
        reason="no match",
    )
    result = translate_mastery_profile({"SIM_UNM": 0.7}, graph=graph, mapping_entries=[entry])
    assert result.canonical_mastery == {}
    assert result.unresolved_simulator_ids == ["SIM_UNM"]
    assert result.entries[0].status == "unmapped"


def test_deprecated_canonical_target_is_not_used():
    graph, concept_map, entries = approved_map_and_entries()
    target_id = concept_map["SIM_A"]
    graph.concepts[target_id].status = ConceptLifecycleStatus.DEPRECATED
    result = translate_mastery_profile(
        {"SIM_A": 0.9}, graph=graph, concept_map=concept_map, mapping_entries=entries
    )
    assert result.canonical_mastery == {}
    assert result.unresolved_simulator_ids == ["SIM_A"]
    assert result.entries[0].status == "deprecated_target"


def test_merged_historical_target_is_deprecated():
    graph, concept_map, entries = approved_map_and_entries()
    target_id = concept_map["SIM_A"]
    successor = concept_map["SIM_B"]
    graph.concepts[target_id].status = ConceptLifecycleStatus.DEPRECATED
    graph.record_id_reference(IdReference(old_id=target_id, current_id=successor, relation="merged_into"))
    result = translate_mastery_profile(
        {"SIM_A": 0.9}, graph=graph, concept_map=concept_map, mapping_entries=entries
    )
    assert result.canonical_mastery == {}
    assert result.entries[0].status == "deprecated_target"


def test_duplicate_canonical_target_is_conflict_not_aggregated():
    graph, concept_map, entries = approved_map_and_entries()
    dup_map = {"SIM_A": concept_map["SIM_A"], "SIM_B": concept_map["SIM_A"]}
    result = translate_mastery_profile({"SIM_A": 0.9, "SIM_B": 0.3}, graph=graph, concept_map=dup_map)
    assert result.canonical_mastery == {}
    assert result.duplicate_targets == [concept_map["SIM_A"]]
    assert all(e.status == "duplicate_target_conflict" for e in result.entries)
    assert result.is_complete is False
    assert result.original_profile == {"SIM_A": 0.9, "SIM_B": 0.3}


def test_partial_profile_translation():
    graph, concept_map, entries = approved_map_and_entries()
    result = translate_mastery_profile(
        {"SIM_A": 0.9, "SIM_B": 0.3, "SIM_X": 0.1, "SIM_Y": 0.2},
        graph=graph,
        concept_map=concept_map,
        mapping_entries=entries,
    )
    assert result.translated_count == 2
    assert result.total_count == 4
    assert result.coverage_rate == 0.5
    assert sorted(result.unresolved_simulator_ids) == ["SIM_X", "SIM_Y"]
    assert result.is_complete is False


def test_empty_profile_is_complete_vacuously():
    graph, concept_map, entries = approved_map_and_entries()
    result = translate_mastery_profile({}, graph=graph, concept_map=concept_map, mapping_entries=entries)
    assert result.canonical_mastery == {}
    assert result.translated_count == 0
    assert result.total_count == 0
    assert result.coverage_rate == 1.0
    assert result.is_complete is True
    assert result.unresolved_simulator_ids == []


def test_invalid_canonical_target_is_reported():
    graph, concept_map, entries = approved_map_and_entries()
    bad_map = {"SIM_A": "cc_does_not_exist"}
    result = translate_mastery_profile({"SIM_A": 0.9}, graph=graph, concept_map=bad_map)
    assert result.canonical_mastery == {}
    assert result.entries[0].status == "invalid_target"
    assert result.unresolved_simulator_ids == ["SIM_A"]


def test_no_concept_map_raises_value_error():
    graph = two_concept_graph()
    with pytest.raises(ValueError):
        translate_mastery_profile({"SIM_A": 0.9}, graph=graph)


def test_validate_simulator_ids_rejects_unknown():
    with pytest.raises(UnknownSimulatorIdError) as excinfo:
        validate_simulator_ids(["PHY_KIN", "NOPE"], {"PHY_KIN": 0})
    assert "NOPE" in str(excinfo.value)
    assert "index 0" in str(excinfo.value)
    assert validate_simulator_ids(["PHY_KIN"], {"PHY_KIN": 0}) == []


def test_validate_simulator_ids_accepts_vocabulary_object():
    class Vocab:
        concept_to_index = {"A": 0, "B": 1}

    assert validate_simulator_ids(["A", "B"], Vocab()) == []
    with pytest.raises(UnknownSimulatorIdError):
        validate_simulator_ids(["C"], Vocab())


def test_index_to_simulator_id_and_profile_from_indexed_output():
    vocab = {"concept_to_index": {"SIM_X": 0, "SIM_Y": 2}}
    reverse = index_to_simulator_id(vocab)
    assert reverse == {0: "SIM_X", 2: "SIM_Y"}
    profile = mastery_profile_from_indexed_output([0.1, 0.2, 0.3], vocab)
    assert profile == {"SIM_X": 0.1, "SIM_Y": 0.3}


def test_vocabulary_index_zero_is_not_implicit_fallback():
    vocab = {"concept_to_index": {"SIM_ONLY": 5}}
    profile = mastery_profile_from_indexed_output([9.9, 9.9, 9.9, 9.9, 9.9, 0.42], vocab)
    assert profile == {"SIM_ONLY": 0.42}
    with pytest.raises(UnknownSimulatorIdError):
        validate_simulator_ids(["UNKNOWN_ID"], vocab)


def test_model_output_and_graph_version_compatible():
    graph, concept_map, entries = approved_map_and_entries()
    result = translate_mastery_profile(
        {"SIM_A": 0.9}, graph=graph, concept_map=concept_map, mapping_entries=entries
    )
    assert result.graph_curriculum_id == graph.curriculum_id
    assert result.graph_fingerprint == graph.content_fingerprint()


def test_original_profile_not_mutated():
    graph, concept_map, entries = approved_map_and_entries()
    profile = {"SIM_A": 0.9}
    snapshot = dict(profile)
    translate_mastery_profile(profile, graph=graph, concept_map=concept_map, mapping_entries=entries)
    assert profile == snapshot

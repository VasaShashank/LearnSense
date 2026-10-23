"""
Simulator bridge (Person 2): explicit, auditable mapping of illustrative data.

The bridge is the only place simulator concept ids meet canonical ids, and the
tests enforce the two rules that matter:

* a simulator id never *becomes* a canonical id -- resolutions point at ids the
  canonical graph already owns, and
* every decision carries a status and a reason (mapped / ambiguous / unmapped),
  so nothing is silently adopted or silently dropped.

The real simulator CSV is read from the sibling ``References/`` archive when it
is present and skipped otherwise; the in-repo tests use hand-built rows so the
rule-table behaviour is exercised without external files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from curriculum.contract import validate_question_record
from curriculum.models import ConceptLifecycleStatus
from curriculum.simulator import (
    QuestionConceptRef,
    SimulatorBridge,
    SimulatorConcept,
    SimulatorMappingStatus,
    load_simulator_concepts,
)

#: The read-only simulator archive lives beside the repo (documented deviation).
SIMULATOR_CSV = (
    Path(__file__).resolve().parents[4]
    / "References"
    / "learnsense_jee_simulator_v2"
    / "concepts.csv"
)

#: Frozen canonical ids of the pilot fixture (hash-derived from
#: curriculum_id + stable_key, so pinning them here is the stability contract,
#: not a copy of a generated value).
UNITS_ID = "cc_f0c09b79a4103d6c"
DISPLACEMENT_ID = "cc_30cf33ecfcb33212"


def row(concept_id: str, name: str, prereqs: str = "", **extra) -> SimulatorConcept:
    return SimulatorConcept.from_row(
        {"concept_id": concept_id, "concept_name": name, "prerequisite_ids": prereqs, **extra}
    )


class TestSimulatorConceptRow:
    def test_from_row_reads_the_simulator_column_names(self):
        concept = SimulatorConcept.from_row(
            {
                "concept_id": "sim_1",
                "concept_name": "Velocity",
                "subject": "PHYSICS",
                "topic_group": "Kinematics",
                "prerequisite_ids": "sim_0; sim_2",
                "curriculum_status": "tested",
            }
        )
        assert concept.simulator_concept_id == "sim_1"
        assert concept.name == "Velocity"
        assert concept.subject == "physics"  # lowercased on the way in
        assert concept.prerequisite_ids == ["sim_0", "sim_2"]

    def test_from_row_tolerates_missing_optional_columns(self):
        concept = SimulatorConcept.from_row({"concept_id": "sim_2", "concept_name": "Work"})
        assert concept.subject == ""
        assert concept.prerequisite_ids == []
        assert concept.curriculum_status == ""

    def test_csv_loader_raises_instead_of_returning_empty(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_simulator_concepts(tmp_path / "concepts.csv")

    def test_csv_loader_parses_and_drops_rows_without_an_id(self, tmp_path):
        csv_path = tmp_path / "concepts.csv"
        csv_path.write_text(
            "concept_id,concept_name,subject,topic_group,prerequisite_ids,curriculum_status\n"
            "sim_a,Displacement,PHYSICS,Kinematics,sim_c; sim_d,tested\n"
            "sim_b,Work,,Mechanics,,\n"
            ",Nameless Row,,,,\n",
            encoding="utf-8",
        )
        concepts = load_simulator_concepts(csv_path)
        assert [c.simulator_concept_id for c in concepts] == ["sim_a", "sim_b"]
        assert concepts[0].prerequisite_ids == ["sim_c", "sim_d"]
        assert concepts[1].subject == ""


class TestConceptMapping:
    def test_exact_canonical_name_maps_decisively(self, pilot_graph):
        entry = SimulatorBridge(pilot_graph).map_concepts([row("s1", "Displacement")])[0]
        assert entry.status == SimulatorMappingStatus.MAPPED
        assert entry.canonical_concept_id == DISPLACEMENT_ID
        assert entry.match_strength == 1.0
        assert entry.match_kind.value == "canonical_name"
        assert entry.reason  # every decision explains itself
        assert not entry.via_override

    def test_alias_maps_with_the_alias_strength(self, pilot_graph):
        entry = SimulatorBridge(pilot_graph).map_concepts([row("s2", "path length")])[0]
        assert entry.status == SimulatorMappingStatus.MAPPED
        assert entry.match_strength == 0.92
        assert entry.match_kind.value == "alias"

    def test_tie_between_two_concepts_goes_to_a_human(self, pilot_graph):
        # "Time Graph" overlaps both *-time-graph concepts equally (R4 at 0.80).
        entry = SimulatorBridge(pilot_graph).map_concepts([row("s3", "Time Graph")])[0]
        assert entry.status == SimulatorMappingStatus.AMBIGUOUS
        assert entry.canonical_concept_id is None  # never a coin-flip auto-pick
        assert entry.match_strength == 0.8
        assert "2 canonical concepts matched within 0.05" in entry.reason
        assert len(entry.alternative_concept_ids) == 1

    @pytest.mark.parametrize("name", ["Phlogiston", "Velocity"])
    def test_no_match_stays_unmapped_with_a_reason(self, pilot_graph, name):
        entry = SimulatorBridge(pilot_graph).map_concepts([row("sx", name)])[0]
        assert entry.status == SimulatorMappingStatus.UNMAPPED
        assert entry.canonical_concept_id is None
        assert "no canonical name or alias matched" in entry.reason

    def test_deprecated_concepts_are_not_mapping_targets(self, pilot_graph):
        distance_id = next(
            cid for cid, c in pilot_graph.concepts.items() if c.name == "Distance"
        )
        pilot_graph.concepts[distance_id].status = ConceptLifecycleStatus.DEPRECATED
        entry = SimulatorBridge(pilot_graph).map_concepts([row("s6", "Distance")])[0]
        assert entry.status == SimulatorMappingStatus.UNMAPPED

    def test_canonical_ids_are_never_simulator_ids(self, pilot_graph):
        entries = SimulatorBridge(pilot_graph).map_concepts(
            [row("sim_1", "Displacement"), row("sim_2", "path length")]
        )
        for entry in entries:
            if entry.canonical_concept_id is not None:
                assert entry.canonical_concept_id in pilot_graph.concepts
                assert entry.canonical_concept_id.startswith("cc_")

    def test_mapping_never_mutates_the_canonical_graph(self, pilot_graph):
        before = pilot_graph.content_fingerprint()
        bridge = SimulatorBridge(pilot_graph)
        entries = bridge.map_concepts([row("a", "Displacement"), row("b", "Phlogiston")])
        bridge.summary(entries)
        bridge.resolve_map(entries)
        assert pilot_graph.content_fingerprint() == before

    def test_resolve_map_returns_only_confident_mappings(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph)
        entries = bridge.map_concepts(
            [row("a", "Displacement"), row("b", "Time Graph"), row("c", "Phlogiston")]
        )
        resolved = bridge.resolve_map(entries)
        assert set(resolved) == {"a"}
        assert resolved["a"] == DISPLACEMENT_ID


class TestExplicitOverride:
    def test_override_maps_without_a_name_match(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph, overrides={"s4": DISPLACEMENT_ID})
        entry = bridge.map_concepts([row("s4", "Phlogiston")])[0]
        assert entry.status == SimulatorMappingStatus.MAPPED
        assert entry.canonical_concept_id == DISPLACEMENT_ID
        assert entry.via_override

    def test_override_wins_over_the_name_match(self, pilot_graph):
        units_id = next(
            cid for cid, c in pilot_graph.concepts.items() if c.name == "Units and Measurement"
        )
        bridge = SimulatorBridge(pilot_graph, overrides={"s1": units_id})
        entry = bridge.map_concepts([row("s1", "Displacement")])[0]
        assert entry.canonical_concept_id == units_id
        assert entry.via_override

    def test_override_pointing_at_an_unknown_id_refuses_to_map(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph, overrides={"s4": "cc_does_not_exist"})
        entry = bridge.map_concepts([row("s4", "Phlogiston")])[0]
        assert entry.status == SimulatorMappingStatus.UNMAPPED
        assert entry.via_override
        assert entry.reason == "override points at unknown canonical concept 'cc_does_not_exist'"


class TestQuestionMapping:
    @pytest.fixture
    def bridge_and_map(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph)
        entries = bridge.map_concepts(
            [
                row("su", "Units and Measurement"),
                row("sd", "Displacement"),
                row("sx", "Phlogiston"),
            ]
        )
        return bridge, bridge.resolve_map(entries)

    def test_partial_unmapped_and_skipped_rows(self, bridge_and_map):
        bridge, concept_map = bridge_and_map
        refs = bridge.map_questions(
            [
                {"question_id": "q1", "primary_concept_id": "sd", "concept_ids": "su;sx"},
                {"question_id": "q2", "primary_concept_id": "sx"},
                {"question_id": "   "},
            ],
            concept_map,
        )
        assert [ref.question_id for ref in refs] == ["q1", "q2"]  # blank id skipped
        q1, q2 = refs
        assert q1.status == "partial"
        assert q1.primary_concept_id == DISPLACEMENT_ID
        assert q1.concept_ids == [DISPLACEMENT_ID, UNITS_ID]
        assert q1.unresolved_simulator_ids == ["sx"]
        # an unresolved primary is reported, never given a stand-in concept id
        assert q2.status == "unmapped"
        assert q2.primary_concept_id is None
        assert q2.concept_ids == []
        assert q2.unresolved_simulator_ids == ["sx"]

    def test_primary_missing_from_concept_ids_is_still_primary(self, bridge_and_map):
        bridge, concept_map = bridge_and_map
        ref = bridge.map_questions(
            [{"question_id": "q4", "primary_concept_id": "sd"}], concept_map
        )[0]
        assert ref.status == "complete"
        assert ref.concept_ids == [DISPLACEMENT_ID]
        assert ref.primary_concept_id == ref.concept_ids[0]

    def test_assesses_weights_and_roles(self, bridge_and_map):
        bridge, concept_map = bridge_and_map
        ref = bridge.map_questions(
            [{"question_id": "q1", "primary_concept_id": "sd", "concept_ids": "su;sx"}],
            concept_map,
        )[0]
        assert ref.to_contract_assesses() == [
            {"concept_id": DISPLACEMENT_ID, "weight": 0.7, "role": "primary"},
            {"concept_id": UNITS_ID, "weight": 0.3, "role": "secondary"},
        ]
        assert QuestionConceptRef(question_id="q0", concept_ids=[]).to_contract_assesses() == []

    def test_three_way_split_evenly_shares_the_remainder(self):
        ref = QuestionConceptRef(
            question_id="q5", primary_concept_id="a", concept_ids=["a", "b", "c"]
        )
        assesses = ref.to_contract_assesses()
        assert [entry["weight"] for entry in assesses] == [0.7, 0.15, 0.15]
        assert [entry["role"] for entry in assesses] == ["primary", "secondary", "supporting"]

    def test_bridge_output_satisfies_the_shared_question_contract(self, bridge_and_map):
        bridge, concept_map = bridge_and_map
        ref = bridge.map_questions(
            [{"question_id": "q1", "primary_concept_id": "sd", "concept_ids": "su;sx"}],
            concept_map,
        )[0]
        result = validate_question_record(
            {
                "question_id": "q1",
                "question_type": "single_choice",
                "prompt": "Which statement is correct?",
                "assesses": ref.to_contract_assesses(),
                "status": "active",
            }
        )
        assert result.ok
        assert result.error_count == 0


class TestPrerequisiteEdgeAudit:
    def test_backed_contradicted_and_unchecked_are_reported_separately(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph)
        concepts = [
            row("su", "Units and Measurement", prereqs="sd"),
            row("sd", "Displacement", prereqs="su;sx"),
        ]
        concept_map = bridge.resolve_map(bridge.map_concepts(concepts))
        report = bridge.prerequisite_edge_report(concepts, concept_map)

        assert report["checked"] == 2
        assert report["backing_rate"] == 0.5
        # units -> displacement exists canonically ...
        assert report["backed"] == [
            {
                "source": UNITS_ID,
                "target": DISPLACEMENT_ID,
                "source_sim": "su",
                "target_sim": "sd",
            }
        ]
        # ... while displacement -> units does not: a contradiction, not a match
        assert report["contradicted"] == [
            {
                "source": DISPLACEMENT_ID,
                "target": UNITS_ID,
                "source_sim": "sd",
                "target_sim": "su",
            }
        ]
        assert report["unchecked"] == [{"source_sim": "sx", "target_sim": "sd"}]
        assert "canonical graph is the source of truth" in report["note"]

    def test_unmapped_endpoints_never_invent_a_canonical_edge(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph)
        concepts = [row("sa", "Phlogiston", prereqs="sb"), row("sb", "Nonsense")]
        report = bridge.prerequisite_edge_report(concepts, {})
        assert report["checked"] == 0
        assert report["backed"] == []
        assert report["backing_rate"] == 0.0
        # only sa declares a prerequisite; with nothing mapped it stays unchecked
        assert report["unchecked"] == [{"source_sim": "sb", "target_sim": "sa"}]
        # endpoint resolution breakdown details
        assert report["endpoint_resolution"]["both_unmapped_count"] == 1
        assert report["endpoint_resolution"]["source_unmapped_only_count"] == 0
        assert report["endpoint_resolution"]["target_unmapped_only_count"] == 0
        assert report["structural_checks"]["is_dag"] is True

    def test_structural_checks_detect_cycles_self_loops_and_duplicates(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph)
        concepts = [
            row("s_loop", "Loop Concept", prereqs="s_loop;s_missing"),
            row("s_dup", "Duplicate Prereq", prereqs="s_loop;s_loop"),
            row("c1", "Cycle 1", prereqs="c2"),
            row("c2", "Cycle 2", prereqs="c1"),
        ]
        report = bridge.prerequisite_edge_report(concepts, {})
        struct = report["structural_checks"]
        assert struct["is_dag"] is False
        assert len(struct["cycles"]) >= 1
        assert struct["self_loops"] == [{"source_sim": "s_loop", "target_sim": "s_loop", "kind": "simulator_identity"}]
        assert struct["duplicates"] == [{"source_sim": "s_loop", "target_sim": "s_dup"}]
        assert struct["missing_endpoints"] == [{"source_sim": "s_missing", "target_sim": "s_loop", "missing": "source"}]


class TestSummary:
    def test_counts_partition_the_entries_and_state_the_fingerprint(self, pilot_graph):
        bridge = SimulatorBridge(pilot_graph)
        entries = bridge.map_concepts(
            [
                row("s1", "Displacement"),
                row("s2", "path length"),
                row("s3", "Time Graph"),
                row("s4", "Phlogiston"),
                row("s5", "Velocity"),
            ]
        )
        summary = bridge.summary(entries)
        assert summary["total"] == 5
        assert summary["mapped"] == 2
        assert summary["ambiguous"] == 1
        assert summary["unmapped"] == 2
        assert summary["excluded"] == 0
        assert summary["total"] == (
            summary["mapped"]
            + summary["ambiguous"]
            + summary["unmapped"]
            + summary["excluded"]
        )
        assert summary["mapped_rate"] == 0.4
        assert summary["unmapped_ids"] == ["s3", "s4", "s5"]
        assert summary["canonical_curriculum_id"] == pilot_graph.curriculum_id
        assert summary["canonical_fingerprint"] == pilot_graph.content_fingerprint()


@pytest.mark.skipif(
    not SIMULATOR_CSV.exists(),
    reason="read-only simulator archive not present beside the repo",
)
def test_real_simulator_csv_maps_deterministically_without_writing(pilot_graph):
    concepts = load_simulator_concepts(SIMULATOR_CSV)
    assert concepts
    before = pilot_graph.content_fingerprint()
    bridge = SimulatorBridge(pilot_graph)
    entries = bridge.map_concepts(concepts)
    summary = bridge.summary(entries)

    assert summary["total"] == len(concepts)
    assert summary["total"] == (
        summary["mapped"]
        + summary["ambiguous"]
        + summary["unmapped"]
        + summary["excluded"]
    )
    assert all(entry.reason for entry in entries)
    for canonical_id in bridge.resolve_map(entries).values():
        assert canonical_id in pilot_graph.concepts
    assert pilot_graph.content_fingerprint() == before

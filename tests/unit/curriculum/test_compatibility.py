"""
Compatibility-report generator (Person 2 <-> Person 3 id/field/edge audit).

The report is the reproducible artifact behind
``docs/curriculum/PERSON3_INTEGRATION_ADDENDUM.md``.  These tests pin its
honesty properties: partial coverage is reported as partial, overrides are the
only way a non-matching id resolves, contradictions are surfaced, and
``complete_compatibility`` cannot be true while anything is unresolved.

Synthetic fixtures only: a passing audit of toy data is interface evidence, not
a curriculum-correctness claim.
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
    main,
    write_report,
)
from curriculum.seed import CurriculumSpec, seed_curriculum
from curriculum.simulator import SimulatorConcept

#: External reference materials (read-only); tests skip when absent.
REFERENCES = Path(__file__).resolve().parents[4] / "References"
V2_CONCEPTS_CSV = REFERENCES / "learnsense_jee_simulator_v2" / "concepts.csv"
PERSON3_DIR = REFERENCES / "LearnSense-Person3-FINAL"
AKT_VOCABULARY = PERSON3_DIR / "data" / "models" / "akt_vocabulary.json"
PERSON3_V3_CONCEPTS_CSV = PERSON3_DIR / "data" / "synthetic jee" / "v3" / "concepts.csv"


def canonical_graph() -> object:
    """Two-concept canonical graph with one accepted prerequisite edge."""
    return seed_curriculum(
        CurriculumSpec.model_validate(
            {
                "curriculum_id": "compat_v1",
                "title": "Compatibility slice",
                "concepts": [
                    {
                        "stable_key": "chem/equilibrium",
                        "name": "Equilibrium",
                        "subject": "chemistry",
                    },
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


def sim_concept(concept_id: str, name: str, prereqs: str = "") -> SimulatorConcept:
    return SimulatorConcept.from_row(
        {
            "concept_id": concept_id,
            "concept_name": name,
            "subject": "Chemistry",
            "topic_group": "Physical Chemistry",
            "prerequisite_ids": prereqs,
            "curriculum_status": "illustrative_pilot_graph_map_to_canonical_LearnSense_graph",
        }
    )


# ---------------------------------------------------------------- vocabulary IO
def test_load_akt_vocabulary_concepts_from_synthetic(tmp_path: Path) -> None:
    vocab = tmp_path / "akt_vocabulary.json"
    vocab.write_text(
        json.dumps({"question_to_index": {"JQ1": 0}, "concept_to_index": {"PHY_KIN": 0, "CHE_EQM": 1}}),
        encoding="utf-8",
    )
    assert load_akt_vocabulary_concepts(vocab) == ["CHE_EQM", "PHY_KIN"]


def test_load_akt_vocabulary_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_akt_vocabulary_concepts(tmp_path / "nope.json")


def test_load_akt_vocabulary_malformed_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"concept_to_index": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_akt_vocabulary_concepts(bad)


# ------------------------------------------------------------------ report core
def test_partial_coverage_reported_as_partial() -> None:
    graph = canonical_graph()
    concepts = [
        sim_concept("CHE_EQM", "Equilibrium"),  # exact canonical-name match
        sim_concept("CHE_AMN", "Amines"),  # no canonical counterpart
    ]
    report = build_compatibility_report(
        graph, concepts, vocabulary_concept_ids=["CHE_EQM", "CHE_AMN", "PHY_KIN"]
    )

    matched = report["akt_vocabulary"]["matched"]
    assert [row["vocabulary_concept_id"] for row in matched] == ["CHE_EQM"]
    assert matched[0]["canonical_name"] == "Equilibrium"
    assert matched[0]["via_override"] is False
    assert [row["vocabulary_concept_id"] for row in report["akt_vocabulary"]["unmapped"]] == [
        "CHE_AMN"
    ]
    assert report["akt_vocabulary"]["not_in_concept_csv"] == ["PHY_KIN"]
    assert report["akt_vocabulary"]["coverage_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert report["claims"]["complete_compatibility"] is False
    assert any("unmapped" in reason for reason in report["claims"]["reasons"])
    assert any("absent from the supplied concepts CSV" in reason for reason in report["claims"]["reasons"])


def test_ambiguous_band_is_reported_not_forced() -> None:
    # Graph holding only 'Equilibrium': simulator 'Ionic Equilibrium' then lands
    # in the 0.60-0.90 uncertain band (R3/R4 containment), which must stay ambiguous.
    graph = seed_curriculum(
        CurriculumSpec.model_validate(
            {
                "curriculum_id": "compat_ambiguous_v1",
                "concepts": [
                    {"stable_key": "chem/equilibrium", "name": "Equilibrium", "subject": "chemistry"}
                ],
            }
        )
    )
    report = build_compatibility_report(
        graph, [sim_concept("CHE_ION", "Ionic Equilibrium")], ["CHE_ION"]
    )
    assert report["akt_vocabulary"]["ambiguous"], "in-between match must be ambiguous"
    assert report["akt_vocabulary"]["matched"] == []
    assert report["claims"]["complete_compatibility"] is False


def test_full_resolution_can_claim_compatibility() -> None:
    graph = canonical_graph()
    concepts = [
        sim_concept("SIM_A", "Equilibrium"),
        sim_concept("SIM_B", "Ionic Equilibrium", prereqs="SIM_A"),
    ]
    report = build_compatibility_report(graph, concepts, ["SIM_A", "SIM_B"])

    assert report["akt_vocabulary"]["coverage_rate"] == 1.0
    assert report["prerequisite_edges"]["checked"] == 1
    backed = report["prerequisite_edges"]["backed"]
    assert len(backed) == 1
    assert backed[0]["source_sim"] == "SIM_A" and backed[0]["target_sim"] == "SIM_B"
    assert backed[0]["source"] != backed[0]["target"]  # canonical ids, not simulator ids
    assert report["prerequisite_edges"]["contradicted"] == []
    assert report["claims"]["complete_compatibility"] is True
    assert report["claims"]["reasons"] == []


def test_contradicted_edge_blocks_compatibility_claim() -> None:
    graph = canonical_graph()  # canonical: Equilibrium -> Ionic Equilibrium
    # Flip direction: simulator says Ionic Equilibrium precedes Equilibrium.
    concepts = [
        sim_concept("SIM_A", "Equilibrium", prereqs="SIM_B"),
        sim_concept("SIM_B", "Ionic Equilibrium"),
    ]
    report = build_compatibility_report(graph, concepts, ["SIM_A", "SIM_B"])

    contradicted = report["prerequisite_edges"]["contradicted"]
    assert len(contradicted) == 1
    assert contradicted[0]["source_sim"] == "SIM_B"
    assert contradicted[0]["target_sim"] == "SIM_A"
    assert report["claims"]["complete_compatibility"] is False
    assert any("contradict" in reason for reason in report["claims"]["reasons"])


def test_override_resolves_and_unknown_override_is_explicit() -> None:
    graph = canonical_graph()
    concepts = [sim_concept("CHE_MOL", "Some Basic Concepts / Mole Concept")]
    report = build_compatibility_report(graph, concepts, ["CHE_MOL"])
    assert report["akt_vocabulary"]["unmapped"], "no rule-table path without an override"

    graph_id = next(iter(graph.concepts))  # type: ignore[attr-defined]
    report = build_compatibility_report(
        graph, concepts, ["CHE_MOL"], overrides={"CHE_MOL": graph_id}
    )
    matched = report["akt_vocabulary"]["matched"]
    assert matched and matched[0]["via_override"] is True
    assert matched[0]["match_strength"] == 1.0

    report = build_compatibility_report(
        graph, concepts, ["CHE_MOL"], overrides={"CHE_MOL": "cc_unknown"}
    )
    assert report["akt_vocabulary"]["unmapped"]
    assert "override points at unknown canonical concept" in report["akt_vocabulary"]["unmapped"][0]["reason"]


def test_deprecated_concepts_reported_and_never_mapped() -> None:
    from curriculum.models import ConceptLifecycleStatus

    graph = canonical_graph()
    equilibrium_id = next(
        concept.concept_id
        for concept in graph.concepts.values()
        if concept.name == "Equilibrium"
    )
    graph.concepts[equilibrium_id].status = ConceptLifecycleStatus.DEPRECATED

    report = build_compatibility_report(
        graph, [sim_concept("CHE_EQM", "Equilibrium")], ["CHE_EQM"]
    )
    assert report["canonical"]["deprecated_concept_ids"] == [equilibrium_id]
    assert report["akt_vocabulary"]["matched"] == []
    entry = report["akt_vocabulary"]["unmapped"] + report["akt_vocabulary"]["ambiguous"]
    assert entry, "deprecated targets must not receive mappings; the id stays unresolved"
    assert entry[0]["canonical_concept_id"] is None


def test_canonical_section_records_identity_and_policy() -> None:
    graph = canonical_graph()
    report = build_compatibility_report(graph, [], [])
    canonical = report["canonical"]
    assert canonical["curriculum_id"] == "compat_v1"
    assert canonical["fingerprint"] == graph.content_fingerprint()
    assert canonical["accepted_prerequisite_edge_count"] == 1
    assert canonical["id_policy"]["simulator_ids_are_canonical"] is False
    assert (
        canonical["traversal_policy"]["edge_convention"]
        == "A --prerequisite_of--> B means A is a prerequisite of B"
    )


def test_field_compatibility_on_canonical_records() -> None:
    graph = canonical_graph()
    result = field_compatibility(list(graph.concepts.values()))  # type: ignore[arg-type]
    assert result["canonical_records_checked"] == 2
    assert result["canonical_records_emit_exactly_contract_keys"] is True
    assert result["missing_for_person3"] == []
    assert sorted(CONTRACT_CONCEPT_KEYS) == sorted(result["person3_required_fields"])


# ------------------------------------------------------------------ determinism
def test_write_report_is_deterministic(tmp_path: Path) -> None:
    graph = canonical_graph()
    report = build_compatibility_report(
        graph, [sim_concept("SIM_A", "Equilibrium")], ["SIM_A"]
    )
    first = write_report(report, tmp_path / "a.json")
    second = write_report(report, tmp_path / "b.json")
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("\n")


# ------------------------------------------------------------------------ CLI
def test_cli_end_to_end_on_synthetic_inputs(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "curriculum_id": "cli_v1",
                "concepts": [
                    {"stable_key": "chem/equilibrium", "name": "Equilibrium", "subject": "chemistry"}
                ],
            }
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "concepts.csv"
    csv_path.write_text(
        "concept_id,subject,concept_name,topic_group,prerequisite_ids,curriculum_status\n"
        "CHE_EQM,Chemistry,Equilibrium,Physical Chemistry,,illustrative_pilot\n",
        encoding="utf-8",
    )
    vocab_path = tmp_path / "akt_vocabulary.json"
    vocab_path.write_text(json.dumps({"concept_to_index": {"CHE_EQM": 0}}), encoding="utf-8")
    out_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--spec", str(spec_path),
            "--concepts-csv", str(csv_path),
            "--vocabulary", str(vocab_path),
            "--out", str(out_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["report_kind"] == "learnsense_person3_curriculum_compatibility"
    assert payload["claims"]["complete_compatibility"] is True


# --------------------------------------------------- external reference materials
@pytest.mark.skipif(not AKT_VOCABULARY.is_file(), reason="Person 3 reference drop not extracted")
def test_real_akt_vocabulary_against_pilot_graph() -> None:
    """The real 62-id vocabulary against the 10-concept canonical pilot slice."""
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "curriculum" / "pilot_dataset.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    spec_keys = ("curriculum_id", "syllabus_version", "title", "concepts", "relationships", "metadata")
    spec = CurriculumSpec.model_validate({key: raw[key] for key in spec_keys if key in raw})
    graph = seed_curriculum(spec)
    from curriculum.simulator import load_simulator_concepts

    concepts = load_simulator_concepts(PERSON3_V3_CONCEPTS_CSV if PERSON3_V3_CONCEPTS_CSV.is_file() else V2_CONCEPTS_CSV)
    vocabulary = load_akt_vocabulary_concepts(AKT_VOCABULARY)

    report = build_compatibility_report(graph, concepts, vocabulary)

    assert len(vocabulary) == 62
    assert report["akt_vocabulary"]["concept_count"] == 62
    coverage = report["akt_vocabulary"]["coverage_rate"]
    assert 0.0 <= coverage < 1.0, "the pilot slice cannot cover the full vocabulary"
    assert report["claims"]["complete_compatibility"] is False
    # every vocabulary id lands in exactly one honest bucket
    buckets = (
        report["akt_vocabulary"]["matched"]
        + report["akt_vocabulary"]["ambiguous"]
        + report["akt_vocabulary"]["unmapped"]
    )
    assert len(buckets) + len(report["akt_vocabulary"]["not_in_concept_csv"]) == 62

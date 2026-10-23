"""
Reproducible Person 3 <-> canonical curriculum compatibility audit (Person 2).

Answers, mechanically and from real data, the questions the Person 3 integration
asked:

* which AKT vocabulary / simulator concept ids map onto canonical concepts
  (explicit override first, then the shared rule table -- never display-name
  guessing beyond the documented rules R1-R5);
* which are ambiguous or unmapped (reported as such, never forced);
* whether simulator prerequisite edges are backed by accepted canonical edges;
* whether a canonical concept record satisfies the shared ``concept_schema.json``
  contract Person 3 validates;
* whether the canonical graph identity (curriculum id, syllabus version,
  fingerprint) is recorded so incompatible graph versions can be detected.

The report is honest by construction: ``claims.complete_compatibility`` is
``True`` only when every vocabulary concept resolved decisively, no prerequisite
edge contradicted the canonical graph, and the canonical graph carried the full
vocabulary's concept set.  Partial coverage is reported as partial.

Run it reproducibly (from the repository root)::

    python -m curriculum.compatibility \
        --spec tests/fixtures/curriculum/pilot_dataset.json \
        --concepts-csv "<reference>/learnsense_jee_simulator_v2/concepts.csv" \
        --vocabulary "<person3>/data/models/akt_vocabulary.json" \
        --out docs/curriculum/person3_compatibility_report.json

The canonical graph is built in memory from ``--spec`` via ``seed_curriculum``;
no repository or storage directory is read or written, so generating the report
cannot mutate a deployed curriculum.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from curriculum.learner_adapter import KnowledgeGraphAdapter
from curriculum.seed import CurriculumSpec, seed_curriculum
from curriculum.simulator import (
    SimulatorBridge,
    SimulatorConcept,
    SimulatorMappingStatus,
    load_simulator_concepts,
)

__all__ = [
    "CONTRACT_CONCEPT_KEYS",
    "PERSON3_CONCEPT_NODE_FIELDS",
    "build_compatibility_report",
    "field_compatibility",
    "load_akt_vocabulary_concepts",
    "main",
    "write_report",
]

#: The ten keys of the shared proposed ``concept_schema.json`` (Draft 2020-12).
CONTRACT_CONCEPT_KEYS = [
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

#: Fields Person 3's ``ConceptNode.to_contract_dict()`` emits and their
#: adapter/readiness code relies on.
PERSON3_CONCEPT_NODE_FIELDS = [
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


def load_akt_vocabulary_concepts(path: str | Path) -> List[str]:
    """
    Read the concept ids out of Person 3's ``akt_vocabulary.json``.

    ``concept_to_index`` is the vocabulary the trained checkpoint was fitted
    with, so it -- not any CSV -- defines the *relevant* id set for mastery
    estimation.  Raises ``FileNotFoundError`` and ``ValueError`` rather than
    returning an empty set, so a missing/malformed vocabulary is a visible
    failure.
    """
    vocab_path = Path(path)
    if not vocab_path.is_file():
        raise FileNotFoundError(f"AKT vocabulary not found: {vocab_path}")
    payload = json.loads(vocab_path.read_text(encoding="utf-8"))
    mapping = payload.get("concept_to_index")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(
            f"AKT vocabulary '{vocab_path}' has no non-empty 'concept_to_index' object"
        )
    return sorted(str(key) for key in mapping)


def field_compatibility(graph_concepts: Sequence[Any]) -> Dict[str, Any]:
    """
    Contract-field check of canonical concept records against Person 3's needs.

    Uses ``CanonicalConcept.to_contract_record()`` -- the exact serialization the
    shared contract constrains -- and reports any of the fields Person 3's
    ``ConceptNode.to_contract_dict()`` surface that would be missing.
    """
    records = [concept.to_contract_record() for concept in graph_concepts]
    key_sets = [sorted(record.keys()) for record in records]
    contract_keys_ok = all(keys == sorted(CONTRACT_CONCEPT_KEYS) for keys in key_sets)
    missing_per_record = {
        record.get("concept_id", "<no-id>"): [
            field for field in PERSON3_CONCEPT_NODE_FIELDS if field not in record
        ]
        for record in records
    }
    missing_any = sorted({field for fields in missing_per_record.values() for field in fields})
    return {
        "contract": "LearnSense_Shared_Contracts_v0_1/schemas/concept_schema.json (draft 2020-12)",
        "canonical_records_checked": len(records),
        "canonical_records_emit_exactly_contract_keys": contract_keys_ok,
        "person3_required_fields": PERSON3_CONCEPT_NODE_FIELDS,
        "missing_for_person3": missing_any,
        "notes": [
            "Person 2 keeps aliases, topic_path, class_levels, review_status, "
            "curriculum_id, curriculum_version, stable_key and audit inside the "
            "contract's open 'metadata' object; the record itself stays "
            "contract-valid (see docs/curriculum/CONTRACT_REVIEW.md).",
            "Person 3's ConceptNode has a 'topic_group' field that is not in the "
            "contract; the canonical equivalents are chapter_id and "
            "metadata.topic_path. No contract expansion is proposed here.",
        ],
    }


def build_compatibility_report(
    graph: Any,
    simulator_concepts: Sequence[SimulatorConcept],
    vocabulary_concept_ids: Sequence[str],
    overrides: Optional[Dict[str, str]] = None,
    sources: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Full compatibility report of one canonical graph against one id universe.

    ``simulator_concepts`` are the rows of a simulator ``concepts.csv`` (the
    metadata the rule table matches on); ``vocabulary_concept_ids`` are the ids
    the AKT checkpoint actually uses.  Keeping the two inputs separate makes
    vocabulary drift (an id in the model but not in the CSV, or vice versa)
    visible instead of hidden.
    """
    bridge = SimulatorBridge(graph, overrides=overrides)
    entries = bridge.map_concepts(simulator_concepts)
    by_sim_id = {entry.simulator_concept_id: entry for entry in entries}
    mapped = bridge.resolve_map(entries)

    # ---- vocabulary coverage, per id
    vocab_matched: List[Dict[str, Any]] = []
    vocab_ambiguous: List[Dict[str, Any]] = []
    vocab_unmapped: List[Dict[str, Any]] = []
    vocab_not_in_csv: List[str] = []
    for vocab_id in sorted(set(vocabulary_concept_ids)):
        entry = by_sim_id.get(vocab_id)
        if entry is None:
            vocab_not_in_csv.append(vocab_id)
            continue
        record: Dict[str, Any] = {
            "vocabulary_concept_id": vocab_id,
            "simulator_name": entry.simulator_name,
            "status": entry.status.value,
            "canonical_concept_id": entry.canonical_concept_id,
            "canonical_name": entry.canonical_name or None,
            "match_strength": entry.match_strength,
            "match_kind": entry.match_kind.value if entry.match_kind else None,
            "via_override": entry.via_override,
            "reason": entry.reason,
        }
        if entry.status == SimulatorMappingStatus.MAPPED:
            vocab_matched.append(record)
        elif entry.status == SimulatorMappingStatus.AMBIGUOUS:
            vocab_ambiguous.append(record)
        else:
            vocab_unmapped.append(record)

    total_vocab = len(set(vocabulary_concept_ids))
    decisive = len(vocab_matched)
    csv_only_unmapped = [
        entry.simulator_concept_id
        for entry in entries
        if entry.simulator_concept_id not in set(vocabulary_concept_ids)
        and entry.status != SimulatorMappingStatus.MAPPED
    ]

    # ---- prerequisite edges, simulator -> canonical
    edge_report = bridge.prerequisite_edge_report(simulator_concepts, mapped)

    # ---- concepts that still need canonical authoring / review
    concepts_requiring_authoring_list: List[Dict[str, Any]] = []
    for entry in entries:
        if entry.status in (SimulatorMappingStatus.AMBIGUOUS, SimulatorMappingStatus.UNMAPPED):
            sim = next(
                (c for c in simulator_concepts if c.simulator_concept_id == entry.simulator_concept_id),
                None,
            )
            concepts_requiring_authoring_list.append(
                {
                    "simulator_concept_id": entry.simulator_concept_id,
                    "simulator_name": entry.simulator_name,
                    "subject": getattr(sim, "subject", ""),
                    "topic_group": getattr(sim, "topic_group", ""),
                    "simulator_prerequisites": list(getattr(sim, "prerequisite_ids", []) or []),
                    "status": entry.status.value,
                    "reason": entry.reason,
                    "required_evidence": [
                        "verified canonical concept record (name, subject, chapter_id, class_levels, tags)",
                        "reviewed canonical prerequisite edges",
                        "curriculum editor approval (override) or an approved alias addition",
                    ],
                }
            )
    concepts_requiring_authoring_list.sort(key=lambda item: item["simulator_concept_id"])
    active_concepts = [
        concept
        for concept in graph.concepts.values()
        if getattr(concept.status, "value", concept.status) != "deprecated"
    ]
    deprecated_ids = sorted(
        concept_id
        for concept_id, concept in graph.concepts.items()
        if getattr(concept.status, "value", concept.status) == "deprecated"
    )
    adapter = KnowledgeGraphAdapter(graph)
    accepted_edge_count = len(graph.prerequisite_edges(include_unreviewed=False))

    reasons: List[str] = []
    if vocab_unmapped or vocab_ambiguous:
        reasons.append(
            f"{len(vocab_unmapped)} vocabulary concept(s) unmapped and "
            f"{len(vocab_ambiguous)} ambiguous against the canonical graph; "
            "a curriculum editor must extend the canonical graph or provide overrides"
        )
    if vocab_not_in_csv:
        reasons.append(
            f"{len(vocab_not_in_csv)} vocabulary id(s) absent from the supplied concepts CSV"
        )
    if edge_report["contradicted"]:
        reasons.append(
            f"{len(edge_report['contradicted'])} simulator prerequisite edge(s) contradict "
            "the accepted canonical graph"
        )
    if edge_report["unchecked"]:
        reasons.append(
            f"{len(edge_report['unchecked'])} simulator prerequisite edge(s) could not be "
            "checked (unmapped endpoint); they are NOT verified"
        )
    if decisive < total_vocab:
        reasons.append(
            f"canonical graph covers {decisive}/{total_vocab} of the AKT vocabulary's concepts"
        )

    report: Dict[str, Any] = {
        "report_kind": "learnsense_person3_curriculum_compatibility",
        "report_version": 1,
        "sources": dict(sources or {}),
        "canonical": {
            "curriculum_id": graph.curriculum_id,
            "syllabus_version": graph.syllabus_version,
            "title": graph.title,
            "fingerprint": graph.content_fingerprint(),
            "concept_count": len(graph.concepts),
            "active_concept_count": len(active_concepts),
            "deprecated_concept_ids": deprecated_ids,
            "accepted_prerequisite_edge_count": accepted_edge_count,
            "total_relationship_count": len(graph.relationships),
            "id_policy": {
                "canonical_id_scheme": "cc_<sha256(curriculum_id::stable_key)[:16]>, frozen at creation",
                "simulator_ids_are_canonical": False,
                "historical_ids_resolve_via": "graph.id_map (merged_into / replaced_by forward; removed resolves to nothing)",
                "graph_version_detection": "compare curriculum_id + syllabus_version + content_fingerprint()",
            },
            "traversal_policy": {
                "edge_convention": "A --prerequisite_of--> B means A is a prerequisite of B",
                "accepted_only_default": adapter.accepted_only,
                "deprecated_concepts_in_traversal": False,
            },
        },
        "akt_vocabulary": {
            "concept_count": total_vocab,
            "matched": vocab_matched,
            "ambiguous": vocab_ambiguous,
            "unmapped": vocab_unmapped,
            "not_in_concept_csv": vocab_not_in_csv,
            "coverage_rate": round(decisive / total_vocab, 4) if total_vocab else 0.0,
            "note": (
                "The vocabulary ids are simulator ids (PHY_*/CHE_*/MAT_*), never "
                "canonical ids. 'matched' rows are the only ids safe to carry into "
                "learner-state records, and only together with an explicit mapping; "
                "unmapped/ambiguous rows must stay unresolved until a curriculum "
                "editor decides."
            ),
        },
        "simulator_concepts": {
            "summary": bridge.summary(entries),
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "unmapped_in_csv_but_not_in_vocabulary": sorted(csv_only_unmapped),
        },
        "prerequisite_edges": edge_report,
        "concepts_requiring_authoring": concepts_requiring_authoring_list,
        "field_compatibility": field_compatibility(
            [graph.concepts[cid] for cid in sorted(graph.concepts)]
        ),
        "claims": {
            "complete_compatibility": not reasons,
            "reasons": reasons,
            "disclaimer": (
                "This report is a mechanical id/field/edge audit of the supplied "
                "inputs. It is not expert review of the curriculum and makes no "
                "accuracy claim about either model."
            ),
        },
    }
    return report


def write_report(report: Dict[str, Any], out_path: str | Path) -> Path:
    """Write the report as pretty, key-sorted JSON (deterministic bytes for diffs)."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m curriculum.compatibility",
        description="Reproducible Person 3 <-> canonical curriculum compatibility report",
    )
    parser.add_argument("--spec", required=True, help="Curriculum seed spec JSON (canonical source)")
    parser.add_argument("--concepts-csv", required=True, help="Simulator concepts.csv (read-only)")
    parser.add_argument("--vocabulary", required=True, help="akt_vocabulary.json (the model's id universe)")
    parser.add_argument("--out", required=True, help="Where to write the JSON report")
    parser.add_argument(
        "--overrides",
        default=None,
        help="Optional JSON file of {simulator_id: canonical_id} reviewed overrides",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    # The pilot fixture doubles as an evaluation reference; keep only the keys
    # the seed schema accepts (same filter tests/unit/curriculum/conftest.py uses).
    spec_keys = ("curriculum_id", "syllabus_version", "title", "concepts", "relationships", "metadata")
    raw_spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    spec = CurriculumSpec.model_validate({key: raw_spec[key] for key in spec_keys if key in raw_spec})
    graph = seed_curriculum(spec, repository=None)  # in-memory only; no storage touched
    concepts = load_simulator_concepts(args.concepts_csv)
    vocabulary = load_akt_vocabulary_concepts(args.vocabulary)
    overrides: Optional[Dict[str, str]] = None
    if args.overrides:
        overrides = json.loads(Path(args.overrides).read_text(encoding="utf-8"))

    report = build_compatibility_report(
        graph,
        concepts,
        vocabulary,
        overrides=overrides,
        sources={
            "canonical_spec": str(args.spec),
            "simulator_concepts_csv": str(args.concepts_csv),
            "akt_vocabulary": str(args.vocabulary),
            "overrides": str(args.overrides) if args.overrides else None,
        },
    )
    path = write_report(report, args.out)
    print(f"wrote {path}")
    print(
        "coverage "
        f"{report['akt_vocabulary']['coverage_rate']:.2%} "
        f"({len(report['akt_vocabulary']['matched'])}/"
        f"{report['akt_vocabulary']['concept_count']} vocabulary concepts), "
        f"complete_compatibility={report['claims']['complete_compatibility']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())

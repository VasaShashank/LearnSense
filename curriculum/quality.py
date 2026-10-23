"""
Structural graph-quality reporting (Person 2).

These metrics describe the *shape and provenance* of the canonical graph and the
behaviour of the mapper and the review queue.  They need no gold standard, so
they can be computed on every commit.

They are **not** a claim of semantic correctness.  A graph can be perfectly
acyclic, fully sourced and 100% reviewed and still teach the wrong physics.
Semantic precision/recall against a reviewed reference set lives in
``evaluation/curriculum_eval.py`` and is reported separately, on purpose.

Every metric carries its denominator in ``definitions``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from curriculum.graph import CurriculumGraphValidator
from curriculum.mapping import ContentMappingResult, MappingStatus
from curriculum.models import ConceptLifecycleStatus, CurriculumGraph
from curriculum.provenance import provenance_coverage

#: Human-readable metric definitions, including the denominator of each rate.
METRIC_DEFINITIONS = {
    "provenance_coverage": "concepts with >= 1 source_ref / all concepts",
    "hashed_excerpt_coverage": (
        "concepts whose every source_ref carries an excerpt_hash / all concepts"
    ),
    "alias_rate": "concepts with >= 1 alias / all non-deprecated concepts",
    "duplicate_name_rate": (
        "DUPLICATE_CONCEPT_NAME validation errors / 1 (a validated graph is 0; "
        "a non-zero value means validation was bypassed)"
    ),
    "unsupported_edge_rate": (
        "accepted edges with no evidence and a non-human extraction_method / "
        "all accepted edges"
    ),
    "duplicate_edge_rate": (
        "DUPLICATE_RELATIONSHIP validation errors / 1 (a validated graph is 0)"
    ),
    "prerequisite_cycle_count": "cycles among prerequisite_of edges (must be 0 to publish)",
    "mapping_abstention_rate": "unmapped mapping items / all mapping items",
    "mapping_uncertain_rate": "uncertain mapping items / all mapping items",
    "human_correction_rate": (
        "review records that merge, deprecate, replace or reject / all review records"
    ),
    "review_rejection_rate": "reject review records / all review records",
}


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _status(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def build_structural_quality_report(
    graph: CurriculumGraph,
    mapping_results: Optional[Sequence[ContentMappingResult]] = None,
    review_records: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """
    Compute the structural quality report for a canonical graph.

    ``mapping_results`` and ``review_records`` are optional; without them the
    mapping/review sections are reported as empty rather than invented.
    """
    validator = CurriculumGraphValidator()
    report = validator.validate(graph)
    concepts = list(graph.concepts.values())
    active = [
        concept
        for concept in concepts
        if _status(concept.status) != ConceptLifecycleStatus.DEPRECATED.value
    ]
    relationships = list(graph.relationships.values())
    accepted_edges = [
        rel for rel in relationships if rel.status_value == "accepted"
    ]
    unsupported = [
        rel
        for rel in accepted_edges
        if not (rel.evidence_ids or rel.source_refs)
        and (rel.extraction_method or "") not in validator.HUMAN_AUTHORED_METHODS
    ]

    provenance = provenance_coverage(concepts)
    cycles = validator.prerequisite_cycles(graph)

    mapping_section = _mapping_section(mapping_results or [])
    review_section = _review_section(review_records or [])

    return {
        "curriculum_id": graph.curriculum_id,
        "syllabus_version": graph.syllabus_version,
        "report_kind": "structural",
        "graph_fingerprint": graph.content_fingerprint(),
        "validation": {
            "is_valid": report.is_valid,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "issue_codes": sorted({issue.code for issue in report.issues}),
        },
        "concept_metrics": {
            "total": len(concepts),
            "active": len(active),
            "deprecated": len(concepts) - len(active),
            "with_source_refs": provenance.get("with_source_refs", 0),
            "provenance_coverage": provenance.get("coverage", 0.0),
            "hashed_excerpt_coverage": provenance.get("hashed_coverage", 0.0),
            "alias_rate": _rate(len([c for c in active if c.aliases]), len(active)),
            "average_aliases_per_concept": round(
                sum(len(c.aliases) for c in active) / len(active), 4
            )
            if active
            else 0.0,
        },
        "relationship_metrics": {
            "total": len(relationships),
            "accepted": len(accepted_edges),
            "candidate": len([rel for rel in relationships if rel.status_value == "candidate"]),
            "rejected": len([rel for rel in relationships if rel.status_value == "rejected"]),
            "prerequisite_edges": len([rel for rel in relationships if rel.is_prerequisite]),
            "unsupported_edge_rate": _rate(len(unsupported), len(accepted_edges)),
            "prerequisite_cycle_count": len(cycles),
            "prerequisite_cycles": cycles,
        },
        "mapping_metrics": mapping_section,
        "review_metrics": review_section,
        "definitions": dict(METRIC_DEFINITIONS),
    }


def _mapping_section(results: Sequence[ContentMappingResult]) -> Dict[str, Any]:
    totals = {"items": 0, "accepted": 0, "uncertain": 0, "unmapped": 0, "runs": len(results)}
    for result in results:
        totals["items"] += len(result.candidates)
        for candidate in result.candidates:
            totals[candidate.status.value] += 1
    return {
        **totals,
        "mapping_abstention_rate": _rate(totals["unmapped"], totals["items"]),
        "mapping_uncertain_rate": _rate(totals["uncertain"], totals["items"]),
        "fingerprints": [result.fingerprint for result in results],
    }


def _review_section(records: Iterable[Any]) -> Dict[str, Any]:
    items = list(records)
    actions: Dict[str, int] = {}
    for record in items:
        action = getattr(record, "action", None)
        key = action.value if hasattr(action, "value") else str(action or "unknown")
        actions[key] = actions.get(key, 0) + 1
    total = len(items)
    corrections = sum(
        count
        for action, count in actions.items()
        if action in {"merge_concepts", "deprecate_concept", "replace_concept", "reject_concept"}
    )
    rejects = actions.get("reject_concept", 0) + actions.get("reject_relationship", 0)
    return {
        "records": total,
        "by_action": dict(sorted(actions.items())),
        "human_correction_rate": _rate(corrections, total),
        "review_rejection_rate": _rate(rejects, total),
    }


def summarize_for_teacher(report: Dict[str, Any]) -> List[str]:
    """Short, actionable sentences for a teacher-facing panel."""
    lines: List[str] = []
    validation = report.get("validation", {})
    if validation.get("is_valid"):
        lines.append("Graph structure is valid: no blocking errors.")
    else:
        lines.append(
            f"Graph has {validation.get('error_count', 0)} blocking error(s); see the validation report."
        )
    concepts = report.get("concept_metrics", {})
    if concepts.get("total"):
        lines.append(
            f"{concepts['active']} active / {concepts['total']} concepts, "
            f"{round(concepts.get('provenance_coverage', 0) * 100)}% backed by source evidence."
        )
    relationships = report.get("relationship_metrics", {})
    if relationships.get("prerequisite_cycle_count"):
        lines.append(
            f"{relationships['prerequisite_cycle_count']} prerequisite cycle(s) must be resolved "
            f"before the graph can be published."
        )
    if relationships.get("unsupported_edge_rate", 0) > 0:
        lines.append(
            f"{round(relationships['unsupported_edge_rate'] * 100)}% of accepted edges have no "
            f"source evidence attached."
        )
    review = report.get("review_metrics", {})
    if review.get("records"):
        lines.append(
            f"{review['records']} review decision(s) recorded; "
            f"{round(review.get('human_correction_rate', 0) * 100)}% were corrections to pipeline output."
        )
    return lines


def status_counts(results: Sequence[ContentMappingResult]) -> Dict[str, int]:
    counts = {status.value: 0 for status in MappingStatus}
    for result in results:
        for candidate in result.candidates:
            counts[candidate.status.value] += 1
    return counts

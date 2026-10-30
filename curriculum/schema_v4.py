"""
Schema v4 (SCHEMA.md v4.0.0) CSV serialization and ingestion for LearnSense.

This module provides strict, production-quality import and export between the
canonical CurriculumGraph and the authoritative concepts.csv format specified
in SCHEMA.md v4.0.0.

Field order and format:
1. concept_id: str (stable canonical concept ID, e.g. cc_...)
2. subject: str ("physics", "chemistry", "mathematics")
3. concept_name: str (human-readable display name)
4. topic_group: str (e.g. "Mechanics", "Physical Chemistry", "Calculus")
5. prerequisite_ids: str (semicolon-delimited list of concept_ids, e.g. "cc_1;cc_2", or empty)
6. curriculum_status: str ("active", "draft", "deprecated", "legacy_retained")
7. topological_depth: int (non-negative integer derived via DAG longest-path traversal)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from curriculum.graph import (
    CurriculumGraphValidator,
    derive_topological_depth,
)
from curriculum.ids import DEFAULT_CURRICULUM_ID, DEFAULT_SYLLABUS_VERSION, slugify
from curriculum.models import (
    AuditInfo,
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    ReviewStatus,
    Subject,
)
from phase2.models import RelationshipStatusEnum, RelationshipTypeEnum

SCHEMA_V4_HEADERS: List[str] = [
    "concept_id",
    "subject",
    "concept_name",
    "topic_group",
    "prerequisite_ids",
    "curriculum_status",
    "topological_depth",
]

__all__ = [
    "SCHEMA_V4_HEADERS",
    "SchemaV4ValidationError",
    "export_to_schema_v4_csv",
    "import_from_schema_v4_csv",
]


class SchemaV4ValidationError(ValueError):
    """Raised when CSV structure, headers, IDs, or relationships violate Schema v4 rules."""


def export_to_schema_v4_csv(
    graph: CurriculumGraph,
    output_path: Union[str, Path],
) -> int:
    """
    Export the canonical curriculum graph to a Schema v4 compliant concepts.csv.

    Args:
        graph: The canonical CurriculumGraph.
        output_path: File path to write the CSV to.

    Returns:
        The number of concept rows written.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Derive topological depths across reviewed prerequisite DAG
    depths = derive_topological_depth(graph)

    rows: List[Dict[str, Any]] = []
    for cid, concept in graph.concepts.items():
        # Subject string normalized
        subj = concept.subject.value if isinstance(concept.subject, Subject) else str(concept.subject)
        
        # Topic group: derived from topic_path, chapter_id, or metadata
        if concept.topic_path:
            topic_group = concept.topic_path[-1]
        elif concept.chapter_id:
            topic_group = concept.chapter_id.replace("ch_", "").replace("_", " ").title()
        else:
            topic_group = "General"

        # Prerequisite IDs: semicolon-delimited, sorted deterministically
        prereqs = sorted(p for p in concept.prerequisite_concept_ids if p in graph.concepts)
        prereq_str = ";".join(prereqs)

        # Status
        status_val = (
            concept.status.value
            if isinstance(concept.status, ConceptLifecycleStatus)
            else str(concept.status)
        )

        depth = depths.get(cid, 0)

        rows.append({
            "concept_id": cid,
            "subject": subj,
            "concept_name": concept.name,
            "topic_group": topic_group,
            "prerequisite_ids": prereq_str,
            "curriculum_status": status_val,
            "topological_depth": depth,
        })

    # Sort rows deterministically: subject, topic_group, topological_depth, concept_id
    rows.sort(key=lambda r: (r["subject"], r["topic_group"], r["topological_depth"], r["concept_id"]))

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_V4_HEADERS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def import_from_schema_v4_csv(
    input_path: Union[str, Path],
    curriculum_id: str = DEFAULT_CURRICULUM_ID,
    syllabus_version: str = DEFAULT_SYLLABUS_VERSION,
    title: str = "Imported Curriculum (Schema v4)",
) -> CurriculumGraph:
    """
    Import and construct a CurriculumGraph from a Schema v4 concepts.csv file.

    Validates:
    - Exact required headers present in CSV
    - No duplicate concept_ids
    - Valid subject names
    - All prerequisite_ids exist in the concept set
    - No self-loops (node cannot be its own prerequisite)
    - No prerequisite cycles (DAG check)
    - Consistency of declared topological_depth

    Raises:
        SchemaV4ValidationError: on invalid CSV structure, duplicate IDs, or missing endpoints.
        PrerequisiteCycleError: on prerequisite cycles.
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Schema v4 CSV file not found: {path}")

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SchemaV4ValidationError("Empty CSV file")
        
        # Verify required headers
        missing = [h for h in SCHEMA_V4_HEADERS if h not in reader.fieldnames]
        if missing:
            raise SchemaV4ValidationError(
                f"Missing required Schema v4 headers: {missing}. Expected: {SCHEMA_V4_HEADERS}"
            )
        
        rows = list(reader)

    graph = CurriculumGraph(
        curriculum_id=curriculum_id,
        syllabus_version=syllabus_version,
        title=title,
        metadata={"imported_from_schema_v4": str(path)},
    )

    seen_ids: Set[str] = set()
    parsed_prereqs: Dict[str, List[str]] = {}
    declared_depths: Dict[str, int] = {}

    # Pass 1: Parse and add concepts
    for idx, row in enumerate(rows, start=2):
        cid = (row.get("concept_id") or "").strip()
        if not cid:
            raise SchemaV4ValidationError(f"Row {idx}: missing concept_id")
        if cid in seen_ids:
            raise SchemaV4ValidationError(f"Row {idx}: duplicate concept_id '{cid}'")
        seen_ids.add(cid)

        raw_subj = (row.get("subject") or "").strip()
        try:
            subj = Subject.coerce(raw_subj)
        except Exception as exc:
            raise SchemaV4ValidationError(f"Row {idx} ({cid}): invalid subject '{raw_subj}': {exc}")

        name = (row.get("concept_name") or "").strip()
        if not name:
            raise SchemaV4ValidationError(f"Row {idx} ({cid}): concept_name cannot be empty")

        group = (row.get("topic_group") or "").strip() or "General"
        raw_status = (row.get("curriculum_status") or "").strip().lower() or "active"

        raw_prereqs = (row.get("prerequisite_ids") or "").strip()
        prereq_list = [p.strip() for p in raw_prereqs.split(";") if p.strip()]
        parsed_prereqs[cid] = prereq_list

        raw_depth = (row.get("topological_depth") or "").strip()
        if raw_depth:
            try:
                declared_depths[cid] = int(raw_depth)
            except ValueError:
                raise SchemaV4ValidationError(
                    f"Row {idx} ({cid}): topological_depth must be an integer, got '{raw_depth}'"
                )

        chapter_id = f"ch_{slugify(group)}"
        concept = CanonicalConcept(
            concept_id=cid,
            name=name,
            subject=subj,
            chapter_id=chapter_id,
            topic_path=[subj.value, group],
            tags=[subj.value, slugify(group)],
            status=ConceptLifecycleStatus.ACTIVE if raw_status == "active" else ConceptLifecycleStatus.DRAFT,
            review_status=ReviewStatus.ACCEPTED,
            curriculum_id=curriculum_id,
            curriculum_version=syllabus_version,
            stable_key=f"{subj.value}/{slugify(group)}/{slugify(name)}",
            audit=AuditInfo(created_by="schema_v4_importer", updated_by="schema_v4_importer"),
        )
        graph.add_concept(concept)

    # Pass 2: Wire prerequisites and relationships
    for cid, prereqs in parsed_prereqs.items():
        for pid in prereqs:
            if pid not in seen_ids:
                raise SchemaV4ValidationError(
                    f"Concept '{cid}' references unknown prerequisite_id '{pid}'"
                )
            if pid == cid:
                raise SchemaV4ValidationError(
                    f"Self-loop detected: Concept '{cid}' cannot be its own prerequisite"
                )

            # Add to concept record
            graph.concepts[cid].add_prerequisite(pid)

            # Create relationship edge
            rel = ConceptRelationship.create(
                source=pid,
                relationship_type=RelationshipTypeEnum.PREREQUISITE_OF,
                target=cid,
                curriculum_id=curriculum_id,
                status=RelationshipStatusEnum.ACCEPTED,
                rationale="Schema v4 imported prerequisite",
                extraction_method="schema_v4_csv",
            )
            if rel.relationship_id not in graph.relationships:
                graph.add_relationship(rel)

    # Pass 3: Strict DAG and depth validation
    report = CurriculumGraphValidator().validate(graph)
    if not report.is_valid:
        error_msgs = [f"[{issue.code}] {issue.message}" for issue in report.issues if issue.severity.value == "error"]
        raise SchemaV4ValidationError(f"Imported graph failed validation: {'; '.join(error_msgs)}")

    derived_depths = derive_topological_depth(graph)
    for cid, decl_depth in declared_depths.items():
        actual_depth = derived_depths.get(cid, 0)
        if decl_depth != actual_depth:
            raise SchemaV4ValidationError(
                f"Topological depth mismatch for '{cid}': declared {decl_depth}, derived {actual_depth}"
            )

    return graph


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Schema v4 CSV import/export utility for LearnSense")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", dest="export_csv", help="Path to export concepts.csv to")
    group.add_argument("--import", dest="import_csv", help="Path to import concepts.csv from")
    parser.add_argument("--spec", default="curriculum/data/jee_curriculum_spec.json", help="Path to curriculum spec JSON for export")
    parser.add_argument("--curriculum-id", default=DEFAULT_CURRICULUM_ID, help="Curriculum ID for import")
    parser.add_argument("--syllabus-version", default=DEFAULT_SYLLABUS_VERSION, help="Syllabus version for import")

    args = parser.parse_args(argv)

    if args.export_csv:
        from curriculum.seed import load_spec, seed_curriculum

        print(f"Loading curriculum spec from {args.spec}...")
        spec = load_spec(args.spec)
        graph = seed_curriculum(spec)
        count = export_to_schema_v4_csv(graph, args.export_csv)
        print(f"Successfully exported {count} concepts to Schema v4 CSV at: {args.export_csv}")
        return 0

    if args.import_csv:
        print(f"Importing concepts from {args.import_csv}...")
        graph = import_from_schema_v4_csv(
            args.import_csv,
            curriculum_id=args.curriculum_id,
            syllabus_version=args.syllabus_version,
        )
        print(f"Successfully imported and validated graph with {len(graph.concepts)} concepts and {len(graph.relationships)} relationships.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

"""
Stage 9 — Semantic QC, Structural Validation, and Packaging.
Performs hard invariant checks, evidence groundedness validation, completeness
auditing, and prepares final EducationalKnowledgeRepresentation output.
Plan §12.
"""

from typing import Dict, Any, List, Set, Tuple
from phase2.models import (
    EducationalKnowledgeRepresentation,
    SectionStatus,
    SectionSemanticStatusEnum,
    WarningMessage,
    RelationshipTypeEnum,
    RelationshipStatusEnum,
)


def check_hard_invariants(ekr: EducationalKnowledgeRepresentation, block_text_map: Dict[str, str]) -> List[str]:
    """Deterministic structural invariants that MUST hold for a valid EKR."""
    violations = []

    # Check concepts
    concept_ids = {c.concept_id for c in ekr.concepts}
    for c in ekr.concepts:
        if not c.canonical_name:
            violations.append(f"Concept {c.concept_id} missing canonical_name")
        if not c.evidence_ids and c.status == "active":
            violations.append(f"Active concept {c.concept_id} has no evidence_ids")

    # Check relationships
    for rel in ekr.relationships:
        if rel.source not in concept_ids:
            violations.append(f"Relationship {rel.relationship_id} has invalid source concept ID {rel.source}")
        if rel.target not in concept_ids:
            violations.append(f"Relationship {rel.relationship_id} has invalid target concept ID {rel.target}")
        if rel.source == rel.target:
            violations.append(f"Relationship {rel.relationship_id} is self-referencing ({rel.source})")

    # Check evidence spans
    for ev in ekr.evidence:
        if ev.block_id in block_text_map:
            full_text = block_text_map[ev.block_id]
            if ev.span.start < 0 or ev.span.end > len(full_text) or ev.span.start > ev.span.end:
                violations.append(f"Evidence {ev.evidence_id} span range [{ev.span.start}:{ev.span.end}] invalid for block {ev.block_id} length {len(full_text)}")
            else:
                span_text = full_text[ev.span.start:ev.span.end]
                # Quote grounding verification
                if ev.excerpt and ev.excerpt not in full_text and span_text != ev.excerpt:
                    violations.append(f"Evidence {ev.evidence_id} excerpt '{ev.excerpt[:80]}...' not grounded in block {ev.block_id}")

    return violations


def check_evidence_groundedness(ekr: EducationalKnowledgeRepresentation, block_text_map: Dict[str, str]) -> List[str]:
    """
    Validates that every concept's evidence chain leads to real document text.
    Concepts with zero grounded evidence are flagged but NOT silently accepted.
    """
    warnings = []
    evidence_by_id = {e.evidence_id: e for e in ekr.evidence}

    for concept in ekr.concepts:
        if concept.status != "active":
            continue
        grounded_ev_count = 0
        for ev_id in concept.evidence_ids:
            ev = evidence_by_id.get(ev_id)
            if ev is None:
                warnings.append(f"Concept '{concept.canonical_name}' references missing evidence {ev_id}")
                continue
            if ev.block_id not in block_text_map:
                warnings.append(f"Concept '{concept.canonical_name}' evidence {ev_id} references non-existent block {ev.block_id}")
                continue
            block_text = block_text_map[ev.block_id]
            # Verify the excerpt is actually present in the block
            if ev.excerpt and ev.excerpt in block_text:
                grounded_ev_count += 1
            elif ev.span.start < len(block_text) and ev.span.end <= len(block_text):
                grounded_ev_count += 1

        if grounded_ev_count == 0 and concept.evidence_ids:
            warnings.append(f"Concept '{concept.canonical_name}' ({concept.concept_id}) has {len(concept.evidence_ids)} evidence IDs but NONE are grounded in document text")

    return warnings


def check_prerequisite_dag_acyclicity(ekr: EducationalKnowledgeRepresentation) -> List[str]:
    """
    Verifies that the prerequisite subgraph is a DAG (no cycles among ACCEPTED
    prerequisite edges).  Uses iterative Kahn's algorithm for efficiency.
    """
    warnings = []
    prereq_edges: List[Tuple[str, str]] = []
    for rel in ekr.relationships:
        r_type = rel.type.value if hasattr(rel.type, "value") else str(rel.type)
        if r_type == RelationshipTypeEnum.PREREQUISITE_OF.value and rel.status == RelationshipStatusEnum.ACCEPTED:
            prereq_edges.append((rel.source, rel.target))

    if not prereq_edges:
        return warnings

    # Build adjacency and in-degree
    from collections import defaultdict, deque
    adj: Dict[str, List[str]] = defaultdict(list)
    in_degree: Dict[str, int] = defaultdict(int)
    nodes: Set[str] = set()
    for src, tgt in prereq_edges:
        adj[src].append(tgt)
        in_degree[tgt] = in_degree.get(tgt, 0) + 1
        nodes.add(src)
        nodes.add(tgt)

    # Kahn's algorithm
    queue = deque([n for n in nodes if in_degree.get(n, 0) == 0])
    visited_count = 0
    while queue:
        node = queue.popleft()
        visited_count += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count < len(nodes):
        cycle_nodes = [n for n in nodes if in_degree.get(n, 0) > 0]
        warnings.append(
            f"Prerequisite DAG contains cycle(s) involving {len(cycle_nodes)} nodes: "
            f"{', '.join(sorted(cycle_nodes)[:5])}{'...' if len(cycle_nodes) > 5 else ''}"
        )

    return warnings


def check_completeness(ekr: EducationalKnowledgeRepresentation) -> Dict[str, Any]:
    """
    Completeness audit: reports coverage metrics so downstream consumers
    know how much of the document was successfully processed.
    """
    total_concepts = len(ekr.concepts)
    active_concepts = sum(1 for c in ekr.concepts if c.status == "active")
    concepts_with_evidence = sum(1 for c in ekr.concepts if c.evidence_ids)
    concepts_with_description = sum(1 for c in ekr.concepts if getattr(c, "description", ""))
    total_relationships = len(ekr.relationships)
    accepted_relationships = sum(1 for r in ekr.relationships if r.status == RelationshipStatusEnum.ACCEPTED)
    relationships_with_evidence = sum(1 for r in ekr.relationships if r.evidence_ids)
    total_evidence = len(ekr.evidence)

    return {
        "total_concepts": total_concepts,
        "active_concepts": active_concepts,
        "concepts_with_evidence": concepts_with_evidence,
        "concepts_with_description": concepts_with_description,
        "evidence_coverage_pct": round(concepts_with_evidence / max(1, total_concepts) * 100, 1),
        "total_relationships": total_relationships,
        "accepted_relationships": accepted_relationships,
        "relationships_with_evidence": relationships_with_evidence,
        "total_evidence": total_evidence,
        "educational_units_count": len(ekr.educational_units),
    }


def run_stage9_qc(
    ekr: EducationalKnowledgeRepresentation,
    block_text_map: Dict[str, str]
) -> EducationalKnowledgeRepresentation:
    # 1. Hard structural invariants
    violations = check_hard_invariants(ekr, block_text_map)

    # 2. Evidence groundedness validation
    groundedness_warnings = check_evidence_groundedness(ekr, block_text_map)

    # 3. Prerequisite DAG acyclicity check
    dag_warnings = check_prerequisite_dag_acyclicity(ekr)

    # 4. Completeness audit
    completeness = check_completeness(ekr)

    all_warnings = violations + groundedness_warnings + dag_warnings

    ekr.qc_report = {
        "hard_invariant_violations_count": len(violations),
        "hard_invariant_violations": violations,
        "groundedness_warnings_count": len(groundedness_warnings),
        "groundedness_warnings": groundedness_warnings,
        "dag_warnings_count": len(dag_warnings),
        "dag_warnings": dag_warnings,
        "passed_qc": len(violations) == 0 and len(dag_warnings) == 0,
    }

    ekr.coverage_report = completeness

    if violations:
        ekr.warnings.append(
            WarningMessage(
                code="QC_HARD_INVARIANT_VIOLATION",
                scope="document",
                message=f"Document failed hard invariant checks with {len(violations)} violations."
            )
        )
        ekr.status = "failed"

    if dag_warnings:
        ekr.warnings.append(
            WarningMessage(
                code="QC_PREREQUISITE_CYCLE",
                scope="document",
                message=f"Prerequisite graph has {len(dag_warnings)} cycle warning(s)."
            )
        )

    if groundedness_warnings:
        ekr.warnings.append(
            WarningMessage(
                code="QC_GROUNDEDNESS_WARNING",
                scope="document",
                message=f"{len(groundedness_warnings)} evidence groundedness issue(s) detected."
            )
        )

    return ekr

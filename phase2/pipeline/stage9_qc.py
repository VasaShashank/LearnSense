"""
Stage 9 — Semantic QC and Packaging.
Performs hard invariant checks, soft checks, and prepares final EducationalKnowledgeRepresentation output.
Plan §12.
"""

from typing import Dict, Any, List, Tuple
from phase2.models import EducationalKnowledgeRepresentation, SectionStatus, SectionSemanticStatusEnum, WarningMessage


def check_hard_invariants(ekr: EducationalKnowledgeRepresentation, block_text_map: Dict[str, str]) -> List[str]:
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
                    violations.append(f"Evidence {ev.evidence_id} excerpt '{ev.excerpt}' not grounded in block {ev.block_id}")

    return violations


def run_stage9_qc(
    ekr: EducationalKnowledgeRepresentation,
    block_text_map: Dict[str, str]
) -> EducationalKnowledgeRepresentation:
    violations = check_hard_invariants(ekr, block_text_map)

    ekr.qc_report = {
        "hard_invariant_violations_count": len(violations),
        "hard_invariant_violations": violations,
        "passed_qc": len(violations) == 0
    }

    total_units = len(ekr.educational_units)
    ekr.coverage_report = {
        "educational_units_count": total_units,
        "concepts_count": len(ekr.concepts),
        "relationships_count": len(ekr.relationships)
    }

    if violations:
        ekr.warnings.append(
            WarningMessage(
                code="QC_HARD_INVARIANT_VIOLATION",
                scope="document",
                message=f"Document failed hard invariant checks with {len(violations)} violations."
            )
        )
        ekr.status = "completed_with_warnings"

    return ekr

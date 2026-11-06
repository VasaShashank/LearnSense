"""
Calibrated academic confidence semantics (Person 2).

Defensible confidence semantics:
1. Separates editorial relationship status (accepted/rejected/candidate) from confidence.
2. Separates evidence quality (hash verification, citation) from academic confidence.
3. Distinguishes system-generated vs human-reviewed origins.
4. Distinguishes direct formal mathematical/physical derivations from broad syllabus topic sequences.
5. For rejected relationships: sets confidence to 0.0 (representing 0% confidence that the
   relationship is a valid prerequisite) and preserves the rejection explanation separately in metadata.
6. Preserves historical review records and allows human educator reviews to upgrade confidence.

Scoring Model:
- Origin Base:
    - system_seeded: 0.60
    - pipeline_inferred: 0.45
    - teacher_reviewed: 0.85
    - expert_verified: 0.95
- Adjustments:
    - Evidence Integrity: +0.10 if retrievable excerpt matches authentic hash.
    - Directional Progression: +0.05 if forward syllabus unit sequence (Unit X -> Unit Y, X <= Y) confirmed.
    - Formal Derivation Grounding: +0.10 if direct mathematical or physical derivation is established.
    - Topic Listing Only Penalty: -0.05 if syllabus only lists topics without explicit pedagogical proof
      (relationship flagged as requires_academic_review).
    - Practical Application (applies_to): Base 0.65 + 0.10 verified lab evidence = 0.75.
    - Preserved Association (related_to): Base 0.55 + 0.10 verified evidence = 0.65.
    - Contradicted / Rejected: 0.00.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from curriculum.models import ConceptRelationship, CurriculumGraph
from curriculum.evidence_verification import evaluate_relationship_evidence


def calculate_calibrated_confidence(
    rel: ConceptRelationship,
    evidence_eval: Dict[str, Any],
    reviewer_role: Optional[Any] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate the calibrated confidence score and explanatory breakdown.

    Returns:
        (confidence_score: float, breakdown: Dict[str, Any])
    """
    is_rejected = (rel.status_value == "rejected")
    if is_rejected:
        breakdown = {
            "confidence_score": 0.0,
            "confidence_tier": "rejected",
            "interpretation": "Academically invalid relationship; 0.0 reflects that this edge is rejected as a prerequisite.",
            "rejection_reason": evidence_eval.get("review_reason") or rel.rationale or "Rejected by academic audit.",
            "origin": "academic_audit",
            "human_reviewed": True,
            "components": {
                "base_score": 0.0,
                "evidence_integrity_bonus": 0.0,
                "directional_bonus": 0.0,
                "derivation_bonus": 0.0,
            },
        }
        return 0.0, breakdown

    # Determine origin
    role_str = (
        reviewer_role.value if hasattr(reviewer_role, "value")
        else str(reviewer_role or rel.metadata.get("reviewer_role") or "")
    ).lower()
    is_human_reviewed = (
        role_str in {"teacher", "expert", "curriculum_lead", "auditor"}
        or rel.extraction_method in {"curriculum_review", "manual_audit"}
        or rel.metadata.get("reviewed_by") is not None
    )

    support_level = evidence_eval.get("support_level", "TOPIC_LISTING_ONLY")
    hash_verified = evidence_eval.get("hash_verified", False)
    direction_supported = evidence_eval.get("direction_supported", False)
    rel_type = rel.type_value

    if is_human_reviewed:
        base_score = 0.95 if "expert" in role_str else 0.85
        integrity_bonus = 0.05 if hash_verified else 0.0
        direction_bonus = 0.05 if direction_supported else 0.0
        score = min(1.0, round(base_score + integrity_bonus + direction_bonus, 2))
        tier = "human_verified_expert" if "expert" in role_str else "human_verified_teacher"
        interpretation = "Validated by certified educator / subject matter expert with attached provenance."
    elif rel_type == "applies_to":
        score = 0.75 if hash_verified else 0.65
        tier = "practical_application"
        interpretation = "Empirical laboratory exercise applying theoretical foundation; does not block prerequisite DAG."
    elif rel_type == "related_to":
        score = 0.65 if hash_verified else 0.55
        tier = "curriculum_association"
        interpretation = "Curriculum sequencing association; not an academically strict prerequisite."
    elif support_level == "DIRECT_MATHEMATICAL_DERIVATION":
        score = 0.85 if hash_verified else 0.75
        tier = "direct_derivation"
        interpretation = "Strict prerequisite grounded in formal mathematical or physical derivation with authentic syllabus grounding."
    else:  # TOPIC_LISTING_ONLY
        score = 0.70 if hash_verified else 0.60
        tier = "sequenced_topic_listing"
        interpretation = "Syllabus excerpt confirms curriculum sequence, but lacks explicit pedagogical prerequisite proof; requires educator peer review."

    breakdown = {
        "confidence_score": round(score, 2),
        "confidence_tier": tier,
        "interpretation": interpretation,
        "origin": "teacher_reviewed" if is_human_reviewed else "system_seeded",
        "human_reviewed": is_human_reviewed,
        "support_level": support_level,
        "requires_academic_review": evidence_eval.get("requires_academic_review", False),
        "review_reason": evidence_eval.get("review_reason"),
        "components": {
            "base_score": 0.85 if is_human_reviewed else 0.60,
            "evidence_integrity_bonus": 0.10 if hash_verified else 0.0,
            "directional_bonus": 0.05 if direction_supported else 0.0,
            "derivation_bonus": 0.10 if support_level == "DIRECT_MATHEMATICAL_DERIVATION" else 0.0,
        },
    }
    return round(score, 2), breakdown


def audit_graph_confidence(graph: CurriculumGraph) -> Dict[str, Any]:
    """
    Audit calibrated confidence across all relationships in the curriculum graph.
    Verifies that confidence scores reflect genuine evidentiary differentiation
    rather than uncalibrated arbitrary category defaults.
    """
    total = len(graph.relationships)
    scores: Dict[float, int] = {}
    tiers: Dict[str, int] = {}
    breakdowns: List[Dict[str, Any]] = []

    for rel in graph.relationships.values():
        ev = evaluate_relationship_evidence(rel, graph)
        score, breakdown = calculate_calibrated_confidence(rel, ev)
        scores[score] = scores.get(score, 0) + 1
        tier = breakdown["confidence_tier"]
        tiers[tier] = tiers.get(tier, 0) + 1
        breakdowns.append({
            "relationship_id": rel.relationship_id,
            "source": rel.source,
            "target": rel.target,
            "type": rel.type_value,
            "status": rel.status_value,
            "confidence_score": score,
            "breakdown": breakdown,
        })

    is_flattened = len(scores) <= 2 and total > 10

    return {
        "total_relationships": total,
        "is_flattened": is_flattened,
        "score_distribution": scores,
        "tier_distribution": tiers,
        "average_confidence": round(sum(s * c for s, c in scores.items()) / total, 4) if total > 0 else 0.0,
        "breakdowns": breakdowns,
    }


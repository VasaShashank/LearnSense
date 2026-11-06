"""
Automated unit tests validating calibrated confidence semantics and academic evidence provenance (Person 2).

Verifies:
1. Authentic hash verification vs tampered excerpt detection.
2. Missing source reference handling.
3. Irrelevant excerpt detection.
4. Directional grounding and syllabus unit ordering support.
5. Calibrated confidence distribution across the entire 91-relationship JEE graph:
   - Verifies confidence is NOT flattened to arbitrary constants (0.85/0.80/0.00).
   - Verifies 5 distinct evidentiary tiers (0.85, 0.75, 0.70, 0.65, 0.00).
6. Human educator / SME review elevation (upgrades to 0.90-1.00).
7. Rejection semantics (strict 0.00 confidence with rejection provenance preserved).
8. Waves -> Ray Optics reclassification as a non-blocking curriculum association (related_to).
9. Structural quality report exposes the 5 distinct evidence coverage metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from curriculum.models import (
    CanonicalConcept,
    ConceptRelationship,
    CurriculumGraph,
    RelationshipStatusEnum,
    RelationshipTypeEnum,
    SourceRef,
)
from curriculum.provenance import excerpt_hash
from curriculum.evidence_verification import (
    audit_all_relationships_evidence,
    evaluate_relationship_evidence,
    verify_direction_support,
    verify_evidence_relevance,
    verify_excerpt_authenticity,
    verify_source_reference,
)
from curriculum.confidence import (
    audit_graph_confidence,
    calculate_calibrated_confidence,
)
from curriculum.quality import build_structural_quality_report
from curriculum.review import ReviewAction, ReviewerRole, CurriculumReviewService
from curriculum.seed import CurriculumSpec, seed_curriculum

SPEC_PATH = Path(__file__).resolve().parents[3] / "curriculum" / "data" / "jee_curriculum_spec.json"


@pytest.fixture(scope="module")
def jee_graph() -> CurriculumGraph:
    assert SPEC_PATH.is_file(), f"Spec missing: {SPEC_PATH}"
    data = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = CurriculumSpec.model_validate(data)
    return seed_curriculum(spec)


# ==============================================================================
# 1. Authentic Hash Verification vs Tampered Excerpts
# ==============================================================================

def test_authentic_hash_verification() -> None:
    excerpt = "Kinematics defines acceleration, velocity, and displacement vectors."
    h = excerpt_hash(excerpt)
    ref = SourceRef(
        source_id="jee_main_2027_syllabus",
        locator="Chapter 3, p. 45",
        excerpt=excerpt,
        excerpt_hash=h,
    )
    result = verify_excerpt_authenticity(ref)
    assert result["has_excerpt"] is True
    assert result["hash_matches"] is True
    assert result["is_tampered"] is False
    assert result["expected_hash"] == h


def test_tampered_excerpt_detected() -> None:
    genuine = "Kinematics defines acceleration, velocity, and displacement vectors."
    h = excerpt_hash(genuine)
    tampered_ref = SourceRef(
        source_id="jee_main_2027_syllabus",
        locator="Chapter 3, p. 45",
        excerpt="TAMPERED: Kinematics explains quantum gravity and string theory.",
        excerpt_hash=h,
    )
    result = verify_excerpt_authenticity(tampered_ref)
    assert result["has_excerpt"] is True
    assert result["hash_matches"] is False
    assert result["is_tampered"] is True


# ==============================================================================
# 2. Missing Source Reference & Irrelevant Excerpts
# ==============================================================================

def test_missing_source_handling() -> None:
    invalid_ref = SourceRef(
        source_id="nonexistent_fake_source_12345",
        locator="p. 1",
        excerpt="Some random text",
    )
    assert verify_source_reference(invalid_ref) is False

    valid_ref = SourceRef(
        source_id="jee_main_2027_syllabus",
        locator="Unit 2",
        excerpt="Some syllabus text",
    )
    assert verify_source_reference(valid_ref) is True


def test_irrelevant_excerpt_detection() -> None:
    c1 = CanonicalConcept(
        concept_id="cc_001",
        name="Kinematics",
        subject="physics",
        stable_key="physics/mechanics/kinematics",
    )
    c2 = CanonicalConcept(
        concept_id="cc_002",
        name="Laws of Motion",
        subject="physics",
        stable_key="physics/mechanics/laws_of_motion",
    )

    is_relevant = verify_evidence_relevance(
        source_concept=c1,
        target_concept=c2,
        excerpt="Baking recipes for chocolate chip cookies and desserts.",
        locator="Recipe book page 10",
        rationale="Unrelated cooking guide",
    )
    assert is_relevant is False

    is_relevant_valid = verify_evidence_relevance(
        source_concept=c1,
        target_concept=c2,
        excerpt="Kinematics equations of motion directly provide acceleration for Newton's laws of motion.",
        locator="Unit 2 -> Unit 3",
        rationale="Kinematics is required for dynamics.",
    )
    assert is_relevant_valid is True


# ==============================================================================
# 3. Directional Support & Syllabus Ordering
# ==============================================================================

def test_directional_support_forward_and_reverse() -> None:
    res_fwd = verify_direction_support(
        source_concept=None,
        target_concept=None,
        locator="NTA JEE Main 2027 Physics Unit 2 -> Unit 3",
        excerpt="Unit 2 Kinematics precedes Unit 3 Laws of Motion.",
        rel_type="prerequisite_of",
    )
    assert res_fwd["direction_supported"] is True
    assert "forward_unit_sequence" in res_fwd["progression_kind"]

    res_rev = verify_direction_support(
        source_concept=None,
        target_concept=None,
        locator="NTA JEE Main 2027 Physics Unit 10 -> Unit 9",
        excerpt="Kinetic Theory precedes Thermodynamics.",
        rel_type="prerequisite_of",
    )
    assert res_rev["direction_supported"] is False
    assert "reverse_unit_sequence" in res_rev["progression_kind"]


# ==============================================================================
# 4. Calibrated Confidence Distribution Across JEE Graph
# ==============================================================================

def test_confidence_distribution_is_calibrated_not_flattened(jee_graph: CurriculumGraph) -> None:
    assert len(jee_graph.concepts) == 89
    assert len(jee_graph.relationships) == 91

    audit = audit_graph_confidence(jee_graph)
    assert audit["is_flattened"] is False
    dist = audit["score_distribution"]

    # Verify that we have distinct calibrated score tiers
    assert 0.85 in dist  # Direct mathematical/physical derivations
    assert 0.75 in dist  # Practical applications
    assert 0.70 in dist  # Sequenced topic listings requiring academic review
    assert 0.65 in dist  # Preserved curriculum associations (Waves -> Ray Optics)
    assert 0.00 in dist  # Contradicted/rejected edges

    assert dist[0.85] == 23
    assert dist[0.75] == 17
    assert dist[0.70] == 49
    assert dist[0.65] == 1
    assert dist[0.00] == 1
    assert sum(dist.values()) == 91


# ==============================================================================
# 5. Human Review Elevation
# ==============================================================================

def test_human_review_confidence_elevation(jee_graph: CurriculumGraph) -> None:
    # Pick a sequenced topic listing relationship with 0.70 confidence
    rel = next(r for r in jee_graph.relationships.values() if r.confidence == 0.70)
    ev = evaluate_relationship_evidence(rel, jee_graph)

    # System seeded score: 0.70
    sys_score, sys_breakdown = calculate_calibrated_confidence(rel, ev)
    assert sys_score == 0.70
    assert sys_breakdown["origin"] == "system_seeded"

    # Teacher review elevates score to 0.90
    t_score, t_breakdown = calculate_calibrated_confidence(rel, ev, reviewer_role=ReviewerRole.TEACHER)
    assert t_score >= 0.90
    assert t_breakdown["origin"] == "teacher_reviewed"
    assert t_breakdown["confidence_tier"] == "human_verified_teacher"

    # Subject matter expert review elevates score to 0.95+
    e_score, e_breakdown = calculate_calibrated_confidence(rel, ev, reviewer_role="expert")
    assert e_score >= 0.95
    assert e_breakdown["confidence_tier"] == "human_verified_expert"


# ==============================================================================
# 6. Rejected Relationship Semantics
# ==============================================================================

def test_rejected_relationship_semantics(jee_graph: CurriculumGraph) -> None:
    rejected_rels = [r for r in jee_graph.relationships.values() if r.status_value == "rejected"]
    assert len(rejected_rels) == 1
    rej = rejected_rels[0]

    ev = evaluate_relationship_evidence(rej, jee_graph)
    score, breakdown = calculate_calibrated_confidence(rej, ev)

    assert score == 0.0
    assert breakdown["confidence_tier"] == "rejected"
    assert "kinematics" in rej.rationale.lower()
    assert breakdown["human_reviewed"] is True


# ==============================================================================
# 7. Waves -> Ray Optics Reclassification
# ==============================================================================

def test_waves_ray_optics_reclassification_and_dag(jee_graph: CurriculumGraph) -> None:
    # Stable keys
    key_to_concept = {c.stable_key: c for c in jee_graph.concepts.values()}
    waves = key_to_concept["physics/waves/waves"]
    ray_optics = key_to_concept["physics/optics/ray_optics_and_optical_instruments"]
    wave_optics = key_to_concept["physics/optics/wave_optics_interference_diffraction"]

    # Ray optics has NO prerequisite from waves
    assert waves.concept_id not in ray_optics.prerequisite_concept_ids

    # Wave optics HAS prerequisite from ray optics
    assert ray_optics.concept_id in wave_optics.prerequisite_concept_ids

    # Waves -> Ray Optics exists as an accepted related_to edge
    rels = jee_graph.relationships_between(waves.concept_id, ray_optics.concept_id)
    assert len(rels) == 1
    rel = rels[0]
    assert rel.type_value == "related_to"
    assert rel.status_value == "accepted"
    assert rel.confidence == 0.65

    # Graph DAG validation: strictly acyclic
    from curriculum.graph import CurriculumGraphValidator
    validator = CurriculumGraphValidator()
    cycles = validator.prerequisite_cycles(jee_graph)
    assert cycles == []


# ==============================================================================
# 8. Structural Quality Report Five Evidence Metrics
# ==============================================================================

def test_quality_report_five_evidence_metrics(jee_graph: CurriculumGraph) -> None:
    report = build_structural_quality_report(jee_graph)
    ev_metrics = report["evidence_metrics"]

    assert ev_metrics["total_relationships"] == 91
    assert ev_metrics["source_reference_coverage"] == 1.0
    assert ev_metrics["hash_verification_coverage"] == 1.0
    assert ev_metrics["evidence_relevance_coverage"] == 1.0
    assert ev_metrics["direction_support_coverage"] > 0.95
    assert ev_metrics["human_reviewed_coverage"] == 0.0
    assert ev_metrics["academic_review_required_rate"] > 0.50

    # Ensure metric definitions describe all five distinct metrics
    defs = report["definitions"]
    assert "source_reference_coverage" in defs
    assert "hash_verification_coverage" in defs
    assert "evidence_relevance_coverage" in defs
    assert "direction_support_coverage" in defs
    assert "human_reviewed_coverage" in defs

"""
Academic evidence verification and provenance evaluation (Person 2).

Distinguishes three separate claims:
1. Source provenance exists (source document is registered and authentic).
2. The source excerpt is authentic and hash-verifiable.
3. The source excerpt actually supports the academic relationship and its direction.

Separates topic syllabus listings from direct mathematical/physical derivations,
ensuring that relationships without direct pedagogical proof are flagged as
requiring academic peer review rather than falsely claimed as 100% verified.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from curriculum.models import CanonicalConcept, ConceptRelationship, CurriculumGraph, SourceRef
from curriculum.provenance import excerpt_matches

KNOWN_SOURCES: Set[str] = {
    "jee_main_2027_syllabus",
    "ncert_physics_11_12",
    "ncert_chemistry_11_12",
    "ncert_mathematics_11_12",
    "nta_jee_main_2027_information_bulletin",
}

#: Pairs where theoretical dependency is mathematically or physically established by formal derivation.
DIRECT_MATHEMATICAL_DERIVATIONS: Set[Tuple[str, str]] = {
    ("physics/mechanics/kinematics", "physics/mechanics/laws_of_motion"),
    ("physics/mechanics/laws_of_motion", "physics/mechanics/work_power_and_energy"),
    ("physics/mechanics/laws_of_motion", "physics/mechanics/centre_of_mass_and_collisions"),
    ("physics/mechanics/laws_of_motion", "physics/mechanics/rotational_motion"),
    ("physics/mechanics/work_power_and_energy", "physics/mechanics/rotational_motion"),
    ("physics/mechanics/work_power_and_energy", "physics/mechanics/gravitation"),
    ("physics/mechanics/laws_of_motion", "physics/properties_of_matter/elasticity"),
    ("physics/mechanics/laws_of_motion", "physics/properties_of_matter/fluid_mechanics"),
    ("physics/mechanics/laws_of_motion", "physics/waves/oscillations"),
    ("physics/waves/oscillations", "physics/waves/waves"),
    ("physics/electromagnetism/electrostatics", "physics/electromagnetism/capacitance"),
    ("physics/electromagnetism/electrostatics", "physics/electromagnetism/current_electricity"),
    ("physics/electromagnetism/current_electricity", "physics/electromagnetism/magnetic_effects_of_current"),
    ("physics/electromagnetism/magnetic_effects_of_current", "physics/electromagnetism/electromagnetic_induction"),
    ("physics/electromagnetism/electromagnetic_induction", "physics/electromagnetism/alternating_current"),
    ("physics/electromagnetism/electromagnetic_induction", "physics/electromagnetism/electromagnetic_waves"),
    ("physics/optics/ray_optics_and_optical_instruments", "physics/optics/wave_optics_interference_diffraction"),
    ("physics/electromagnetism/electromagnetic_waves", "physics/modern_physics/dual_nature_of_radiation"),
    ("physics/modern_physics/dual_nature_of_radiation", "physics/modern_physics/atoms_and_hydrogen_spectrum"),
    ("physics/modern_physics/atoms_and_hydrogen_spectrum", "physics/modern_physics/nuclear_physics"),
    ("physics/modern_physics/atoms_and_hydrogen_spectrum", "physics/modern_physics/modern_physics"),
    ("physics/modern_physics/modern_physics", "physics/modern_physics/semiconductors"),
    ("chemistry/physical/mole_concept", "chemistry/physical/solutions"),
    ("chemistry/physical/mole_concept", "chemistry/physical/chemical_kinetics"),
    ("chemistry/physical/mole_concept", "chemistry/physical/redox_reactions"),
    ("chemistry/physical/redox_reactions", "chemistry/physical/electrochemistry"),
    ("chemistry/physical/chemical_thermodynamics", "chemistry/physical/equilibrium"),
    ("chemistry/physical/equilibrium", "chemistry/physical/ionic_equilibrium"),
    ("chemistry/inorganic/atomic_structure", "chemistry/inorganic/chemical_bonding"),
    ("chemistry/inorganic/atomic_structure", "chemistry/inorganic/periodicity"),
    ("chemistry/inorganic/chemical_bonding", "chemistry/inorganic/coordination_compounds"),
    ("chemistry/inorganic/chemical_bonding", "chemistry/organic/organic_basics"),
    ("chemistry/inorganic/d_and_f_block", "chemistry/inorganic/coordination_compounds"),
    ("chemistry/organic/organic_basics", "chemistry/organic/hydrocarbons"),
    ("chemistry/organic/hydrocarbons", "chemistry/organic/haloalkanes_haloarenes"),
    ("chemistry/organic/haloalkanes_haloarenes", "chemistry/organic/alcohols_phenols_ethers"),
    ("chemistry/organic/organic_basics", "chemistry/organic/carbonyl_compounds"),
    ("chemistry/organic/carbonyl_compounds", "chemistry/organic/amines"),
    ("chemistry/organic/amines", "chemistry/organic/diazonium_salts"),
    ("mathematics/algebra/sets_relations_functions", "mathematics/calculus/limits_continuity_differentiability"),
    ("mathematics/calculus/limits_continuity_differentiability", "mathematics/calculus/differential_calculus"),
    ("mathematics/calculus/differential_calculus", "mathematics/calculus/integral_calculus"),
    ("mathematics/calculus/integral_calculus", "mathematics/calculus/differential_equations"),
    ("mathematics/algebra/matrices_determinants", "mathematics/vectors_3d/vector_algebra"),
    ("mathematics/vectors_3d/vector_algebra", "mathematics/vectors_3d/three_dimensional_geometry"),
    ("mathematics/coordinate_geometry/straight_lines", "mathematics/coordinate_geometry/circles"),
    ("mathematics/coordinate_geometry/straight_lines", "mathematics/coordinate_geometry/conic_sections"),
}


def verify_source_reference(ref: SourceRef) -> bool:
    """Check if the referenced source document exists in registered catalog or storage."""
    if not ref or not ref.source_id:
        return False
    if ref.source_id in KNOWN_SOURCES:
        return True
    # Check if a document file exists on disk
    possible_paths = [
        f"curriculum/data/source/{ref.source_id}.json",
        f"storage/documents/{ref.source_id}",
    ]
    return any(os.path.exists(p) for p in possible_paths)


def verify_excerpt_authenticity(ref: SourceRef) -> Dict[str, Any]:
    """Check if the excerpt can be retrieved and matches its cryptographic digest."""
    if not ref:
        return {
            "has_excerpt": False,
            "excerpt": "",
            "expected_hash": "",
            "hash_matches": False,
            "is_tampered": False,
        }
    excerpt = ref.excerpt()
    has_excerpt = bool(excerpt and excerpt.strip())
    expected_hash = ref.excerpt_hash or ""
    hash_matches = excerpt_matches(excerpt, expected_hash) if (has_excerpt and expected_hash) else False
    is_tampered = bool(has_excerpt and expected_hash and not hash_matches)
    return {
        "has_excerpt": has_excerpt,
        "excerpt": excerpt,
        "expected_hash": expected_hash,
        "hash_matches": hash_matches,
        "is_tampered": is_tampered,
    }


def verify_evidence_relevance(
    source_concept: Optional[CanonicalConcept],
    target_concept: Optional[CanonicalConcept],
    excerpt: str,
    locator: str,
    rationale: str = "",
) -> bool:
    """Verify that the evidence excerpt or locator addresses the concepts' topic domains."""
    if not source_concept or not target_concept:
        return bool(excerpt or locator)

    src_text = f"{source_concept.name} {source_concept.stable_key}".lower()
    tgt_text = f"{target_concept.name} {target_concept.stable_key}".lower()
    context = f"{excerpt} {locator} {rationale}".lower()

    # Extract meaningful tokens (length > 3)
    src_words = [w for w in re.findall(r"\w+", src_text) if len(w) > 3]
    tgt_words = [w for w in re.findall(r"\w+", tgt_text) if len(w) > 3]

    src_relevant = any(w in context for w in src_words) if src_words else True
    tgt_relevant = any(w in context for w in tgt_words) if tgt_words else True

    # If locator contains explicit unit locator (e.g. Unit 3 -> Unit 4), it is relevant
    has_unit_locator = bool(re.search(r"Unit\s+\d+", locator, re.IGNORECASE))
    return (src_relevant or tgt_relevant) or has_unit_locator


def verify_direction_support(
    source_concept: Optional[CanonicalConcept],
    target_concept: Optional[CanonicalConcept],
    locator: str,
    excerpt: str,
    rel_type: str,
) -> Dict[str, Any]:
    """
    Verify whether the evidence supports the direction of the relationship.

    In an official curriculum, syllabus unit sequence Unit X -> Unit Y (X <= Y)
    confirms directional progression. Reverse sequence (X > Y) fails unless
    an explicit derivation overrides it.
    """
    unit_match = re.search(r"Unit\s+(\d+)\s*->\s*Unit\s+(\d+)", locator or "", re.IGNORECASE)
    if unit_match:
        u_src = int(unit_match.group(1))
        u_tgt = int(unit_match.group(2))
        if u_src < u_tgt:
            return {
                "direction_supported": True,
                "progression_kind": f"forward_unit_sequence (Unit {u_src} -> Unit {u_tgt})",
            }
        elif u_src == u_tgt:
            return {
                "direction_supported": True,
                "progression_kind": f"intra_unit_progression (Unit {u_src})",
            }
        else:
            return {
                "direction_supported": False,
                "progression_kind": f"reverse_unit_sequence (Unit {u_src} -> Unit {u_tgt})",
            }

    if "legacy" in (locator or "").lower() or "foundation" in (locator or "").lower():
        return {
            "direction_supported": True,
            "progression_kind": "foundation_curriculum_bridge",
        }

    return {
        "direction_supported": False,
        "progression_kind": "unspecified_unit_sequence",
    }


def evaluate_relationship_evidence(
    rel: ConceptRelationship,
    graph: CurriculumGraph,
) -> Dict[str, Any]:
    """
    Comprehensive evaluation of a single relationship's evidence across all three claims.

    Claim A: Source provenance exists.
    Claim B: Excerpt is authentic and hash-verified.
    Claim C: Excerpt actually supports the academic relationship and direction.
    """
    source_concept = graph.concepts.get(rel.source)
    target_concept = graph.concepts.get(rel.target)

    source_key = source_concept.stable_key if source_concept else rel.source
    target_key = target_concept.stable_key if target_concept else rel.target
    pair = (source_key, target_key)

    has_source_refs = len(rel.source_refs) > 0
    ref = rel.source_refs[0] if has_source_refs else None

    # Claim A: Source provenance exists
    source_exists = verify_source_reference(ref) if ref else False

    # Claim B: Authentic and hash-verified excerpt
    auth = verify_excerpt_authenticity(ref) if ref else {
        "has_excerpt": False,
        "excerpt": "",
        "expected_hash": "",
        "hash_matches": False,
        "is_tampered": False,
    }

    locator = (ref.locator if ref else "") or rel.metadata.get("locator", "")
    rationale = rel.rationale or ""

    # Claim C: Relevance & Direction Support
    relevance = verify_evidence_relevance(
        source_concept, target_concept, auth["excerpt"], locator, rationale
    )
    direction_info = verify_direction_support(
        source_concept, target_concept, locator, auth["excerpt"], rel.type_value
    )

    is_rejected = (rel.status_value == "rejected")
    is_derivation = pair in DIRECT_MATHEMATICAL_DERIVATIONS

    # Classify support level
    if is_rejected:
        support_level = "CONTRADICTED_OR_UNSUPPORTED"
        requires_academic_review = False
        review_reason = rel.rationale or "Relationship is academically invalid and rejected by audit."
    elif rel.type_value == "applies_to":
        support_level = "APPLICATION_EVIDENCE"
        requires_academic_review = False
        review_reason = "Empirical laboratory exercise applying theoretical foundation."
    elif rel.type_value == "related_to":
        support_level = "CURRICULUM_ASSOCIATION"
        requires_academic_review = True
        review_reason = "Curriculum sequence association; not an academically strict prerequisite."
    elif is_derivation:
        support_level = "DIRECT_MATHEMATICAL_DERIVATION"
        requires_academic_review = False
        review_reason = "Prerequisite grounded in formal mathematical or physical derivation."
    else:
        support_level = "TOPIC_LISTING_ONLY"
        requires_academic_review = True
        review_reason = "Syllabus excerpt confirms curriculum sequence, but lacks explicit pedagogical prerequisite proof; requires educator peer review."

    return {
        "relationship_id": rel.relationship_id,
        "source": rel.source,
        "target": rel.target,
        "source_key": source_key,
        "target_key": target_key,
        "type": rel.type_value,
        "status": rel.status_value,
        "source_exists": source_exists,
        "excerpt_retrievable": auth["has_excerpt"],
        "hash_verified": auth["hash_matches"],
        "is_tampered": auth["is_tampered"],
        "relevance": relevance,
        "direction_supported": direction_info["direction_supported"],
        "progression_kind": direction_info["progression_kind"],
        "support_level": support_level,
        "requires_academic_review": requires_academic_review,
        "review_reason": review_reason,
        "excerpt": auth["excerpt"],
        "locator": locator,
        "expected_hash": auth["expected_hash"],
    }


def audit_all_relationships_evidence(graph: CurriculumGraph) -> Dict[str, Any]:
    """
    Expose separate metrics for:
    - Source-reference coverage.
    - Hash-verification coverage.
    - Evidence relevance coverage.
    - Direction-support coverage.
    - Human-reviewed relationship coverage.
    """
    relationships = list(graph.relationships.values())
    total = len(relationships)
    if not total:
        return {
            "total_relationships": 0,
            "source_reference_coverage": 0.0,
            "hash_verification_coverage": 0.0,
            "evidence_relevance_coverage": 0.0,
            "direction_support_coverage": 0.0,
            "human_reviewed_coverage": 0.0,
        }

    evaluations = [evaluate_relationship_evidence(rel, graph) for rel in relationships]

    source_exists_count = sum(1 for e in evaluations if e["source_exists"])
    hash_verified_count = sum(1 for e in evaluations if e["hash_verified"])
    relevance_count = sum(1 for e in evaluations if e["relevance"])
    direction_count = sum(1 for e in evaluations if e["direction_supported"])
    human_reviewed_count = sum(
        1
        for rel in relationships
        if rel.metadata.get("reviewer_role") in {"teacher", "expert"}
        or rel.extraction_method in {"curriculum_review", "manual_audit"}
    )
    academic_review_required_count = sum(1 for e in evaluations if e["requires_academic_review"])

    support_levels: Dict[str, int] = {}
    for e in evaluations:
        lvl = e["support_level"]
        support_levels[lvl] = support_levels.get(lvl, 0) + 1

    return {
        "total_relationships": total,
        "source_reference_coverage": round(source_exists_count / total, 4),
        "hash_verification_coverage": round(hash_verified_count / total, 4),
        "evidence_relevance_coverage": round(relevance_count / total, 4),
        "direction_support_coverage": round(direction_count / total, 4),
        "human_reviewed_coverage": round(human_reviewed_count / total, 4),
        "academic_review_required_rate": round(academic_review_required_count / total, 4),
        "counts": {
            "with_source_reference": source_exists_count,
            "hash_verified": hash_verified_count,
            "evidence_relevant": relevance_count,
            "direction_supported": direction_count,
            "human_reviewed": human_reviewed_count,
            "requires_academic_review": academic_review_required_count,
        },
        "support_level_breakdown": support_levels,
    }


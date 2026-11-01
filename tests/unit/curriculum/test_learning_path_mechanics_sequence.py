"""
Unit and regression tests for Phase 3 Learning Path Ordering and Pedagogical Sequence.
Verifies:
1. False prerequisite ('static friction', 'centripetal acceleration') is absent.
2. Centripetal Acceleration does not require Static Friction.
3. Mechanics sequence generates all 14 concepts without truncation at 10.
4. Chapter coherence is strictly preserved: Dynamics -> Friction -> Circular Motion.
"""

import pytest
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from phase4.planning.prerequisite_resolver import PrerequisiteResolver
from phase4.planning.learning_path_generator import LearningPathGenerator


DOC_ID = "doc_121418-jee-main-2023-24-laws-of-motion-revision-notes-free-pdf-download"


def test_no_false_friction_to_circular_prerequisite():
    """Verify static friction is NOT a prerequisite for centripetal acceleration."""
    ks = KnowledgeService()
    graph = ks.get_subject_graph(DOC_ID)

    concepts = {c["concept_id"]: c for c in graph["concepts"]}

    # Find Centripetal Acceleration
    ca_id = None
    sf_id = None
    for c_id, c in concepts.items():
        if "centripetal acceleration" in c["name"].lower():
            ca_id = c_id
        if "static friction" in c["name"].lower() and "coefficient" not in c["name"].lower():
            sf_id = c_id

    assert ca_id is not None, "Centripetal Acceleration concept must exist"
    assert sf_id is not None, "Static Friction concept must exist"

    ca_prereqs = concepts[ca_id].get("prerequisites", [])
    assert sf_id not in ca_prereqs, (
        f"False prerequisite detected: Static Friction ({sf_id}) must NOT be "
        f"a prerequisite for Centripetal Acceleration ({ca_id})"
    )


def test_mechanics_learning_sequence_chapter_coherence():
    """Verify get_learning_sequence orders chapters sequentially without cross-topic jumps."""
    ks = KnowledgeService()
    seq_data = ks.get_learning_sequence(DOC_ID)
    sequence = seq_data.get("sequence", [])

    assert len(sequence) == 14, f"Expected 14 sequence steps, got {len(sequence)}"

    # Topic transitions must be monotonic
    seen_chapters = []
    for item in sequence:
        chap = item["chapter_name"]
        if not seen_chapters or seen_chapters[-1] != chap:
            assert chap not in seen_chapters, (
                f"Chapter interleaving detected: {chap} reappeared after {seen_chapters}"
            )
            seen_chapters.append(chap)

    assert seen_chapters == ["Newton's Laws of Motion", "Friction", "Centripetal Motion"], (
        f"Unexpected chapter progression: {seen_chapters}"
    )


def test_learning_path_no_truncation():
    """Verify LearningPathGenerator does not truncate 14-step mechanics subject to 10 nodes."""
    ls = LearnerService()
    res = ls.get_gaps_and_path("student_alex", DOC_ID)
    path = res.get("learning_path", {})
    nodes = path.get("nodes", [])

    assert len(nodes) == 14, (
        f"Expected all 14 mechanics concepts in path, but got {len(nodes)} (truncation regression)"
    )

    concept_names = [n["concept_name"] for n in nodes]

    # Verify foundational starts with Newton's First Law
    assert "Newton's First Law" in concept_names[0]

    # Verify all 3 major chapter clusters exist in path
    assert any("Newton" in name for name in concept_names)
    assert any("Friction" in name for name in concept_names)
    assert any("Acceleration" in name or "Angular" in name for name in concept_names)


def test_topological_sort_respects_topic_rank():
    """Verify PrerequisiteResolver prioritizes topic rank over arbitrary string ordering."""
    ks = KnowledgeService()
    ctx = ks.get_learning_context(DOC_ID)
    graph = ks.get_subject_graph(DOC_ID)
    concept_ids = [c["concept_id"] for c in graph["concepts"]]

    resolver = PrerequisiteResolver()
    sorted_ids = resolver.cycle_safe_topological_sort(ctx, concept_ids)

    assert len(sorted_ids) == len(concept_ids)

    # Convert sorted ids to names
    name_map = {c["concept_id"]: c["name"] for c in graph["concepts"]}
    sorted_names = [name_map[cid] for cid in sorted_ids]

    # Dynamics concepts should appear before Friction concepts
    n1_idx = next(i for i, n in enumerate(sorted_names) if "First Law" in n)
    sf_idx = next(i for i, n in enumerate(sorted_names) if n == "Static Friction")
    av_idx = next(i for i, n in enumerate(sorted_names) if "Angular Velocity" in n)

    assert n1_idx < sf_idx, "Dynamics (First Law) must precede Friction (Static Friction)"
    assert sf_idx < av_idx, "Friction (Static Friction) must precede Circular Motion (Angular Velocity)"

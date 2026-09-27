"""
Unit tests for Phase 4 Gap Detection, Reasoning, and Deterministic Prioritization.
"""

from phase2.models import RelationshipTypeEnum
from phase3.knowledge.phase2_adapter import ConceptView, LearningContext, PrerequisiteLink
from phase3.learner.models import ConceptState, LearnerState
from phase4.gaps.gap_detector import GapDetector
from phase4.gaps.gap_prioritizer import GapPrioritizer
from phase4.gaps.gap_reasoner import GapReasoner
from phase4.models import GapType


def build_mock_context_and_state():
    context = LearningContext(
        document_id="doc1",
        knowledge_document_id="kdoc1",
        concepts={
            "c_var": ConceptView(concept_id="c_var", canonical_name="Variables", type="concept"),
            "c_eq": ConceptView(concept_id="c_eq", canonical_name="Linear Equations", type="concept"),
            "c_quad": ConceptView(concept_id="c_quad", canonical_name="Quadratic Equations", type="concept"),
        },
        prerequisites=[
            PrerequisiteLink(source_concept_id="c_var", target_concept_id="c_eq", confidence=1.0),
            PrerequisiteLink(source_concept_id="c_eq", target_concept_id="c_quad", confidence=1.0),
        ]
    )

    learner_state = LearnerState(
        learner_id="learner_1",
        concept_states={
            "c_var": ConceptState(concept_id="c_var", mastery_probability=0.8, uncertainty=0.1, attempt_count=5),
            "c_eq": ConceptState(concept_id="c_eq", mastery_probability=0.3, uncertainty=0.5, attempt_count=5),
            "c_quad": ConceptState(concept_id="c_quad", mastery_probability=0.2, uncertainty=0.6, attempt_count=1),
        }
    )
    return context, learner_state


def test_gap_detection_categories():
    context, state = build_mock_context_and_state()
    detector = GapDetector()

    gaps = detector.detect_gaps(context, state, ["c_var", "c_eq", "c_quad"])

    # c_var has mastery 0.8, uncertainty 0.1, attempt_count 5 -> sufficient mastery, no gap
    # c_eq has mastery 0.3 -> LOW_MASTERY gap
    # c_quad has mastery 0.2, attempt_count 1 -> INSUFFICIENT_EVIDENCE & WEAK_PREREQUISITE
    gap_concepts = [g.concept_id for g in gaps]

    assert "c_var" not in gap_concepts
    assert "c_eq" in gap_concepts
    assert "c_quad" in gap_concepts


def test_gap_reasoner_and_prioritization():
    context, state = build_mock_context_and_state()
    detector = GapDetector()
    prioritizer = GapPrioritizer()
    reasoner = GapReasoner()

    gaps = detector.detect_gaps(context, state, ["c_eq", "c_quad"])
    prioritized = prioritizer.prioritize_gaps(gaps)

    assert len(prioritized) == 2
    for g in prioritized:
        explanations = reasoner.generate_explanation(g)
        assert len(explanations) > 0
        assert g.priority_score >= 0.0 and g.priority_score <= 1.0

    # Prioritization must be deterministic
    p2 = prioritizer.prioritize_gaps(gaps)
    assert [g.concept_id for g in prioritized] == [g.concept_id for g in p2]

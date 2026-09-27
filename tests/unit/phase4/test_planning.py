"""
Unit tests for Phase 4 Path Planning, Prerequisite Resolver, and Target Selection.
"""

from phase3.knowledge.phase2_adapter import ConceptView, LearningContext, PrerequisiteLink
from phase3.learner.models import ConceptState, LearnerState
from phase4.planning.learning_path_generator import LearningPathGenerator
from phase4.planning.next_target_selector import NextTargetSelector
from phase4.planning.prerequisite_resolver import PrerequisiteResolver


def build_graph_context():
    # Graph: c_var -> c_eq -> c_quad
    # Foundational root: c_var
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


def test_prerequisite_resolver_foundational_concepts():
    context, state = build_graph_context()
    resolver = PrerequisiteResolver()

    foundational = resolver.find_foundational_concepts(context, ["c_var", "c_eq", "c_quad"])
    # c_var has no in-edges in this subgraph -> foundational root
    assert foundational == ["c_var"]


def test_prerequisite_resolver_cycle_safety():
    # Construct graph with a cycle: c1 -> c2 -> c3 -> c1
    context = LearningContext(
        document_id="doc1",
        knowledge_document_id="kdoc1",
        concepts={
            "c1": ConceptView(concept_id="c1", canonical_name="C1", type="concept"),
            "c2": ConceptView(concept_id="c2", canonical_name="C2", type="concept"),
            "c3": ConceptView(concept_id="c3", canonical_name="C3", type="concept"),
        },
        prerequisites=[
            PrerequisiteLink(source_concept_id="c1", target_concept_id="c2", confidence=1.0),
            PrerequisiteLink(source_concept_id="c2", target_concept_id="c3", confidence=1.0),
            PrerequisiteLink(source_concept_id="c3", target_concept_id="c1", confidence=1.0),
        ]
    )

    resolver = PrerequisiteResolver()
    sorted_nodes = resolver.cycle_safe_topological_sort(context, ["c1", "c2", "c3"])

    # Must complete without infinite loop and return all 3 nodes
    assert len(sorted_nodes) == 3
    assert set(sorted_nodes) == {"c1", "c2", "c3"}


def test_learning_path_generator_and_next_target():
    context, state = build_graph_context()
    generator = LearningPathGenerator()
    selector = NextTargetSelector()

    path = generator.generate_path(context, state, ["c_var", "c_eq", "c_quad"])

    # Path should order prerequisite gaps correctly: c_eq before c_quad
    concept_order = [node.concept_id for node in path.nodes]
    assert concept_order.index("c_eq") < concept_order.index("c_quad")

    target = selector.select_next_target(path, state, context)
    assert target is not None
    assert target.concept_id == concept_order[0]

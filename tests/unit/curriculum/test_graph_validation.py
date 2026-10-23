"""
Graph validation, traversal and the prerequisite policy (Person 2).

Policy under test:

* ``A --prerequisite_of--> B`` means A is learned before B.
* Self loops, duplicate edges, missing endpoints and duplicate surfaces are
  ERRORs; the graph is never silently repaired.
* The concept-level prerequisite list and the typed edge set must agree in both
  directions, or the graph is inconsistent.
* Prerequisite cycles are rejected.  A cycle among a *different* relationship
  type (which carries no ordering promise) is tolerated.
"""

from __future__ import annotations

import pytest

from curriculum.graph import (
    CurriculumGraphValidator,
    PrerequisiteCycleError,
    cycle_safe_topological_order,
    dependent_closure,
    prerequisite_closure,
    prerequisite_subgraph,
    topological_order,
    would_create_cycle,
)
from curriculum.models import (
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    CurriculumGraphError,
    Subject,
)
from phase2.models import RelationshipStatusEnum

ACCEPTED = RelationshipStatusEnum.ACCEPTED
REJECTED = RelationshipStatusEnum.REJECTED
#: Extraction method the validator treats as human-authored, so accepted edges
#: do not trip the "unsourced assertion" warning.
HUMAN = "curriculum_review"


def concept(key: str, name: str = "", subject: Subject = Subject.PHYSICS) -> CanonicalConcept:
    return CanonicalConcept.create(
        name or key.upper(), subject, stable_key=key, curriculum_id="t"
    )


def link(
    graph: CurriculumGraph,
    source: CanonicalConcept,
    target: CanonicalConcept,
    *,
    status=ACCEPTED,
    rel_type: str = "prerequisite_of",
) -> ConceptRelationship:
    """
    Add an edge, keeping the concept-level prerequisite list consistent.

    A rejected edge must *not* be reflected in the list: the validator treats a
    list entry as an ordering promise and rejects one that no live edge backs.
    """
    relationship = ConceptRelationship.create(
        source.concept_id,
        rel_type,
        target.concept_id,
        curriculum_id=graph.curriculum_id,
        status=status,
        extraction_method=HUMAN,
    )
    graph.add_relationship(relationship)
    if rel_type == "prerequisite_of" and status != REJECTED:
        target.add_prerequisite(source.concept_id)
    return relationship


def add_cycle(graph: CurriculumGraph, first: CanonicalConcept, second: CanonicalConcept) -> None:
    """Wire first -> second -> first in both the edge set and the lists."""
    graph.add_relationship(
        ConceptRelationship.create(
            second.concept_id, "prerequisite_of", first.concept_id,
            curriculum_id=graph.curriculum_id, status=ACCEPTED, extraction_method=HUMAN,
        )
    )
    first.add_prerequisite(second.concept_id)


def report_of(graph: CurriculumGraph):
    return CurriculumGraphValidator().validate(graph)


class TestStructuralErrors:
    def test_clean_chain_is_valid(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b, c = concept("a"), concept("b"), concept("c")
        for item in (a, b, c):
            graph.add_concept(item)
        link(graph, a, b)
        link(graph, b, c)
        report = report_of(graph)
        assert report.is_valid is True
        assert report.error_count == 0

    def test_missing_endpoint_is_an_error(self):
        graph = CurriculumGraph(curriculum_id="t")
        a = concept("a")
        graph.add_concept(a)
        ghost = concept("ghost")
        graph.add_relationship(
            ConceptRelationship.create(
                a.concept_id, "prerequisite_of", ghost.concept_id,
                curriculum_id="t", status=ACCEPTED, extraction_method=HUMAN,
            )
        )
        report = report_of(graph)
        assert report.issues_with_code("MISSING_TARGET_CONCEPT")
        assert report.is_valid is False

    def test_self_loop_is_an_error(self):
        graph = CurriculumGraph(curriculum_id="t")
        a = concept("a")
        graph.add_concept(a)
        graph.add_relationship(
            ConceptRelationship.create(
                a.concept_id, "prerequisite_of", a.concept_id,
                curriculum_id="t", status=ACCEPTED, extraction_method=HUMAN,
            )
        )
        issues = report_of(graph).issues_with_code("SELF_LOOP")
        assert issues and issues[0].severity.value == "error"

    def test_duplicate_edge_is_an_error_even_with_a_distinct_id(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        relationship = link(graph, a, b)
        # The store refuses an identical id; a differing id for the same triple
        # is the dangerous case, because it survives the add-contract.
        clone = relationship.model_copy(
            update={"relationship_id": relationship.relationship_id + "_dup"}
        )
        graph.relationships[clone.relationship_id] = clone
        issues = report_of(graph).issues_with_code("DUPLICATE_RELATIONSHIP")
        assert issues and issues[0].severity.value == "error"

    def test_duplicate_id_is_refused_by_the_store(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        relationship = ConceptRelationship.create(
            a.concept_id, "part_of", b.concept_id, curriculum_id="t"
        )
        graph.add_relationship(relationship)
        with pytest.raises(CurriculumGraphError):
            graph.add_relationship(relationship)

    def test_accepted_edge_without_evidence_is_a_warning_not_an_error(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        graph.add_relationship(
            ConceptRelationship.create(
                a.concept_id, "prerequisite_of", b.concept_id,
                curriculum_id="t", status=ACCEPTED,
            )
        )
        b.add_prerequisite(a.concept_id)
        report = report_of(graph)
        assert report.issues_with_code("UNSUPPORTED_RELATIONSHIP")
        assert report.is_valid is True  # a warning never blocks the graph

    def test_low_confidence_accepted_prerequisite_is_a_warning(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        threshold = CurriculumGraphValidator.MIN_ACCEPTED_PREREQUISITE_CONFIDENCE
        graph.add_relationship(
            ConceptRelationship.create(
                a.concept_id, "prerequisite_of", b.concept_id,
                curriculum_id="t", status=ACCEPTED,
                confidence=threshold - 0.1, extraction_method=HUMAN,
            )
        )
        b.add_prerequisite(a.concept_id)
        assert report_of(graph).issues_with_code("LOW_CONFIDENCE_PREREQUISITE")

    def test_orphan_concept_is_a_warning(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        graph.add_concept(a)
        graph.add_concept(b)
        lonely = concept("lonely")
        graph.add_concept(lonely)
        link(graph, a, b)
        orphan_issues = report_of(graph).issues_with_code("ORPHAN_CONCEPT")
        assert orphan_issues and orphan_issues[0].subject_id == lonely.concept_id

    def test_single_concept_graph_has_no_orphan_complaint(self):
        graph = CurriculumGraph(curriculum_id="t")
        graph.add_concept(concept("a"))
        assert report_of(graph).issues_with_code("ORPHAN_CONCEPT") == []

    def test_edge_from_a_deprecated_concept_is_flagged(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b)
        a.status = ConceptLifecycleStatus.DEPRECATED
        assert report_of(graph).issues_with_code("EDGE_FROM_DEPRECATED_CONCEPT")


class TestPrerequisiteConsistency:
    def test_list_entry_with_no_live_edge_is_an_error(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        b.add_prerequisite(a.concept_id)  # an ordering promise nothing backs
        issues = report_of(graph).issues_with_code("PREREQUISITE_LIST_UNBACKED")
        assert issues and issues[0].severity.value == "error"

    def test_mismatch_when_edge_and_list_disagree(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b)  # a is a prerequisite of b, list agrees...
        b.prerequisite_concept_ids = []  # ...until the list quietly disagrees
        issues = report_of(graph).issues_with_code("PREREQUISITE_DIRECTION_MISMATCH")
        assert issues and issues[0].severity.value == "error"

    def test_prerequisite_cycle_is_an_error(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b)
        add_cycle(graph, a, b)  # b becomes a prerequisite of a
        report = report_of(graph)
        cycle = report.issues_with_code("PREREQUISITE_CYCLE")
        assert cycle and cycle[0].severity.value == "error"
        assert report.is_valid is False

    def test_cycle_in_a_non_prerequisite_type_is_tolerated(self):
        # part_of makes no ordering promise, so a cycle carries no contradiction.
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b, rel_type="part_of")
        link(graph, b, a, rel_type="part_of")
        assert report_of(graph).issues_with_code("PREREQUISITE_CYCLE") == []
        assert report_of(graph).is_valid is True

    def test_rejected_edges_are_not_ordering_constraints(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b, status=REJECTED)
        assert graph.prerequisite_edges(include_unreviewed=False) == []
        assert would_create_cycle(graph, b.concept_id, a.concept_id) is False


class TestTraversal:
    @pytest.fixture
    def chain(self):
        # a -> b -> c, plus an isolated d
        graph = CurriculumGraph(curriculum_id="t")
        nodes = {key: concept(key) for key in ("a", "b", "c", "d")}
        for node in nodes.values():
            graph.add_concept(node)
        link(graph, nodes["a"], nodes["b"])
        link(graph, nodes["b"], nodes["c"])
        return graph, nodes

    def test_closure_directions(self, chain):
        graph, nodes = chain
        # what c must know first
        assert set(prerequisite_closure(graph, nodes["c"].concept_id)) == {
            nodes["a"].concept_id,
            nodes["b"].concept_id,
        }
        # who depends on a
        assert set(dependent_closure(graph, nodes["a"].concept_id)) == {
            nodes["b"].concept_id,
            nodes["c"].concept_id,
        }
        assert prerequisite_closure(graph, nodes["a"].concept_id) == []

    def test_depth_limits_closure(self, chain):
        graph, nodes = chain
        assert list(prerequisite_closure(graph, nodes["c"].concept_id, max_depth=1)) == [
            nodes["b"].concept_id
        ]

    def test_topological_order_puts_prerequisites_first(self, chain):
        graph, nodes = chain
        order = topological_order(graph)
        assert order.index(nodes["a"].concept_id) < order.index(nodes["b"].concept_id)
        assert order.index(nodes["b"].concept_id) < order.index(nodes["c"].concept_id)
        assert nodes["d"].concept_id in order

    def test_topological_order_is_deterministic(self, chain):
        graph, _ = chain
        assert topological_order(graph) == topological_order(graph)

    def test_strict_order_raises_on_a_cycle(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b)
        add_cycle(graph, a, b)
        with pytest.raises(PrerequisiteCycleError):
            topological_order(graph)
        # the tolerant variant still returns a total order
        assert set(cycle_safe_topological_order(graph)) == {a.concept_id, b.concept_id}

    def test_subgraph_returns_the_local_neighbourhood(self, chain):
        graph, nodes = chain
        sub = prerequisite_subgraph(graph, nodes["c"].concept_id, depth=1)
        ids = {item["concept_id"] for item in sub["concepts"]}
        assert ids == {nodes["b"].concept_id, nodes["c"].concept_id}
        assert all(
            edge["source"] in ids and edge["target"] in ids for edge in sub["relationships"]
        )

    def test_would_create_cycle(self, chain):
        graph, nodes = chain
        # c is already downstream of a, so declaring a prerequisite of c is fine
        assert would_create_cycle(graph, nodes["a"].concept_id, nodes["c"].concept_id) is False
        # ...but making a depend on c would close the loop a -> b -> c -> a
        assert would_create_cycle(graph, nodes["c"].concept_id, nodes["a"].concept_id) is True
        assert would_create_cycle(graph, nodes["a"].concept_id, nodes["a"].concept_id) is True

    def test_cycle_check_ignores_unreviewed_edges(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b, status=RelationshipStatusEnum.CANDIDATE)
        # nothing is reviewed yet, so the reverse edge is not a cycle
        assert would_create_cycle(graph, b.concept_id, a.concept_id) is False


class TestDeterminism:
    def test_validation_is_repeatable(self):
        graph = CurriculumGraph(curriculum_id="t")
        a, b = concept("a"), concept("b")
        for item in (a, b):
            graph.add_concept(item)
        link(graph, a, b)
        first = report_of(graph)
        second = report_of(graph)
        assert first.issues == second.issues
        assert first.error_count == second.error_count

    def test_prerequisite_edges_are_sorted(self):
        graph = CurriculumGraph(curriculum_id="t")
        nodes = {key: concept(key) for key in ("a", "b", "c")}
        for node in nodes.values():
            graph.add_concept(node)
        link(graph, nodes["a"], nodes["c"])
        link(graph, nodes["a"], nodes["b"])
        keys = [(rel.source, rel.target) for rel in graph.prerequisite_edges()]
        assert keys == sorted(keys)

    def test_fingerprint_changes_when_a_relationship_is_added(self):
        graph = CurriculumGraph(curriculum_id="t", syllabus_version="v1")
        a, b = concept("a"), concept("b")
        before = graph.content_fingerprint()
        for item in (a, b):
            graph.add_concept(item)
        with_edge = graph.content_fingerprint()
        link(graph, a, b)
        after = graph.content_fingerprint()
        assert len({before, with_edge, after}) == 3

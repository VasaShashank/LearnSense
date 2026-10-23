"""
Teacher review, id history, versioning and provenance (Person 2).

The invariants under test:

* merge / deprecate / replace never invalidate historical references: an old
  id keeps resolving to the concept that now carries its meaning, and the
  absorbed concept stays inspectable as a deprecated record.
* a review decision that would leave the graph invalid (for example a merge
  that closes a prerequisite loop) is refused *and rolled back*, never applied
  partially.
* version ids are content-addressed, so the same curriculum state yields the
  same id on every machine.
"""

from __future__ import annotations

import pytest

from curriculum.mapping import (
    ContentMapper,
    ExtractedConceptCandidate,
    MappingContext,
    MappingStatus,
)
from curriculum.models import (
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    ReviewStatus,
    Subject,
)
from curriculum.graph import CurriculumGraphValidator
from curriculum import provenance as provenance_module
from curriculum.provenance import ProvenanceLedger, build_source_ref
from curriculum.quality import build_structural_quality_report, summarize_for_teacher
from curriculum.repository import CurriculumRepository
from curriculum.review import (
    CurriculumReviewService,
    ReviewAction,
    ReviewConflictError,
)
from curriculum.versioning import CurriculumVersioning, diff_graphs
from phase2.models import RelationshipStatusEnum

ACCEPTED = RelationshipStatusEnum.ACCEPTED
HUMAN = "curriculum_review"
REVIEWER = "teacher_1"


def concept(key: str, name: str = "", **kwargs) -> CanonicalConcept:
    return CanonicalConcept.create(
        name or key.upper(), Subject.PHYSICS, stable_key=key, curriculum_id="t", **kwargs
    )


def link(graph: CurriculumGraph, source: CanonicalConcept, target: CanonicalConcept):
    graph.add_relationship(
        ConceptRelationship.create(
            source.concept_id, "prerequisite_of", target.concept_id,
            curriculum_id=graph.curriculum_id, status=ACCEPTED, extraction_method=HUMAN,
        )
    )
    target.add_prerequisite(source.concept_id)


def new_graph(*concepts: CanonicalConcept) -> CurriculumGraph:
    graph = CurriculumGraph(curriculum_id="t", syllabus_version="v1")
    for item in concepts:
        graph.add_concept(item)
    return graph


def valid(graph: CurriculumGraph) -> bool:
    return CurriculumGraphValidator().validate(graph).is_valid


class TestAcceptAndRejectProposedConcepts:
    def test_accept_creates_an_active_concept_and_an_audit_record(self):
        graph = new_graph()
        service = CurriculumReviewService()
        from curriculum.mapping import ProposedConcept

        proposed = ProposedConcept.build(
            name="Velocity", subject=Subject.PHYSICS, description="Rate of change of position."
        )
        created = service.accept_proposed_concept(
            graph, proposed, REVIEWER, stable_key="physics/velocity"
        )
        assert created.concept_id in graph.concepts
        assert created.status is ConceptLifecycleStatus.ACTIVE
        assert created.review_status is ReviewStatus.ACCEPTED
        # the decision is recorded in memory; persisting it is an explicit save()
        assert [record.action for record in service.records] == [ReviewAction.ACCEPT_CONCEPT]

    def test_accepting_a_colliding_surface_is_refused(self):
        existing = concept("ohm", "Ohm's Law")
        graph = new_graph(existing)
        service = CurriculumReviewService()
        from curriculum.mapping import ProposedConcept

        proposed = ProposedConcept.build(name="Ohm's Law", subject=Subject.PHYSICS)
        with pytest.raises(ReviewConflictError, match="Ohm"):
            service.accept_proposed_concept(graph, proposed, REVIEWER, stable_key="physics/ohm2")
        assert len(graph.concepts) == 1  # nothing was added

    def test_rejecting_a_candidate_remembers_the_item(self):
        graph = new_graph(concept("a", "Alpha"))
        mapper = ContentMapper(graph, MappingContext(document_id="doc1"))
        result = mapper.map_extracted_concepts(
            [ExtractedConceptCandidate(item_id="ex_77", name="Quantum Entanglement")]
        )
        assert result.candidates[0].status is MappingStatus.UNMAPPED

        service = CurriculumReviewService()
        service.reject_candidate(graph, "Quantum Entanglement", "ex_77", REVIEWER, "out of scope")
        assert service.is_rejected(graph, "ex_77") is True
        assert len(graph.concepts) == 1  # rejection never creates a concept

    def test_rejecting_an_unknown_item_is_recorded_not_crashed(self):
        graph = new_graph()
        service = CurriculumReviewService()
        record = service.reject_candidate(graph, "Anything", "ex_1", REVIEWER, "noise")
        assert record.action == ReviewAction.REJECT_CONCEPT
        assert service.is_rejected(graph, "ex_1")


class TestMerge:
    def build_pair(self):
        keep = concept("keep", "Displacement", aliases=["change in position"])
        doomed = concept("doomed", "Displacment", aliases=["displacement vector"])
        helper = concept("helper", "Velocity")
        downstream = concept("down", "Speed")
        graph = new_graph(keep, doomed, helper, downstream)
        link(graph, helper, doomed)   # velocity -> doomed
        link(graph, doomed, downstream)  # doomed -> speed
        return graph, keep, doomed, helper, downstream

    def test_merge_folds_edges_aliases_and_prerequisites(self):
        graph, keep, doomed, helper, downstream = self.build_pair()
        service = CurriculumReviewService()
        service.merge_concepts(graph, keep.concept_id, [doomed.concept_id], REVIEWER, note="typo")

        # absorbed concept is deprecated but still inspectable
        assert graph.concepts[doomed.concept_id].status is ConceptLifecycleStatus.DEPRECATED
        assert graph.concepts[doomed.concept_id].metadata["replaced_by"] == keep.concept_id
        # aliases and prerequisite position are absorbed
        assert "displacement vector" in keep.aliases
        assert helper.concept_id in keep.prerequisite_concept_ids
        assert downstream.prerequisite_concept_ids == [keep.concept_id]
        assert valid(graph)

    def test_historical_references_still_resolve_after_a_merge(self):
        graph, keep, doomed, _, _ = self.build_pair()
        ledger = ProvenanceLedger()
        for record in provenance_module.concept_provenance_records(
            doomed, curriculum_version=graph.syllabus_version, method="curriculum_spec"
        ):
            ledger.record(record)
        service = CurriculumReviewService(ledger=ledger)
        service.merge_concepts(graph, keep.concept_id, [doomed.concept_id], REVIEWER, note="typo")

        assert graph.resolve_id(doomed.concept_id) == keep.concept_id
        assert graph.successor_id(doomed.concept_id) == keep.concept_id
        # the old id's evidence trail is still readable
        assert ledger.trace(doomed.concept_id)

    def test_merge_that_would_close_a_loop_is_refused_and_rolled_back(self):
        # keep -> q -> p, and doomed depends on p: folding doomed into keep
        # rewrites p -> doomed into p -> keep, closing p -> keep -> q -> p.
        keep = concept("keep")
        q = concept("q")
        p = concept("p")
        doomed = concept("doomed")
        graph = new_graph(keep, q, p, doomed)
        link(graph, keep, q)
        link(graph, q, p)
        link(graph, p, doomed)
        before = graph.content_fingerprint()

        service = CurriculumReviewService()
        with pytest.raises(ReviewConflictError, match="invalid"):
            service.merge_concepts(graph, keep.concept_id, [doomed.concept_id], REVIEWER, note="x")

        assert graph.content_fingerprint() == before
        assert graph.concepts[doomed.concept_id].status is not ConceptLifecycleStatus.DEPRECATED
        assert graph.resolve_id(doomed.concept_id) == doomed.concept_id

    def test_merge_into_an_unknown_concept_is_refused(self):
        graph = new_graph(concept("a"))
        service = CurriculumReviewService()
        with pytest.raises(ReviewConflictError):
            service.merge_concepts(graph, "cc_does_not_exist", ["a"], REVIEWER, note="x")


class TestDeprecateAndReplace:
    def test_deprecate_records_the_reason_and_keeps_history(self):
        old = concept("old", "Old Notion")
        graph = new_graph(old)
        service = CurriculumReviewService()
        service.deprecate_concept(graph, old.concept_id, REVIEWER, reason="superseded")
        stored = graph.concepts[old.concept_id]
        assert stored.status is ConceptLifecycleStatus.DEPRECATED
        assert stored.metadata["deprecated_reason"] == "superseded"
        assert graph.resolve_id(old.concept_id) == old.concept_id  # no successor yet

    def test_deprecate_with_a_successor_repoints_references(self):
        old = concept("old", "Old Notion")
        new = concept("new", "New Notion")
        user = concept("user", "Uses Old")
        graph = new_graph(old, new, user)
        link(graph, old, user)
        service = CurriculumReviewService()
        service.deprecate_concept(
            graph, old.concept_id, REVIEWER, reason="renamed", replaced_by=new.concept_id
        )
        assert graph.resolve_id(old.concept_id) == new.concept_id
        assert user.prerequisite_concept_ids == [new.concept_id]
        assert valid(graph)

    def test_replace_swaps_the_concept_in_place(self):
        old = concept("old", "Old Notion")
        replacement = concept("fresh", "Fresh Notion")
        graph = new_graph(old)  # the re-authored concept is *not* in the graph yet

        service = CurriculumReviewService()
        created = service.replace_concept(
            graph, old.concept_id, replacement, REVIEWER, note="better source"
        )
        assert created.concept_id == replacement.concept_id
        assert created.status is ConceptLifecycleStatus.ACTIVE
        assert replacement.concept_id in graph.concepts
        assert graph.concepts[old.concept_id].status is ConceptLifecycleStatus.DEPRECATED
        assert graph.resolve_id(old.concept_id) == replacement.concept_id


class TestRelationshipReview:
    def test_accepting_an_unsourced_edge_is_refused(self):
        a, b = concept("a"), concept("b")
        graph = new_graph(a, b)
        relationship = ConceptRelationship.create(
            a.concept_id, "prerequisite_of", b.concept_id,
            curriculum_id="t", status=RelationshipStatusEnum.CANDIDATE,
        )
        graph.add_relationship(relationship)
        service = CurriculumReviewService()
        with pytest.raises(ReviewConflictError, match="evidence"):
            service.set_relationship_status(
                graph, relationship.relationship_id, ACCEPTED, REVIEWER, note="looks right"
            )

    def test_accepting_keeps_edge_and_list_in_sync(self):
        a, b = concept("a"), concept("b")
        graph = new_graph(a, b)
        relationship = ConceptRelationship.create(
            a.concept_id, "prerequisite_of", b.concept_id,
            curriculum_id="t", status=RelationshipStatusEnum.CANDIDATE,
        )
        graph.add_relationship(relationship)
        service = CurriculumReviewService()
        service.set_relationship_status(
            graph, relationship.relationship_id, ACCEPTED, REVIEWER, note="confirmed",
            source_refs=[build_source_ref("doc_1", "p.2", "A precedes B.")],
        )
        assert graph.relationships[relationship.relationship_id].status_value == "accepted"
        assert b.prerequisite_concept_ids == [a.concept_id]
        assert valid(graph)

    def test_rejecting_an_edge_removes_the_list_entry(self):
        a, b = concept("a"), concept("b")
        graph = new_graph(a, b)
        relationship = ConceptRelationship.create(
            a.concept_id, "prerequisite_of", b.concept_id,
            curriculum_id="t", status=ACCEPTED, extraction_method=HUMAN,
        )
        graph.add_relationship(relationship)
        b.add_prerequisite(a.concept_id)

        service = CurriculumReviewService()
        service.set_relationship_status(
            graph, relationship.relationship_id, RelationshipStatusEnum.REJECTED, REVIEWER,
            note="wrong direction",
        )
        assert b.prerequisite_concept_ids == []
        assert graph.prerequisite_edges(include_unreviewed=False) == []
        assert valid(graph)

    def test_accepting_an_edge_that_would_cycle_is_refused(self):
        a, b = concept("a"), concept("b")
        graph = new_graph(a, b)
        link(graph, a, b)
        reverse = ConceptRelationship.create(
            b.concept_id, "prerequisite_of", a.concept_id,
            curriculum_id="t", status=RelationshipStatusEnum.CANDIDATE,
        )
        graph.add_relationship(reverse)
        service = CurriculumReviewService()
        with pytest.raises(ReviewConflictError, match="cycle"):
            service.set_relationship_status(
                graph, reverse.relationship_id, ACCEPTED, REVIEWER, note="x",
                source_refs=[build_source_ref("doc_1", "p.9", "b before a")],
            )
        assert b.prerequisite_concept_ids == [a.concept_id]  # unchanged

    def test_unknown_relationship_is_reported(self):
        graph = new_graph()
        service = CurriculumReviewService()
        with pytest.raises(ReviewConflictError):
            service.set_relationship_status(
                graph, "rel_missing", ACCEPTED, REVIEWER, note="x"
            )


class TestVersioning:
    @pytest.fixture
    def versioning(self, tmp_path):
        # Never the shared ./storage directory: version commits must be hermetic.
        repository = CurriculumRepository(base_dir=str(tmp_path / "curriculum_store"))
        return CurriculumVersioning(repository=repository)

    def test_snapshot_ids_are_content_addressed(self, versioning):
        graph = new_graph(concept("a"), concept("b"))
        first = versioning.snapshot(graph, created_by="tester", note="one")
        second = versioning.snapshot(graph, created_by="tester", note="two")
        assert first.version.version_id == second.version.version_id
        assert first.version.version_id.startswith("cv_")

    def test_any_content_change_makes_a_new_version_id(self, versioning):
        graph = new_graph(concept("a"))
        before = versioning.snapshot(graph, created_by="tester").version.version_id
        graph.add_concept(concept("b"))
        after = versioning.snapshot(graph, created_by="tester").version.version_id
        assert before != after

    def test_commit_and_reload(self, versioning):
        graph = new_graph(concept("a"))
        snapshot = versioning.snapshot(graph, created_by="tester", note="first")
        versioning.commit(snapshot)
        listed = versioning.list_versions("t")
        assert [entry["version_id"] for entry in listed] == [snapshot.version.version_id]
        assert listed[0]["note"] == "first"
        loaded = versioning.load(snapshot.version.version_id)
        assert set(loaded.graph.concepts) == set(graph.concepts)

    def test_resolve_at_recalls_a_renamed_concept(self, versioning):
        alpha = concept("a", "Alpha")
        graph = new_graph(alpha)
        old_snapshot = versioning.snapshot(graph, created_by="tester", note="before")
        versioning.commit(old_snapshot)
        alpha.rename("Gamma", actor="tester")
        new_snapshot = versioning.snapshot(graph, created_by="tester", note="after")
        versioning.commit(new_snapshot)

        assert versioning.resolve_at(alpha.concept_id, old_snapshot.version.version_id).name == "Alpha"
        assert versioning.resolve_at(alpha.concept_id, new_snapshot.version.version_id).name == "Gamma"
        assert versioning.resolve_at("cc_unknown", old_snapshot.version.version_id) is None

    def test_diff_graphs_reports_what_changed(self):
        older = new_graph(concept("a", "Alpha"))
        newer = new_graph(concept("a", "Alpha"), concept("b", "Beta"))
        diff = diff_graphs(older, newer)
        assert len(diff["concepts_added"]) == 1
        assert diff["concepts_removed"] == []
        assert diff["concept_count_delta"] == 1
        assert diff["fingerprint_changed"] is True

    def test_diff_detects_a_rename(self):
        alpha = concept("a", "Alpha")
        older = new_graph(alpha)
        newer = new_graph(concept("a", "Alpha"))
        newer.concepts[alpha.concept_id].rename("Gamma", actor="tester")
        diff = diff_graphs(older, newer)
        assert diff["concepts_renamed"][alpha.concept_id] == {"from": "Alpha", "to": "Gamma"}


class TestProvenanceAndQuality:
    def test_provenance_round_trips_and_traces_evidence(self):
        alpha = concept("a", "Alpha")
        alpha.add_source_ref(build_source_ref("doc_1", "p.1", "Alpha is a thing."))
        ledger = ProvenanceLedger()
        for record in provenance_module.concept_provenance_records(
            alpha, curriculum_version="v1", method="curriculum_spec"
        ):
            ledger.record(record)
        assert ledger.subjects() == [alpha.concept_id]
        assert ledger.trace(alpha.concept_id)
        assert ledger.evidence_for(alpha.concept_id)[0].source_id == "doc_1"

        restored = ProvenanceLedger.load(ledger.dump())
        assert restored.dump() == ledger.dump()

    def test_excerpt_hashes_never_leak_the_text(self):
        text = "Alpha is a thing."
        ref = build_source_ref("doc_1", "p.1", text)
        assert text not in ref.excerpt_hash
        assert provenance_module.excerpt_matches(text, ref.excerpt_hash) is True
        assert provenance_module.excerpt_matches("different text", ref.excerpt_hash) is False

    def test_coverage_counts_concepts_without_evidence(self):
        alpha = concept("a", "Alpha")
        beta = concept("b", "Beta")
        alpha.add_source_ref(build_source_ref("doc_1", "p.1", "Alpha is a thing."))
        coverage = provenance_module.provenance_coverage([alpha, beta])
        assert coverage["total"] == 2
        assert coverage["with_source_refs"] == 1
        assert coverage["coverage"] == 0.5

    def test_quality_report_separates_the_four_views(self):
        graph = new_graph(concept("a"), concept("b"))
        report = build_structural_quality_report(graph)
        for key in (
            "concept_metrics",
            "relationship_metrics",
            "mapping_metrics",
            "review_metrics",
            "validation",
            "definitions",
        ):
            assert key in report
        summary = summarize_for_teacher(report)
        assert summary and all(isinstance(line, str) for line in summary)

"""
Canonical concept identity, aliases and the proposed contract round trip.

The property that matters most: a concept id must be stable across a rename and
independent of the display name, because every downstream reference (questions,
learner history, review records) points at the id rather than the label.
"""

from __future__ import annotations

import pytest

from curriculum.ids import generate_concept_id, slugify, stable_key_from_name
from curriculum.models import (
    CanonicalConcept,
    ClassLevel,
    ConceptLifecycleStatus,
    CurriculumGraph,
    ReviewStatus,
    SourceRef,
    Subject,
)
from curriculum.graph import CurriculumGraphValidator


def make(name: str, stable_key: str, **kwargs) -> CanonicalConcept:
    kwargs.setdefault("curriculum_id", "t")
    subject = kwargs.pop("subject", Subject.PHYSICS)
    return CanonicalConcept.create(name, subject, stable_key=stable_key, **kwargs)


class TestStableIds:
    def test_id_is_derived_from_stable_key_not_name(self):
        one = make("Position-Time Graph", "physics/ptg")
        two = make("Position Time Graph", "physics/ptg-other")
        assert one.concept_id != two.concept_id

    def test_id_is_document_independent(self):
        a = make("Displacement", "physics/disp", document_ids=["doc_1"])
        b = make("Displacement", "physics/disp", document_ids=["doc_9"])
        assert a.concept_id == b.concept_id

    def test_rename_keeps_the_id(self):
        concept = make("Position-Time Graph", "physics/ptg")
        before = concept.concept_id
        concept.rename("Position vs Time Plot", actor="tester")
        assert concept.concept_id == before
        assert concept.name == "Position vs Time Plot"
        # the old label survives so old references keep resolving
        assert "Position-Time Graph" in concept.metadata["previous_names"]

    def test_ids_are_deterministic(self):
        assert generate_concept_id("t", "physics/x") == generate_concept_id("t", "physics/x")
        assert generate_concept_id("t", "physics/x") != generate_concept_id("u", "physics/x")

    def test_stable_key_from_name_is_a_fallback_not_a_contract(self):
        key = stable_key_from_name("Position-Time Graph", "ch_1")
        assert "position" in key
        # documented as a slug; the canonical id still hashes curriculum+key
        assert slugify("Position-Time Graph") == "position_time_graph"


class TestAliases:
    def test_alias_that_only_differs_by_typography_is_not_duplicated(self):
        concept = make("Position-Time Graph", "physics/ptg")
        assert concept.add_alias("Position\u2013Time Graph") is False
        assert concept.add_alias("Position–Time Graph") is False  # en dash folds to the name
        assert concept.add_alias("position  time   graph") is False
        assert concept.aliases == []  # no duplicate was stored

    def test_alias_becomes_a_surface_form(self):
        concept = make("Position-Time Graph", "physics/ptg", aliases=["x-t graph"])
        surfaces = {entry["surface"] for entry in concept.surface_keys()}
        assert surfaces == {"position time graph", "x t graph"}

    def test_aliasing_does_not_create_a_second_concept(self):
        concept = make("Position-Time Graph", "physics/ptg")
        concept.add_alias("Motion Plots")
        assert list(concept.surface_keys())[-1]["kind"] == "alias"

    def test_add_prerequisite_deduplicates(self):
        concept = make("B", "physics/b")
        concept.add_prerequisite("a")
        concept.add_prerequisite("a")
        assert concept.prerequisite_concept_ids == ["a"]


class TestLifecycleAndContract:
    def test_contract_record_has_exactly_the_ten_declared_keys(self):
        record = make("Displacement", "physics/d", aliases=["change in position"]).to_contract_record()
        # exactly the property list of the shared concept_schema.json, whose
        # additionalProperties is false -- anything extra would be rejected.
        assert set(record) == {
            "concept_id",
            "name",
            "description",
            "subject",
            "chapter_id",
            "tags",
            "status",
            "prerequisite_concept_ids",
            "source_refs",
            "metadata",
        }

    def test_contract_round_trip_is_lossless(self):
        concept = make(
            "Chemical Equilibrium",
            "chemistry/ce",
            subject=Subject.CHEMISTRY,
            description="Reversible reaction at balance.",
            chapter_id="ch_eq",
            class_levels=[ClassLevel.CLASS_12],
            tags=["jee"],
            aliases=["reversible reaction equilibrium"],
            status=ConceptLifecycleStatus.ACTIVE,
            review_status=ReviewStatus.ACCEPTED,
        )
        restored = CanonicalConcept.from_contract_record(concept.to_contract_record())
        assert restored.content_dict() == concept.content_dict()

    def test_subject_and_level_coercion(self):
        assert Subject.coerce("Physics") is Subject.PHYSICS
        assert Subject.coerce("maths") is Subject.MATHEMATICS
        assert ClassLevel.coerce("CLASS_11") is ClassLevel.CLASS_11

    def test_source_refs_keep_hashed_excerpts_only(self):
        ref = SourceRef.build(
            source_id="doc_1", locator="p.3", excerpt="Displacement is a vector.", page_index=2
        )
        assert ref.excerpt_hash
        assert "Displacement" not in ref.excerpt_hash


class TestGraphStorage:
    def test_duplicate_concept_id_is_rejected(self):
        graph = CurriculumGraph(curriculum_id="t")
        graph.add_concept(make("Alpha", "a"))
        with pytest.raises(Exception):
            graph.add_concept(make("Alpha", "a"))

    def test_concept_ids_are_sorted_for_iteration(self):
        graph = CurriculumGraph(curriculum_id="t")
        for key in ("c", "a", "b"):
            graph.add_concept(make(key.upper(), key))
        assert graph.concept_ids() == sorted(graph.concept_ids())

    def test_content_fingerprint_ignores_insertion_order(self):
        first = CurriculumGraph(curriculum_id="t", syllabus_version="v1")
        second = CurriculumGraph(curriculum_id="t", syllabus_version="v1")
        concepts = [make("Alpha", "a"), make("Beta", "b")]
        for concept in concepts:
            first.add_concept(concept)
        for concept in reversed(concepts):
            second.add_concept(make(concept.name, concept.stable_key))
        assert first.content_fingerprint() == second.content_fingerprint()

    def test_validator_reports_duplicate_name_within_a_subject_only(self):
        graph = CurriculumGraph(curriculum_id="t")
        graph.add_concept(make("Ohm's Law", "physics/ohm"))
        graph.add_concept(
            CanonicalConcept.create(
                "Ohm's Law", Subject.CHEMISTRY, stable_key="chem/ohm", curriculum_id="t"
            )
        )
        report = CurriculumGraphValidator().validate(graph)
        assert report.issues_with_code("DUPLICATE_CONCEPT_NAME") == []

        graph.add_concept(make("Ohms Law", "physics/ohm2", aliases=["Ohm's Law"]))
        report = CurriculumGraphValidator().validate(graph)
        duplicates = report.issues_with_code("DUPLICATE_CONCEPT_NAME")
        assert duplicates and duplicates[0].severity.value == "error"

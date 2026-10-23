"""
Seeding (Person 2): one spec must build the same canonical graph anywhere.

Four properties are pinned here:

* determinism -- spec order and reviewer identity cannot change graph content;
* single-edge semantics -- prerequisites declared in both the concept list and
  the ``relationships`` list produce exactly one edge, never two;
* the explicit-accept state of seeded facts (active/accepted, SYSTEM review,
  provenance covering both concepts and relationships); and
* the storage boundary -- seeding without a repository writes nothing, and with
  a repository writes exactly graph + reviews + provenance under the caller's
  base dir.  A version snapshot is a separate, explicit step and is not faked
  by seeding.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from curriculum.graph import CurriculumGraphValidator
from curriculum.models import ConceptLifecycleStatus, ReviewStatus
from curriculum.provenance import ProvenanceLedger
from curriculum.repository import CurriculumRepository
from curriculum.review import ReviewAction, ReviewerRole
from curriculum.seed import CurriculumSpec, load_spec, seed_curriculum

PREREQ = "prerequisite_of"


def two_concept_cycle_spec():
    """A minimal 2-concept prerequisite cycle (A before B before A)."""
    return CurriculumSpec.model_validate(
        {
            "curriculum_id": "cycle_fixture_v1",
            "concepts": [
                {"stable_key": "physics/kinematics/alpha", "name": "Alpha", "subject": "physics"},
                {"stable_key": "physics/kinematics/beta", "name": "Beta", "subject": "physics"},
            ],
            "relationships": [
                {
                    "source_key": "physics/kinematics/alpha",
                    "target_key": "physics/kinematics/beta",
                    "type": PREREQ,
                },
                {
                    "source_key": "physics/kinematics/beta",
                    "target_key": "physics/kinematics/alpha",
                    "type": PREREQ,
                },
            ],
        }
    )


class TestDeterminism:
    def test_reordering_the_spec_does_not_change_the_graph(self, pilot_spec):
        reordered = pilot_spec.model_copy(
            update={
                "concepts": list(reversed(pilot_spec.concepts)),
                "relationships": list(reversed(pilot_spec.relationships)),
            }
        )
        first = seed_curriculum(pilot_spec)
        second = seed_curriculum(reordered)
        assert first.content_fingerprint() == second.content_fingerprint()
        assert set(first.concepts) == set(second.concepts)
        assert set(first.relationships) == set(second.relationships)

    def test_graph_content_ignores_the_reviewer_identity(self, pilot_spec):
        alice = seed_curriculum(pilot_spec, reviewer_id="alice")
        bob = seed_curriculum(pilot_spec, reviewer_id="bob")
        # same content, different audit trail: the fingerprint covers the former
        assert alice.content_fingerprint() == bob.content_fingerprint()
        assert {c.audit.created_by for c in alice.concepts.values()} == {"alice"}
        assert {c.audit.created_by for c in bob.concepts.values()} == {"bob"}
        assert {c.audit.updated_by for c in alice.concepts.values()} == {"alice"}

    def test_repository_persists_the_canonical_form_regardless_of_spec_order(
        self, pilot_spec, tmp_path
    ):
        repo = CurriculumRepository(base_dir=str(tmp_path / "store"))
        graph = seed_curriculum(pilot_spec, repository=repo, reviewer_id="order_tester")
        reordered = pilot_spec.model_copy(
            update={"concepts": list(reversed(pilot_spec.concepts))}
        )
        seed_curriculum(reordered, repository=repo, reviewer_id="order_tester")
        reloaded = repo.load_graph(pilot_spec.curriculum_id)
        assert reloaded.content_fingerprint() == graph.content_fingerprint()


class TestGraphContents:
    def test_prerequisites_declared_twice_yield_exactly_one_edge(self, pilot_spec):
        graph = seed_curriculum(pilot_spec)
        key_to_id = {
            concept.stable_key: concept_id
            for concept_id, concept in graph.concepts.items()
        }

        declared = set()
        for concept_spec in pilot_spec.concepts:
            for prereq_key in concept_spec.prerequisites:
                declared.add((key_to_id[prereq_key], key_to_id[concept_spec.stable_key]))
        for rel_spec in pilot_spec.relationships:
            if rel_spec.type == PREREQ:
                declared.add(
                    (key_to_id[rel_spec.source_key], key_to_id[rel_spec.target_key])
                )
        # the fixture says each edge twice (concept list + relationships) ...
        raw_declarations = sum(
            len(concept_spec.prerequisites) for concept_spec in pilot_spec.concepts
        ) + sum(1 for rel_spec in pilot_spec.relationships if rel_spec.type == PREREQ)
        assert raw_declarations > len(declared)

        # ... and seeding de-duplicates instead of stacking edges or list entries.
        assert len(declared) == 7
        assert len(graph.relationships) == 8  # 7 prerequisites + 1 part_of
        assert len(graph.prerequisite_edges()) == 7
        for source, target in declared:
            edges = [
                rel
                for rel in graph.relationships_between(source, target)
                if rel.is_prerequisite
            ]
            assert len(edges) == 1
            assert graph.concepts[target].prerequisite_concept_ids.count(source) == 1

    def test_seeded_graph_passes_validation_without_any_issue(self, pilot_graph):
        report = CurriculumGraphValidator().validate(pilot_graph)
        assert report.is_valid
        assert report.issues == []  # no errors and no warnings

    def test_seeded_concepts_land_as_accepted_actives(self, pilot_graph):
        for concept in pilot_graph.concepts.values():
            assert concept.status == ConceptLifecycleStatus.ACTIVE
            assert concept.review_status == ReviewStatus.ACCEPTED
            assert concept.audit.created_by == "curriculum_seeder"
            assert concept.audit.updated_by == "curriculum_seeder"


class TestPersistenceBoundary:
    @pytest.fixture
    def seeded_repo(self, pilot_spec, tmp_path):
        store = tmp_path / "store"
        repo = CurriculumRepository(base_dir=str(store))
        graph = seed_curriculum(pilot_spec, repository=repo, reviewer_id="seed_tester")
        return repo, store, graph

    def test_seed_writes_graph_reviews_and_provenance_only(self, pilot_spec, seeded_repo):
        repo, store, graph = seeded_repo
        curriculum_id = pilot_spec.curriculum_id

        assert repo.list_curriculum_ids() == [curriculum_id]
        assert repo.load_graph(curriculum_id).content_fingerprint() == (
            graph.content_fingerprint()
        )
        assert repo.list_snapshots(curriculum_id) == []  # versions are explicit, not faked

        written = {
            path.relative_to(store) for path in store.rglob("*") if path.is_file()
        }
        assert written == {
            Path("graphs") / f"{curriculum_id}.json",
            Path("reviews") / f"{curriculum_id}.json",
            Path("provenance") / f"{curriculum_id}.json",
        }

    def test_every_seeded_concept_gets_a_system_accept_review(self, pilot_spec, seeded_repo):
        repo, _store, graph = seeded_repo
        reviews = repo.load_reviews(pilot_spec.curriculum_id)
        assert len(reviews) == len(graph.concepts) == 10
        assert {r["action"] for r in reviews} == {ReviewAction.ACCEPT_CONCEPT.value}
        assert {r["reviewer_role"] for r in reviews} == {ReviewerRole.SYSTEM.value}
        assert {r["reviewer_id"] for r in reviews} == {"seed_tester"}
        assert {r["note"] for r in reviews} == {"seeded from curriculum reference spec"}
        assert {r["subject_kind"] for r in reviews} == {"concept"}
        assert {r["subject_id"] for r in reviews} == set(graph.concept_ids())

    def test_provenance_covers_concepts_and_relationships_with_a_review_trail(
        self, pilot_spec, seeded_repo
    ):
        repo, _store, graph = seeded_repo
        ledger = ProvenanceLedger.load(repo.load_provenance(pilot_spec.curriculum_id))
        records = ledger.records()
        subjects = set(ledger.subjects())

        assert subjects >= set(graph.concept_ids())
        assert subjects >= set(graph.relationships)
        assert {r.subject_kind for r in records} == {"concept", "relationship"}
        reviewed = {
            r.subject_id for r in records if getattr(r.stage, "value", r.stage) == "review"
        }
        assert reviewed >= set(graph.concept_ids())

    def test_second_curriculum_never_erases_the_first(self, tmp_path):
        repo = CurriculumRepository(base_dir=str(tmp_path / "store"))
        first_spec = CurriculumSpec.model_validate(
            {
                "curriculum_id": "first_v1",
                "concepts": [
                    {"stable_key": "physics/kinematics/alpha", "name": "Alpha", "subject": "physics"}
                ],
            }
        )
        second_spec = CurriculumSpec.model_validate(
            {
                "curriculum_id": "second_v1",
                "concepts": [
                    {"stable_key": "physics/kinematics/gamma", "name": "Gamma", "subject": "physics"}
                ],
            }
        )
        seed_curriculum(first_spec, repository=repo)
        first_reviews = repo.load_reviews("first_v1")
        first_provenance = repo.load_provenance("first_v1")

        seed_curriculum(second_spec, repository=repo)

        assert set(repo.list_curriculum_ids()) == {"first_v1", "second_v1"}
        assert repo.load_reviews("first_v1") == first_reviews
        assert repo.load_provenance("first_v1") == first_provenance

    def test_reseeding_the_same_curriculum_keeps_existing_history(
        self, pilot_spec, seeded_repo
    ):
        repo, _store, _graph = seeded_repo
        before_reviews = repo.load_reviews(pilot_spec.curriculum_id)
        before_records = len(
            ProvenanceLedger.load(repo.load_provenance(pilot_spec.curriculum_id)).records()
        )

        seed_curriculum(pilot_spec, repository=repo, reviewer_id="seed_tester")

        after_ids = {r["review_id"] for r in repo.load_reviews(pilot_spec.curriculum_id)}
        assert {r["review_id"] for r in before_reviews} <= after_ids  # nothing lost
        after_records = len(
            ProvenanceLedger.load(repo.load_provenance(pilot_spec.curriculum_id)).records()
        )
        assert after_records == before_records  # stage-addressed: no duplicates

    def test_reseed_across_a_clock_boundary_keeps_creation_history(
        self, pilot_spec, seeded_repo, monkeypatch
    ):
        """Regression: a reseed must not restamp concept creation identities.

        ``concept_provenance_records`` hashes ``audit.created_at``/``created_by``
        into the REVIEW-stage record id, so when the wall clock crossed a second
        between the first seed and a reseed, the rebuilt concepts got a new
        stamp, ten provenance ids changed, and the ledger grew duplicates.
        The reseed must carry the original creation identity forward instead.
        """
        repo, _store, _graph = seeded_repo
        before_records = len(
            ProvenanceLedger.load(repo.load_provenance(pilot_spec.curriculum_id)).records()
        )

        # Deterministically move the clock forward for the reseed only.
        monkeypatch.setattr(
            "curriculum.models.utc_now_iso", lambda: "2099-01-01T00:00:00+00:00"
        )
        reseeded = seed_curriculum(pilot_spec, repository=repo, reviewer_id="seed_tester")

        after_records = len(
            ProvenanceLedger.load(repo.load_provenance(pilot_spec.curriculum_id)).records()
        )
        assert after_records == before_records  # ids stable across the boundary

        # The stored graph still reports the original creation time, not 2099.
        stored = repo.load_graph(pilot_spec.curriculum_id)
        assert stored is not None
        for concept_id in reseeded.concept_ids():
            assert stored.concepts[concept_id].audit.created_at != "2099-01-01T00:00:00+00:00"
            assert stored.concepts[concept_id].audit.created_at == (
                _graph.concepts[concept_id].audit.created_at
            )


class TestSpecErrors:
    def test_duplicate_stable_key_is_rejected(self, pilot_spec):
        clone = pilot_spec.model_copy(deep=True)
        clone.concepts.append(clone.concepts[0])
        with pytest.raises(ValueError, match="Duplicate stable_key in spec"):
            seed_curriculum(clone)

    def test_unknown_prerequisite_key_is_rejected(self, pilot_spec):
        clone = pilot_spec.model_copy(deep=True)
        clone.concepts[0].prerequisites.append("physics/does/not/exist")
        with pytest.raises(ValueError, match="declares unknown prerequisite key"):
            seed_curriculum(clone)

    def test_self_prerequisite_is_rejected(self, pilot_spec):
        clone = pilot_spec.model_copy(deep=True)
        clone.concepts[0].prerequisites.append(clone.concepts[0].stable_key)
        with pytest.raises(ValueError, match="is its own prerequisite"):
            seed_curriculum(clone)

    def test_unknown_relationship_key_is_rejected(self, pilot_spec):
        clone = pilot_spec.model_copy(deep=True)
        clone.relationships[0].target_key = "physics/unknown/key"
        with pytest.raises(ValueError, match="unknown stable_key"):
            seed_curriculum(clone)

    def test_prerequisite_cycle_is_rejected_when_validating(self):
        with pytest.raises(ValueError, match="Seeded curriculum graph is invalid"):
            seed_curriculum(two_concept_cycle_spec())

    def test_cycle_can_only_seed_with_validation_explicitly_off(self):
        graph = seed_curriculum(two_concept_cycle_spec(), validate=False)
        assert len(graph.concepts) == 2
        assert len(graph.relationships) == 2
        # validate=False is an inspection escape hatch, not a claim of validity
        assert not CurriculumGraphValidator().validate(graph).is_valid


class TestLoadSpec:
    def test_file_round_trip_seeds_the_same_way_as_an_inline_spec(self, tmp_path):
        payload = {
            "curriculum_id": "handwritten_v1",
            "syllabus_version": "v1",
            "title": "Handwritten",
            "concepts": [
                {
                    "stable_key": "physics/kinematics/alpha",
                    "name": "Alpha",
                    "subject": "physics",
                    "aliases": ["first"],
                },
                {
                    "stable_key": "physics/kinematics/beta",
                    "name": "Beta",
                    "subject": "physics",
                    "prerequisites": ["physics/kinematics/alpha"],
                },
            ],
            "relationships": [
                {
                    "source_key": "physics/kinematics/alpha",
                    "target_key": "physics/kinematics/beta",
                    "type": PREREQ,
                    "rationale": "alpha before beta",
                }
            ],
        }
        path = tmp_path / "spec.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        graph = seed_curriculum(load_spec(path))

        assert len(graph.concepts) == 2
        assert len(graph.relationships) == 1  # declared twice, seeded once
        alpha_id = next(cid for cid, c in graph.concepts.items() if c.name == "Alpha")
        beta_id = next(cid for cid, c in graph.concepts.items() if c.name == "Beta")
        assert graph.concepts[beta_id].prerequisite_concept_ids == [alpha_id]
        assert graph.concepts[alpha_id].aliases == ["first"]

    def test_unknown_spec_field_is_rejected_not_ignored(self, tmp_path):
        path = tmp_path / "spec.json"
        path.write_text(
            json.dumps(
                {
                    "curriculum_id": "handwritten_v1",
                    "concepts": [
                        {"stable_key": "k", "name": "Alpha", "subject": "physics"}
                    ],
                    "bogus_field": 1,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            load_spec(path)

    def test_missing_spec_file_raises_loudly(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_spec(tmp_path / "absent.json")

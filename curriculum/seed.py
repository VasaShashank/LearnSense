"""
Seeding a curriculum from a declarative specification (Person 2).

Why a spec format at all: the canonical graph has to be buildable identically on
two machines (test fixtures, evaluation runs, a colleague's checkout).  A spec is
keyed by explicit ``stable_key`` values rather than by array order, so concept
ids do not depend on iteration order, and prerequisites are declared by stable
key too, which means a spec never references a generated id it cannot know.

Seeding is an *explicit* accept step: every seeded concept lands as
``status=active`` / ``review_status=accepted`` with a ``SYSTEM``-role review
record saying where it came from.  It is not a substitute for teacher review of
pipeline output -- ``CurriculumReviewService`` still handles everything a
pipeline proposes.

Example spec::

    {
      "curriculum_id": "pilot_jee_physics_v1",
      "syllabus_version": "2026.pilot.v1",
      "title": "Physics pilot",
      "concepts": [
        {
          "stable_key": "physics/kinematics/position-time-graph",
          "name": "Position-Time Graph",
          "subject": "physics",
          "chapter_id": "ch_kinematics",
          "aliases": ["x-t graph"],
          "prerequisites": ["physics/units-and-measurement/units"]
        }
      ],
      "relationships": [
        {"source_key": "physics/...", "target_key": "physics/...",
         "type": "prerequisite_of"}
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from curriculum.graph import CurriculumGraphValidator
from curriculum.models import (
    AuditInfo,
    CanonicalConcept,
    ClassLevel,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    IdReference,
    ReviewStatus,
    SourceRef,
    Subject,
)
from curriculum.provenance import ProvenanceLedger, concept_provenance_records, relationship_provenance_records
from curriculum.repository import CurriculumRepository
from curriculum.review import ReviewAction, ReviewerRole, ReviewRecord
from phase2.models import RelationshipStatusEnum, RelationshipTypeEnum

__all__ = ["CurriculumSpec", "SeededConceptSpec", "SeededRelationshipSpec", "load_spec", "seed_curriculum"]


class SeededConceptSpec(BaseModel):
    """One canonical concept in a curriculum spec."""

    model_config = ConfigDict(extra="forbid")

    stable_key: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    subject: Subject
    description: str = ""
    chapter_id: Optional[str] = None
    topic_path: List[str] = Field(default_factory=list)
    class_levels: List[ClassLevel] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    source_refs: List[SourceRef] = Field(default_factory=list)
    status: Optional[str] = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("subject", mode="before")
    @classmethod
    def _coerce_subject(cls, value: Any) -> Any:
        return Subject.coerce(value) if not isinstance(value, Subject) else value


class SeededRelationshipSpec(BaseModel):
    """One typed edge beyond the concept-level ``prerequisites`` declarations."""

    model_config = ConfigDict(extra="forbid")

    source_key: str
    target_key: str
    type: str = "prerequisite_of"
    status: str = "accepted"
    rationale: Optional[str] = None


class CurriculumSpec(BaseModel):
    """A declarative, order-independent curriculum definition."""

    model_config = ConfigDict(extra="forbid")

    curriculum_id: str = Field(..., min_length=1)
    syllabus_version: str = "2026.jee.v1"
    title: str = ""
    concepts: List[SeededConceptSpec] = Field(default_factory=list)
    relationships: List[SeededRelationshipSpec] = Field(default_factory=list)
    id_map: List[IdReference] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def concept_by_key(self) -> Dict[str, SeededConceptSpec]:
        return {concept.stable_key: concept for concept in self.concepts}


def load_spec(path: str | Path) -> CurriculumSpec:
    """Load and validate a curriculum spec JSON file."""
    spec_path = Path(path)
    with open(spec_path, "r", encoding="utf-8") as handle:
        return CurriculumSpec.model_validate(json.load(handle))


def seed_curriculum(
    spec: CurriculumSpec,
    repository: Optional[CurriculumRepository] = None,
    reviewer_id: str = "curriculum_seeder",
    validate: bool = True,
) -> CurriculumGraph:
    """
    Build a canonical graph from a spec.

    Deterministic: concepts are created sorted by ``stable_key``, so the same
    spec produces the same graph fingerprint regardless of how it is written down.

    Raises ``ValueError`` on an unknown prerequisite key, a duplicate stable key
    or (when ``validate`` is set) an invalid resulting graph.  Seeding never
    leaves a half-built graph in memory for a caller to persist by accident.
    """
    by_key: Dict[str, SeededConceptSpec] = {}
    for concept in spec.concepts:
        if concept.stable_key in by_key:
            raise ValueError(f"Duplicate stable_key in spec: '{concept.stable_key}'")
        by_key[concept.stable_key] = concept

    graph = CurriculumGraph(
        curriculum_id=spec.curriculum_id,
        syllabus_version=spec.syllabus_version,
        title=spec.title,
        metadata=dict(spec.metadata),
        id_map=list(spec.id_map),
    )
    # What the store already holds for this curriculum (None on first seed).
    # Re-seeding rewrites the graph file, so concept creation identities must
    # be carried forward from here rather than restamped (see pass 1).
    stored = repository.load_graph(spec.curriculum_id) if repository is not None else None
    prior_concepts = stored.concepts if stored is not None else {}
    key_to_id: Dict[str, str] = {}
    ordered = sorted(spec.concepts, key=lambda concept: concept.stable_key)

    # Pass 1: identities.  Prerequisites are wired in pass 2 because a concept may
    # legitimately declare a prerequisite that sorts after it.
    for concept_spec in ordered:
        concept_status = (
            ConceptLifecycleStatus(concept_spec.status)
            if concept_spec.status
            else ConceptLifecycleStatus.ACTIVE
        )
        concept = CanonicalConcept.create(
            concept_spec.name,
            concept_spec.subject,
            stable_key=concept_spec.stable_key,
            description=concept_spec.description,
            chapter_id=concept_spec.chapter_id,
            topic_path=concept_spec.topic_path,
            class_levels=concept_spec.class_levels,
            tags=concept_spec.tags,
            aliases=concept_spec.aliases,
            source_refs=concept_spec.source_refs,
            curriculum_id=graph.curriculum_id,
            curriculum_version=graph.syllabus_version,
            status=concept_status,
            review_status=ReviewStatus.ACCEPTED,
            created_by=reviewer_id,
        )
        if concept_spec.metadata:
            concept.metadata.update(concept_spec.metadata)
        prior = prior_concepts.get(concept.concept_id)
        if prior is not None:
            # Re-seed of an existing concept: keep its original creation
            # identity.  Provenance record ids hash created_at/created_by, so
            # restamping them would break idempotent dedupe whenever the wall
            # clock crosses a second between seeds, and would silently rewrite
            # when the concept was actually created.
            concept.audit = AuditInfo(
                created_at=prior.audit.created_at,
                updated_at=concept.audit.updated_at,
                created_by=prior.audit.created_by,
                updated_by=reviewer_id,
                revision=prior.audit.revision,
                source_document_ids=list(prior.audit.source_document_ids),
            )
        else:
            concept.audit = AuditInfo(
                created_at=concept.audit.created_at,
                updated_at=concept.audit.updated_at,
                created_by=reviewer_id,
                updated_by=reviewer_id,
            )
        if concept.concept_id in graph.concepts:
            raise ValueError(
                f"stable_key '{concept_spec.stable_key}' collides with an existing concept id; "
                f"keys must be unique across chapters in the same subject scope"
            )
        graph.add_concept(concept)
        key_to_id[concept_spec.stable_key] = concept.concept_id

    # Pass 2: prerequisites declared at concept level.
    for concept_spec in ordered:
        concept_id = key_to_id[concept_spec.stable_key]
        for prereq_key in concept_spec.prerequisites:
            prereq_id = key_to_id.get(prereq_key)
            if prereq_id is None:
                raise ValueError(
                    f"Concept '{concept_spec.stable_key}' declares unknown prerequisite key "
                    f"'{prereq_key}'"
                )
            if prereq_id == concept_id:
                raise ValueError(f"Concept '{concept_spec.stable_key}' is its own prerequisite")
            graph.concepts[concept_id].add_prerequisite(prereq_id)
            _ensure_prerequisite_edge(graph, prereq_id, concept_id, reviewer_id)

    # Pass 3: explicitly declared relationships.
    for rel_spec in sorted(
        spec.relationships, key=lambda rel: (rel.source_key, rel.type, rel.target_key)
    ):
        source_id = key_to_id.get(rel_spec.source_key)
        target_id = key_to_id.get(rel_spec.target_key)
        if source_id is None or target_id is None:
            missing = [k for k, v in ((rel_spec.source_key, source_id), (rel_spec.target_key, target_id)) if v is None]
            raise ValueError(f"Relationship references unknown stable_key(s): {', '.join(missing)}")
        rel_type = RelationshipTypeEnum(rel_spec.type)
        relationship = ConceptRelationship.create(
            source_id,
            rel_type,
            target_id,
            curriculum_id=graph.curriculum_id,
            status=RelationshipStatusEnum(rel_spec.status),
            rationale=rel_spec.rationale,
            extraction_method="curriculum_spec",
        )
        if relationship.relationship_id in graph.relationships:
            continue
        graph.add_relationship(relationship)
        if rel_type == RelationshipTypeEnum.PREREQUISITE_OF and rel_spec.status == "accepted":
            graph.concepts[target_id].add_prerequisite(source_id)

    if validate:
        report = CurriculumGraphValidator().validate(graph)
        if not report.is_valid:
            details = "; ".join(issue.message for issue in report.issues[:5])
            raise ValueError(f"Seeded curriculum graph is invalid: {details}")

    if repository is not None:
        _record_seed_provenance(graph, repository, reviewer_id)
        repository.save_graph(graph)
    return graph


def _ensure_prerequisite_edge(
    graph: CurriculumGraph, source: str, target: str, reviewer_id: str
) -> None:
    for existing in graph.relationships_between(source, target):
        if existing.is_prerequisite:
            return
    graph.add_relationship(
        ConceptRelationship.create(
            source,
            RelationshipTypeEnum.PREREQUISITE_OF,
            target,
            curriculum_id=graph.curriculum_id,
            status=RelationshipStatusEnum.ACCEPTED,
            rationale=f"declared in curriculum spec, confirmed by {reviewer_id}",
            extraction_method="curriculum_spec",
        )
    )


def _record_seed_provenance(
    graph: CurriculumGraph, repository: CurriculumRepository, reviewer_id: str
) -> None:
    """
    Persist provenance + review records so seeded facts are traceable too.

    Existing ledgers are loaded first and extended, never overwritten: seeding a
    second curriculum must not erase the review history of the first.
    """
    ledger = ProvenanceLedger.load(repository.load_provenance(graph.curriculum_id))
    records = [
        ReviewRecord.model_validate(item) for item in repository.load_reviews(graph.curriculum_id)
    ]

    for concept_id in graph.concept_ids():
        concept = graph.concepts[concept_id]
        for record in concept_provenance_records(concept, curriculum_version=graph.syllabus_version):
            ledger.record(record)
        ledger.record_review(
            "concept",
            concept_id,
            {
                "action": ReviewAction.ACCEPT_CONCEPT.value,
                "reviewer_id": reviewer_id,
                "reviewer_role": ReviewerRole.SYSTEM.value,
                "note": "seeded from curriculum reference spec",
                "stable_key": concept.stable_key,
            },
            refs=concept.source_refs,
            curriculum_version=graph.syllabus_version,
        )
        records.append(
            ReviewRecord.build(
                ReviewAction.ACCEPT_CONCEPT,
                "concept",
                concept_id,
                reviewer_id,
                reviewer_role=ReviewerRole.SYSTEM,
                note="seeded from curriculum reference spec",
                new_state={"name": concept.name, "status": concept.status.value},
            )
        )

    for relationship in sorted(graph.relationships.values(), key=lambda rel: rel.relationship_id):
        for record in relationship_provenance_records(relationship, graph.syllabus_version):
            ledger.record(record)

    repository.save_provenance(graph.curriculum_id, ledger.dump())
    repository.save_reviews(
        graph.curriculum_id, [record.model_dump(mode="json") for record in records]
    )

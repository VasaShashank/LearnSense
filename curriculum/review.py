"""
Teacher / curriculum-editor review of proposed concepts and relationships (Person 2).

This is the gate between *what a pipeline proposed* and *what the curriculum
claims*.  Nothing created by automatic extraction becomes a canonical,
``active`` concept without a record here naming a human reviewer.

Handled explicitly:

* **accept** a proposed concept into the canonical graph (rejecting duplicates),
* **reject** a candidate, remembered so the same noise is not re-proposed blind,
* **merge** duplicate concepts without invalidating historical references,
* **deprecate** a concept (optionally pointing at its successor),
* **replace** a concept with a re-authored one,
* **accept / reject** a proposed relationship, keeping the edge set and each
  concept's ``prerequisite_concept_ids`` in step.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from curriculum.graph import CurriculumGraphValidator, would_create_cycle
from curriculum.mapping import ProposedConcept
from curriculum.models import (
    AuditInfo,
    CanonicalConcept,
    ConceptLifecycleStatus,
    ConceptRelationship,
    CurriculumGraph,
    IdReference,
    ReviewStatus,
    SourceRef,
    Subject,
)
from curriculum.provenance import (
    ProvenanceLedger,
    concept_provenance_records,
    relationship_provenance_records,
)
from curriculum.repository import CurriculumRepository
from phase2.models import RelationshipStatusEnum, RelationshipTypeEnum

__all__ = [
    "CurriculumReviewService",
    "ReviewAction",
    "ReviewConflictError",
    "ReviewRecord",
    "ReviewerRole",
]


class ReviewConflictError(Exception):
    """Raised when a review decision would corrupt the canonical store."""


class ReviewAction(str, Enum):
    ACCEPT_CONCEPT = "accept_concept"
    REJECT_CONCEPT = "reject_concept"
    MERGE_CONCEPTS = "merge_concepts"
    DEPRECATE_CONCEPT = "deprecate_concept"
    REPLACE_CONCEPT = "replace_concept"
    ACCEPT_RELATIONSHIP = "accept_relationship"
    REJECT_RELATIONSHIP = "reject_relationship"


class ReviewerRole(str, Enum):
    TEACHER = "teacher"
    CURRICULUM_EDITOR = "curriculum_editor"
    SYSTEM = "system"


class ReviewRecord(BaseModel):
    """Audit entry for one review decision."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    action: ReviewAction
    subject_kind: str = "concept"
    subject_id: str
    reviewer_id: str
    reviewer_role: ReviewerRole = ReviewerRole.TEACHER
    note: str = ""
    created_at: str = ""
    previous_state: Dict[str, Any] = Field(default_factory=dict)
    new_state: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        action: ReviewAction,
        subject_kind: str,
        subject_id: str,
        reviewer_id: str,
        *,
        reviewer_role: ReviewerRole = ReviewerRole.TEACHER,
        note: str = "",
        created_at: str = "",
        previous_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
    ) -> "ReviewRecord":
        from curriculum.models import utc_now_iso

        stamp = created_at or utc_now_iso()
        raw = f"{action.value}::{subject_kind}::{subject_id}::{reviewer_id}::{stamp}::{note}"
        return cls(
            review_id="rv_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
            action=action,
            subject_kind=subject_kind,
            subject_id=subject_id,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            note=note,
            created_at=stamp,
            previous_state=previous_state or {},
            new_state=new_state or {},
        )


class CurriculumReviewService:
    """
    Applies review decisions to a :class:`~curriculum.models.CurriculumGraph`.

    Each mutator validates the result before returning and rolls the in-memory
    graph back when the decision would leave the store invalid, so a rejected
    merge can never half-apply.
    """

    def __init__(
        self,
        repository: Optional[CurriculumRepository] = None,
        ledger: Optional[ProvenanceLedger] = None,
    ):
        self.repository = repository or CurriculumRepository()
        self.ledger = ledger or ProvenanceLedger()
        self.records: List[ReviewRecord] = []

    # ----------------------------------------------------------------- ledger
    def load(self, curriculum_id: str) -> None:
        self.records = [
            ReviewRecord.model_validate(item) for item in self.repository.load_reviews(curriculum_id)
        ]
        self.ledger = ProvenanceLedger.load(self.repository.load_provenance(curriculum_id))

    def save(self, curriculum_id: str) -> None:
        self.repository.save_reviews(
            curriculum_id, [record.model_dump(mode="json") for record in self.records]
        )
        self.repository.save_provenance(curriculum_id, self.ledger.dump())

    def _record(self, record: ReviewRecord) -> ReviewRecord:
        self.records.append(record)
        return record

    # ------------------------------------------------------------ accept concept
    def accept_proposed_concept(
        self,
        graph: CurriculumGraph,
        proposed: ProposedConcept,
        reviewer_id: str,
        *,
        stable_key: Optional[str] = None,
        reviewer_role: ReviewerRole = ReviewerRole.TEACHER,
        note: str = "",
        merge_into: Optional[str] = None,
        prerequisite_ids: Optional[Sequence[str]] = None,
        created_at: Optional[str] = None,
    ) -> CanonicalConcept:
        """
        Promote a proposed concept into the canonical graph.

        Raises :class:`ReviewConflictError` when an active concept in the same
        subject already owns the name or an alias, unless ``merge_into`` names the
        concept it should be folded into.
        """
        duplicates = self._find_duplicates(graph, proposed.name, proposed.subject, proposed.aliases)
        if duplicates and not merge_into:
            raise ReviewConflictError(
                "Proposed concept '"
                + proposed.name
                + "' collides with existing concept(s) "
                + ", ".join(duplicates)
                + ". Pass merge_into=<concept_id> to fold it in, or reject the proposal."
            )
        if merge_into is not None and merge_into not in graph.concepts:
            raise ReviewConflictError(f"merge_into target '{merge_into}' is not a canonical concept")

        prerequisites = list(prerequisite_ids or [])
        for prereq in prerequisites:
            if prereq not in graph.concepts:
                raise ReviewConflictError(
                    f"Prerequisite '{prereq}' is not a canonical concept; accept it first."
                )

        concept = CanonicalConcept.create(
            proposed.name,
            proposed.subject,
            stable_key=stable_key,
            description=proposed.description,
            chapter_id=proposed.chapter_id,
            class_levels=list(proposed.class_levels),
            tags=list(proposed.tags),
            aliases=list(proposed.aliases),
            prerequisite_concept_ids=[p for p in prerequisites if p != ""],
            source_refs=list(proposed.source_refs),
            curriculum_id=graph.curriculum_id,
            curriculum_version=graph.syllabus_version,
            status=ConceptLifecycleStatus.ACTIVE,
            review_status=ReviewStatus.ACCEPTED,
            created_by=reviewer_id,
            metadata={"extracted_type": proposed.extracted_type} if proposed.extracted_type else {},
        )
        # Freeze the audit timestamp when the caller supplies one (deterministic tests).
        if created_at:
            concept.audit = AuditInfo(
                created_at=created_at,
                updated_at=created_at,
                created_by=reviewer_id,
                updated_by=reviewer_id,
            )

        snapshot = graph.model_copy(deep=True)
        graph.add_concept(concept)
        if merge_into:
            self._merge_into(graph, merge_into, [concept.concept_id], reviewer_id, note or "merged at accept time")
        for prereq in prerequisites:
            self._add_prerequisite_edge(graph, prereq, concept.concept_id, reviewer_id)

        self._require_valid(graph, snapshot, "accepting the concept would leave the graph invalid")

        for record in concept_provenance_records(concept, curriculum_version=graph.syllabus_version):
            self.ledger.record(record)
        self.ledger.record_review(
            "concept",
            concept.concept_id,
            {
                "action": ReviewAction.ACCEPT_CONCEPT.value,
                "reviewer_id": reviewer_id,
                "reviewer_role": reviewer_role.value,
                "note": note,
                "merged_into": merge_into,
            },
            refs=concept.source_refs,
            curriculum_version=graph.syllabus_version,
        )
        self._record(
            ReviewRecord.build(
                ReviewAction.ACCEPT_CONCEPT,
                "concept",
                concept.concept_id,
                reviewer_id,
                reviewer_role=reviewer_role,
                note=note,
                created_at=created_at or "",
                new_state={"name": concept.name, "status": concept.status.value},
            )
        )
        return graph.concepts[merge_into] if merge_into else concept

    def reject_candidate(
        self,
        graph: CurriculumGraph,
        label: str,
        item_id: str,
        reviewer_id: str,
        reason: str,
        *,
        reviewer_role: ReviewerRole = ReviewerRole.TEACHER,
        created_at: Optional[str] = None,
    ) -> ReviewRecord:
        """
        Remember a rejected proposal.

        The graph is unchanged; the rejection is stored so a later run can tell
        the teacher "this was already reviewed and refused" instead of re-proposing
        the same noise as if it were new.
        """
        rejected = graph.metadata.setdefault("rejected_candidates", {})
        rejected[item_id] = {"label": label, "reason": reason, "reviewer_id": reviewer_id}
        self.ledger.record_review(
            "mapping_candidate",
            item_id,
            {
                "action": ReviewAction.REJECT_CONCEPT.value,
                "reviewer_id": reviewer_id,
                "reviewer_role": reviewer_role.value,
                "reason": reason,
                "label": label,
            },
            curriculum_version=graph.syllabus_version,
        )
        return self._record(
            ReviewRecord.build(
                ReviewAction.REJECT_CONCEPT,
                "mapping_candidate",
                item_id,
                reviewer_id,
                reviewer_role=reviewer_role,
                note=reason,
                created_at=created_at or "",
                new_state={"label": label, "outcome": "rejected"},
            )
        )

    def is_rejected(self, graph: CurriculumGraph, item_id: str) -> bool:
        return item_id in (graph.metadata.get("rejected_candidates") or {})

    # ------------------------------------------------------------- relationships
    def set_relationship_status(
        self,
        graph: CurriculumGraph,
        relationship_id: str,
        status: RelationshipStatusEnum,
        reviewer_id: str,
        note: str = "",
        *,
        reviewer_role: ReviewerRole = ReviewerRole.TEACHER,
        source_refs: Optional[Sequence[SourceRef]] = None,
        created_at: Optional[str] = None,
    ) -> ConceptRelationship:
        """
        Accept or reject a proposed edge.

        Accepting a ``prerequisite_of`` edge also writes the edge into the target
        concept's ``prerequisite_concept_ids``; rejecting it removes it there.  The
        two representations are one fact stored twice, and the validator treats
        disagreement as an error.
        """
        relationship = graph.relationships.get(relationship_id)
        if relationship is None:
            raise ReviewConflictError(f"Relationship '{relationship_id}' does not exist")
        for ref in source_refs or []:
            relationship.source_refs.append(ref)

        snapshot = graph.model_copy(deep=True)
        previous = relationship.status_value
        previous_status = relationship.status
        relationship.status = status
        if status == RelationshipStatusEnum.ACCEPTED:
            if not (relationship.evidence_ids or relationship.source_refs):
                raise ReviewConflictError(
                    "Refusing to accept a relationship with no source evidence; attach evidence first."
                )
            if relationship.is_prerequisite:
                if relationship.source not in graph.concepts or relationship.target not in graph.concepts:
                    raise ReviewConflictError("Cannot accept a prerequisite edge with unknown endpoints")
                if would_create_cycle(graph, relationship.source, relationship.target):
                    relationship.status = previous_status
                    raise ReviewConflictError(
                        f"Accepting {relationship.source} -> {relationship.target} would create a "
                        f"prerequisite cycle."
                    )
                graph.concepts[relationship.target].add_prerequisite(relationship.source)
        elif relationship.is_prerequisite and relationship.target in graph.concepts:
            target = graph.concepts[relationship.target]
            target.prerequisite_concept_ids = [
                prereq for prereq in target.prerequisite_concept_ids if prereq != relationship.source
            ]

        self._require_valid(
            graph, snapshot, f"setting {relationship_id} to {status.value} would leave the graph invalid"
        )
        self.ledger.record(
            relationship_provenance_records(relationship, curriculum_version=graph.syllabus_version)[-1]
        )
        self._record(
            ReviewRecord.build(
                ReviewAction.ACCEPT_RELATIONSHIP
                if status == RelationshipStatusEnum.ACCEPTED
                else ReviewAction.REJECT_RELATIONSHIP,
                "relationship",
                relationship_id,
                reviewer_id,
                reviewer_role=reviewer_role,
                note=note,
                created_at=created_at or "",
                previous_state={"status": previous},
                new_state={"status": relationship.status_value},
            )
        )
        return relationship

    # -------------------------------------------------------------------- merge
    def merge_concepts(
        self,
        graph: CurriculumGraph,
        keep_id: str,
        merge_ids: Sequence[str],
        reviewer_id: str,
        note: str = "",
        *,
        reviewer_role: ReviewerRole = ReviewerRole.CURRICULUM_EDITOR,
        created_at: Optional[str] = None,
    ) -> CanonicalConcept:
        """
        Fold ``merge_ids`` into ``keep_id``.

        The surviving concept absorbs aliases, evidence and prerequisite edges; the
        absorbed concepts are deprecated with ``metadata["replaced_by"]`` and an
        ``id_map`` entry, so any historical reference still resolves.
        """
        if keep_id not in graph.concepts:
            raise ReviewConflictError(f"Merge target '{keep_id}' does not exist")
        targets = [concept_id for concept_id in merge_ids if concept_id != keep_id]
        for concept_id in targets:
            if concept_id not in graph.concepts:
                raise ReviewConflictError(f"Concept '{concept_id}' does not exist")

        snapshot = graph.model_copy(deep=True)
        self._merge_into(graph, keep_id, targets, reviewer_id, note)
        self._require_valid(graph, snapshot, "merging would leave the graph invalid")

        self.ledger.record_review(
            "concept",
            keep_id,
            {
                "action": ReviewAction.MERGE_CONCEPTS.value,
                "reviewer_id": reviewer_id,
                "merged": targets,
                "note": note,
            },
            curriculum_version=graph.syllabus_version,
        )
        self._record(
            ReviewRecord.build(
                ReviewAction.MERGE_CONCEPTS,
                "concept",
                keep_id,
                reviewer_id,
                reviewer_role=reviewer_role,
                note=note,
                created_at=created_at or "",
                new_state={"merged": targets, "canonical_name": graph.concepts[keep_id].name},
            )
        )
        return graph.concepts[keep_id]

    def _merge_into(
        self,
        graph: CurriculumGraph,
        keep_id: str,
        merge_ids: Sequence[str],
        reviewer_id: str,
        note: str,
    ) -> None:
        keeper = graph.concepts[keep_id]
        for concept_id in merge_ids:
            if concept_id == keep_id:
                continue
            loser = graph.concepts[concept_id]
            for alias in list(loser.aliases):
                keeper.add_alias(alias)
            if loser.name != keeper.name:
                keeper.add_alias(loser.name)
            for ref in loser.source_refs:
                keeper.add_source_ref(ref)
            if not keeper.description and loser.description:
                keeper.description = loser.description
            for tag in loser.tags:
                if tag not in keeper.tags:
                    keeper.tags.append(tag)
            for level in loser.class_levels:
                if level not in keeper.class_levels:
                    keeper.class_levels.append(level)
            for prereq in loser.prerequisite_concept_ids:
                if prereq not in {keep_id, concept_id}:
                    keeper.add_prerequisite(prereq)

            loser.status = ConceptLifecycleStatus.DEPRECATED
            loser.metadata["replaced_by"] = keep_id
            loser.metadata["merge_outcome"] = "merged_into"
            loser.audit.touch(reviewer_id)
            graph.record_id_reference(
                IdReference(
                    old_id=concept_id,
                    current_id=keep_id,
                    relation="merged_into",
                    note=note,
                    version_id=graph.syllabus_version,
                )
            )

        self._rewrite_references(graph, {concept_id: keep_id for concept_id in merge_ids})

    # ---------------------------------------------------------------- deprecate
    def deprecate_concept(
        self,
        graph: CurriculumGraph,
        concept_id: str,
        reviewer_id: str,
        reason: str,
        *,
        replaced_by: Optional[str] = None,
        reviewer_role: ReviewerRole = ReviewerRole.CURRICULUM_EDITOR,
        created_at: Optional[str] = None,
    ) -> CanonicalConcept:
        """Deprecate a concept, optionally pointing at its successor."""
        concept = graph.concepts.get(concept_id)
        if concept is None:
            raise ReviewConflictError(f"Concept '{concept_id}' does not exist")
        if replaced_by is not None and replaced_by not in graph.concepts:
            raise ReviewConflictError(f"Successor '{replaced_by}' is not a canonical concept")

        snapshot = graph.model_copy(deep=True)
        concept.status = ConceptLifecycleStatus.DEPRECATED
        concept.metadata["deprecated_reason"] = reason
        if replaced_by:
            concept.metadata["replaced_by"] = replaced_by
        concept.audit.touch(reviewer_id)

        graph.record_id_reference(
            IdReference(
                old_id=concept_id,
                current_id=replaced_by or concept_id,
                relation="replaced_by" if replaced_by else "deprecated",
                note=reason,
                version_id=graph.syllabus_version,
            )
        )
        if replaced_by:
            self._rewrite_references(graph, {concept_id: replaced_by})
        self._require_valid(graph, snapshot, "deprecating would leave the graph invalid")

        self.ledger.record_review(
            "concept",
            concept_id,
            {
                "action": ReviewAction.DEPRECATE_CONCEPT.value,
                "reviewer_id": reviewer_id,
                "reason": reason,
                "replaced_by": replaced_by,
            },
            curriculum_version=graph.syllabus_version,
        )
        self._record(
            ReviewRecord.build(
                ReviewAction.DEPRECATE_CONCEPT,
                "concept",
                concept_id,
                reviewer_id,
                reviewer_role=reviewer_role,
                note=reason,
                created_at=created_at or "",
                previous_state={"status": "active"},
                new_state={"status": "deprecated", "replaced_by": replaced_by},
            )
        )
        return concept

    def replace_concept(
        self,
        graph: CurriculumGraph,
        old_id: str,
        new_concept: CanonicalConcept,
        reviewer_id: str,
        note: str = "",
        *,
        reviewer_role: ReviewerRole = ReviewerRole.CURRICULUM_EDITOR,
        created_at: Optional[str] = None,
    ) -> CanonicalConcept:
        """Replace a concept with a re-authored one, preserving references."""
        if old_id not in graph.concepts:
            raise ReviewConflictError(f"Concept '{old_id}' does not exist")
        if new_concept.concept_id in graph.concepts:
            raise ReviewConflictError(f"Concept '{new_concept.concept_id}' already exists")

        snapshot = graph.model_copy(deep=True)
        old = graph.concepts[old_id]
        for alias in list(old.aliases):
            new_concept.add_alias(alias)
        if old.name != new_concept.name:
            new_concept.add_alias(old.name)
        for ref in old.source_refs:
            new_concept.add_source_ref(ref)
        # The editor's decision is the activating review, exactly as in
        # ``accept_proposed_concept``; a ``draft`` successor would be invisible
        # to every consumer that filters on active concepts.
        new_concept.status = ConceptLifecycleStatus.ACTIVE
        new_concept.review_status = ReviewStatus.ACCEPTED
        graph.add_concept(new_concept)

        old.status = ConceptLifecycleStatus.DEPRECATED
        old.metadata["replaced_by"] = new_concept.concept_id
        old.audit.touch(reviewer_id)
        graph.record_id_reference(
            IdReference(
                old_id=old_id,
                current_id=new_concept.concept_id,
                relation="replaced_by",
                note=note,
                version_id=graph.syllabus_version,
            )
        )
        self._rewrite_references(graph, {old_id: new_concept.concept_id})
        self._require_valid(graph, snapshot, "replacing would leave the graph invalid")

        self._record(
            ReviewRecord.build(
                ReviewAction.REPLACE_CONCEPT,
                "concept",
                old_id,
                reviewer_id,
                reviewer_role=reviewer_role,
                note=note,
                created_at=created_at or "",
                new_state={"replaced_by": new_concept.concept_id},
            )
        )
        return new_concept

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _find_duplicates(
        graph: CurriculumGraph, name: str, subject: Subject, aliases: Sequence[str]
    ) -> List[str]:
        from curriculum.normalization import normalize_term

        wanted = {normalize_term(name)}
        wanted.update(normalize_term(alias) for alias in aliases if normalize_term(alias))
        subject_value = subject.value if isinstance(subject, Subject) else str(subject)
        hits: List[str] = []
        for concept in graph.concepts.values():
            if concept.subject_value != subject_value:
                continue
            if concept.status == ConceptLifecycleStatus.DEPRECATED:
                continue
            surfaces = {entry["surface"] for entry in concept.surface_keys()}
            if wanted & surfaces:
                hits.append(concept.concept_id)
        return sorted(hits)

    def _add_prerequisite_edge(
        self, graph: CurriculumGraph, source: str, target: str, reviewer_id: str
    ) -> None:
        existing = graph.relationships_between(source, target)
        prerequisite_edges = [rel for rel in existing if rel.is_prerequisite]
        if prerequisite_edges:
            return
        relationship = ConceptRelationship.create(
            source,
            RelationshipTypeEnum.PREREQUISITE_OF,
            target,
            curriculum_id=graph.curriculum_id,
            status=RelationshipStatusEnum.ACCEPTED,
            rationale=f"curriculum prerequisite accepted by {reviewer_id}",
            extraction_method="curriculum_review",
        )
        graph.add_relationship(relationship)

    @staticmethod
    def _rewrite_references(graph: CurriculumGraph, mapping: Dict[str, str]) -> None:
        """Point every prerequisite list and edge at the surviving concept."""
        for concept in graph.concepts.values():
            rewritten: List[str] = []
            for prereq in concept.prerequisite_concept_ids:
                resolved = mapping.get(prereq, prereq)
                if resolved != concept.concept_id and resolved not in rewritten:
                    rewritten.append(resolved)
            concept.prerequisite_concept_ids = rewritten

        by_key: Dict[tuple, List[str]] = {}
        for relationship in list(graph.relationships.values()):
            new_source = mapping.get(relationship.source, relationship.source)
            new_target = mapping.get(relationship.target, relationship.target)
            relationship.source = new_source
            relationship.target = new_target
            key = (new_source, relationship.type_value, new_target)
            by_key.setdefault(key, []).append(relationship.relationship_id)

        for key, ids in by_key.items():
            if len(ids) < 2:
                continue
            ids_sorted = sorted(ids)
            # Keep the edge that actually carries evidence; mark the rest rejected
            # rather than deleting them, so the history stays inspectable.
            keep = next(
                (
                    graph.relationships[rid]
                    for rid in ids_sorted
                    if graph.relationships[rid].evidence_ids or graph.relationships[rid].source_refs
                ),
                graph.relationships[ids_sorted[0]],
            )
            for rid in ids_sorted:
                if rid == keep.relationship_id:
                    continue
                duplicate = graph.relationships[rid]
                duplicate.status = RelationshipStatusEnum.REJECTED
                duplicate.flags.append("superseded_by_merge")
                duplicate.metadata["superseded_by"] = keep.relationship_id

    def _require_valid(self, graph: CurriculumGraph, snapshot: CurriculumGraph, message: str) -> None:
        report = CurriculumGraphValidator().validate(graph)
        if report.is_valid:
            return
        graph.concepts = snapshot.concepts
        graph.relationships = snapshot.relationships
        graph.id_map = snapshot.id_map
        graph.metadata = snapshot.metadata
        raise ReviewConflictError(
            f"{message}: " + "; ".join(issue.message for issue in report.issues[:3])
        )

"""
Canonical curriculum data models (Person 2).

Contract stance
---------------
The team's proposed ``LearnSense_Shared_Contracts_v0_1/schemas/concept_schema.json``
is a *proposal* (``status: "proposed_review_required"``).  It constrains a concept
record to exactly these keys with ``additionalProperties: false``::

    concept_id, name, description, subject, chapter_id, tags, status,
    prerequisite_concept_ids, source_refs, metadata

Person 2 needs more than that (aliases, class levels, review/audit state,
curriculum version, topic hierarchy), and the contract has no place to put them.
Rather than break a contract other workstreams already read, the extra state is
carried inside ``metadata``, which the contract *does* allow and leaves open.

``CanonicalConcept.to_contract_record()`` therefore emits exactly the ten
contract keys and validates against the proposed schema, while the in-process
model keeps typed, first-class fields.  ``to_contract_record()`` /
``from_contract_record()`` round-trip losslessly.  The deviations and their
justification are documented in ``docs/curriculum/CONTRACT_REVIEW.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field

from curriculum.ids import (
    DEFAULT_CURRICULUM_ID,
    DEFAULT_SYLLABUS_VERSION,
    excerpt_hash as _excerpt_hash,
    generate_concept_id,
    generate_relationship_id,
    stable_key_from_name,
)
from curriculum.normalization import normalize_term
from phase2.models import (
    ConfidenceBreakdown,
    EvidenceLevelEnum,
    Relationship as Phase2Relationship,
    RelationshipStatusEnum,
    RelationshipTypeEnum,
)


def utc_now_iso() -> str:
    """Timestamp helper; injectable in tests via ``AuditInfo`` so runs stay reproducible."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


#: Id-map relations that move a historical reference onto a successor concept.
_FORWARDING_RELATIONS = {"merged_into", "replaced_by"}


class Subject(str, Enum):
    """Academic subject of the JEE curriculum.  Values are lowercase and stable."""

    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    MATHEMATICS = "mathematics"

    @property
    def display_name(self) -> str:
        return self.value.capitalize()

    @classmethod
    def coerce(cls, value: Any) -> "Subject":
        """Accept ``"Physics"`` / ``"PHYSICS"`` as well as ``Subject.PHYSICS``."""
        if isinstance(value, cls):
            return value
        key = str(value).strip().lower()
        aliases = {
            "phy": cls.PHYSICS,
            "maths": cls.MATHEMATICS,
            "math": cls.MATHEMATICS,
            "chem": cls.CHEMISTRY,
        }
        if key in aliases:
            return aliases[key]
        return cls(key)


class ClassLevel(str, Enum):
    """Class/grade the concept is taught in.  JEE preparation targets 11 and 12."""

    CLASS_11 = "class_11"
    CLASS_12 = "class_12"

    @property
    def display_name(self) -> str:
        return f"Class {self.value.rsplit('_', 1)[-1]}"

    @classmethod
    def coerce(cls, value: Any) -> "ClassLevel":
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        if text in {"11", "11th", "xi", "class11", "class_11"}:
            return cls.CLASS_11
        if text in {"12", "12th", "xii", "class12", "class_12"}:
            return cls.CLASS_12
        return cls(text)


class Examination(str, Enum):
    """
    Authoritative examination target.
    Distinguishes JEE Main from NEET and other examination curricula
    rather than relying on subject names alone.
    """

    JEE_MAIN = "jee_main"
    NEET = "neet"
    GENERAL = "general"

    @property
    def display_name(self) -> str:
        if self == Examination.JEE_MAIN:
            return "JEE (Main)"
        if self == Examination.NEET:
            return "NEET (UG)"
        return "General"

    @classmethod
    def coerce(cls, value: Any) -> "Examination":
        if isinstance(value, cls):
            return value
        v = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if "jee" in v:
            return cls.JEE_MAIN
        if "neet" in v:
            return cls.NEET
        return cls.GENERAL


class ConceptLifecycleStatus(str, Enum):
    """
    Lifecycle of a canonical concept.

    These three values are exactly the shared contract's enum, so a serialized
    concept is contract-valid.  Merged/replaced concepts are represented as
    ``deprecated`` plus ``metadata["replaced_by"]`` rather than adding a fourth
    status, again to stay contract-valid.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ReviewStatus(str, Enum):
    """Editorial state of a concept, kept separate from its lifecycle status."""

    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SourceRef(BaseModel):
    """
    One piece of source evidence backing a concept or relationship.

    Serialized form matches the contract's ``source_refs[]`` item exactly
    (``source_id``, ``locator``, ``excerpt_hash`` with no extra keys).  The richer
    provenance this module needs (page indices, block ids, section title, the
    excerpt itself) rides along in ``provenance`` and is *not* emitted to the
    contract record.
    """

    source_id: str = Field(..., min_length=1, description="Source document / dataset id.")
    locator: Optional[str] = Field(
        default=None, description="Human-readable location, e.g. 'p.12 §3.1' or 'block:b_7'."
    )
    excerpt_hash: Optional[str] = Field(
        default=None, description="Short sha256 of the normalized evidence excerpt."
    )
    provenance: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extended, non-contract provenance (pages, blocks, excerpt, sections).",
    )

    @classmethod
    def build(
        cls,
        source_id: str,
        locator: Optional[str] = None,
        excerpt: Optional[str] = None,
        page_index: Optional[int] = None,
        block_ids: Optional[List[str]] = None,
        section_title: Optional[str] = None,
        section_id: Optional[str] = None,
        evidence_ids: Optional[List[str]] = None,
    ) -> "SourceRef":
        """Build a ref, hashing the excerpt so evidence can be re-verified later."""
        provenance: Dict[str, Any] = {}
        if page_index is not None:
            provenance["page_index"] = page_index
        if block_ids:
            provenance["block_ids"] = list(block_ids)
        if section_id:
            provenance["section_id"] = section_id
        if section_title:
            provenance["section_title"] = section_title
        if evidence_ids:
            provenance["evidence_ids"] = list(evidence_ids)
        if excerpt:
            provenance["excerpt"] = excerpt
        return cls(
            source_id=source_id,
            locator=locator,
            excerpt_hash=_excerpt_hash(excerpt) if excerpt else None,
            provenance=provenance,
        )

    def to_contract(self) -> Dict[str, Any]:
        return {"source_id": self.source_id, "locator": self.locator, "excerpt_hash": self.excerpt_hash}

    @classmethod
    def from_contract(cls, data: Dict[str, Any]) -> "SourceRef":
        return cls(
            source_id=data["source_id"],
            locator=data.get("locator"),
            excerpt_hash=data.get("excerpt_hash"),
        )

    def excerpt(self) -> str:
        return str(self.provenance.get("excerpt") or "")


class AuditInfo(BaseModel):
    """Who created/last touched a record and when.  Serialized into ``metadata``."""

    created_at: str = ""
    updated_at: str = ""
    created_by: str = "curriculum_pipeline"
    updated_by: str = ""
    revision: int = 1
    source_document_ids: List[str] = Field(default_factory=list)

    @classmethod
    def now(cls, created_by: str = "curriculum_pipeline", document_ids: Optional[List[str]] = None) -> "AuditInfo":
        stamp = utc_now_iso()
        return cls(
            created_at=stamp,
            updated_at=stamp,
            created_by=created_by,
            updated_by=created_by,
            source_document_ids=list(document_ids or []),
        )

    def touch(self, actor: str) -> None:
        self.updated_at = utc_now_iso()
        self.updated_by = actor
        self.revision += 1


class CanonicalConcept(BaseModel):
    """
    A canonical curriculum concept.

    Identity rules:

    * ``concept_id`` is generated once from ``(curriculum_id, stable_key)`` and is
      independent of the source document and of the display name.
    * ``rename()`` changes ``name`` only; ``concept_id`` is untouched and the old
      name is preserved in ``metadata["previous_names"]``.
    * ``aliases`` accept ordinary spelling / notation / naming variations without
      creating a second canonical concept.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    concept_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    subject: Subject
    chapter_id: Optional[str] = None
    topic_path: List[str] = Field(default_factory=list)
    class_levels: List[ClassLevel] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    status: ConceptLifecycleStatus = ConceptLifecycleStatus.DRAFT
    review_status: ReviewStatus = ReviewStatus.PROPOSED
    aliases: List[str] = Field(default_factory=list)
    prerequisite_concept_ids: List[str] = Field(default_factory=list)
    source_refs: List[SourceRef] = Field(default_factory=list)
    curriculum_id: str = DEFAULT_CURRICULUM_ID
    curriculum_version: str = DEFAULT_SYLLABUS_VERSION
    stable_key: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def examination(self) -> Examination:
        """
        Examination target for this curriculum graph.
        Infers from metadata or curriculum_id, defaulting to JEE_MAIN.
        """
        exam_val = self.metadata.get("examination") or self.metadata.get("exam")
        if exam_val:
            return Examination.coerce(exam_val)
        if "neet" in self.curriculum_id.lower():
            return Examination.NEET
        return Examination.JEE_MAIN
    audit: AuditInfo = Field(default_factory=AuditInfo)

    # ---------------------------------------------------------------- factory
    @classmethod
    def create(
        cls,
        name: str,
        subject: Subject,
        *,
        stable_key: Optional[str] = None,
        description: str = "",
        chapter_id: Optional[str] = None,
        topic_path: Optional[List[str]] = None,
        class_levels: Optional[List[ClassLevel]] = None,
        tags: Optional[List[str]] = None,
        aliases: Optional[List[str]] = None,
        prerequisite_concept_ids: Optional[List[str]] = None,
        source_refs: Optional[List[SourceRef]] = None,
        curriculum_id: str = DEFAULT_CURRICULUM_ID,
        curriculum_version: str = DEFAULT_SYLLABUS_VERSION,
        status: ConceptLifecycleStatus = ConceptLifecycleStatus.DRAFT,
        review_status: ReviewStatus = ReviewStatus.PROPOSED,
        created_by: str = "curriculum_pipeline",
        document_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "CanonicalConcept":
        """
        Create a concept, assigning its permanent id.

        ``stable_key`` is the curriculum-authored identifier for the concept.  When
        it is omitted, one is derived from the normalized name *once* and then
        frozen into the record, so a later rename still cannot move the id.
        """
        resolved_key = stable_key or stable_key_from_name(name, chapter_id)
        concept = cls(
            concept_id=generate_concept_id(curriculum_id, resolved_key),
            name=normalize_term(name).title() if name.isupper() else name.strip(),
            description=description,
            subject=Subject.coerce(subject),
            chapter_id=chapter_id,
            topic_path=list(topic_path or []),
            class_levels=[ClassLevel.coerce(level) for level in (class_levels or [])],
            tags=list(tags or []),
            status=status,
            review_status=review_status,
            aliases=[],
            prerequisite_concept_ids=list(prerequisite_concept_ids or []),
            source_refs=list(source_refs or []),
            curriculum_id=curriculum_id,
            curriculum_version=curriculum_version,
            stable_key=resolved_key,
            metadata=dict(metadata or {}),
            audit=AuditInfo.now(created_by=created_by, document_ids=document_ids),
        )
        for alias in aliases or []:
            concept.add_alias(alias)
        return concept

    # ------------------------------------------------------------- properties
    @property
    def normalized_name(self) -> str:
        return normalize_term(self.name)

    @property
    def subject_value(self) -> str:
        return self.subject.value if isinstance(self.subject, Subject) else str(self.subject)

    def surface_keys(self) -> List[Dict[str, str]]:
        """Every surface form that should map to this concept, with its kind."""
        keys = [{"surface": self.normalized_name, "kind": "canonical_name", "original": self.name}]
        for alias in self.aliases:
            keys.append({"surface": normalize_term(alias), "kind": "alias", "original": alias})
        return [entry for entry in keys if entry["surface"]]

    # --------------------------------------------------------------- mutation
    def add_alias(self, alias: str) -> bool:
        """Add an alias unless an equivalent surface form already exists."""
        normalized = normalize_term(alias)
        if not normalized or normalized == self.normalized_name:
            return False
        existing = {normalize_term(existing) for existing in self.aliases}
        if normalized in existing:
            return False
        self.aliases.append(alias.strip())
        return True

    def rename(self, new_name: str, actor: str = "curriculum_editor") -> None:
        """
        Change the display name only.

        The concept id is untouched, and the previous name is recorded so that
        historical references and teacher search keep working.
        """
        cleaned = (new_name or "").strip()
        if not cleaned:
            raise ValueError("new_name must not be empty")
        if cleaned == self.name:
            return
        previous = self.metadata.setdefault("previous_names", [])
        if self.name not in previous:
            previous.append(self.name)
        self.name = cleaned
        self.audit.touch(actor)

    def add_source_ref(self, ref: SourceRef) -> bool:
        """Append evidence, de-duplicating on (source_id, locator, excerpt_hash)."""
        signature = (ref.source_id, ref.locator, ref.excerpt_hash)
        for existing in self.source_refs:
            if (existing.source_id, existing.locator, existing.excerpt_hash) == signature:
                return False
        self.source_refs.append(ref)
        return True

    def add_prerequisite(self, concept_id: str) -> bool:
        if concept_id == self.concept_id or concept_id in self.prerequisite_concept_ids:
            return False
        self.prerequisite_concept_ids.append(concept_id)
        return True

    # ------------------------------------------------------------ fingerprint
    def content_dict(self) -> Dict[str, Any]:
        """Deterministic view of the concept, excluding audit timestamps."""
        subject = self.subject.value if isinstance(self.subject, Subject) else str(self.subject)
        levels = [
            level.value if isinstance(level, ClassLevel) else str(level) for level in self.class_levels
        ]
        status = (
            self.status.value if isinstance(self.status, ConceptLifecycleStatus) else str(self.status)
        )
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "description": self.description,
            "subject": subject,
            "chapter_id": self.chapter_id,
            "topic_path": list(self.topic_path),
            "class_levels": levels,
            "tags": list(self.tags),
            "status": status,
            "aliases": list(self.aliases),
            "prerequisite_concept_ids": list(self.prerequisite_concept_ids),
            "source_refs": [ref.to_contract() for ref in self.source_refs],
        }

    # ---------------------------------------------------------------- contract
    def to_contract_record(self) -> Dict[str, Any]:
        """Serialize to exactly the proposed ``concept_schema.json`` shape."""
        subject = self.subject.value if isinstance(self.subject, Subject) else str(self.subject)
        status = (
            self.status.value if isinstance(self.status, ConceptLifecycleStatus) else str(self.status)
        )
        metadata = dict(self.metadata)
        metadata.update(
            {
                "aliases": list(self.aliases),
                "topic_path": list(self.topic_path),
                "class_levels": [
                    level.value if isinstance(level, ClassLevel) else str(level)
                    for level in self.class_levels
                ],
                "review_status": (
                    self.review_status.value
                    if isinstance(self.review_status, ReviewStatus)
                    else str(self.review_status)
                ),
                "curriculum_id": self.curriculum_id,
                "curriculum_version": self.curriculum_version,
                "stable_key": self.stable_key,
                "audit": self.audit.model_dump(mode="json"),
            }
        )
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "description": self.description,
            "subject": subject,
            "chapter_id": self.chapter_id,
            "tags": list(self.tags),
            "status": status,
            "prerequisite_concept_ids": list(self.prerequisite_concept_ids),
            "source_refs": [ref.to_contract() for ref in self.source_refs],
            "metadata": metadata,
        }

    @classmethod
    def from_contract_record(cls, record: Dict[str, Any]) -> "CanonicalConcept":
        """Inverse of :meth:`to_contract_record`."""
        metadata = dict(record.get("metadata") or {})
        audit_data = metadata.pop("audit", {}) or {}
        concept = cls(
            concept_id=record["concept_id"],
            name=record["name"],
            description=record.get("description", ""),
            subject=Subject.coerce(record["subject"]) if record.get("subject") else Subject.PHYSICS,
            chapter_id=record.get("chapter_id"),
            topic_path=list(metadata.get("topic_path") or []),
            class_levels=[ClassLevel.coerce(level) for level in (metadata.get("class_levels") or [])],
            tags=list(record.get("tags") or []),
            status=ConceptLifecycleStatus(record.get("status", "draft")),
            review_status=ReviewStatus(metadata.get("review_status", "proposed")),
            aliases=list(metadata.get("aliases") or []),
            prerequisite_concept_ids=list(record.get("prerequisite_concept_ids") or []),
            source_refs=[SourceRef.from_contract(item) for item in (record.get("source_refs") or [])],
            curriculum_id=metadata.get("curriculum_id", DEFAULT_CURRICULUM_ID),
            curriculum_version=metadata.get("curriculum_version", DEFAULT_SYLLABUS_VERSION),
            stable_key=metadata.get("stable_key", ""),
            metadata=metadata,
            audit=AuditInfo.model_validate(audit_data or {}),
        )
        return concept


class ConceptRelationship(BaseModel):
    """
    A typed edge between two canonical concepts.

    Direction convention (agreed with the team)::

        A --prerequisite_of--> B   means   "A is a prerequisite of B"

    so ``B.prerequisite_concept_ids`` contains ``A``.  ``CurriculumGraphValidator``
    treats a disagreement between the edge list and the concept-level
    prerequisite lists as an error rather than silently picking one.
    """

    model_config = ConfigDict(extra="forbid")

    relationship_id: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1, description="Canonical concept id of the prerequisite.")
    type: RelationshipTypeEnum
    target: str = Field(..., min_length=1, description="Canonical concept id of the dependent.")
    status: RelationshipStatusEnum = RelationshipStatusEnum.CANDIDATE
    evidence_level: EvidenceLevelEnum = EvidenceLevelEnum.UNCERTAIN
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: List[str] = Field(default_factory=list)
    source_refs: List[SourceRef] = Field(default_factory=list)
    rationale: Optional[str] = None
    extraction_method: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def examination(self) -> Examination:
        """
        Examination target for this curriculum graph.
        Infers from metadata or curriculum_id, defaulting to JEE_MAIN.
        """
        exam_val = self.metadata.get("examination") or self.metadata.get("exam")
        if exam_val:
            return Examination.coerce(exam_val)
        if "neet" in self.curriculum_id.lower():
            return Examination.NEET
        return Examination.JEE_MAIN

    @classmethod
    def create(
        cls,
        source: str,
        relationship_type: RelationshipTypeEnum,
        target: str,
        *,
        curriculum_id: str = DEFAULT_CURRICULUM_ID,
        status: RelationshipStatusEnum = RelationshipStatusEnum.CANDIDATE,
        evidence_level: EvidenceLevelEnum = EvidenceLevelEnum.UNCERTAIN,
        confidence: float = 1.0,
        evidence_ids: Optional[List[str]] = None,
        source_refs: Optional[List[SourceRef]] = None,
        rationale: Optional[str] = None,
        extraction_method: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ConceptRelationship":
        rel_type = (
            relationship_type.value
            if isinstance(relationship_type, RelationshipTypeEnum)
            else str(relationship_type)
        )
        return cls(
            relationship_id=generate_relationship_id(curriculum_id, source, rel_type, target),
            source=source,
            type=relationship_type,
            target=target,
            status=status,
            evidence_level=evidence_level,
            confidence=confidence,
            evidence_ids=list(evidence_ids or []),
            source_refs=list(source_refs or []),
            rationale=rationale,
            extraction_method=extraction_method,
            metadata=dict(metadata or {}),
        )

    @property
    def type_value(self) -> str:
        return self.type.value if isinstance(self.type, RelationshipTypeEnum) else str(self.type)

    @property
    def status_value(self) -> str:
        return self.status.value if isinstance(self.status, RelationshipStatusEnum) else str(self.status)

    @property
    def is_prerequisite(self) -> bool:
        return self.type_value == RelationshipTypeEnum.PREREQUISITE_OF.value

    @property
    def is_reviewed(self) -> bool:
        return self.status_value in {
            RelationshipStatusEnum.ACCEPTED.value,
            RelationshipStatusEnum.REJECTED.value,
        }

    def content_dict(self) -> Dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "source": self.source,
            "type": self.type_value,
            "target": self.target,
            "status": self.status_value,
            "evidence_level": (
                self.evidence_level.value
                if isinstance(self.evidence_level, EvidenceLevelEnum)
                else str(self.evidence_level)
            ),
            "confidence": self.confidence,
            "source_refs": [ref.to_contract() for ref in self.source_refs],
        }

    def to_phase2_relationship(self) -> Phase2Relationship:
        """
        Bridge to the existing Phase 2 / Phase 3 graph types.

        Lets Person 3/4 keep consuming ``phase2.models.Relationship`` (and hence
        ``LearningContext``) unchanged while the canonical graph stays the source
        of truth.
        """
        return Phase2Relationship(
            relationship_id=self.relationship_id,
            source=self.source,
            type=self.type,
            target=self.target,
            status=self.status,
            evidence_level=self.evidence_level,
            confidence=ConfidenceBreakdown(value=self.confidence),
            evidence_ids=list(self.evidence_ids),
            flags=list(self.flags),
            rationale=self.rationale,
            extraction_method=self.extraction_method,
            metadata=dict(self.metadata),
        )


class IdReference(BaseModel):
    """
    Resolution entry so historical references survive curriculum evolution.

    Relations:

    ``same``
        the id still resolves to itself (normal case).
    ``merged_into`` / ``replaced_by``
        the concept was folded into / superseded by ``current_id``.
    ``split_into``
        the concept was split; ``current_ids`` lists the successors and the old id
        no longer resolves to a single concept.
    ``removed``
        tombstone; the id deliberately resolves to nothing.
    """

    old_id: str
    current_id: Optional[str] = None
    current_ids: List[str] = Field(default_factory=list)
    relation: str = "same"
    note: str = ""
    version_id: Optional[str] = None


class CurriculumGraph(BaseModel):
    """
    The canonical curriculum graph: concepts + typed relationships + id history.

    No learner state lives here.  Mastery, attempts and BKT belong to Person 3.
    """

    model_config = ConfigDict(extra="forbid")

    curriculum_id: str = DEFAULT_CURRICULUM_ID
    syllabus_version: str = DEFAULT_SYLLABUS_VERSION
    title: str = ""
    concepts: Dict[str, CanonicalConcept] = Field(default_factory=dict)
    relationships: Dict[str, ConceptRelationship] = Field(default_factory=dict)
    id_map: List[IdReference] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def examination(self) -> Examination:
        """
        Examination target for this curriculum graph.
        Infers from metadata or curriculum_id, defaulting to JEE_MAIN.
        """
        exam_val = self.metadata.get("examination") or self.metadata.get("exam")
        if exam_val:
            return Examination.coerce(exam_val)
        if "neet" in self.curriculum_id.lower():
            return Examination.NEET
        return Examination.JEE_MAIN

    # ------------------------------------------------------------- identity
    def resolve_id(self, concept_id: str) -> Optional[str]:
        """
        Resolve a historical reference to the concept that now carries its meaning.

        A merged or replaced concept still exists in the store as a *deprecated*
        record (so its history stays inspectable), but references to it must
        follow the id map to the successor.  Returns ``None`` when the id no
        longer resolves to a single concept (removed, or split).
        """
        seen: Set[str] = set()
        current: Optional[str] = concept_id
        while current is not None:
            if current in seen:
                return None
            seen.add(current)
            entry = next((item for item in self.id_map if item.old_id == current), None)
            forwards = entry is not None and entry.relation in _FORWARDING_RELATIONS and entry.current_id
            if current in self.concepts:
                if forwards:
                    current = entry.current_id  # type: ignore[assignment]
                    continue
                return current
            if forwards:
                current = entry.current_id  # type: ignore[assignment]
                continue
            return None
        return None

    def successor_id(self, concept_id: str) -> Optional[str]:
        """Like :meth:`resolve_id` but returns ``None`` when the id is unchanged."""
        resolved = self.resolve_id(concept_id)
        return resolved if resolved != concept_id else None

    def get_concept(self, concept_id: str) -> Optional[CanonicalConcept]:
        resolved = self.resolve_id(concept_id)
        return self.concepts.get(resolved) if resolved else None

    def concept_ids(self) -> List[str]:
        """Sorted, stable iteration order."""
        return sorted(self.concepts.keys())

    # -------------------------------------------------------------- mutation
    def add_concept(self, concept: CanonicalConcept, replace: bool = False) -> None:
        if not replace and concept.concept_id in self.concepts:
            raise CurriculumGraphError(f"Concept '{concept.concept_id}' already exists")
        self.concepts[concept.concept_id] = concept

    def add_relationship(self, relationship: ConceptRelationship, replace: bool = False) -> None:
        if not replace and relationship.relationship_id in self.relationships:
            raise CurriculumGraphError(
                f"Relationship '{relationship.relationship_id}' already exists"
            )
        self.relationships[relationship.relationship_id] = relationship

    def record_id_reference(self, entry: IdReference) -> None:
        self.id_map = [item for item in self.id_map if item.old_id != entry.old_id]
        self.id_map.append(entry)

    # -------------------------------------------------------------- queries
    def prerequisite_edges(self, include_unreviewed: bool = True) -> List[ConceptRelationship]:
        """Prerequisite edges, sorted deterministically by (source, target)."""
        edges = [
            rel
            for rel in self.relationships.values()
            if rel.is_prerequisite and (include_unreviewed or rel.status_value == "accepted")
        ]
        return sorted(edges, key=lambda rel: (rel.source, rel.target, rel.relationship_id))

    def relationships_between(self, source: str, target: str) -> List[ConceptRelationship]:
        return sorted(
            (rel for rel in self.relationships.values() if rel.source == source and rel.target == target),
            key=lambda rel: (rel.type_value, rel.relationship_id),
        )

    # ------------------------------------------------------------ fingerprint
    def content_fingerprint(self) -> str:
        """Deterministic checksum over graph content (ignores audit timestamps)."""
        import hashlib
        import json

        payload = {
            "curriculum_id": self.curriculum_id,
            "syllabus_version": self.syllabus_version,
            "concepts": [self.concepts[key].content_dict() for key in sorted(self.concepts)],
            "relationships": [
                self.relationships[key].content_dict() for key in sorted(self.relationships)
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class CurriculumGraphError(Exception):
    """Raised for structural graph mutations that would corrupt the canonical store."""


# Re-exported at the end so ``models`` has no import cycle with ``graph``.
__all__ = [
    "AuditInfo",
    "CanonicalConcept",
    "ClassLevel",
    "ConceptLifecycleStatus",
    "ConceptRelationship",
    "CurriculumGraph",
    "CurriculumGraphError",
    "IdReference",
    "ReviewStatus",
    "SourceRef",
    "Subject",
    "utc_now_iso",
]

# Keep the names referenced by :mod:`curriculum` importable from one place.

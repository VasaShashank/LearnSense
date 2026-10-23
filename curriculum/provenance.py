"""
Provenance tracking for the canonical curriculum (Person 2).

The point of this module is to keep five things apart that are easy to confuse:

``source``
    where a piece of text actually came from (document, page, block, section) and
    a hash of the excerpt so the claim can be re-checked later.
``extraction``
    what an automated pipeline *proposed*, with its method and pipeline version.
    A proposal is not a curriculum fact.
``canonical``
    the canonical concept or relationship a proposal was mapped onto.
``validation``
    the structural verdict recorded at the time of acceptance.
``review``
    the human decision that promoted (or refused) the proposal.
``version``
    the curriculum/graph version under which all of the above was accepted.

A record never claims more than it knows: an extracted claim with no teacher
review stays ``EXTRACTION``-stage and is never presented as verified curriculum.
"""

from __future__ import annotations

import hashlib
import json
import logging
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from curriculum.ids import excerpt_hash
from curriculum.models import CanonicalConcept, ConceptRelationship, SourceRef, utc_now_iso

logger = logging.getLogger(__name__)


class ProvenanceStage(str, Enum):
    SOURCE = "source"
    EXTRACTION = "extraction"
    CANONICAL = "canonical"
    VALIDATION = "validation"
    REVIEW = "review"
    VERSION = "version"


_STAGE_ORDER = {stage: index for index, stage in enumerate(ProvenanceStage)}


class ProvenanceRecord(BaseModel):
    """One link in a concept's/relationship's history."""

    model_config = ConfigDict(extra="forbid")

    record_id: str
    stage: ProvenanceStage
    subject_kind: str = Field(..., description="concept | relationship | mapping_candidate")
    subject_id: str
    source_refs: List[SourceRef] = Field(default_factory=list)
    extraction: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    review: Dict[str, Any] = Field(default_factory=dict)
    curriculum_version: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)

    @classmethod
    def build(
        cls,
        stage: ProvenanceStage,
        subject_kind: str,
        subject_id: str,
        *,
        source_refs: Optional[Iterable[SourceRef]] = None,
        extraction: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
        review: Optional[Dict[str, Any]] = None,
        curriculum_version: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> "ProvenanceRecord":
        """Deterministic record id so re-recording the same fact is idempotent."""
        payload = {
            "stage": stage.value if isinstance(stage, ProvenanceStage) else str(stage),
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "extraction": extraction or {},
            "validation": validation or {},
            "review": review or {},
            "curriculum_version": curriculum_version,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        record_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return cls(
            record_id=f"pv_{record_id}",
            stage=stage,
            subject_kind=subject_kind,
            subject_id=subject_id,
            source_refs=list(source_refs or []),
            extraction=dict(extraction or {}),
            validation=dict(validation or {}),
            review=dict(review or {}),
            curriculum_version=curriculum_version,
            created_at=created_at or utc_now_iso(),
        )

    def sort_key(self) -> tuple:
        return (_STAGE_ORDER[self.stage], self.record_id)


class ProvenanceLedger:
    """
    Append-only provenance store backed by the shared JSON repository conventions.

    Records are de-duplicated on their deterministic id, so replaying the same
    mapping run or re-approving the same candidate does not duplicate history.
    """

    def __init__(self, records: Optional[Iterable[ProvenanceRecord]] = None):
        self._records: Dict[str, ProvenanceRecord] = {}
        for record in records or []:
            self._records[record.record_id] = record

    # ------------------------------------------------------------------ write
    def record(self, record: ProvenanceRecord) -> ProvenanceRecord:
        self._records[record.record_id] = record
        return record

    def record_source(self, subject_kind: str, subject_id: str, refs: Iterable[SourceRef]) -> ProvenanceRecord:
        return self.record(
            ProvenanceRecord.build(
                ProvenanceStage.SOURCE, subject_kind, subject_id, source_refs=refs
            )
        )

    def record_extraction(
        self, subject_kind: str, subject_id: str, extraction: Dict[str, Any], refs: Iterable[SourceRef] = ()
    ) -> ProvenanceRecord:
        return self.record(
            ProvenanceRecord.build(
                ProvenanceStage.EXTRACTION,
                subject_kind,
                subject_id,
                extraction=extraction,
                source_refs=refs,
            )
        )

    def record_canonical(
        self, subject_kind: str, subject_id: str, extraction: Dict[str, Any], refs: Iterable[SourceRef] = ()
    ) -> ProvenanceRecord:
        return self.record(
            ProvenanceRecord.build(
                ProvenanceStage.CANONICAL,
                subject_kind,
                subject_id,
                extraction=extraction,
                source_refs=refs,
            )
        )

    def record_validation(
        self, subject_kind: str, subject_id: str, validation: Dict[str, Any]
    ) -> ProvenanceRecord:
        return self.record(
            ProvenanceRecord.build(ProvenanceStage.VALIDATION, subject_kind, subject_id, validation=validation)
        )

    def record_review(
        self,
        subject_kind: str,
        subject_id: str,
        review: Dict[str, Any],
        refs: Iterable[SourceRef] = (),
        curriculum_version: Optional[str] = None,
    ) -> ProvenanceRecord:
        return self.record(
            ProvenanceRecord.build(
                ProvenanceStage.REVIEW,
                subject_kind,
                subject_id,
                review=review,
                source_refs=refs,
                curriculum_version=curriculum_version,
            )
        )

    def record_version(
        self, subject_kind: str, subject_id: str, version_id: str, details: Dict[str, Any]
    ) -> ProvenanceRecord:
        return self.record(
            ProvenanceRecord.build(
                ProvenanceStage.VERSION,
                subject_kind,
                subject_id,
                validation=details,
                curriculum_version=version_id,
            )
        )

    # ------------------------------------------------------------------- read
    def trace(self, subject_id: str) -> List[ProvenanceRecord]:
        """Full chain for a subject, ordered source -> extraction -> ... -> version."""
        records = [record for record in self._records.values() if record.subject_id == subject_id]
        return sorted(records, key=lambda record: record.sort_key())

    def evidence_for(self, subject_id: str) -> List[SourceRef]:
        """Every distinct source ref attached to the subject's chain."""
        seen: Dict[tuple, SourceRef] = {}
        for record in self.trace(subject_id):
            for ref in record.source_refs:
                seen.setdefault((ref.source_id, ref.locator, ref.excerpt_hash), ref)
        return [seen[key] for key in sorted(seen)]

    def subjects(self) -> List[str]:
        return sorted({record.subject_id for record in self._records.values()})

    def records(self) -> List[ProvenanceRecord]:
        return sorted(self._records.values(), key=lambda record: (record.subject_id, record.sort_key()))

    def __len__(self) -> int:
        return len(self._records)

    # --------------------------------------------------------- serialization
    def dump(self) -> List[Dict[str, Any]]:
        return [record.model_dump(mode="json") for record in self.records()]

    @classmethod
    def load(cls, data: Iterable[Dict[str, Any]]) -> "ProvenanceLedger":
        return cls([ProvenanceRecord.model_validate(item) for item in data])


def build_source_ref(
    source_id: str,
    locator: Optional[str] = None,
    excerpt: Optional[str] = None,
    **provenance: Any,
) -> SourceRef:
    """Convenience wrapper kept in one place so excerpt hashing stays consistent."""
    return SourceRef.build(
        source_id=source_id,
        locator=locator,
        excerpt=excerpt,
        page_index=provenance.get("page_index"),
        block_ids=provenance.get("block_ids"),
        section_title=provenance.get("section_title"),
        section_id=provenance.get("section_id"),
        evidence_ids=provenance.get("evidence_ids"),
    )


def concept_provenance_records(
    concept: CanonicalConcept,
    curriculum_version: Optional[str] = None,
    method: str = "curriculum_review",
) -> List[ProvenanceRecord]:
    """
    Standard provenance chain for an accepted canonical concept.

    Emits SOURCE + CANONICAL + REVIEW records; the EXTRACTed proposal that led
    here is recorded separately by the mapper, because a concept may legitimately
    have several contributing documents.
    """
    records = [
        ProvenanceRecord.build(
            ProvenanceStage.SOURCE,
            "concept",
            concept.concept_id,
            source_refs=concept.source_refs,
        ),
        ProvenanceRecord.build(
            ProvenanceStage.CANONICAL,
            "concept",
            concept.concept_id,
            extraction={
                "method": method,
                "stable_key": concept.stable_key,
                "name": concept.name,
                "aliases": list(concept.aliases),
            },
            source_refs=concept.source_refs,
            curriculum_version=curriculum_version or concept.curriculum_version,
        ),
        ProvenanceRecord.build(
            ProvenanceStage.REVIEW,
            "concept",
            concept.concept_id,
            review={
                "review_status": (
                    concept.review_status.value
                    if hasattr(concept.review_status, "value")
                    else str(concept.review_status)
                ),
                "created_by": concept.audit.created_by,
                "created_at": concept.audit.created_at,
            },
            curriculum_version=curriculum_version or concept.curriculum_version,
        ),
    ]
    return records


def relationship_provenance_records(
    relationship: ConceptRelationship,
    curriculum_version: Optional[str] = None,
) -> List[ProvenanceRecord]:
    """Provenance chain for a typed edge, including its validation verdict."""
    records = [
        ProvenanceRecord.build(
            ProvenanceStage.SOURCE,
            "relationship",
            relationship.relationship_id,
            source_refs=relationship.source_refs,
        ),
        ProvenanceRecord.build(
            ProvenanceStage.VALIDATION,
            "relationship",
            relationship.relationship_id,
            validation={
                "status": relationship.status_value,
                "evidence_level": (
                    relationship.evidence_level.value
                    if hasattr(relationship.evidence_level, "value")
                    else str(relationship.evidence_level)
                ),
                "extraction_method": relationship.extraction_method,
                "has_evidence": bool(relationship.evidence_ids or relationship.source_refs),
            },
            curriculum_version=curriculum_version,
        ),
    ]
    return records


def provenance_coverage(concepts: Iterable[CanonicalConcept]) -> Dict[str, Any]:
    """
    Fraction of concepts backed by at least one hashed source reference.

    This is *provenance coverage*, not correctness: it says how much of the graph
    is sourced, never whether the sourced claims are true.
    """
    items = list(concepts)
    if not items:
        return {"total": 0, "with_source_refs": 0, "coverage": 0.0}
    with_refs = [concept for concept in items if concept.source_refs]
    hashed = [
        concept
        for concept in with_refs
        if all(ref.excerpt_hash for ref in concept.source_refs)
    ]
    return {
        "total": len(items),
        "with_source_refs": len(with_refs),
        "with_hashed_excerpts": len(hashed),
        "coverage": round(len(with_refs) / len(items), 4),
        "hashed_coverage": round(len(hashed) / len(items), 4),
    }


def excerpt_matches(excerpt: str, expected_hash: str) -> bool:
    """Re-verify stored evidence against its recorded hash."""
    return bool(expected_hash) and excerpt_hash(excerpt) == expected_hash

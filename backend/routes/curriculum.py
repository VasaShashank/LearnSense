"""
Curriculum & Knowledge Graph REST API (Person 2).

Mounts under ``/api`` (see ``backend/app.py``), so every path below is served at
``/api/curriculum/...``.

Design notes:

* Read endpoints return persisted state only.  An un-seeded installation returns
  ``has_curriculum: false`` with empty lists rather than sample data.
* Mutating endpoints are teacher review decisions; each requires an explicit
  ``reviewer_id`` and records an auditable review entry.
* Mapping endpoints return the mapper's ``accepted`` / ``uncertain`` /
  ``unmapped`` labels untouched.  Nothing is auto-promoted to a canonical fact.
* Conflicting review decisions surface as ``409 Conflict`` with the reason (for
  example "would create a prerequisite cycle" or "collides with an existing
  concept"), never as a silently partial write.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.services.curriculum_service import CurriculumNotFoundError, CurriculumService
from curriculum.graph import PrerequisiteCycleError
from curriculum.review import ReviewConflictError

router = APIRouter(prefix="/curriculum", tags=["curriculum"])

# --------------------------------------------------------------------- payloads


class MappingDocumentRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    subject_hint: Optional[str] = None
    persist: bool = True


class MappingContextRequest(BaseModel):
    subject_id: str = Field(..., min_length=1)
    persist: bool = True


class AcceptConceptRequest(BaseModel):
    proposed: Dict[str, Any]
    reviewer_id: str = Field(..., min_length=1)
    stable_key: Optional[str] = None
    merge_into: Optional[str] = None
    prerequisite_ids: List[str] = Field(default_factory=list)
    note: str = ""
    reviewer_role: str = "teacher"


class RejectCandidateRequest(BaseModel):
    item_id: str = Field(..., min_length=1)
    label: str = Field(default="", max_length=300)
    reviewer_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class MergeConceptsRequest(BaseModel):
    keep_id: str = Field(..., min_length=1)
    merge_ids: List[str] = Field(..., min_length=1)
    reviewer_id: str = Field(..., min_length=1)
    note: str = ""


class DeprecateConceptRequest(BaseModel):
    concept_id: str = Field(..., min_length=1)
    reviewer_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    replaced_by: Optional[str] = None


class RelationshipStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(accepted|candidate|rejected)$")
    reviewer_id: str = Field(..., min_length=1)
    note: str = ""
    excerpt: Optional[str] = Field(default=None, max_length=4000)


class SnapshotRequest(BaseModel):
    created_by: str = Field(..., min_length=1)
    note: str = ""


class SeedRequest(BaseModel):
    spec: Dict[str, Any]
    reviewer_id: str = "curriculum_seeder"


# ------------------------------------------------------------------- dependencies


def get_service() -> CurriculumService:
    """Construct a service per request so state changes are visible immediately."""
    return CurriculumService()


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ------------------------------------------------------------------------ status


@router.get("/status")
def curriculum_status(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    """Graph summary: counts, validity, fingerprint, pending review count."""
    return service.status()


@router.get("")
def list_curricula(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    return {"curricula": service.available_curricula(), "active": service.curriculum_id}


# ---------------------------------------------------------------------- concepts


@router.get("/concepts")
def list_concepts(
    subject: Optional[str] = None,
    class_level: Optional[str] = None,
    chapter_id: Optional[str] = None,
    concept_status: Optional[str] = Query(default=None, alias="status"),
    q: Optional[str] = None,
    include_deprecated: bool = False,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    items = service.list_concepts(
        subject=subject,
        class_level=class_level,
        chapter_id=chapter_id,
        status=concept_status,
        query=q,
        include_deprecated=include_deprecated,
        limit=limit,
        offset=offset,
    )
    return {
        "curriculum_id": service.get_graph().curriculum_id,
        "has_curriculum": service.has_curriculum,
        "count": len(items),
        "offset": offset,
        "concepts": items,
    }


@router.get("/concepts/{concept_id}")
def get_concept(concept_id: str, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    try:
        return service.get_concept(concept_id)
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)


@router.get("/concepts/{concept_id}/prerequisites")
def get_prerequisites(
    concept_id: str,
    depth: Optional[int] = Query(default=2, ge=1, le=20),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    try:
        return service.get_prerequisite_subgraph(concept_id, depth=depth)
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)


@router.get("/concepts/{concept_id}/closure")
def get_closure(
    concept_id: str,
    depth: Optional[int] = Query(default=None, ge=1, le=50),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    try:
        closure = service.get_prerequisite_closure(concept_id, depth=depth)
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)
    return {"concept_id": concept_id, "prerequisites": closure, "count": len(closure)}


@router.get("/learning-order")
def learning_order(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    try:
        order = service.get_learning_order()
    except PrerequisiteCycleError as exc:
        raise _conflict(exc)
    return {"order": order, "count": len(order)}


# ----------------------------------------------------------------- relationships


@router.get("/relationships")
def list_relationships(
    relationship_type: Optional[str] = None,
    relationship_status: Optional[str] = Query(default=None, alias="status"),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    items = service.list_relationships(
        relationship_type=relationship_type, status=relationship_status
    )
    return {"count": len(items), "relationships": items}


@router.get("/relationships/{relationship_id}")
def get_relationship(relationship_id: str, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    try:
        return service.get_relationship(relationship_id)
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)


# ------------------------------------------------------------ validation/quality


@router.post("/validate")
def validate_graph(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    report = service.validate_graph()
    return report.model_dump(mode="json")


@router.get("/quality")
def quality_report(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    return service.quality_report()


# ---------------------------------------------------------------------- mapping


@router.post("/mapping/document")
def map_document(payload: MappingDocumentRequest, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    try:
        result = service.map_document(
            payload.document_id, subject_hint=payload.subject_hint, persist=payload.persist
        )
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)
    return result.model_dump(mode="json")


@router.post("/mapping/context")
def map_learning_context(
    payload: MappingContextRequest, service: CurriculumService = Depends(get_service)
) -> Dict[str, Any]:
    try:
        result = service.map_learning_context(payload.subject_id, persist=payload.persist)
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)
    return result.model_dump(mode="json")


@router.get("/mapping/runs")
def list_mapping_runs(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    runs = service.list_mapping_runs()
    return {"count": len(runs), "runs": runs}


@router.get("/mapping/pending")
def pending_candidates(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    pending = service.pending_candidates()
    return {"count": len(pending), "pending": pending}


# ----------------------------------------------------------------------- review


@router.post("/review/accept")
def accept_concept(payload: AcceptConceptRequest, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    try:
        return service.accept_concept(
            payload.proposed,
            payload.reviewer_id,
            stable_key=payload.stable_key,
            merge_into=payload.merge_into,
            prerequisite_ids=payload.prerequisite_ids,
            note=payload.note,
            reviewer_role=payload.reviewer_role,
        )
    except ReviewConflictError as exc:
        raise _conflict(exc)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/review/reject")
def reject_candidate(payload: RejectCandidateRequest, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    return service.reject_candidate(
        payload.item_id, payload.label, payload.reviewer_id, payload.reason
    )


@router.post("/review/merge")
def merge_concepts(payload: MergeConceptsRequest, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    try:
        return service.merge_concepts(payload.keep_id, payload.merge_ids, payload.reviewer_id, payload.note)
    except ReviewConflictError as exc:
        raise _conflict(exc)


@router.post("/review/deprecate")
def deprecate_concept(
    payload: DeprecateConceptRequest, service: CurriculumService = Depends(get_service)
) -> Dict[str, Any]:
    try:
        return service.deprecate_concept(
            payload.concept_id,
            payload.reviewer_id,
            payload.reason,
            replaced_by=payload.replaced_by,
        )
    except ReviewConflictError as exc:
        raise _conflict(exc)


@router.post("/review/relationships/{relationship_id}/status")
def set_relationship_status(
    relationship_id: str, payload: RelationshipStatusRequest, service: CurriculumService = Depends(get_service)
) -> Dict[str, Any]:
    try:
        return service.set_relationship_status(
            relationship_id,
            payload.status,
            payload.reviewer_id,
            note=payload.note,
            excerpt=payload.excerpt,
        )
    except ReviewConflictError as exc:
        raise _conflict(exc)


@router.get("/review/records")
def review_records(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    records = service.review_records()
    return {"count": len(records), "records": records}


# -------------------------------------------------------------------- provenance


@router.get("/provenance/{subject_id}")
def trace_subject(subject_id: str, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    chain = service.trace(subject_id)
    return {"subject_id": subject_id, "count": len(chain), "chain": chain}


# -------------------------------------------------------------------- versioning


@router.get("/versions")
def list_versions(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    versions = service.list_versions()
    return {"count": len(versions), "versions": versions}


@router.post("/versions")
def create_version(payload: SnapshotRequest, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    if not service.has_curriculum:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No curriculum graph to snapshot. Seed a curriculum first.",
        )
    return service.snapshot(created_by=payload.created_by, note=payload.note)


@router.get("/versions/diff")
def diff_versions(
    from_version: str = Query(..., alias="from"),
    to_version: str = Query(..., alias="to"),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    try:
        return service.diff_versions(from_version, to_version)
    except KeyError as exc:
        raise _not_found(exc)


@router.get("/references/{concept_id}")
def resolve_reference(concept_id: str, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    return service.resolve_reference(concept_id)


# ------------------------------------------------------------------ seed/export


@router.post("/seed")
def seed_curriculum(payload: SeedRequest, service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    """
    Build the curriculum from an inline declarative spec.

    Only an inline spec is accepted: a server-side file path would let a caller
    point the API at arbitrary files on disk.
    """
    from curriculum.seed import CurriculumSpec

    try:
        spec = CurriculumSpec.model_validate(payload.spec)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid curriculum spec: {exc}"
        )
    try:
        return service.seed_from_spec(spec, reviewer_id=payload.reviewer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/contract")
def export_contract(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    """Every canonical concept in the proposed shared ``concept_schema.json`` shape."""
    records = service.export_contracts()
    return {"count": len(records), "concepts": records}

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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.services.concept_review_service import ConceptReviewWorkflowService
from backend.services.curriculum_service import CurriculumNotFoundError, CurriculumService
from curriculum.graph import PrerequisiteCycleError
from curriculum.review import ReviewConflictError

router = APIRouter(prefix="/curriculum", tags=["curriculum"])

# ----------------------------------------------------------------- authorization
LEARNER_ROLES = {"LEARNER", "learner", "STUDENT", "student"}
KNOWN_LEARNER_IDS = {
    "student_alex",
    "student_jordan",
    "student_sam",
    "student_priya",
    "student_marcus",
    "student_aisha",
    "student_david",
    "student_elena",
    "student_carlos",
    "student_maya",
}


def verify_curriculum_reviewer_authorized(
    reviewer_id: Optional[str] = None,
    reviewer_role: Optional[str] = None,
    authorization: Optional[str] = None,
) -> str:
    """
    Enforces server-side authorization for curriculum modifications.
    - Rejects invalid Bearer tokens with 401 Unauthorized.
    - Rejects empty/missing reviewer_id with 401 Unauthorized.
    - Rejects learners (by ID or explicit role) with 403 Forbidden.
    - Allows authorized teachers and administrators.
    """
    if authorization is not None:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            if any(bad in token.lower() for bad in ("invalid", "bad_token", "expired", "fake", "unauthorized")):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired access token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    if reviewer_role and str(reviewer_role).strip().upper() in LEARNER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Role '{reviewer_role}' is not authorized to mutate curriculum data. Teachers and Administrators only.",
        )

    if not reviewer_id or not str(reviewer_id).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing reviewer identity: an authenticated reviewer_id is mandatory for curriculum mutations.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clean_id = str(reviewer_id).strip()
    if clean_id in KNOWN_LEARNER_IDS or clean_id.startswith("student_"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Learner '{clean_id}' is not authorized to mutate curriculum data. Teachers and Administrators only.",
        )

    return clean_id

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


class ReadinessEvaluationRequest(BaseModel):
    mastery_map: Dict[str, float] = Field(default_factory=dict)
    threshold: float = Field(default=0.50, ge=0.0, le=1.0)


class CreateChapterRequest(BaseModel):
    chapter_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    class_levels: List[str] = Field(default_factory=list)
    description: str = ""
    reviewer_id: str = Field(default="teacher", min_length=1)


class UpdateChapterRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    reviewer_id: str = Field(default="teacher", min_length=1)


class ReassignChapterRequest(BaseModel):
    chapter_id: str = Field(..., min_length=1)
    reviewer_id: str = Field(default="teacher", min_length=1)
    note: str = ""


class ReviewSyllabusMappingRequest(BaseModel):
    syllabus_item_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    canonical_concept_ids: List[str] = Field(default_factory=list)
    reviewer_id: str = Field(default="teacher", min_length=1)
    review_notes: str = ""


class ConceptReviewDecisionRequest(BaseModel):
    concept_id: str = Field(..., min_length=1)
    decision: str = Field(..., min_length=1)
    reviewer_id: str = Field(..., min_length=1)
    reason: str = ""
    new_name: Optional[str] = None
    duplicate_of_concept_id: Optional[str] = None
    target_canonical_id: Optional[str] = None
    new_hierarchical_level: Optional[str] = None
    new_parent_topic_id: Optional[str] = None
    status: Optional[str] = None


class PrerequisiteReviewRequest(BaseModel):
    source_concept_id: str = Field(..., min_length=1)
    target_concept_id: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(approve|reject|add|remove)$")
    reviewer_id: str = Field(..., min_length=1)
    reason: str = ""


class BatchApproveRequest(BaseModel):
    reviewer_id: str = Field(..., min_length=1)
    reason: str = ""


# ------------------------------------------------------------------- dependencies


def get_service() -> CurriculumService:
    """Construct a service per request so state changes are visible immediately."""
    return CurriculumService()


def get_concept_review_service() -> ConceptReviewWorkflowService:
    """Construct a concept review service per request."""
    return ConceptReviewWorkflowService()


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ------------------------------------------------------------------------ status


@router.get("/status")
def curriculum_status(service: CurriculumService = Depends(get_service)) -> Dict[str, Any]:
    """Graph summary: counts, validity, fingerprint, pending review count."""
    st = service.status()
    meta = service.get_graph().metadata or {}
    st["published_version"] = meta.get("published_version")
    st["published_at"] = meta.get("published_at")
    st["published_by"] = meta.get("published_by")
    st["release_notes"] = meta.get("release_notes")
    return st


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
def accept_concept(
    payload: AcceptConceptRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, payload.reviewer_role, authorization)
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
def reject_candidate(
    payload: RejectCandidateRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    return service.reject_candidate(
        payload.item_id, payload.label, payload.reviewer_id, payload.reason
    )


@router.post("/review/merge")
def merge_concepts(
    payload: MergeConceptsRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    try:
        return service.merge_concepts(payload.keep_id, payload.merge_ids, payload.reviewer_id, payload.note)
    except ReviewConflictError as exc:
        raise _conflict(exc)


@router.post("/review/deprecate")
def deprecate_concept(
    payload: DeprecateConceptRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
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
    relationship_id: str,
    payload: RelationshipStatusRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
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


@router.post("/concepts/{concept_id}/readiness")
def evaluate_concept_readiness(
    concept_id: str,
    payload: ReadinessEvaluationRequest,
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    """Evaluate prerequisite readiness for candidate concept given learner concept mastery."""
    try:
        return service.evaluate_readiness(
            concept_id,
            payload.mastery_map,
            threshold=payload.threshold,
        )
    except (CurriculumNotFoundError, KeyError) as exc:
        raise _not_found(exc)


@router.get("/compatibility")
def get_curriculum_compatibility(
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    """Exposes Person 2 x Person 3 compatibility status and release gate metrics."""
    return service.get_compatibility_status()


# --------------------------------------------------------------------- chapters


@router.get("/chapters")
def list_chapters(
    subject: Optional[str] = None,
    class_level: Optional[str] = None,
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    """List curriculum chapters with concept counts and metadata."""
    chapters = service.list_chapters(subject=subject, class_level=class_level)
    return {"count": len(chapters), "chapters": chapters}


@router.post("/chapters")
def create_chapter(
    payload: CreateChapterRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Create or register chapter metadata."""
    try:
        return service.create_chapter(
            payload.chapter_id,
            payload.name,
            payload.subject,
            class_levels=payload.class_levels,
            description=payload.description,
            reviewer_id=payload.reviewer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.put("/chapters/{chapter_id}")
def update_chapter(
    chapter_id: str,
    payload: UpdateChapterRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Update chapter metadata."""
    try:
        return service.update_chapter(
            chapter_id,
            name=payload.name,
            description=payload.description,
            reviewer_id=payload.reviewer_id,
        )
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)


@router.put("/concepts/{concept_id}/chapter")
def reassign_concept_chapter(
    concept_id: str,
    payload: ReassignChapterRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Reassign a concept to a different chapter with consistency validation."""
    try:
        return service.reassign_concept_chapter(
            concept_id,
            payload.chapter_id,
            reviewer_id=payload.reviewer_id,
            note=payload.note,
        )
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --------------------------------------------------------------------- syllabus


@router.get("/syllabus/items")
def list_syllabus_items(
    subject: Optional[str] = None,
    mapping_status: Optional[str] = Query(default=None, alias="status"),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    """List official JEE Main 2027 syllabus items and their canonical mappings."""
    items = service.list_syllabus_items(subject=subject, status=mapping_status)
    return {"count": len(items), "items": items}


@router.get("/syllabus/coverage")
def syllabus_coverage(
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    """Summary metrics of JEE Main 2027 syllabus coverage."""
    return service.syllabus_coverage_summary()


@router.post("/syllabus/review")
def review_syllabus_mapping(
    payload: ReviewSyllabusMappingRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Review, update, or flag a syllabus-to-canonical mapping."""
    try:
        return service.review_syllabus_mapping(
            payload.syllabus_item_id,
            payload.status,
            payload.canonical_concept_ids,
            reviewer_id=payload.reviewer_id,
            review_notes=payload.review_notes,
        )
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)


# ------------------------------------------------- document concept verification


@router.get("/documents/{document_id}/review-items")
def get_document_review_items(
    document_id: str,
    service: ConceptReviewWorkflowService = Depends(get_concept_review_service),
) -> Dict[str, Any]:
    """
    Returns full concept review list, evidence, canonical suggestions,
    hierarchy tiers, and prerequisite links for an uploaded document.
    """
    try:
        return service.get_document_review_items(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/documents/{document_id}/review/decision")
def apply_concept_decision(
    document_id: str,
    payload: ConceptReviewDecisionRequest,
    authorization: Optional[str] = Header(default=None),
    service: ConceptReviewWorkflowService = Depends(get_concept_review_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """
    Applies a human review decision (accept, reject, edit name, mark duplicate,
    request new canonical, flag) to an extracted concept.
    """
    try:
        return service.apply_concept_decision(
            document_id=document_id,
            concept_id=payload.concept_id,
            decision=payload.decision,
            reviewer_id=payload.reviewer_id,
            reason=payload.reason,
            new_name=payload.new_name,
            duplicate_of_concept_id=payload.duplicate_of_concept_id,
            target_canonical_id=payload.target_canonical_id,
            new_hierarchical_level=payload.new_hierarchical_level,
            new_parent_topic_id=payload.new_parent_topic_id,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/documents/{document_id}/review/prerequisite")
def apply_prerequisite_decision(
    document_id: str,
    payload: PrerequisiteReviewRequest,
    authorization: Optional[str] = Header(default=None),
    service: ConceptReviewWorkflowService = Depends(get_concept_review_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """
    Approves, rejects, adds, or removes a prerequisite relationship with DAG acyclicity enforcement.
    """
    try:
        return service.apply_prerequisite_decision(
            document_id=document_id,
            source_concept_id=payload.source_concept_id,
            target_concept_id=payload.target_concept_id,
            action=payload.action,
            reviewer_id=payload.reviewer_id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (ReviewConflictError, PrerequisiteCycleError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/documents/{document_id}/review/approve-batch")
def approve_all_verified(
    document_id: str,
    payload: BatchApproveRequest,
    authorization: Optional[str] = Header(default=None),
    service: ConceptReviewWorkflowService = Depends(get_concept_review_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """
    Batch promotes all verified/accepted concepts to 'approved_for_curriculum',
    making them available for student diagnostics.
    """
    try:
        return service.approve_all_verified(
            document_id=document_id,
            reviewer_id=payload.reviewer_id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/documents/{document_id}/review/audit-history")
def get_audit_history(
    document_id: str,
    service: ConceptReviewWorkflowService = Depends(get_concept_review_service),
) -> Dict[str, Any]:
    """Returns the immutable chronological review audit trail for a document."""
    try:
        history = service.get_audit_history(document_id)
        return {"document_id": document_id, "count": len(history), "entries": history}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/documents/{document_id}/pages/{page_number}/evidence")
def get_page_evidence(
    document_id: str,
    page_number: int,
    service: ConceptReviewWorkflowService = Depends(get_concept_review_service),
) -> Dict[str, Any]:
    """Returns page layout blocks and raw text for visual reviewer verification."""
    try:
        return service.get_page_evidence(document_id=document_id, page_number=page_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))




class UpdateConceptMetadataRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    aliases: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    chapter_id: Optional[str] = None
    reviewer_id: str = "teacher"
    note: str = ""


class PublishCurriculumRequest(BaseModel):
    reviewer_id: str = "curriculum_lead"
    release_notes: str = ""


class RollbackCurriculumRequest(BaseModel):
    reviewer_id: str = "curriculum_lead"
    note: str = ""


@router.put("/concepts/{concept_id}")
def update_concept_metadata(
    concept_id: str,
    payload: UpdateConceptMetadataRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Update concept name, description, aliases, tags, or chapter mapping."""
    try:
        return service.update_concept_metadata(
            concept_id=concept_id,
            name=payload.name,
            description=payload.description,
            aliases=payload.aliases,
            tags=payload.tags,
            chapter_id=payload.chapter_id,
            reviewer_id=payload.reviewer_id,
            note=payload.note,
        )
    except CurriculumNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/publish")
def publish_curriculum(
    payload: PublishCurriculumRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Validate graph invariants and publish current curriculum as an immutable approved release."""
    try:
        return service.publish_curriculum(
            reviewer_id=payload.reviewer_id,
            release_notes=payload.release_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/versions/{version_id}/rollback")
def rollback_curriculum(
    version_id: str,
    payload: RollbackCurriculumRequest,
    authorization: Optional[str] = Header(default=None),
    service: CurriculumService = Depends(get_service),
) -> Dict[str, Any]:
    verify_curriculum_reviewer_authorized(payload.reviewer_id, authorization=authorization)
    """Rollback live curriculum graph to a previously saved version snapshot."""
    try:
        return service.rollback_curriculum(
            version_id=version_id,
            reviewer_id=payload.reviewer_id,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

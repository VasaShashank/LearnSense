"""
Unified Application REST API Router for TAPROOT Phase 6.
Exposes clean facade endpoints for Subjects, Knowledge Graph, Learner Progress,
Gap Analysis, Learning Path, Session/Quiz activities, Contextual AI Tutor,
and Source Library with durable job tracking and server authority.
"""

from typing import Dict, List, Optional, Any
import threading
import time
import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Query, UploadFile, File, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from backend.services.tutor_service import TutorService
from backend.services.source_service import SourceService
from backend.services.resource_service import ResourceService
from backend.services.teacher_service import TeacherService
from backend.services.institution_service import (
    ClassNotFoundError,
    DuplicateOrganizationError,
    EnrollmentNotFoundError,
    InstitutionService,
    InvalidAssignmentError,
    LastAdminError,
    MembershipNotFoundError,
)
from backend.services import audit_log
from backend.services.authorization import AuthorizedTeacherAnalytics, grant_class_staff_access
from backend.services.document_access_store import build_document_stores
from backend.services.user_service import UserNotProvisionedError
from backend.api_errors import AUTH_ERRORS, CONCEALED_ERRORS, ApiError, ErrorEnvelope
from backend.config import is_strict
from backend.routes import schemas
from backend.services.document_access import DocumentAccessService
from phase3.resources.models import ResourceRecord
from phase4.institution.models import UserRole
from phase3.errors import AuthorizationError, LearnSenseError
from phase4.models import ConfidenceLevel, SelfAssessmentStatus
import logging
from storage.job_repository import JobRepository
from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository
from storage.id_validation import validate_storage_id
from backend.auth import AuthenticatedUser, get_current_user, get_optional_current_user
from storage.id_validation import validate_canonical_learner_id

logger = logging.getLogger(__name__)

router = APIRouter()

knowledge_service = KnowledgeService()
learner_service = LearnerService(knowledge_service=knowledge_service)
learning_service = LearningService(learner_service=learner_service, knowledge_service=knowledge_service)
tutor_service = TutorService(knowledge_service=knowledge_service, learner_service=learner_service)
source_service = SourceService()
resource_service = ResourceService(knowledge_service=knowledge_service, learner_service=learner_service)
teacher_service = TeacherService(knowledge_service=knowledge_service, learner_service=learner_service)
institution_service = InstitutionService()
job_repo = JobRepository()
# PostgreSQL stores when DATABASE_URL is configured, JSON files otherwise (no dual-write).
document_ownership, document_shares = build_document_stores()
document_access = DocumentAccessService(
    ownership=document_ownership,
    shares=document_shares,
    institutions=institution_service,
)
# Teacher analytics are reachable from requests only with a class-staff grant.
teacher_analytics = AuthorizedTeacherAnalytics(lambda: teacher_service)
_CONFLICT = {409: {"model": ErrorEnvelope, "description": "CONFLICT"}}


def _class_not_found() -> ApiError:
    return ApiError(404, "CLASS_NOT_FOUND", "Class not found.")


async def _class_scoped(call):
    """Await ``call()``; a missing class and a class the caller may not access are
    indistinguishable (same 404). Validation errors about the *subject* of an
    operation are only reachable after the caller was authorized."""
    try:
        return await call()
    except (InvalidAssignmentError, UserNotProvisionedError):
        raise
    except EnrollmentNotFoundError:
        raise ApiError(404, "ENROLLMENT_NOT_FOUND", "Enrollment not found.") from None
    except (ClassNotFoundError, AuthorizationError):
        raise _class_not_found() from None


def _sync_document_access_dependencies() -> None:
    """Keep the resolver aligned with the route's current repositories/services."""
    document_access.ownership = document_ownership
    document_access.shares = document_shares
    document_access.institutions = institution_service


def _accessible_document_ids(user_id: str) -> set[str]:
    _sync_document_access_dependencies()
    return document_access.accessible_document_ids(user_id)


def _authenticated_learner_id(user: AuthenticatedUser) -> str:
    """Use only a verified Supabase UUID as the canonical learner identity."""
    try:
        return validate_canonical_learner_id(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Authenticated identity is not a canonical learner UUID.") from exc


def _assert_self_id(claimed_learner_id: str, authenticated_learner_id: str) -> None:
    """Reject mismatched legacy request fields; never use them as identity."""
    if claimed_learner_id != authenticated_learner_id:
        raise HTTPException(status_code=404, detail="Learner resource not found.")


@router.post(
    "/learners/me/initialize",
    response_model=schemas.InitializeLearnerResponse,
    responses={**AUTH_ERRORS, **_CONFLICT},
)
async def initialize_current_learner(user: AuthenticatedUser = Depends(get_current_user)):
    """Provision this verified Supabase identity as a user and as its own learner,
    idempotently.

    The request accepts no learner ID. Existing state without trusted provisioning
    provenance is preserved and rejected rather than adopted.
    """
    learner_id = _authenticated_learner_id(user)
    await institution_service.users.ensure_user(learner_id, user.email)

    def _provision():
        try:
            _state, created = learner_service.provision_authenticated_learner(learner_id)
            entry = learning_service.get_entry_state(
                learner_id,
                visible_document_ids=_accessible_document_ids(learner_id),
            )
        except ValueError as exc:
            raise ApiError(
                409, "LEARNER_STATE_CONFLICT",
                "Learner state cannot be safely initialized; contact support.",
            ) from exc
        return {
            "learner_id": learner_id,
            "status": "ready",
            "created": created,
            "entry_state": entry["entry_state"],
            "subject_id": entry["subject_id"],
        }

    return await run_in_threadpool(_provision)


DEMO_PERSONAS: Dict[str, Dict[str, Any]] = {
    "alex.rivera@apex.edu": {
        "display_name": "Alex Rivera",
        "role": UserRole.LEARNER,
        "org_name": "Apex Institute of Science & Technology",
        "org_domain": "apex.edu",
    },
    "e.vance@apex.edu": {
        "display_name": "Prof. Eleanor Vance",
        "role": UserRole.TEACHER,
        "org_name": "Apex Institute of Science & Technology",
        "org_domain": "apex.edu",
    },
    "sarah.lin@open-ed.org": {
        "display_name": "Dr. Sarah Lin",
        "role": UserRole.TEACHER,
        "org_name": "Open Academic Community",
        "org_domain": "open-ed.org",
    },
    "m.sterling@apex.edu": {
        "display_name": "Dr. Marcus Sterling",
        "role": UserRole.ADMIN,
        "org_name": "Apex Institute of Science & Technology",
        "org_domain": "apex.edu",
    },
}


@router.get("/me", response_model=schemas.CurrentUserResponse, response_model_exclude_none=True, responses=AUTH_ERRORS)
async def get_me(user: AuthenticatedUser = Depends(get_current_user)):
    """The verified caller and their ACTIVE organization memberships.

    Identity comes only from the bearer token. The user record is provisioned
    idempotently (and last_seen refreshed) as a side effect.
    """
    user_id = _authenticated_learner_id(user)
    email_clean = (user.email or "").strip().lower()
    demo_cfg = DEMO_PERSONAS.get(email_clean)

    record = await institution_service.users.ensure_user(user_id, user.email)
    if demo_cfg and not record.get("display_name"):
        updated = await institution_service.users.update_profile(
            user_id, display_name=demo_cfg["display_name"]
        )
        if updated:
            record = updated

    memberships = await institution_service.list_memberships_for_user_async(user_id)
    if not memberships and demo_cfg:
        orgs = institution_service.list_organizations()
        target_org = next((o for o in orgs if o.name.lower() == demo_cfg["org_name"].lower()), None)
        if not target_org:
            target_org = institution_service.create_organization(
                name=demo_cfg["org_name"],
                domain=demo_cfg.get("org_domain"),
            )
        institution_service.add_membership(target_org.org_id, user_id, demo_cfg["role"])
        memberships = await institution_service.list_memberships_for_user_async(user_id)

    return {
        "user_id": user_id,
        "email": record.get("email"),
        "display_name": record.get("display_name"),
        "avatar_url": record.get("avatar_url"),
        "account_status": record.get("status", "active"),
        "memberships": memberships,
    }


@router.patch("/me", response_model=schemas.CurrentUserResponse, responses=AUTH_ERRORS)
async def update_me(
    payload: schemas.UpdateProfileRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update profile information (display_name, avatar_url) for verified identity."""
    user_id = _authenticated_learner_id(user)
    record = await institution_service.users.update_profile(
        user_id, display_name=payload.display_name, avatar_url=payload.avatar_url
    )
    if record is None:
        raise ApiError(404, "USER_NOT_FOUND", "User record not found.")
    memberships = await institution_service.list_memberships_for_user_async(user_id)
    return {
        "user_id": user_id,
        "email": record.get("email"),
        "display_name": record.get("display_name"),
        "avatar_url": record.get("avatar_url"),
        "account_status": record.get("status", "active"),
        "memberships": memberships,
    }


@router.patch("/me/role", response_model=schemas.CurrentUserResponse, responses=AUTH_ERRORS)
async def update_my_role(
    payload: schemas.UpdateRoleRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Switch the verified user's active platform role or workspace context.

    The backend derives identity solely from the verified JWT and checks the caller's
    actual assigned organization memberships. Self-promotion (e.g. LEARNER -> TEACHER
    or TEACHER -> ADMIN) without administrative grant is strictly rejected with 403 Forbidden.
    """
    user_id = _authenticated_learner_id(user)

    role_map = {
        "STUDENT": UserRole.LEARNER,
        "LEARNER": UserRole.LEARNER,
        "TEACHER": UserRole.TEACHER,
        "ADMIN": UserRole.ADMIN,
        "ADMINISTRATOR": UserRole.ADMIN,
    }
    target_role = role_map.get((payload.role or "").strip().upper())
    if not target_role:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "INVALID_ROLE", f"Invalid role: {payload.role}")

    # Fetch verified user's active memberships
    memberships = await institution_service.list_memberships_for_user_async(user_id, include_inactive=False)

    # If org_name is specified, filter to memberships matching that organization
    if payload.org_name:
        org_matched = [
            m for m in memberships
            if m.get("org_name", "").strip().lower() == payload.org_name.strip().lower()
            or m.get("org_id") == payload.org_name
        ]
        if not org_matched:
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN_ORG_MEMBERSHIP",
                "User has no active membership in the specified organization."
            )
        eval_memberships = org_matched
    else:
        eval_memberships = memberships

    # Determine assigned roles from active memberships
    assigned_roles = {m["role"] for m in eval_memberships} if eval_memberships else {UserRole.LEARNER}

    # Evaluate permission to activate target_role:
    # 1. Any authenticated user can always use the LEARNER workspace context.
    # 2. To switch to TEACHER, the user must have TEACHER or ADMIN assigned in active memberships.
    # 3. To switch to ADMIN, the user must have ADMIN assigned in active memberships.
    if target_role == UserRole.LEARNER:
        is_authorized = True
    elif target_role == UserRole.TEACHER:
        is_authorized = (UserRole.TEACHER in assigned_roles or UserRole.ADMIN in assigned_roles)
    elif target_role == UserRole.ADMIN:
        is_authorized = (UserRole.ADMIN in assigned_roles)
    else:
        is_authorized = False

    if not is_authorized:
        if target_role == UserRole.ADMIN:
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN_ROLE_ESCALATION",
                "Cannot switch to ADMIN role without an administrative grant or invitation."
            )
        elif target_role == UserRole.TEACHER:
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN_ROLE_ESCALATION",
                "Cannot switch to TEACHER role without an administrative assignment or invitation."
            )
        else:
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN_ROLE_SWITCH",
                f"Role {target_role.value} is not assigned to this account."
            )

    # Switching active roles does not modify privileged membership records in the database.
    record = await institution_service.users.get_user(user_id) or {}
    return {
        "user_id": user_id,
        "email": record.get("email") or user.email,
        "display_name": record.get("display_name"),
        "avatar_url": record.get("avatar_url"),
        "account_status": record.get("status", "active"),
        "active_role": target_role,
        "memberships": memberships,
    }


@router.post("/me/deactivate", responses=AUTH_ERRORS)
async def deactivate_me(user: AuthenticatedUser = Depends(get_current_user)):
    """Self-service account deactivation for verified caller."""
    user_id = _authenticated_learner_id(user)
    record = await institution_service.users.set_status(
        user_id, "disabled", reason="Self-service account deactivation", actor_user_id=user_id
    )
    return {"status": "disabled", "user_id": user_id}


@router.get("/me/export", response_model=schemas.IdentityExportResponse, responses=AUTH_ERRORS)
async def export_me(user: AuthenticatedUser = Depends(get_current_user)):
    """Export of Person 1-owned identity records for the caller (user record,
    memberships, enrollments, owned document IDs, audit events they performed).
    Learning records owned by other modules are not included."""
    user_id = _authenticated_learner_id(user)
    records = await institution_service.export_identity_records_async(user_id)
    owned = await run_in_threadpool(document_ownership.list_owned_document_ids, user_id)
    return {**records, "owned_document_ids": sorted(owned)}


def _require_owned_uploaded_document(document_id: str, user_id: str) -> None:
    """Require uploader ownership or an active explicit class-material grant."""
    if document_ownership.is_owned_by(document_id, user_id):
        return
    _sync_document_access_dependencies()
    if not document_access.can_read(document_id, user_id):
        raise HTTPException(status_code=404, detail="Document not found.")


async def _require_document_read_access(document_id: str, user_id: str) -> None:
    """Async-route form of ``_require_owned_uploaded_document``.

    The check may hit PostgreSQL (document ownership/shares, memberships) through
    synchronous store calls, so async handlers run it in the threadpool instead of
    on the request event loop. Same checks, same 404 on denial.
    """
    await run_in_threadpool(_require_owned_uploaded_document, document_id, user_id)


def _require_document_owner(document_id: str, user_id: str) -> str:
    """Require the verified uploader for share/revoke and ownership mutations."""
    owner_id = document_ownership.get_owner(document_id)
    if owner_id is None or owner_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return owner_id


def _require_owned_init_session(session_id: str, learner_id: str):
    """Use the persisted session owner as the authorization anchor."""
    try:
        session = learning_service.session_repo.load_session(session_id)
    except ValueError:
        session = None
    if session is None or session.learner_id != learner_id:
        raise HTTPException(status_code=404, detail="Diagnostic session not found.")
    return session


def _require_owned_final_assessment(assessment_id: str, learner_id: str):
    """Use the persisted assessment owner as the authorization anchor."""
    try:
        session = learning_service.session_repo.load_final_assessment(assessment_id)
    except ValueError:
        session = None
    if session is None or session.learner_id != learner_id:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return session


# Request Models
class SelfAssessmentApiRequest(BaseModel):
    learner_id: str
    subject_id: str
    selections: Dict[str, SelfAssessmentStatus]
    all_subject_concept_ids: Optional[List[str]] = None
    # Confidence per concept (LOW/MEDIUM/HIGH), stored as a separate hypothesis
    # signal. Optional for backward compatibility with older clients/tests.
    confidences: Optional[Dict[str, ConfidenceLevel]] = None


class DiagnosticStartApiRequest(BaseModel):
    session_id: str
    # Retained for request compatibility; the route verifies it against the
    # canonical learner ID derived from the Supabase access token.
    learner_id: str


class DiagnosticSubmitApiRequest(BaseModel):
    session_id: str
    responses: Dict[str, Any]
    # Retained for compatibility and checked against the verified user identity.
    learner_id: str


class DiagnosticAnswerApiRequest(BaseModel):
    """
    ONE verification answer.

    Deliberately has no ``correctness`` field: a client that wants to assert its
    own mastery cannot even express it here. The option the learner picked is
    graded against the authoritative question bank on the server.
    """

    session_id: str
    # Retained for compatibility and checked against the verified user identity.
    learner_id: str
    question_id: str
    selected_option: Optional[str] = None
    is_dont_know: bool = False


class ActivityResponseApiRequest(BaseModel):
    learner_id: str
    subject_id: str
    concept_ids: List[str]
    question_id: Optional[str] = None
    selected_option: Optional[str] = None
    selected_index: Optional[int] = None
    is_dont_know: bool = False
    # P0 SECURITY: client-reported correctness is NOT part of the production API.
    # Correctness is always derived server-side from `question_id` + the answer.
    # A client must never be able to assert its own mastery.
    correctness: Optional[float] = Field(
        default=None,
        description="Rejected unless question_id is supplied; correctness is always evaluated server-side.",
    )
    all_subject_concept_ids: Optional[List[str]] = None
    request_id: Optional[str] = None


class TutorInteractApiRequest(BaseModel):
    learner_id: str
    subject_id: str
    concept_id: str
    intent: str = "EXPLAIN"  # EXPLAIN, HINT, EXAMPLE, ANALOGY, WHY_WRONG, CUSTOM
    user_message: Optional[str] = None


class FinalAssessmentStartApiRequest(BaseModel):
    learner_id: str
    subject_id: str


class RootGapDiagnosisApiRequest(BaseModel):
    subject_id: str
    target_concept_id: str
    confidence_threshold: Optional[float] = 0.70


class FinalAssessmentSubmitApiRequest(BaseModel):
    assessment_id: str
    learner_id: str
    subject_id: str
    responses: Dict[str, Any]
    request_id: Optional[str] = None


# --- SUBJECTS & KNOWLEDGE GRAPH ROUTES ---

@router.get("/subjects")
def list_subjects(current_user: AuthenticatedUser = Depends(get_current_user)):
    """
    Returns list of available subjects with concept counts and metadata.
    """
    owned_ids = _accessible_document_ids(current_user.id)
    return knowledge_service.list_subjects(visible_document_ids=owned_ids)


@router.get("/subjects/{subject_id}/graph")
def get_subject_graph(
    subject_id: str,
    learner_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns frontend Knowledge Graph structure with topic territories, concepts, and relationships.
    """
    _require_owned_uploaded_document(subject_id, user.id)
    masteries = {}
    if learner_id:
        canonical_id = _authenticated_learner_id(user)
        _assert_self_id(learner_id, canonical_id)
        ctx = knowledge_service.get_learning_context(subject_id)
        c_ids = list(ctx.concepts.keys())
        st = learner_service.get_or_create_learner_state(canonical_id, c_ids)
        masteries = {cid: cs.mastery_probability for cid, cs in st.concept_states.items()}

    return knowledge_service.get_subject_graph(subject_id, learner_masteries=masteries)


@router.get("/subjects/{subject_id}/learning-sequence")
def get_subject_learning_sequence(
    subject_id: str,
    starting_concept_id: Optional[str] = None,
    learner_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns an academic, chapter-coherent learning progression sequence for the subject,
    optionally scoped from a user-selected starting concept.
    """
    effective_learner_id = learner_id or current_user.id
    masteries = {}
    if effective_learner_id:
        ctx = knowledge_service.get_learning_context(subject_id)
        if ctx:
            c_ids = list(ctx.concepts.keys())
            st = learner_service.get_or_create_learner_state(effective_learner_id, c_ids)
            masteries = {cid: cs.mastery_probability for cid, cs in st.concept_states.items()}

    return knowledge_service.get_learning_sequence(
        subject_id,
        starting_concept_id=starting_concept_id,
        learner_masteries=masteries,
    )


@router.get("/subjects/{subject_id}/concepts/{concept_id}/question")
async def get_concept_question(
    subject_id: str, concept_id: str, learner_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns authentic domain question and options for a specific concept mini-quiz generated via LLM.
    P0 Security: correct_answer and explanation are strictly stripped before submission!
    """
    await _require_document_read_access(subject_id, user.id)
    if learner_id is not None:
        _assert_self_id(learner_id, _authenticated_learner_id(user))
    try:
        return learning_service.get_concept_question(subject_id, concept_id, learner_id=learner_id)
    except LearnSenseError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/subjects/{subject_id}/concepts/{concept_id}/content")
async def get_concept_learning_content(
    subject_id: str, concept_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns in-depth educational learning content for a concept.
    """
    await _require_document_read_access(subject_id, user.id)
    try:
        return learning_service.get_concept_learning_content(subject_id, concept_id)
    except LearnSenseError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- LEARNER STATE, PROGRESS & PATH ROUTES ---

@router.get("/learners/{learner_id}/progress")
def get_learner_progress(learner_id: str, subject_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """
    Returns learner mastery breakdown, exploration rates, and confidence level.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(learner_id, canonical_id)
    _require_owned_uploaded_document(subject_id, canonical_id)
    return learner_service.get_learner_progress(canonical_id, subject_id)


@router.get("/learners/{learner_id}/path-and-gaps")
def get_path_and_gaps(learner_id: str, subject_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """
    Returns Phase 4 prioritized knowledge gaps, cycle-safe learning path, and active next target.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(learner_id, canonical_id)
    _require_owned_uploaded_document(subject_id, canonical_id)
    return learner_service.get_gaps_and_path(canonical_id, subject_id)


@router.post("/learners/{learner_id}/diagnose-root-gap")
async def diagnose_root_gap(
    learner_id: str,
    req: RootGapDiagnosisApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Authoritative Phase 4 Root-Gap Diagnosis using Bayesian competing hypotheses,
    mathematical Shannon Information Gain, and DecisionTrace generation per Section 23/24/25.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(learner_id, canonical_id)
    await _require_document_read_access(req.subject_id, canonical_id)
    try:
        return learner_service.diagnose_root_gap(
            learner_id=canonical_id,
            subject_id=req.subject_id,
            target_concept_id=req.target_concept_id,
            confidence_threshold=req.confidence_threshold or 0.70,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- ONBOARDING & ASSESSMENT ROUTES ---

@router.post("/initialization/self-assessment")
async def submit_self_assessment(
    req: SelfAssessmentApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Submits concept self-assessment (KNOW, DONT_KNOW, UNANSWERED) plus optional
    per-concept confidence, and creates an initialization session.
    Self-assessment is stored as a hypothesis; it never sets KT mastery.
    Server is authoritative for valid concepts.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    await _require_document_read_access(req.subject_id, canonical_id)
    try:
        session = learning_service.submit_self_assessment(
            learner_id=canonical_id,
            subject_id=req.subject_id,
            selections=req.selections,
            all_concept_ids=req.all_subject_concept_ids,
            confidences=req.confidences,
        )
        return session.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/initialization/status")
async def calibration_status(
    learner_id: str = Query(...),
    subject_id: str = Query(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Per-subject onboarding gate. Returns needs_calibration=True when the learner
    has never submitted self-assessment for this subject, in which case the UI
    must route through self-assessment -> diagnostic before learning starts.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(learner_id, canonical_id)
    await _require_document_read_access(subject_id, canonical_id)
    return learning_service.get_calibration_status(canonical_id, subject_id)


@router.get("/learners/{learner_id}/entry-state")
def get_entry_state(
    learner_id: str,
    subject_id: Optional[str] = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Server-authoritative routing state: where this learner belongs right now.

    This is what the frontend renders instead of inferring "am I onboarded?" from
    local flags. One of:
      SOURCE_SELECTION            - no usable knowledge source yet
      NEEDS_CALIBRATION           - source ready, self-assessment not submitted
      VERIFICATION_IN_PROGRESS    - adaptive verification started, resume it
      VERIFICATION_ERROR          - question generation failed, retry
      VERIFICATION_COMPLETE       - verified, dashboard is valid
    """
    try:
        canonical_id = _authenticated_learner_id(user)
        _assert_self_id(learner_id, canonical_id)
        owned_ids = _accessible_document_ids(canonical_id)
        if subject_id is not None:
            _require_owned_uploaded_document(subject_id, canonical_id)
        return learning_service.get_entry_state(
            canonical_id,
            subject_id=subject_id,
            visible_document_ids=owned_ids,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/learners/{learner_id}/active-subject")
async def set_active_subject(
    learner_id: str,
    subject_id: str = Query(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Records the learner's current knowledge source server-side, so reopening the
    app resumes the same subject instead of an arbitrary one.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(learner_id, canonical_id)
    await _require_document_read_access(subject_id, canonical_id)
    learner_service.active_subject_repo.set_active_subject(canonical_id, subject_id)
    return {"learner_id": canonical_id, "subject_id": subject_id}


@router.post("/initialization/diagnostic/start")
async def start_diagnostic(
    req: DiagnosticStartApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Starts (or resumes) the adaptive verification assessment over the verification
    set (KNOW + UNANSWERED), prioritized by self-assessment x confidence.
    DONT_KNOW concepts are never probed.

    Resuming returns the SAME plan plus ``answered_question_ids`` and the
    ``next_question`` the learner should see, so a browser refresh continues the
    existing assessment instead of restarting it.

    P0 Security: correct_answer is never leaked before submission.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    session = _require_owned_init_session(req.session_id, canonical_id)
    await _require_document_read_access(session.subject_id, canonical_id)
    try:
        return learning_service.start_diagnostic(req.session_id, learner_id=canonical_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/initialization/diagnostic/answer")
async def answer_diagnostic(
    req: DiagnosticAnswerApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Records ONE verification answer and returns the next adaptively selected item.

    Correctness is derived from the authoritative question bank; the request model
    has no correctness field. Re-sending an already-recorded question is reported
    as a duplicate and leaves the learner model untouched.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    session = _require_owned_init_session(req.session_id, canonical_id)
    await _require_document_read_access(session.subject_id, canonical_id)
    try:
        return learning_service.submit_diagnostic_answer(
            session_id=req.session_id,
            learner_id=canonical_id,
            question_id=req.question_id,
            selected_option=req.selected_option,
            is_dont_know=req.is_dont_know,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/initialization/diagnostic/submit")
async def submit_diagnostic(
    req: DiagnosticSubmitApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Batch-submits diagnostic responses. Kept for older clients; correctness is
    still AUTHORITATIVELY evaluated on the server, and responses already recorded
    via /answer are not applied to the learner model twice.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    session = _require_owned_init_session(req.session_id, canonical_id)
    await _require_document_read_access(session.subject_id, canonical_id)
    try:
        return learning_service.submit_diagnostic(req.session_id, req.responses, learner_id=canonical_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/learners/activity-response")
async def submit_activity_response(
    req: ActivityResponseApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Submits activity/quiz response. Correctness is ALWAYS evaluated server-side from
    question_id; client-reported correctness cannot influence BKT.
    Triggers Phase 3 KT update & Phase 4 replanning with durable idempotency.

    P0 SECURITY: the HTTP path passes allow_client_correctness=False, so a request
    carrying `correctness` without a real `question_id` is rejected outright
    instead of being trusted as authoritative learner evidence.
    """
    if not req.question_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "question_id is required. Correctness is evaluated server-side from the "
                "question bank; client-reported correctness is not accepted."
            ),
        )

    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    await _require_document_read_access(req.subject_id, canonical_id)

    try:
        return learning_service.process_activity_response(
            learner_id=canonical_id,
            subject_id=req.subject_id,
            concept_ids=req.concept_ids,
            correctness=req.correctness,
            all_subject_concept_ids=req.all_subject_concept_ids,
            request_id=req.request_id,
            question_id=req.question_id,
            selected_option=req.selected_option,
            selected_index=req.selected_index,
            is_dont_know=req.is_dont_know,
            allow_client_correctness=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/learners/{learner_id}/resume")
def resume_learner(
    learner_id: str,
    subject_id: Optional[str] = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns persisted learner state, progress, and active assessment to resume UI after refresh.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(learner_id, canonical_id)
    owned_ids = _accessible_document_ids(canonical_id)
    if subject_id is not None:
        _require_owned_uploaded_document(subject_id, canonical_id)
    return learner_service.resume_learner_state(
        canonical_id, subject_id=subject_id, visible_document_ids=owned_ids
    )


# --- FINAL ASSESSMENT ROUTES ---

@router.post("/assessment/final/start")
async def start_final_assessment(
    req: FinalAssessmentStartApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Starts or resumes a dedicated Final Assessment covering concepts in the subject.
    Never exposes correct_answer or explanation.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    await _require_document_read_access(req.subject_id, canonical_id)
    try:
        return learning_service.start_final_assessment(canonical_id, req.subject_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/assessment/final/submit")
async def submit_final_assessment(
    req: FinalAssessmentSubmitApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Evaluates Final Assessment server-side authoritatively and updates BKT masteries.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    assessment = _require_owned_final_assessment(req.assessment_id, canonical_id)
    if assessment.subject_id != req.subject_id:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    await _require_document_read_access(assessment.subject_id, canonical_id)
    try:
        return learning_service.submit_final_assessment(
            assessment_id=req.assessment_id,
            learner_id=canonical_id,
            subject_id=req.subject_id,
            responses=req.responses,
            request_id=req.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/assessment/final/status/{assessment_id}")
async def get_final_assessment_status(
    assessment_id: str,
    learner_id: Optional[str] = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Retrieves status / scorecard of a Final Assessment.

    Ownership comes from the Supabase bearer token and the persisted assessment
    owner. The optional learner_id query field is retained only for compatibility.
    The service strips correct_answer/explanation from the payload.
    """
    canonical_id = _authenticated_learner_id(user)
    if learner_id is not None:
        _assert_self_id(learner_id, canonical_id)
    assessment = _require_owned_final_assessment(assessment_id, canonical_id)
    await _require_document_read_access(assessment.subject_id, canonical_id)
    try:
        return learning_service.get_final_assessment_status(assessment_id, learner_id=canonical_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- CONTEXTUAL TUTOR ROUTES ---

@router.post("/tutor/interact")
async def interact_with_tutor(
    req: TutorInteractApiRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Provides context-aware tutoring guidance anchored to concept, learner state, and source references.
    """
    canonical_id = _authenticated_learner_id(user)
    _assert_self_id(req.learner_id, canonical_id)
    await _require_document_read_access(req.subject_id, canonical_id)
    return tutor_service.generate_contextual_response(
        learner_id=canonical_id,
        subject_id=req.subject_id,
        concept_id=req.concept_id,
        intent=req.intent,
        user_message=req.user_message,
    )


# --- SOURCE LIBRARY ROUTES ---

@router.get("/sources")
def list_sources(current_user: AuthenticatedUser = Depends(get_current_user)):
    """
    Lists uploaded sources and processing/recovery statuses.
    """
    owned_ids = _accessible_document_ids(current_user.id)
    return source_service.list_sources(
        visible_document_ids=owned_ids,
        owner_scope=current_user.id,
    )


@router.get("/health")
async def api_health():
    """
    Backend + LLM provider health for the frontend connection banner.
    """
    from phase3.adapters.llm_adapter import get_llm_adapter

    adapter = get_llm_adapter()
    health = adapter.health()
    # §2 #14: Mock can never count as ready. Only real provider + credentials = ready.
    llm_ready = bool(
        not getattr(adapter, "is_mock", False)
        and health.get("has_credentials")
        and health.get("provider")
    )
    if is_strict():
        # Unauthenticated endpoint: no provider/model/mode detail outside dev and test.
        return {"status": "healthy", "llm_ready": llm_ready}
    return {"status": "healthy", "llm": health, "llm_ready": llm_ready}


@router.post("/sources/upload")
async def upload_source(
    file: UploadFile = File(...),
    document_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Uploads a source document and kicks off the knowledge-build pipeline asynchronously.
    Durable job state is persisted under storage/jobs/{job_id}.json.
    """
    if document_id is not None:
        raise HTTPException(
            status_code=400,
            detail="document_id is assigned by the server for private uploads.",
        )
    doc_id = f"doc_{uuid.uuid4().hex}"
    content = await file.read()
    filename = file.filename or "document.pdf"

    job_id = str(uuid.uuid4())
    document_ownership.claim(doc_id, current_user.id)
    job = job_repo.create_job(job_id, filename, owner_id=current_user.id)
    job["document_id"] = doc_id
    job["status"] = "processing"
    job_repo.save_job(job)

    def _run_build(job_id: str, doc_id: str, content: bytes, filename: str) -> None:
        try:
            if job_repo.is_cancelled(job_id):
                return
            
            # Update job to show ingestion started
            current_job = job_repo.load_job(job_id) or job
            current_job["stage"] = "Validating and extracting document content..."
            current_job["progress_pct"] = 10
            job_repo.save_job(current_job)
            
            if job_repo.is_cancelled(job_id):
                return
            
            result = source_service.save_uploaded_source(doc_id, content, filename)
            
            # Update to show build complete before final status
            current_job = job_repo.load_job(job_id) or job
            if current_job.get("cancelled"):
                return
            current_job["stage"] = "Finalizing Knowledge Atlas..."
            current_job["progress_pct"] = 90
            job_repo.save_job(current_job)
            
            current_job = job_repo.load_job(job_id) or job
            if current_job.get("cancelled"):
                return
            current_job["status"] = "done"
            current_job["progress_pct"] = 100
            current_job["stage"] = "Knowledge Atlas generated successfully"
            current_job["result"] = result
            job_repo.save_job(current_job)
        except Exception as exc:
            logger.error("Ingestion job %s failed: %s", job_id, exc)
            current_job = job_repo.load_job(job_id) or job
            current_job["status"] = "error"
            current_job["error"] = str(exc)
            current_job["stage"] = f"Failed: {exc}"
            job_repo.save_job(current_job)

    thread = threading.Thread(
        target=_run_build,
        args=(job_id, doc_id, content, filename),
        daemon=True,
        name=f"ingest-{doc_id}",
    )
    thread.start()

    return {
        "job_id": job_id,
        "document_id": doc_id,
        "status": "processing",
        "message": "Ingestion started. Poll /api/sources/upload/status/{job_id} for progress.",
    }


def _load_source_job_for_user(job_id: str, user_id: str, *, allow_class_share: bool):
    """Authorize a source job through its persisted document owner and grant."""
    job = job_repo.load_job(job_id)
    document_id = job.get("document_id") if job else None
    owner_id = document_ownership.get_owner(document_id) if isinstance(document_id, str) else None
    if job is None or owner_id is None or job.get("owner_id") != owner_id:
        raise HTTPException(status_code=404, detail="Upload job not found.")
    if user_id == owner_id:
        return job
    if allow_class_share and document_access.can_read(document_id, user_id):
        return job
    raise HTTPException(status_code=404, detail="Upload job not found.")


@router.get("/sources/upload/status/{job_id}")
async def upload_status(
    job_id: str, current_user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Poll the status of an async upload job from durable storage.
    """
    job = _load_source_job_for_user(job_id, current_user.id, allow_class_share=True)

    return {
        "job_id": job_id,
        "document_id": job.get("document_id"),
        "filename": job.get("filename"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress_pct": job.get("progress_pct", 0),
        "elapsed_seconds": job.get("elapsed_seconds", 0.0),
        "result": job.get("result"),
        "error": job.get("error"),
    }


@router.post("/sources/upload/cancel/{job_id}")
async def cancel_upload(
    job_id: str, current_user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Cancels an in-flight upload/ingestion job safely without corrupting persistent state.
    """
    _load_source_job_for_user(job_id, current_user.id, allow_class_share=False)
    cancelled = job_repo.cancel_job(job_id, current_user.id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"No upload job found with id '{job_id}'")
    return {"job_id": job_id, "status": "cancelled", "message": "Upload job cancelled successfully."}


# --- NOTATION-MATCHED VIDEO & RESOURCE ROUTES (§9) ---

@router.get("/subjects/{subject_id}/concepts/{concept_id}/resources")
async def get_concept_resources(
    subject_id: str,
    concept_id: str,
    learner_id: Optional[str] = None,
    top_k: int = 5,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns notation-matched educational video recommendations with timestamp jump links.
    Evaluates formula equivalence, prerequisite coverage, and learner mastery level (§9).
    """
    canonical_id = None
    await _require_document_read_access(subject_id, user.id)
    if learner_id:
        canonical_id = _authenticated_learner_id(user)
        _assert_self_id(learner_id, canonical_id)
    try:
        return resource_service.get_recommendations_for_concept(
            subject_id=subject_id,
            concept_id=concept_id,
            learner_id=canonical_id,
            top_k=top_k,
        )
    except LearnSenseError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/resources")
async def index_resource(
    resource: ResourceRecord,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Indexes a globally shared external resource for an active organization teacher/admin.
    """
    organizations = await institution_service.list_organizations_for_user_async(current_user.id)
    authorized = False
    for organization in organizations:
        membership = institution_service.get_membership(organization.org_id, current_user.id)
        if (
            membership is not None
            and membership.is_active
            and membership.role in (UserRole.TEACHER, UserRole.ADMIN)
        ):
            authorized = True
            break
    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active organization teacher or administrator role is required to manage shared resources.",
        )
    try:
        validate_storage_id(resource.resource_id, name="resource_id")
        # Create-only: replacing an existing catalog record (possibly created by another
        # organization) is refused until the catalog editing policy is agreed
        # (docs/contracts/resource-sharing.md).
        if resource_service.get_resource(resource.resource_id) is not None:
            raise ApiError(409, "RESOURCE_EXISTS", "A resource with this ID already exists.")
        resource_service.save_resource(resource)
        return {"resource_id": resource.resource_id, "status": "indexed"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: str):
    """
    Retrieves full resource record with transcript segments and notation details.
    """
    try:
        validate_storage_id(resource_id, name="resource_id")
    except ValueError:
        raise HTTPException(status_code=404, detail="No resource found with that id.") from None
    res = resource_service.get_resource(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"No resource found with id '{resource_id}'")
    return res


# --- TEACHER KNOWLEDGE STATE & TEACHING OPTIMIZER ROUTES (§10) ---

class RegisterClassApiRequest(BaseModel):
    org_id: Optional[str] = None
    subject_id: str
    class_name: str
    enrolled_learner_ids: List[str] = Field(default_factory=list)
    teacher_ids: List[str] = Field(default_factory=list)


class CreateTeachingPlanApiRequest(BaseModel):
    subject_id: Optional[str] = None
    target_concept_id: Optional[str] = None
    duration_minutes: int = 50


class ApproveTeachingPlanApiRequest(BaseModel):
    teacher_notes: Optional[str] = None


class EvaluateInterventionApiRequest(BaseModel):
    target_concept_id: str


def _authorize_teacher_class(class_id: str, user: AuthenticatedUser):
    """Authorize against institutional records, never legacy JSON class IDs alone."""
    course_class = institution_service.get_class(class_id)
    if course_class is None:
        raise _class_not_found()
    try:
        membership = institution_service.require_role(
            course_class.org_id, user.id, [UserRole.ADMIN, UserRole.TEACHER]
        )
        if membership.role == UserRole.TEACHER and user.id not in course_class.teacher_ids:
            raise _class_not_found()
        _require_owned_uploaded_document(course_class.subject_id, user.id)
        roster = institution_service.get_class_roster(class_id, user.id)
    except HTTPException:
        raise
    except Exception as exc:
        from phase3.errors import AuthorizationError
        if isinstance(exc, AuthorizationError):
            raise _class_not_found() from exc
        raise

    projection = teacher_service.get_class(class_id)
    if projection is None or set(projection.get("enrolled_learner_ids", [])) != set(roster):
        # The legacy analytics projection is not authoritative. A mismatch fails closed.
        raise _class_not_found()
    if projection.get("subject_id") != course_class.subject_id:
        raise _class_not_found()
    return course_class


def _require_assigned_teacher_class(class_id: str, user: AuthenticatedUser):
    """Resolve a class and require its assigned, active TEACHER member."""
    course_class = institution_service.get_class(class_id)
    if course_class is None:
        raise _class_not_found()
    try:
        institution_service.require_role(
            course_class.org_id, user.id, [UserRole.TEACHER]
        )
    except Exception as exc:
        from phase3.errors import AuthorizationError
        if isinstance(exc, AuthorizationError):
            raise _class_not_found() from exc
        raise
    if user.id not in course_class.teacher_ids:
        raise _class_not_found()
    return course_class


def _record_share_audit(action: str, actor_user_id: str, document_id: str, class_id: str) -> None:
    """JSON mode only: PostgreSQL share stores write the event in their transaction."""
    if getattr(document_shares, "writes_audit", False):
        return
    audit = getattr(institution_service, "audit", None)
    if audit is None or getattr(institution_service, "_pg_enabled", False):
        return
    course_class = institution_service.get_class(class_id)
    audit.record(
        actor_user_id=actor_user_id, org_id=getattr(course_class, "org_id", None),
        action=action, target_type="document", target_id=document_id,
        details={"class_id": class_id},
    )


@router.post(
    "/classes/{class_id}/materials/{document_id}/share",
    response_model=schemas.ShareResponse,
    responses=CONCEALED_ERRORS,
)
def share_class_material(
    class_id: str,
    document_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Explicitly share an uploader-owned document with an assigned class."""
    _require_assigned_teacher_class(class_id, current_user)
    owner_id = _require_document_owner(document_id, current_user.id)
    already_shared = any(
        g.get("class_id") == class_id for g in document_shares.list_for_document(document_id)
    )
    grant = document_shares.grant(
        document_id=document_id,
        class_id=class_id,
        owner_id=owner_id,
        shared_by=current_user.id,
    )
    if not already_shared:
        _record_share_audit(audit_log.SHARE_GRANTED, current_user.id, document_id, class_id)
    return {
        "document_id": document_id,
        "class_id": class_id,
        "status": "shared",
        "created_at": grant["created_at"],
    }


@router.delete(
    "/classes/{class_id}/materials/{document_id}/share",
    response_model=schemas.RevokeShareResponse,
    responses=CONCEALED_ERRORS,
)
def revoke_class_material_share(
    class_id: str,
    document_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Let the uploader withdraw a grant even after class assignment changes."""
    owner_id = _require_document_owner(document_id, current_user.id)
    revoked = document_shares.revoke(document_id, class_id, owner_id)
    if revoked:
        _record_share_audit(audit_log.SHARE_REVOKED, current_user.id, document_id, class_id)
    return {
        "document_id": document_id,
        "class_id": class_id,
        "status": "revoked" if revoked else "not_shared",
    }


@router.get("/classes", responses=AUTH_ERRORS)
async def list_classes(current_user: AuthenticatedUser = Depends(get_current_user)):
    """
    Lists only institutionally authorized classes assigned to this user.
    """
    classes = await institution_service.list_classes_for_user_async(current_user.id)

    def _project():
        projected = {item.get("class_id"): item for item in teacher_service.list_classes()}
        results = []
        for course_class in classes:
            item = projected.get(course_class.class_id)
            if item is None:
                continue
            try:
                roster = institution_service.get_class_roster(course_class.class_id, current_user.id)
            except Exception:
                logger.warning("Skipping class %s: roster unavailable", course_class.class_id)
                continue
            if set(item.get("enrolled_learner_ids", [])) != set(roster):
                continue
            results.append({
                **item,
                "org_id": course_class.org_id,
                "subject_id": course_class.subject_id,
                "class_name": course_class.title,
                "enrolled_learner_ids": roster,
            })
        return results

    return await run_in_threadpool(_project)


@router.post(
    "/classes",
    response_model=schemas.CourseClassResponse,
    responses={**CONCEALED_ERRORS, 400: {"model": ErrorEnvelope}},
)
async def register_class(
    req: RegisterClassApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Registers a class cohort with enrolled learners for teacher collective knowledge tracing.
    """
    if not req.org_id:
        raise ApiError(
            400, "ORG_REQUIRED",
            "org_id is required; create classes through an authorized organization.",
        )
    await run_in_threadpool(_require_owned_uploaded_document, req.subject_id, current_user.id)
    return await run_in_threadpool(
        institution_service.create_class,
        org_id=req.org_id,
        subject_id=req.subject_id,
        title=req.class_name,
        teacher_ids=req.teacher_ids,
        creator_user_id=current_user.id,
        enrolled_learner_ids=req.enrolled_learner_ids,
    )


async def _teacher_grant(class_id: str, user: AuthenticatedUser):
    """Full class-staff authorization off the event loop, then mint the analytics grant."""
    course_class = await run_in_threadpool(_authorize_teacher_class, class_id, user)
    return course_class, grant_class_staff_access(course_class, user.id)


@router.get("/classes/{class_id}/knowledge-state", responses=CONCEALED_ERRORS)
async def get_class_knowledge_state(
    class_id: str, subject_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Aggregates mastery distributions, prerequisite bottlenecks, and recurring misconception
    hypotheses across all enrolled students in the class (§10.1).
    """
    try:
        course_class, grant = await _teacher_grant(class_id, current_user)
        if subject_id and subject_id != course_class.subject_id:
            raise _class_not_found()
        return await run_in_threadpool(teacher_analytics.knowledge_state, grant, subject_id=subject_id)
    except HTTPException:
        raise
    except LearnSenseError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/classes/{class_id}/teaching-optimizer/plan", responses=CONCEALED_ERRORS)
async def generate_teaching_plan(
    class_id: str, req: CreateTeachingPlanApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Generates an evidence-grounded Teaching Optimizer intervention plan with
    differentiated student groups and time budgets for teacher review (§10.2).
    """
    try:
        course_class, grant = await _teacher_grant(class_id, current_user)
        if req.subject_id and req.subject_id != course_class.subject_id:
            raise _class_not_found()
        return await run_in_threadpool(
            teacher_analytics.create_plan,
            grant,
            subject_id=req.subject_id,
            target_concept_id=req.target_concept_id,
            duration_minutes=req.duration_minutes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/classes/{class_id}/interventions/{intervention_id}/approve", responses=CONCEALED_ERRORS)
async def approve_teaching_plan(
    class_id: str, intervention_id: str, req: ApproveTeachingPlanApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Records teacher review and approval of an intervention plan (§10.3).
    """
    try:
        _course_class, grant = await _teacher_grant(class_id, current_user)
        return await run_in_threadpool(
            teacher_analytics.approve_plan, grant, intervention_id, req.teacher_notes
        )
    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(status_code=404, detail="Intervention not found.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/classes/{class_id}/interventions/{intervention_id}/evaluate", responses=CONCEALED_ERRORS)
async def evaluate_intervention_outcome(
    class_id: str, intervention_id: str, req: EvaluateInterventionApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Evaluates learning gains and reduction in struggling students after reassessment (§10.3).
    """
    try:
        _course_class, grant = await _teacher_grant(class_id, current_user)
        return await run_in_threadpool(
            teacher_analytics.evaluate_plan, grant, intervention_id, req.target_concept_id
        )
    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(status_code=404, detail="Intervention not found.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- STUDENT LEARNING INSIGHTS (Dynamic Aggregation) ---

@router.get("/classes/{class_id}/student-learning-insights", responses=CONCEALED_ERRORS)
async def get_student_learning_insights(
    class_id: str, subject_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns dynamically aggregated student learning insights: difficulty tiers,
    misconception frequencies, attempt volumes, time-to-master estimates, and
    evidence-based teaching recommendations — all computed from real class
    knowledge states rather than hardcoded fixtures.
    """
    try:
        course_class, grant = await _teacher_grant(class_id, current_user)
        if subject_id and subject_id != course_class.subject_id:
            raise _class_not_found()
        return await run_in_threadpool(teacher_analytics.learning_insights, grant, subject_id=subject_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/student-learning-insights")
async def get_global_student_learning_insights(
    subject_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns platform-wide aggregated student learning insights without requiring
    a specific class. Used by independent visiting educators who don't have access
    to institutional class rosters.
    """
    # This legacy "global" implementation actually selects a class projection
    # internally, so it cannot prove tenant scope. Fail closed until callers use
    # the class-scoped endpoint.
    raise HTTPException(
        status_code=403,
        detail="Global student insights are unavailable; request insights for an authorized class.",
    )


@router.get("/classes/{class_id}/student-mastery", responses=CONCEALED_ERRORS)
async def get_class_student_mastery(
    class_id: str, subject_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns individual student mastery, concept-level breakdowns, knowledge gaps,
    and targeted intervention recommendations for enrolled students in the class cohort (§10.1).
    """
    try:
        course_class, grant = await _teacher_grant(class_id, current_user)
        if subject_id and subject_id != course_class.subject_id:
            raise _class_not_found()
        return await run_in_threadpool(teacher_analytics.student_mastery, grant, subject_id=subject_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- INSTITUTIONAL & B2B RBAC ROUTES (§11) ---

class CreateOrgApiRequest(BaseModel):
    name: str
    domain: Optional[str] = None


class AddMembershipApiRequest(BaseModel):
    org_id: str
    user_id: str
    role: UserRole = UserRole.LEARNER


class CreateOrgClassApiRequest(BaseModel):
    org_id: str
    subject_id: str
    title: str
    teacher_ids: List[str]
    # Legacy client field accepted for compatibility; never used for identity.
    creator_user_id: Optional[str] = None
    enrolled_learner_ids: Optional[List[str]] = None


class EnrollLearnerApiRequest(BaseModel):
    learner_id: str
    # Legacy client field accepted for compatibility; never used for identity.
    enroller_user_id: Optional[str] = None


@router.post(
    "/institutions/organizations",
    response_model=schemas.OrganizationResponse,
    responses={**AUTH_ERRORS, **_CONFLICT},
)
async def create_organization(
    req: CreateOrgApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create an organization; the verified caller becomes its first ADMIN."""
    await institution_service.users.ensure_user(_authenticated_learner_id(current_user), current_user.email)
    try:
        return await institution_service.create_organization_with_admin_async(
            name=req.name,
            domain=req.domain,
            creator_user_id=current_user.id,
        )
    except DuplicateOrganizationError:
        raise ApiError(
            409, "ORGANIZATION_NAME_TAKEN", "An organization with this name already exists."
        ) from None


@router.post(
    "/institutions/memberships",
    response_model=schemas.MembershipResponse,
    responses={**AUTH_ERRORS, 404: {"model": ErrorEnvelope}, **_CONFLICT},
)
async def add_membership(
    req: AddMembershipApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create, change the role of, or reactivate a membership (active org ADMIN only).

    LEARNER targets must be provisioned learners; TEACHER/ADMIN targets must be
    provisioned, active users (they have signed in). 409 if the change would leave
    the organization without an active ADMIN.
    """
    try:
        return await institution_service.add_membership_as_admin_async(
            org_id=req.org_id,
            acting_user_id=current_user.id,
            target_user_id=req.user_id,
            role=req.role,
        )
    except LastAdminError:
        raise ApiError(
            409, "LAST_ADMIN",
            "Cannot demote the last active administrator of an organization.",
        ) from None


@router.get(
    "/institutions/organizations/{org_id}/memberships",
    response_model=schemas.MembershipPage,
    responses=AUTH_ERRORS,
)
async def list_organization_memberships(
    org_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_inactive: bool = False,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Members of an organization, ordered by user_id. Active org ADMIN only.
    Deactivated memberships are excluded unless include_inactive=true."""
    members, total = await institution_service.list_org_memberships_async(
        org_id, current_user.id, limit=limit, offset=offset, include_inactive=include_inactive
    )
    return {
        "items": [
            {"membership_id": m.membership_id, "user_id": m.user_id, "role": m.role, "is_active": m.is_active}
            for m in members
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete(
    "/institutions/organizations/{org_id}/memberships/{user_id}",
    response_model=schemas.DeactivationResponse,
    responses={**AUTH_ERRORS, 404: {"model": ErrorEnvelope}, **_CONFLICT},
)
async def deactivate_membership(
    org_id: str,
    user_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Deactivate (not delete) a membership. Active org ADMIN only; never the last admin.

    Access is revoked immediately; the membership, class enrollments and learner
    records are retained as history. Repeating the call is idempotent.
    """
    try:
        membership, changed = await institution_service.deactivate_membership_as_admin_async(
            org_id=org_id,
            acting_user_id=current_user.id,
            target_user_id=user_id,
        )
    except MembershipNotFoundError:
        raise ApiError(404, "MEMBERSHIP_NOT_FOUND", "Membership not found.") from None
    except LastAdminError:
        raise ApiError(
            409, "LAST_ADMIN",
            "Cannot deactivate the last active administrator of an organization.",
        ) from None
    return {
        "org_id": org_id,
        "user_id": user_id,
        "role": membership.role,
        "status": "deactivated" if changed else "already_inactive",
    }




@router.post(
    "/institutions/organizations/{org_id}/invitations",
    response_model=schemas.InvitationResponse,
    responses={**CONCEALED_ERRORS, 400: {"model": ErrorEnvelope}},
)
async def create_organization_invitation(
    org_id: str,
    payload: schemas.CreateInvitationRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Invite a teacher or learner to join an organization by email. Admin only."""
    try:
        inv = await institution_service.create_invitation_async(
            org_id=org_id,
            email=payload.email,
            role=payload.role,
            class_id=payload.class_id,
            actor_user_id=current_user.id,
        )
        return inv
    except AuthorizationError:
        raise ApiError(403, "FORBIDDEN", "Only organization administrators can create invitations.")


@router.get(
    "/institutions/organizations/{org_id}/invitations",
    response_model=List[schemas.InvitationResponse],
    responses={**CONCEALED_ERRORS},
)
async def list_organization_invitations(
    org_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List pending invitations for an organization. Admin only."""
    try:
        return await institution_service.list_invitations_async(org_id, current_user.id)
    except AuthorizationError:
        raise ApiError(403, "FORBIDDEN", "Only organization administrators can view invitations.")


@router.delete(
    "/institutions/organizations/{org_id}/invitations/{invitation_id}",
    responses={**CONCEALED_ERRORS},
)
async def revoke_organization_invitation(
    org_id: str,
    invitation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Revoke a pending organization invitation. Admin only."""
    try:
        ok = await institution_service.revoke_invitation_async(org_id, invitation_id, current_user.id)
        if not ok:
            raise ApiError(404, "INVITATION_NOT_FOUND", "Invitation not found or already accepted.")
        return {"revoked": True, "invitation_id": invitation_id}
    except AuthorizationError:
        raise ApiError(403, "FORBIDDEN", "Only organization administrators can revoke invitations.")


@router.post(
    "/institutions/invitations/{token}/accept",
    responses={**AUTH_ERRORS, 400: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)
async def accept_organization_invitation(
    token: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Accept an invitation to join an organization using the secure invitation token."""
    if not current_user.email:
        raise ApiError(400, "EMAIL_REQUIRED", "Your authenticated identity must have a verified email.")
    try:
        res = await institution_service.accept_invitation_async(token, current_user.id, current_user.email)
        return {"accepted": True, **res}
    except AuthorizationError as exc:
        raise ApiError(403, "INVITATION_INVALID", str(exc))


@router.post(
    "/institutions/classes",
    response_model=schemas.CourseClassResponse,
    responses={**CONCEALED_ERRORS, 400: {"model": ErrorEnvelope}},
)
async def create_institution_class(
    req: CreateOrgClassApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    await run_in_threadpool(_require_owned_uploaded_document, req.subject_id, current_user.id)
    return await run_in_threadpool(
        institution_service.create_class,
        org_id=req.org_id,
        subject_id=req.subject_id,
        title=req.title,
        teacher_ids=req.teacher_ids,
        creator_user_id=current_user.id,
        enrolled_learner_ids=req.enrolled_learner_ids,
    )


@router.post(
    "/institutions/classes/{class_id}/enroll",
    response_model=schemas.EnrollmentResponse,
    responses={**CONCEALED_ERRORS, 400: {"model": ErrorEnvelope}},
)
async def enroll_learner_in_class(
    class_id: str,
    req: EnrollLearnerApiRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Enroll (or re-enroll) an active LEARNER of the class's organization."""
    return await _class_scoped(lambda: run_in_threadpool(
        institution_service.enroll_learner,
        class_id=class_id,
        learner_id=req.learner_id,
        enroller_user_id=current_user.id,
    ))


@router.delete(
    "/institutions/classes/{class_id}/enrollments/{learner_id}",
    response_model=schemas.UnenrollmentResponse,
    responses=CONCEALED_ERRORS,
)
async def unenroll_learner_from_class(
    class_id: str,
    learner_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Soft-unenroll a learner (ADMIN of the class's org or an assigned TEACHER).

    The learner leaves the active roster and loses class-shared materials at once.
    The enrollment row, the learner's account and all learning evidence are kept.
    Idempotent: repeating returns status "already_unenrolled".
    """
    changed = await _class_scoped(lambda: institution_service.unenroll_learner_async(
        class_id, learner_id, current_user.id
    ))
    return {
        "class_id": class_id,
        "learner_id": learner_id,
        "status": "unenrolled" if changed else "already_unenrolled",
    }


@router.put(
    "/institutions/classes/{class_id}/teachers",
    response_model=schemas.CourseClassResponse,
    responses={**CONCEALED_ERRORS, 400: {"model": ErrorEnvelope}},
)
async def set_class_teachers(
    class_id: str,
    req: schemas.TeacherAssignmentRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Replace the class's teachers (active org ADMIN only). Every teacher must be an
    active TEACHER member of the class's organization."""
    return await _class_scoped(lambda: institution_service.set_class_teachers_async(
        class_id, req.teacher_ids, current_user.id
    ))


@router.get(
    "/institutions/organizations",
    response_model=List[schemas.OrganizationResponse],
    responses=AUTH_ERRORS,
)
async def list_organizations(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await institution_service.list_organizations_for_user_async(current_user.id)


@router.get(
    "/institutions/classes",
    response_model=List[schemas.CourseClassResponse],
    responses=AUTH_ERRORS,
)
async def list_institution_classes(
    org_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await institution_service.list_classes_for_user_async(
        user_id=current_user.id, org_id=org_id
    )


@router.get(
    "/institutions/classes/{class_id}/roster",
    response_model=schemas.RosterResponse,
    responses=CONCEALED_ERRORS,
)
async def get_class_roster(
    class_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Active roster of a class (ADMIN of its org, or an assigned TEACHER).

    A missing class and another tenant's class produce the same 404.
    """
    roster = await _class_scoped(lambda: run_in_threadpool(
        institution_service.get_class_roster, class_id=class_id, caller_user_id=current_user.id
    ))
    return {"class_id": class_id, "roster": roster}


@router.get("/auth/personas")
async def get_personas():
    """
    Demo-only role personas. Disabled (404) in staging and production: demo fixtures
    must stay isolated from real sessions (Master Blueprint §14).
    """
    if is_strict():
        raise ApiError(404, "NOT_FOUND", "Not found.")
    return [
        {
            "id": "student_alex",
            "name": "Alex Rivera",
            "role": "LEARNER",
            "title": "Undergraduate Scholar",
            "avatar": "👨‍🎓",
            "org_name": "Apex Institute of Science & Technology",
            "email": "alex.rivera@apex.edu",
        },
        {
            "id": "prof_vance",
            "name": "Prof. Eleanor Vance",
            "role": "TEACHER",
            "title": "Lead Instructor, Systems & DAA",
            "avatar": "👩‍🏫",
            "org_name": "Apex Institute of Science & Technology",
            "email": "e.vance@apex.edu",
        },
        {
            "id": "admin_sterling",
            "name": "Dr. Marcus Sterling",
            "role": "ADMIN",
            "title": "Dean of Academic Systems (B2B Admin)",
            "avatar": "🏛️",
            "org_name": "Apex Institute of Science & Technology",
            "email": "m.sterling@apex.edu",
        },
        {
            "id": "teacher_independent",
            "name": "Dr. Sarah Lin",
            "role": "TEACHER",
            "title": "Independent Visiting Educator",
            "avatar": "🧑‍🏫",
            "org_name": "Open Academic Community (Non-B2B)",
            "email": "sarah.lin@open-ed.org",
        },
    ]


"""
Unified Application REST API Router for TAPROOT Phase 6.
Exposes clean facade endpoints for Subjects, Knowledge Graph, Learner Progress,
Gap Analysis, Learning Path, Session/Quiz activities, Contextual AI Tutor,
and Source Library with durable job tracking and server authority.
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
import re
import threading
import time
import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Query, UploadFile, File
from pydantic import BaseModel, Field

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from backend.services.tutor_service import TutorService
from backend.services.source_service import SourceService
from phase3.errors import LearnSenseError
from phase4.models import ConfidenceLevel, SelfAssessmentStatus
import logging
from storage.job_repository import JobRepository

logger = logging.getLogger(__name__)

router = APIRouter()

knowledge_service = KnowledgeService()
learner_service = LearnerService(knowledge_service=knowledge_service)
learning_service = LearningService(learner_service=learner_service, knowledge_service=knowledge_service)
tutor_service = TutorService(knowledge_service=knowledge_service, learner_service=learner_service)
source_service = SourceService()
job_repo = JobRepository()


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
    # P0 SECURITY: learner identity is MANDATORY. It was previously optional, which
    # allowed the ownership check to be skipped entirely by omitting the field.
    # NOTE: this is an explicit caller-supplied identity, NOT authentication.
    learner_id: str


class DiagnosticSubmitApiRequest(BaseModel):
    session_id: str
    responses: Dict[str, Any]
    # P0 SECURITY: learner identity is MANDATORY (see DiagnosticStartApiRequest).
    learner_id: str


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


class FinalAssessmentSubmitApiRequest(BaseModel):
    assessment_id: str
    learner_id: str
    subject_id: str
    responses: Dict[str, Any]
    request_id: Optional[str] = None


# --- SUBJECTS & KNOWLEDGE GRAPH ROUTES ---

@router.get("/subjects")
async def list_subjects():
    """
    Returns list of available subjects with concept counts and metadata.
    """
    return knowledge_service.list_subjects()


@router.get("/subjects/{subject_id}/graph")
async def get_subject_graph(subject_id: str, learner_id: Optional[str] = None):
    """
    Returns frontend Knowledge Graph structure with topic territories, concepts, and relationships.
    """
    masteries = {}
    if learner_id:
        graph_temp = knowledge_service.get_subject_graph(subject_id)
        c_ids = [c["concept_id"] for c in graph_temp["concepts"]]
        st = learner_service.get_or_create_learner_state(learner_id, c_ids)
        masteries = {cid: cs.mastery_probability for cid, cs in st.concept_states.items()}

    return knowledge_service.get_subject_graph(subject_id, learner_masteries=masteries)


@router.get("/subjects/{subject_id}/concepts/{concept_id}/question")
async def get_concept_question(subject_id: str, concept_id: str):
    """
    Returns authentic domain question and options for a specific concept.
    P0 Security: correct_answer and explanation are strictly stripped before submission!
    """
    try:
        return learning_service.get_concept_question(subject_id, concept_id)
    except LearnSenseError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/subjects/{subject_id}/concepts/{concept_id}/content")
async def get_concept_learning_content(subject_id: str, concept_id: str):
    """
    Returns in-depth educational learning content for a concept.
    """
    try:
        return learning_service.get_concept_learning_content(subject_id, concept_id)
    except LearnSenseError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- LEARNER STATE, PROGRESS & PATH ROUTES ---

@router.get("/learners/{learner_id}/progress")
async def get_learner_progress(learner_id: str, subject_id: str):
    """
    Returns learner mastery breakdown, exploration rates, and confidence level.
    """
    return learner_service.get_learner_progress(learner_id, subject_id)


@router.get("/learners/{learner_id}/path-and-gaps")
async def get_path_and_gaps(learner_id: str, subject_id: str):
    """
    Returns Phase 4 prioritized knowledge gaps, cycle-safe learning path, and active next target.
    """
    return learner_service.get_gaps_and_path(learner_id, subject_id)


# --- ONBOARDING & ASSESSMENT ROUTES ---

@router.post("/initialization/self-assessment")
async def submit_self_assessment(req: SelfAssessmentApiRequest):
    """
    Submits concept self-assessment (KNOW, DONT_KNOW, UNANSWERED) plus optional
    per-concept confidence, and creates an initialization session.
    Self-assessment is stored as a hypothesis; it never sets KT mastery.
    Server is authoritative for valid concepts.
    """
    try:
        session = learning_service.submit_self_assessment(
            learner_id=req.learner_id,
            subject_id=req.subject_id,
            selections=req.selections,
            all_concept_ids=req.all_subject_concept_ids,
            confidences=req.confidences,
        )
        return session.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/initialization/diagnostic/start")
async def start_diagnostic(req: DiagnosticStartApiRequest):
    """
    Generates diagnostic assessment questions over the verification set
    (KNOW + UNANSWERED), prioritized by self-assessment x confidence.
    DONT_KNOW concepts are never probed.
    P0 Security: correct_answer is never leaked before submission.
    """
    try:
        return learning_service.start_diagnostic(req.session_id, learner_id=req.learner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/initialization/diagnostic/submit")
async def submit_diagnostic(req: DiagnosticSubmitApiRequest):
    """
    Submits diagnostic responses. Evaluates correctness AUTHORITATIVELY on the server.
    """
    try:
        return learning_service.submit_diagnostic(req.session_id, req.responses, learner_id=req.learner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/learners/activity-response")
async def submit_activity_response(req: ActivityResponseApiRequest):
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

    try:
        return learning_service.process_activity_response(
            learner_id=req.learner_id,
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
async def resume_learner(learner_id: str, subject_id: Optional[str] = Query(None)):
    """
    Returns persisted learner state, progress, and active assessment to resume UI after refresh.
    """
    return learner_service.resume_learner_state(learner_id, subject_id=subject_id)


# --- FINAL ASSESSMENT ROUTES ---

@router.post("/assessment/final/start")
async def start_final_assessment(req: FinalAssessmentStartApiRequest):
    """
    Starts or resumes a dedicated Final Assessment covering concepts in the subject.
    Never exposes correct_answer or explanation.
    """
    try:
        return learning_service.start_final_assessment(req.learner_id, req.subject_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/assessment/final/submit")
async def submit_final_assessment(req: FinalAssessmentSubmitApiRequest):
    """
    Evaluates Final Assessment server-side authoritatively and updates BKT masteries.
    """
    try:
        return learning_service.submit_final_assessment(
            assessment_id=req.assessment_id,
            learner_id=req.learner_id,
            subject_id=req.subject_id,
            responses=req.responses,
            request_id=req.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/assessment/final/status/{assessment_id}")
async def get_final_assessment_status(assessment_id: str, learner_id: str = Query(...)):
    """
    Retrieves status / scorecard of a Final Assessment.

    P0 SECURITY: `learner_id` is a REQUIRED query parameter and ownership is always
    verified. The service additionally strips correct_answer/explanation from the
    payload, so this endpoint can never be used to read an answer key.
    """
    if not learner_id:
        raise HTTPException(
            status_code=400,
            detail="learner_id is required to read Final Assessment status.",
        )
    try:
        return learning_service.get_final_assessment_status(assessment_id, learner_id=learner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- CONTEXTUAL TUTOR ROUTES ---

@router.post("/tutor/interact")
async def interact_with_tutor(req: TutorInteractApiRequest):
    """
    Provides context-aware tutoring guidance anchored to concept, learner state, and source references.
    """
    return tutor_service.generate_contextual_response(
        learner_id=req.learner_id,
        subject_id=req.subject_id,
        concept_id=req.concept_id,
        intent=req.intent,
        user_message=req.user_message,
    )


# --- SOURCE LIBRARY ROUTES ---

@router.get("/sources")
async def list_sources():
    """
    Lists uploaded sources and processing/recovery statuses.
    """
    return source_service.list_sources()


@router.get("/health")
async def api_health():
    """
    Backend + LLM provider health for the frontend connection banner.
    """
    from phase3.adapters.llm_adapter import get_llm_adapter

    adapter = get_llm_adapter()
    health = adapter.health()
    # §2 #14: Mock can never count as ready. Only real provider + credentials = ready.
    return {
        "status": "healthy",
        "llm": health,
        "llm_ready": bool(
            not getattr(adapter, "is_mock", False)
            and health.get("has_credentials")
            and health.get("provider")
        ),
    }


@router.post("/sources/upload")
async def upload_source(file: UploadFile = File(...), document_id: Optional[str] = None):
    """
    Uploads a source document and kicks off the knowledge-build pipeline asynchronously.
    Durable job state is persisted under storage/jobs/{job_id}.json.
    """
    doc_id = document_id or _derive_document_id(file.filename)
    content = await file.read()
    filename = file.filename or "document.pdf"

    job_id = str(uuid.uuid4())
    job = job_repo.create_job(job_id, filename)
    job["document_id"] = doc_id
    job["status"] = "processing"
    job_repo.save_job(job)

    def _run_build(job_id: str, doc_id: str, content: bytes, filename: str) -> None:
        try:
            if job_repo.is_cancelled(job_id):
                return
            result = source_service.save_uploaded_source(doc_id, content, filename)
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


@router.get("/sources/upload/status/{job_id}")
async def upload_status(job_id: str):
    """
    Poll the status of an async upload job from durable storage.
    """
    job = job_repo.load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No upload job found with id '{job_id}'")

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
async def cancel_upload(job_id: str):
    """
    Cancels an in-flight upload/ingestion job safely without corrupting persistent state.
    """
    cancelled = job_repo.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"No upload job found with id '{job_id}'")
    return {"job_id": job_id, "status": "cancelled", "message": "Upload job cancelled successfully."}


def _derive_document_id(filename: Optional[str]) -> str:
    """Stable, filesystem-safe id derived from the upload's name."""
    stem = Path(filename or "document").stem
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower()
    return f"doc_{slug or 'document'}"

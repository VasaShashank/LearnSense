"""
Unified Application REST API Router for TAPROOT Phase 6.
Exposes clean facade endpoints for Subjects, Knowledge Graph, Learner Progress, Gap Analysis, Learning Path, Session/Quiz activities, Contextual AI Tutor, and Source Library.
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
from phase4.models import SelfAssessmentStatus

router = APIRouter()

knowledge_service = KnowledgeService()
learner_service = LearnerService(knowledge_service=knowledge_service)
learning_service = LearningService(learner_service=learner_service, knowledge_service=knowledge_service)
tutor_service = TutorService(knowledge_service=knowledge_service, learner_service=learner_service)
source_service = SourceService()

# In-memory job store for async upload tracking
# {job_id: {"status": str, "result": dict|None, "error": str|None, "started_at": float}}
_upload_jobs: Dict[str, Dict] = {}


# Request Models
class SelfAssessmentApiRequest(BaseModel):
    learner_id: str
    subject_id: str
    selections: Dict[str, SelfAssessmentStatus]
    all_subject_concept_ids: List[str]


class DiagnosticStartApiRequest(BaseModel):
    session_id: str


class DiagnosticSubmitApiRequest(BaseModel):
    session_id: str
    responses: Dict[str, float]


class ActivityResponseApiRequest(BaseModel):
    learner_id: str
    subject_id: str
    concept_ids: List[str]
    correctness: float
    all_subject_concept_ids: List[str]
    request_id: Optional[str] = None


class TutorInteractApiRequest(BaseModel):
    learner_id: str
    subject_id: str
    concept_id: str
    intent: str = "EXPLAIN"  # EXPLAIN, HINT, EXAMPLE, ANALOGY, WHY_WRONG, CUSTOM
    user_message: Optional[str] = None


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
    """
    try:
        return learning_service.get_concept_question(subject_id, concept_id)
    except LearnSenseError:
        # Typed runtime errors are rendered by the global handler in app.py.
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/subjects/{subject_id}/concepts/{concept_id}/content")
async def get_concept_learning_content(subject_id: str, concept_id: str):
    """
    Returns in-depth educational learning content (overview, intuition, key principles, worked example, misconceptions, takeaway) for a concept.
    """
    try:
        return learning_service.get_concept_learning_content(subject_id, concept_id)
    except LearnSenseError:
        # Typed runtime errors are rendered by the global handler in app.py.
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
    Submits concept self-assessment (KNOW, DONT_KNOW, UNANSWERED) and creates initialization session.
    """
    try:
        session = learning_service.submit_self_assessment(
            learner_id=req.learner_id,
            subject_id=req.subject_id,
            selections=req.selections,
            all_concept_ids=req.all_subject_concept_ids,
        )
        return session.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/initialization/diagnostic/start")
async def start_diagnostic(req: DiagnosticStartApiRequest):
    """
    Generates diagnostic assessment questions restricted strictly to KNOW concepts.
    """
    try:
        return learning_service.start_diagnostic(req.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/initialization/diagnostic/submit")
async def submit_diagnostic(req: DiagnosticSubmitApiRequest):
    """
    Submits diagnostic responses, updates KT state, and sets diagnostic completion.
    """
    try:
        return learning_service.submit_diagnostic(req.session_id, req.responses)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/learners/activity-response")
async def submit_activity_response(req: ActivityResponseApiRequest):
    """
    Submits activity/quiz response, triggers Phase 3 KT update & Phase 4 replanning with Phase 5 idempotency.
    """
    try:
        return learning_service.process_activity_response(
            learner_id=req.learner_id,
            subject_id=req.subject_id,
            concept_ids=req.concept_ids,
            correctness=req.correctness,
            all_subject_concept_ids=req.all_subject_concept_ids,
            request_id=req.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- CONTEXTUAL TUTOR ROUTES ---

@router.post("/tutor/interact")
async def interact_with_tutor(req: TutorInteractApiRequest):
    """
    Provides context-aware tutoring guidance anchored to concept, learner state, and sources.
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
    Lists uploaded PDF sources and Phase 5 processing/recovery statuses.
    """
    return source_service.list_sources()


@router.get("/health")
async def api_health():
    """
    Backend + LLM provider health for the frontend connection banner.

    Reports whether a real model is reachable, so the UI can warn *before* a learner
    uploads a document that generation will then fail to process.
    """
    from phase3.adapters.llm_adapter import get_llm_adapter

    adapter = get_llm_adapter()
    health = adapter.health()
    return {
        "status": "healthy",
        "llm": health,
        "llm_ready": bool(adapter.is_mock or (health["has_credentials"] and health["provider"])),
    }


@router.post("/sources/upload")
async def upload_source(file: UploadFile = File(...), document_id: Optional[str] = None):
    """
    Uploads a source document and kicks off the knowledge-build pipeline asynchronously.

    Returns a ``job_id`` immediately. Poll ``GET /api/sources/upload/status/{job_id}``
    to track progress. The full Phase 1 → Phase 2 → Phase 3 chain runs in a background
    thread so the HTTP connection is never held open for the full ingestion time.
    """
    doc_id = document_id or _derive_document_id(file.filename)
    content = await file.read()
    filename = file.filename or "document.pdf"

    job_id = str(uuid.uuid4())
    _upload_jobs[job_id] = {
        "status": "processing",
        "document_id": doc_id,
        "filename": filename,
        "result": None,
        "error": None,
        "started_at": time.time(),
    }

    def _run_build(job_id: str, doc_id: str, content: bytes, filename: str) -> None:
        try:
            result = source_service.save_uploaded_source(doc_id, content, filename)
            _upload_jobs[job_id]["status"] = "done"
            _upload_jobs[job_id]["result"] = result
        except Exception as exc:  # pragma: no cover
            _upload_jobs[job_id]["status"] = "error"
            _upload_jobs[job_id]["error"] = str(exc)

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
    Poll the status of an async upload job started by POST /api/sources/upload.

    Returns one of:
    - ``{"status": "processing", ...}``  – still running
    - ``{"status": "done", "result": {...}}``  – completed successfully
    - ``{"status": "error", "error": "..."}``  – failed with reason
    """
    job = _upload_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No upload job found with id '{job_id}'")

    elapsed = round(time.time() - job["started_at"], 1)
    return {
        "job_id": job_id,
        "document_id": job["document_id"],
        "filename": job["filename"],
        "status": job["status"],
        "elapsed_seconds": elapsed,
        "result": job["result"],
        "error": job["error"],
    }


def _derive_document_id(filename: Optional[str]) -> str:
    """Stable, filesystem-safe id derived from the upload's name."""
    stem = Path(filename or "document").stem
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower()
    return f"doc_{slug or 'document'}"

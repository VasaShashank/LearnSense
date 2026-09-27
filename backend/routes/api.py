"""
Unified Application REST API Router for TAPROOT Phase 6.
Exposes clean facade endpoints for Subjects, Knowledge Graph, Learner Progress, Gap Analysis, Learning Path, Session/Quiz activities, Contextual AI Tutor, and Source Library.
"""

from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, status, Query, UploadFile, File
from pydantic import BaseModel, Field

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from backend.services.tutor_service import TutorService
from backend.services.source_service import SourceService
from phase4.models import SelfAssessmentStatus

router = APIRouter()

knowledge_service = KnowledgeService()
learner_service = LearnerService(knowledge_service=knowledge_service)
learning_service = LearningService(learner_service=learner_service, knowledge_service=knowledge_service)
tutor_service = TutorService(knowledge_service=knowledge_service, learner_service=learner_service)
source_service = SourceService()


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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/subjects/{subject_id}/concepts/{concept_id}/content")
async def get_concept_learning_content(subject_id: str, concept_id: str):
    """
    Returns in-depth educational learning content (overview, intuition, key principles, worked example, misconceptions, takeaway) for a concept.
    """
    try:
        return learning_service.get_concept_learning_content(subject_id, concept_id)
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


@router.post("/sources/upload")
async def upload_source(file: UploadFile = File(...), document_id: Optional[str] = None):
    """
    Uploads a source PDF document.
    """
    doc_id = document_id or file.filename.replace(" ", "_").lower().replace(".pdf", "")
    content = await file.read()
    try:
        return source_service.save_uploaded_source(doc_id, content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

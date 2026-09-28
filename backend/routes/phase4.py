"""
Phase 4 FastAPI REST API Routes.
Exposes endpoints for concept self-assessment, diagnostic lifecycle, knowledge gap detection,
personalized learning path generation, next target selection, and adaptive activity responses.
Integrated with Phase 5 validators and response submission idempotency checks.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.kt import KnowledgeTracer
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionType
from phase4.integration.phase3_adapter import Phase3Adapter
from phase4.models import (
    ActivityType,
    KnowledgeGap,
    KnowledgeInitializationSession,
    LearningActivity,
    LearningPath,
    LearningTarget,
    SelfAssessmentStatus,
)
from phase5.validation import LearnerStateValidator, IdempotencyTracker, PlanningValidator

router = APIRouter()

# In-memory session and state persistence for REST endpoints
_SESSIONS: Dict[str, KnowledgeInitializationSession] = {}
_LEARNER_STATES: Dict[str, LearnerState] = {}
_LEARNING_CONTEXTS: Dict[str, LearningContext] = {}
_QUESTION_BANKS: Dict[str, QuestionBank] = {}

adapter = Phase3Adapter()
idempotency_tracker = IdempotencyTracker()
learner_state_validator = LearnerStateValidator(idempotency_tracker=idempotency_tracker)
planning_validator = PlanningValidator()


class SelfAssessmentRequest(BaseModel):
    learner_id: str
    subject_id: str
    selections: Dict[str, SelfAssessmentStatus]
    all_subject_concept_ids: List[str]


class DiagnosticStartRequest(BaseModel):
    session_id: str


class DiagnosticSubmitRequest(BaseModel):
    session_id: str
    responses: Dict[str, float]  # question_id -> correctness 0.0 to 1.0


class ActivityResponseRequest(BaseModel):
    learner_id: str
    subject_id: str
    concept_ids: List[str]
    correctness: float
    all_subject_concept_ids: List[str]
    request_id: Optional[str] = None  # Idempotency token


def _get_or_create_learner_state(learner_id: str, concept_ids: List[str]) -> LearnerState:
    if learner_id not in _LEARNER_STATES:
        _LEARNER_STATES[learner_id] = adapter.tracer.initialize_learner(learner_id, concept_ids)
    return _LEARNER_STATES[learner_id]


def _get_or_create_learning_context(subject_id: str, concept_ids: List[str]) -> LearningContext:
    if subject_id not in _LEARNING_CONTEXTS:
        _LEARNING_CONTEXTS[subject_id] = LearningContext(
            document_id=subject_id,
            knowledge_document_id=f"kdoc_{subject_id}",
        )
    return _LEARNING_CONTEXTS[subject_id]


def _get_or_create_question_bank(subject_id: str, concept_ids: Optional[List[str]] = None) -> QuestionBank:
    from backend.services.learning_service import LearningService
    _svc = LearningService()
    return _svc.get_or_create_question_bank(subject_id, concept_ids or [])



@router.post("/initialization/self-assessment", response_model=KnowledgeInitializationSession)
async def submit_self_assessment(req: SelfAssessmentRequest):
    """
    Submits learner concept self-assessment (KNOW, DONT_KNOW, UNANSWERED).
    Self-reported status is kept separate from objective KT evidence.
    """
    val_res = planning_validator.validate_self_assessment(req.selections, req.all_subject_concept_ids)
    if not val_res.is_valid:
        raise HTTPException(status_code=400, detail=val_res.errors[0])

    session = adapter.self_assessment_handler.create_session(
        learner_id=req.learner_id,
        subject_id=req.subject_id,
        selections=req.selections,
        all_subject_concept_ids=req.all_subject_concept_ids,
    )
    _SESSIONS[session.session_id] = session
    _get_or_create_learner_state(req.learner_id, req.all_subject_concept_ids)
    _get_or_create_learning_context(req.subject_id, req.all_subject_concept_ids)
    return session


@router.post("/initialization/diagnostic/start")
async def start_diagnostic(req: DiagnosticStartRequest):
    """
    Creates diagnostic assessment questions restricted strictly to selected KNOW concepts.
    Returns empty list if zero KNOW concepts were selected.
    """
    session = _SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    bank = _get_or_create_question_bank(session.subject_id, session.know_concept_ids)
    questions = adapter.diagnostic_orchestrator.create_diagnostic_quiz(session, bank)

    # Validate diagnostic questions restriction
    val_res = planning_validator.validate_diagnostic_quiz_creation(session, questions)
    if not val_res.is_valid:
        raise HTTPException(status_code=422, detail=val_res.errors[0])

    safe_questions = []
    for q in questions:
        q_dict = q.model_dump(mode="json") if hasattr(q, "model_dump") else dict(q)
        q_dict.pop("correct_answer", None)
        safe_questions.append(q_dict)

    return {
        "session_id": session.session_id,
        "know_concepts": session.know_concept_ids,
        "question_count": len(safe_questions),
        "questions": safe_questions,
    }


@router.post("/initialization/diagnostic/submit")
async def submit_diagnostic(req: DiagnosticSubmitRequest):
    """
    Submits diagnostic question responses and initializes objective KT state.
    """
    session = _SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    learner_state = _LEARNER_STATES.get(session.learner_id)
    if not learner_state:
        learner_state = adapter.tracer.initialize_learner(
            session.learner_id, session.know_concept_ids + session.dont_know_concept_ids
        )
        _LEARNER_STATES[session.learner_id] = learner_state

    bank = _get_or_create_question_bank(session.subject_id)
    updated_masteries = adapter.diagnostic_orchestrator.submit_diagnostic_responses(
        init_session=session,
        learner_state=learner_state,
        question_responses=req.responses,
        question_bank=bank,
    )

    return {
        "session_id": session.session_id,
        "diagnostic_completed": session.diagnostic_completed,
        "diagnostic_score": session.diagnostic_score,
        "updated_masteries": updated_masteries,
    }


@router.get("/learners/{learner_id}/gaps", response_model=List[KnowledgeGap])
async def get_knowledge_gaps(learner_id: str, subject_id: str, concept_ids: str):
    """
    Detects and returns prioritized knowledge gaps with explainable data-driven reasons.
    """
    c_ids = [c.strip() for c in concept_ids.split(",") if c.strip()]
    learner_state = _get_or_create_learner_state(learner_id, c_ids)
    learning_context = _get_or_create_learning_context(subject_id, c_ids)

    gaps = adapter.gap_detector.detect_gaps(learning_context, learner_state, c_ids)
    prioritized = adapter.gap_prioritizer.prioritize_gaps(gaps)
    return prioritized


@router.get("/learners/{learner_id}/path", response_model=LearningPath)
async def get_learning_path(learner_id: str, subject_id: str, concept_ids: str):
    """
    Generates personalized, prerequisite-aware, cycle-safe learning path.
    """
    c_ids = [c.strip() for c in concept_ids.split(",") if c.strip()]
    learner_state = _get_or_create_learner_state(learner_id, c_ids)
    learning_context = _get_or_create_learning_context(subject_id, c_ids)

    path = adapter.path_generator.generate_path(learning_context, learner_state, c_ids)

    val_res = planning_validator.validate_learning_path(path, set(c_ids))
    if not val_res.is_valid:
        raise HTTPException(status_code=422, detail=val_res.errors[0])

    return path


@router.get("/learners/{learner_id}/next-target", response_model=Optional[LearningTarget])
async def get_next_learning_target(learner_id: str, subject_id: str, concept_ids: str):
    """
    Selects active next learning target from personalized learning path.
    """
    c_ids = [c.strip() for c in concept_ids.split(",") if c.strip()]
    learner_state = _get_or_create_learner_state(learner_id, c_ids)
    learning_context = _get_or_create_learning_context(subject_id, c_ids)

    path = adapter.path_generator.generate_path(learning_context, learner_state, c_ids)
    target = adapter.target_selector.select_next_target(path, learner_state, learning_context)
    return target


@router.post("/learners/activity-response")
async def submit_activity_response(req: ActivityResponseRequest):
    """
    Submits response for a learning activity, updates Phase 3 KT, and triggers Phase 4 replanning.
    Protects against duplicate submission double-updating KT via idempotency tracking.
    """
    learner_state = _get_or_create_learner_state(req.learner_id, req.all_subject_concept_ids)
    learning_context = _get_or_create_learning_context(req.subject_id, req.all_subject_concept_ids)

    # Phase 5 Response Submission Validation & Idempotency Check
    val_res = learner_state_validator.validate_response_submission(
        learner_id=req.learner_id,
        concept_ids=req.concept_ids,
        correctness=req.correctness,
        request_id=req.request_id,
        valid_subject_concepts=set(req.all_subject_concept_ids),
    )

    if not val_res.is_valid:
        raise HTTPException(status_code=400, detail=val_res.errors[0])

    if val_res.metadata.get("duplicate_submission", False):
        # Return current state without reapplying double KT mutation
        path = adapter.path_generator.generate_path(learning_context, learner_state, req.all_subject_concept_ids)
        next_target = adapter.target_selector.select_next_target(path, learner_state, learning_context)
        return {
            "duplicate_submission": True,
            "updated_masteries": {
                c_id: learner_state.concept_states[c_id].mastery_probability
                for c_id in req.concept_ids if c_id in learner_state.concept_states
            },
            "path_node_count": len(path.nodes),
            "next_target": next_target,
        }

    updated_masteries, path, next_target = adapter.handle_activity_response_and_replan(
        learner_state=learner_state,
        learning_context=learning_context,
        subject_concept_ids=req.all_subject_concept_ids,
        concept_ids=req.concept_ids,
        correctness=req.correctness,
    )

    if req.request_id:
        idempotency_tracker.mark_processed(req.request_id)

    return {
        "updated_masteries": updated_masteries,
        "path_node_count": len(path.nodes),
        "next_target": next_target,
    }

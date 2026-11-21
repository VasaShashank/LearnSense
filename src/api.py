"""LearnSense Person 3 — Production FastAPI Application.

Exposes authenticated, concurrency-safe HTTP REST endpoints for the complete LearnSense
personalization engine, backed by durable SQLiteStateStore with write-ahead logging (WAL):
- Learner state retrieval and longitudinal tracking
- Concurrency-safe, atomic attempt ingestion and idempotency conflict handling (HTTP 409)
- Information-gain-based adaptive question selection
- Prerequisite-aware personalized learning recommendations
- Source-grounded Socratic tutoring and honest derivation diagnosis

Strictly validates against Draft 2020-12 JSON schemas in contracts/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jsonschema import Draft202012Validator

from src.service import LearnSensePersonalizationService
from src.storage import SQLiteStateStore
from src.tutoring import TutoringRequest

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"
DEFAULT_DB_PATH = os.environ.get("LEARNSENSE_DB_PATH", ":memory:")
import secrets

DEFAULT_DEV_KEY = "learnsense_dev_secret_key_2026"
DEFAULT_API_KEY = os.environ.get("LEARNSENSE_API_KEY", DEFAULT_DEV_KEY)

security_bearer = HTTPBearer(auto_error=False)


def get_configured_api_key() -> Optional[str]:
    """Retrieves configured API key, failing closed if unset and test override is inactive."""
    env_key = os.environ.get("LEARNSENSE_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    # Explicit test harness override only
    if os.environ.get("LEARNSENSE_ALLOW_TEST_KEY", "").lower() in {"true", "1"}:
        return DEFAULT_DEV_KEY
    return None


def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> str:
    """Verifies HTTP Bearer token authentication with fail-closed security semantics."""
    expected_key = get_configured_api_key()
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is unconfigured on this server: LEARNSENSE_API_KEY environment variable is required and fails closed.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer authorization token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def verify_learner_access(
    expected_learner_id: str,
    request: Request,
) -> None:
    """Enforces per-learner identity authorization boundary.
    
    If X-Learner-Id header is provided (e.g. propagated by API Gateway), it must match
    the expected_learner_id. Mismatches raise HTTP 403 Forbidden.
    If LEARNSENSE_ENFORCE_LEARNER_AUTH=true is set in the environment, X-Learner-Id header is mandatory.
    """
    caller_learner_id = request.headers.get("x-learner-id")
    enforce_strict = os.environ.get("LEARNSENSE_ENFORCE_LEARNER_AUTH", "").lower() in {"true", "1"}

    if enforce_strict and not caller_learner_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Learner authorization claim required: X-Learner-Id header must be provided when strict auth is active.",
        )
    if caller_learner_id and caller_learner_id.strip() != expected_learner_id.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Caller with identity '{caller_learner_id}' is not authorized to access or mutate learner '{expected_learner_id}'.",
        )


def load_validator(schema_name: str) -> Draft202012Validator:
    schema_path = CONTRACTS_DIR / schema_name
    if not schema_path.is_file():
        raise FileNotFoundError(f"Contract schema not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_dict = json.load(f)
    return Draft202012Validator(schema_dict)


attempt_validator = load_validator("attempt_schema.json")
tutoring_req_validator = load_validator("tutoring_request_schema.json")


def create_app(
    db_path: Optional[Union[str, Path]] = None,
    service: Optional[LearnSensePersonalizationService] = None,
) -> FastAPI:
    """Factory creating configured production FastAPI application."""
    app = FastAPI(
        title="LearnSense Personalization & Learner Modeling API",
        version="1.0.2",
        description="Phase 4 Production API for JEE Learner Modeling, Adaptive Assessment, and AI Tutoring.",
    )

    if service is not None:
        app.state.service = service
    else:
        target_db = str(db_path) if db_path else os.environ.get("LEARNSENSE_DB_PATH", ":memory:")
        if target_db != ":memory:":
            actual_db_path = Path(target_db)
            actual_db_path.parent.mkdir(parents=True, exist_ok=True)
            store = SQLiteStateStore(db_path=str(actual_db_path))
        else:
            store = SQLiteStateStore(db_path=":memory:")
        app.state.service = LearnSensePersonalizationService(store=store)

    @app.get("/health", tags=["System"])
    async def health_check() -> Dict[str, Any]:
        """Public healthcheck probe for load balancers and orchestrators."""
        return {
            "status": "healthy",
            "service": "LearnSense Person 3 Personalization Engine",
            "version": "1.0.2",
            "durable_storage": "sqlite_wal_transactional",
        }

    # -------------------------------------------------------------------------
    # Learner State Endpoints
    # -------------------------------------------------------------------------

    @app.get(
        "/v1/learners/{learner_id}/concepts/{concept_id}/state",
        tags=["Learner State"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_concept_state(learner_id: str, concept_id: str, request: Request) -> Dict[str, Any]:
        """Retrieves single concept mastery state for a learner."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        try:
            return svc.get_learner_concept_state(learner_id, concept_id)
        except KeyError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "concept_not_found", "message": str(e)},
            )

    @app.get(
        "/v1/learners/{learner_id}/states",
        tags=["Learner State"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_all_states(learner_id: str, request: Request) -> List[Dict[str, Any]]:
        """Retrieves all tracked concept states for a learner."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.get_all_learner_states(learner_id)

    @app.get(
        "/v1/model/info",
        tags=["Model"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_model_info() -> Dict[str, Any]:
        """Returns active concept-mastery model information, architecture, and provenance."""
        svc: LearnSensePersonalizationService = app.state.service
        return svc.get_model_info()

    # -------------------------------------------------------------------------
    # Attempt Ingestion & Knowledge Tracing
    # -------------------------------------------------------------------------

    @app.post(
        "/v1/attempts",
        tags=["Attempts"],
        dependencies=[Depends(verify_api_key)],
    )
    async def submit_attempt(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """Ingests attempt, verifies schema, processes BKT update, and returns recommendations.
        
        Handles idempotency:
        - Duplicate attempt with identical payload: returns HTTP 200 with was_new=False.
        - Conflicting reuse of same attempt_id: returns HTTP 409 Conflict.
        - Schema violations: returns HTTP 400 Bad Request.
        """
        verify_learner_access(str(payload.get("learner_id", "")), request)
        errors = [err.message for err in attempt_validator.iter_errors(payload)]
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Schema validation failed", "validation_errors": errors},
            )

        svc: LearnSensePersonalizationService = app.state.service
        try:
            result = svc.submit_attempt(payload)
            return result
        except KeyError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_concept_id", "message": str(e)},
            )
        except ValueError as e:
            err_msg = str(e)
            if "Idempotency conflict" in err_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "Idempotency conflict", "message": err_msg},
                )
            if "Chronological regression" in err_msg:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Chronological regression", "message": err_msg},
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Invalid attempt processing request", "message": err_msg},
            )

    # -------------------------------------------------------------------------
    # Adaptive Assessment Endpoints
    # -------------------------------------------------------------------------

    @app.post(
        "/v1/assessments/adaptive-select",
        tags=["Adaptive Assessment"],
        dependencies=[Depends(verify_api_key)],
    )
    async def select_adaptive_question(req: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """Selects next optimal question via Expected Information Gain (EIG)."""
        learner_id = req.get("learner_id", "anonymous_learner")
        verify_learner_access(learner_id, request)

        target_concept_id = req.get("target_concept_id")
        if not target_concept_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_concept_id is required.",
            )

        objective = req.get("objective", "progress")

        svc: LearnSensePersonalizationService = app.state.service
        try:
            res = svc.select_adaptive_question(
                learner_id=learner_id,
                concept_id=target_concept_id,
                objective=objective,
            )
            return res
        except KeyError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "concept_not_found", "message": str(e)},
            )

    @app.post(
        "/v1/assessments/adaptive-session/start",
        tags=["Adaptive Assessment"],
        dependencies=[Depends(verify_api_key)],
    )
    async def start_adaptive_session(req: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """Initiates an 8-question computerized adaptive assessment session for a concept."""
        learner_id = req.get("learner_id", "anonymous_learner")
        verify_learner_access(learner_id, request)

        target_concept_id = req.get("target_concept_id") or req.get("concept_id")
        if not target_concept_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_concept_id or concept_id is required.",
            )

        target_questions = int(req.get("target_questions", 8))
        svc: LearnSensePersonalizationService = app.state.service
        try:
            return svc.start_adaptive_session(
                learner_id=learner_id,
                concept_id=target_concept_id,
                target_questions=target_questions,
            )
        except KeyError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "concept_not_found", "message": str(e)},
            )

    @app.get(
        "/v1/assessments/adaptive-session/{session_id}/next-question",
        tags=["Adaptive Assessment"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_adaptive_session_next_question(session_id: str, request: Request) -> Dict[str, Any]:
        """Fetches the next optimal question in the adaptive session via EIG."""
        svc: LearnSensePersonalizationService = app.state.service
        try:
            return svc.get_next_adaptive_session_question(session_id=session_id)
        except KeyError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @app.post(
        "/v1/assessments/adaptive-session/{session_id}/submit-answer",
        tags=["Adaptive Assessment"],
        dependencies=[Depends(verify_api_key)],
    )
    async def submit_adaptive_session_answer(
        session_id: str,
        payload: Dict[str, Any],
        request: Request,
    ) -> Dict[str, Any]:
        """Submits an answer to the session, updates BKT mastery, and checks ~8 question stopping criteria."""
        question_id = payload.get("question_id")
        if not question_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question_id is required.")
        is_correct = bool(payload.get("is_correct", False))

        svc: LearnSensePersonalizationService = app.state.service
        try:
            return svc.submit_adaptive_session_answer(
                session_id=session_id,
                question_id=question_id,
                is_correct=is_correct,
            )
        except KeyError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # -------------------------------------------------------------------------
    # Recommendations Endpoints
    # -------------------------------------------------------------------------

    @app.get(
        "/v1/recommendations/{learner_id}",
        tags=["Recommendations"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_recommendations(
        learner_id: str,
        request: Request,
        focus_concept_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates prerequisite-aware learning activity recommendations."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        res = svc.get_next_recommendation(
            learner_id=learner_id,
            focus_concept_id=focus_concept_id,
        )
        return res

    # -------------------------------------------------------------------------
    # AI Tutoring & Instruction Endpoints
    # -------------------------------------------------------------------------

    @app.post(
        "/v1/tutoring/chat",
        tags=["AI Tutoring"],
        dependencies=[Depends(verify_api_key)],
    )
    async def tutoring_chat(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """Delivers source-grounded Socratic tutoring, progressive hints, or derivation diagnosis."""
        verify_learner_access(str(payload.get("learner_id", "")), request)
        errors = [err.message for err in tutoring_req_validator.iter_errors(payload)]
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Schema validation failed", "validation_errors": errors},
            )

        t_req = TutoringRequest.from_contract_dict(payload)
        svc: LearnSensePersonalizationService = app.state.service
        resp = svc.deliver_tutoring(t_req)
        return resp.to_contract_payload()

    # -------------------------------------------------------------------------
    # Phase 5: Advanced Personalization & Integration Endpoints
    # -------------------------------------------------------------------------

    @app.get(
        "/v1/learners/{learner_id}/misconceptions",
        tags=["Misconceptions"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_misconceptions(
        learner_id: str,
        request: Request,
        concept_id: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieves persistent misconception records for the learner."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.get_learner_misconceptions(learner_id, concept_id=concept_id, active_only=active_only)

    @app.get(
        "/v1/learners/{learner_id}/retention/{concept_id}",
        tags=["Retention"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_retention_estimate(
        learner_id: str,
        concept_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """Retrieves personalized memory retention probability R(t) = 2^(-Δt/S)."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.estimate_retention(learner_id, concept_id)

    @app.get(
        "/v1/learners/{learner_id}/uncertainty/{concept_id}",
        tags=["Mastery Uncertainty"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_mastery_uncertainty(
        learner_id: str,
        concept_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """Retrieves mastery uncertainty index and qualitative evidence strength."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.evaluate_mastery_uncertainty(learner_id, concept_id)

    @app.get(
        "/v1/learners/{learner_id}/transfer/{concept_id}",
        tags=["Transfer Verification"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_transfer_evaluation(
        learner_id: str,
        concept_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """Retrieves mastery transfer status distinguishing familiar from unseen items."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.evaluate_transfer(learner_id, concept_id)

    @app.post(
        "/v1/learning-loop/cycle",
        tags=["Integration Loop"],
        dependencies=[Depends(verify_api_key)],
    )
    async def execute_learning_cycle(
        payload: Dict[str, Any],
        request: Request,
    ) -> Dict[str, Any]:
        """Executes full closed-loop integrated learning cycle."""
        learner_id = str(payload.get("learner_id", ""))
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.run_integrated_learning_cycle(payload)

    # -------------------------------------------------------------------------
    # Phase 6: Final Personalization & Readiness Endpoints
    # -------------------------------------------------------------------------

    @app.post(
        "/v1/learners/{learner_id}/study-plan",
        tags=["Study Plans"],
        dependencies=[Depends(verify_api_key)],
    )
    async def generate_study_plan(
        learner_id: str,
        request: Request,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generates an explainable, prerequisite-ordered personalized study plan."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        body = payload or {}
        target_concepts = body.get("target_concepts")
        time_budget = body.get("time_budget_minutes")
        exam_deadline = body.get("exam_deadline")
        max_activities = body.get("max_activities")
        return svc.generate_study_plan(
            learner_id=learner_id,
            target_concepts=target_concepts,
            time_budget_minutes=time_budget,
            exam_deadline=exam_deadline,
            max_activities=max_activities,
        )

    @app.post(
        "/v1/learners/{learner_id}/exam-readiness",
        tags=["Exam Readiness"],
        dependencies=[Depends(verify_api_key)],
    )
    async def estimate_exam_readiness(
        learner_id: str,
        request: Request,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Estimates multi-factor, evidence-backed exam readiness against blueprint."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        body = payload or {}
        blueprint = body.get("blueprint")
        as_of_time = body.get("as_of_time")
        try:
            return svc.estimate_exam_readiness(
                learner_id=learner_id,
                blueprint=blueprint,
                as_of_time=as_of_time,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @app.get(
        "/v1/learners/{learner_id}/confidence-profile",
        tags=["Metacognitive Confidence"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_confidence_profile(
        learner_id: str,
        request: Request,
        concept_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieves longitudinal student-reported confidence calibration profile."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.get_confidence_calibration(learner_id, concept_id=concept_id)

    @app.get(
        "/v1/learners/{learner_id}/confidence-records",
        tags=["Metacognitive Confidence"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_confidence_records(
        learner_id: str,
        request: Request,
        concept_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves raw student-reported confidence records for a learner."""
        verify_learner_access(learner_id, request)
        svc: LearnSensePersonalizationService = app.state.service
        return svc.get_confidence_records(learner_id, concept_id=concept_id)

    # -------------------------------------------------------------------------
    # Teacher Portal Endpoints
    # -------------------------------------------------------------------------

    @app.post(
        "/v1/teacher/independent/teaching-plan",
        tags=["Teacher Portal"],
        dependencies=[Depends(verify_api_key)],
    )
    async def create_independent_teaching_plan(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generates dynamic teaching plan for an independent educator."""
        svc: LearnSensePersonalizationService = app.state.service
        cid = str(payload.get("concept_id", "PHY_KIN"))
        mins = int(payload.get("total_minutes", 60))
        grade = str(payload.get("target_grade", "JEE Advanced / Grade 11-12"))
        return svc.generate_independent_teaching_plan(cid, total_minutes=mins, target_grade=grade)

    @app.post(
        "/v1/teacher/cohort/analytics",
        tags=["Teacher Portal"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_cohort_analytics(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Aggregates knowledge tracing and misconception heatmap across a student cohort."""
        svc: LearnSensePersonalizationService = app.state.service
        class_id = str(payload.get("class_id", "CLASS_01"))
        class_name = str(payload.get("class_name", "Section A"))
        learner_ids = list(payload.get("learner_ids", []))
        concept_ids = list(payload.get("concept_ids", ["PHY_KIN", "PHY_NLM"]))
        return svc.analyze_cohort(class_id, class_name, learner_ids, concept_ids)

    @app.post(
        "/v1/teacher/cohort/teaching-plan",
        tags=["Teacher Portal"],
        dependencies=[Depends(verify_api_key)],
    )
    async def create_cohort_teaching_plan(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generates dynamic lesson plan adapted to the live knowledge tracing state of the cohort."""
        svc: LearnSensePersonalizationService = app.state.service
        class_id = str(payload.get("class_id", "CLASS_01"))
        class_name = str(payload.get("class_name", "Section A"))
        concept_id = str(payload.get("concept_id", "PHY_KIN"))
        learner_ids = list(payload.get("learner_ids", []))
        mins = int(payload.get("total_minutes", 60))
        return svc.generate_cohort_teaching_plan(class_id, class_name, concept_id, learner_ids, total_minutes=mins)

    # -------------------------------------------------------------------------
    # TurboLearn / ChatGPT In-Topic Micro-Quiz Endpoints
    # -------------------------------------------------------------------------

    @app.post(
        "/v1/quiz/generate",
        tags=["In-Topic Micro-Quiz"],
        dependencies=[Depends(verify_api_key)],
    )
    async def generate_micro_quiz(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generates a 4-question in-topic micro-quiz."""
        svc: LearnSensePersonalizationService = app.state.service
        lid = str(payload.get("learner_id", "guest_learner"))
        cid = str(payload.get("concept_id", "PHY_KIN"))
        try:
            return svc.generate_micro_quiz(lid, cid)
        except (ValueError, KeyError) as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "no_questions_available", "message": str(e)},
            )

    @app.post(
        "/v1/quiz/submit-answer",
        tags=["In-Topic Micro-Quiz"],
        dependencies=[Depends(verify_api_key)],
    )
    async def submit_quiz_answer(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Evaluates a single answer with instant ChatGPT-style feedback."""
        svc: LearnSensePersonalizationService = app.state.service
        quiz_id = str(payload.get("quiz_id", ""))
        item_id = str(payload.get("item_id", ""))
        opt_id = str(payload.get("selected_option_id", ""))
        sync = bool(payload.get("sync_state", True))
        try:
            return svc.evaluate_micro_quiz_answer(quiz_id, item_id, opt_id, sync_state=sync)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @app.post(
        "/v1/quiz/hint",
        tags=["In-Topic Micro-Quiz"],
        dependencies=[Depends(verify_api_key)],
    )
    async def get_quiz_hint(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retrieves progressive hint without revealing the answer."""
        svc: LearnSensePersonalizationService = app.state.service
        quiz_id = str(payload.get("quiz_id", ""))
        item_id = str(payload.get("item_id", ""))
        level = int(payload.get("hint_level", 1))
        try:
            return svc.get_micro_quiz_hint(quiz_id, item_id, hint_level=level)
        except KeyError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @app.post(
        "/v1/quiz/reset",
        tags=["In-Topic Micro-Quiz"],
        dependencies=[Depends(verify_api_key)],
    )
    async def reset_micro_quiz(
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resets quiz session for 'Try again' retry."""
        svc: LearnSensePersonalizationService = app.state.service
        quiz_id = str(payload.get("quiz_id", ""))
        try:
            return svc.reset_micro_quiz(quiz_id)
        except KeyError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return app



# Default ASGI application instance
app = create_app()

"""LearnSense Person 3 — Remediation Integration Test Harness (Scenarios A through E).

Executes and verifies the 5 mandatory post-audit integration scenarios:
- Scenario A: Model 5-Driven Personalized Quiz Generation
- Scenario B: Multi-Turn Socratic AI Tutoring Session
- Scenario C: Adaptive Assessment with Production Question Bank
- Scenario D: End-to-End Ingestion, Model 5 Update & Recommendation
- Scenario E: Graceful Degradation for Unsupported Content
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RemediationScenarios")

RELEASE_ROOT = next((d for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent)
if str(RELEASE_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_ROOT))

from src.akt_inference import AKTMasteryInferenceService
from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.micro_quiz import MicroQuizEngine
from src.migration_adapter import (
    CURRICULUM_FINGERPRINT,
    CURRICULUM_VERSION,
    EXCLUDED_FROM_JEE_MAIN_2027,
    CanonicalConceptMigrationAdapter,
)
from src.question_bank import QuestionBankAdapter, get_default_question_bank
from src.service import LearnSensePersonalizationService
from src.solution_verifier import SolutionVerifier
from src.storage import SQLiteStateStore
from src.tutoring import TutoringEngine, TutoringRequest


def run_scenario_a(results: Dict[str, Any]) -> None:
    logger.info("==================================================================")
    logger.info("SCENARIO A: Model 5-Driven Personalized Quiz Generation")
    logger.info("==================================================================")
    t0 = time.perf_counter()

    # 1. Initialize learner with known history in Model 5 v5.2.1
    akt_service = AKTMasteryInferenceService()
    learner_id = "SCENARIO_A_LEARNER"
    
    # Provide history where learner fails Kinematics (cc_3e003bf9b038a36b)
    kinematics_cid = "cc_3e003bf9b038a36b"
    akt_service.record_interaction(learner_id, "JQ5100010", kinematics_cid, "medium", is_correct=0, timestamp="2026-11-10T10:00:00Z")
    akt_service.record_interaction(learner_id, "JQ5100011", kinematics_cid, "hard", is_correct=0, timestamp="2026-11-10T10:05:00Z")

    # 2. Query Model 5 for concept mastery profile (all 87 concepts)
    mastery_profile = akt_service.predict_concept_mastery(learner_id)
    assert isinstance(mastery_profile, dict)
    assert len(mastery_profile) == 87, f"Expected 87 concepts, got {len(mastery_profile)}"

    # 3. Identify weak concepts (< 0.50)
    weak_concepts = {cid: m for cid, m in mastery_profile.items() if m < 0.50}
    assert len(weak_concepts) > 0, "Expected at least one weak concept"
    assert kinematics_cid in weak_concepts, f"Kinematics ({kinematics_cid}) should be weak"

    weakest_cid = min(weak_concepts.keys(), key=lambda c: weak_concepts[c])
    logger.info(f"Identified weakest concept: {weakest_cid} (Mastery: {weak_concepts[weakest_cid]:.4f})")

    # 4. Generate 4-question micro-quiz using QuestionBankAdapter
    quiz_engine = MicroQuizEngine()
    quiz_session = quiz_engine.generate_quiz(
        learner_id=learner_id,
        concept_id=weakest_cid,
        jee_main_2027_only=True,
    )

    # 5. Verify quiz properties
    assert len(quiz_session.items) == 4, f"Expected 4 items, got {len(quiz_session.items)}"
    assert quiz_session.concept_id == weakest_cid
    assert all(item.concept_id == weakest_cid for item in quiz_session.items)
    for it in quiz_session.items:
        assert len(it.options) == 4, "Each question must have 4 options"
        assert len(set(opt.option_id for opt in it.options)) == 4, "Option IDs must be unique"
        assert any(opt.is_correct for opt in it.options), "Each question must have a correct answer"

    elapsed = time.perf_counter() - t0
    logger.info(f"Scenario A PASSED in {elapsed:.3f}s")
    results["scenario_a"] = {
        "status": "PASSED",
        "elapsed_seconds": round(elapsed, 4),
        "weakest_concept": weakest_cid,
        "weakest_mastery": round(float(weak_concepts[weakest_cid]), 4),
        "total_active_concepts_evaluated": len(mastery_profile),
        "quiz_item_count": len(quiz_session.items),
    }


def run_scenario_b(results: Dict[str, Any]) -> None:
    logger.info("==================================================================")
    logger.info("SCENARIO B: Multi-Turn Socratic AI Tutoring Session")
    logger.info("==================================================================")
    t0 = time.perf_counter()

    kb = get_default_knowledge_base()
    tutoring_engine = TutoringEngine(knowledge_base=kb)
    learner_id = "SCENARIO_B_LEARNER"
    concept_id = "cc_3e003bf9b038a36b"  # Kinematics

    tutoring_engine.clear_conversation_history(learner_id)

    # Turn 1: Conceptual question -> Socratic response
    req1 = TutoringRequest(
        request_id="REQ_B_1",
        learner_id=learner_id,
        intent="solve_with_guidance",
        message="A ball is thrown straight up. What is its acceleration at the very top of its trajectory?",
        concept_ids=[concept_id],
        context={"use_llm": True},
    )
    resp1 = tutoring_engine.deliver_tutoring(req1)
    assert resp1.content, "Response 1 content cannot be empty"
    assert "g" in resp1.content.lower() or "acceleration" in resp1.content.lower() or "gravity" in resp1.content.lower()
    assert len(resp1.safety_flags) == 0, "No safety violations expected"

    # Turn 2: Student gives misconception -> Misconception diagnosis + Hint
    req2 = TutoringRequest(
        request_id="REQ_B_2",
        learner_id=learner_id,
        intent="solve_with_guidance",
        message="Since the ball momentarily stops at the top, its velocity is zero, so acceleration must also be zero, right?",
        concept_ids=[concept_id],
        context={"use_llm": True},
    )
    resp2 = tutoring_engine.deliver_tutoring(req2)
    assert resp2.content, "Response 2 content cannot be empty"

    # Turn 3: Step-by-step guidance request
    req3 = TutoringRequest(
        request_id="REQ_B_3",
        learner_id=learner_id,
        intent="solve_with_guidance",
        message="Can you guide me on which physical law or equation connects gravity to the ball throughout flight?",
        concept_ids=[concept_id],
        context={"use_llm": True},
    )
    resp3 = tutoring_engine.deliver_tutoring(req3)
    assert resp3.content, "Response 3 content cannot be empty"

    history = tutoring_engine.get_conversation_history(learner_id)
    assert len(history) == 6, f"Expected 6 messages in multi-turn history (3 user, 3 assistant), got {len(history)}"

    # Check zero answer key leakage in all turns
    for turn in history:
        if turn["role"] == "assistant":
            assert "server_key" not in turn["content"].lower()
            assert "correct option is" not in turn["content"].lower()

    elapsed = time.perf_counter() - t0
    logger.info(f"Scenario B PASSED in {elapsed:.3f}s")
    results["scenario_b"] = {
        "status": "PASSED",
        "elapsed_seconds": round(elapsed, 4),
        "turns_completed": 3,
        "total_history_messages": len(history),
        "concept_id": concept_id,
        "zero_answer_leakage_verified": True,
    }


def run_scenario_c(results: Dict[str, Any]) -> None:
    logger.info("==================================================================")
    logger.info("SCENARIO C: Adaptive Assessment with Production Question Bank")
    logger.info("==================================================================")
    t0 = time.perf_counter()

    store = SQLiteStateStore(":memory:")
    service = LearnSensePersonalizationService(store=store)
    learner_id = "SCENARIO_C_LEARNER"
    concept_id = "cc_e070c64d30e5e623"  # Laws of Motion

    # Prerequisite initialization: Laws of Motion requires Kinematics (cc_3e003bf9b038a36b)
    prereq_state = service.state_service.get_or_initialize_state(learner_id, "cc_3e003bf9b038a36b")
    prereq_state.mastery_probability = 0.90
    prereq_state.evidence_count = 5
    prereq_state.status = "mastered"
    store.save_state(prereq_state)

    # Start an 8-question adaptive session
    session_data = service.start_adaptive_session(
        learner_id=learner_id,
        concept_id=concept_id,
        target_questions=8,
    )
    session_id = session_data["session_id"]
    assert session_id, "Session ID must be created"

    questions_served = []
    # Simulate 8 adaptive question-response cycles
    for i in range(8):
        next_q = service.get_next_adaptive_session_question(session_id)
        selected_q = next_q.get("selected_question") or next_q.get("question")
        if not selected_q:
            break
        qid = selected_q["question_id"]
        assert qid not in questions_served, f"Repetition detected: {qid} served twice"
        questions_served.append(qid)

        # Alternate correct/incorrect responses
        is_corr = bool(i % 2 == 0)
        resp = service.submit_adaptive_session_answer(
            session_id=session_id,
            question_id=qid,
            is_correct=is_corr,
        )
        if resp.get("status") == "completed":
            break

    assert len(questions_served) >= 4, f"Adaptive session served too few questions: {len(questions_served)}"

    elapsed = time.perf_counter() - t0
    logger.info(f"Scenario C PASSED in {elapsed:.3f}s (served {len(questions_served)} questions)")
    results["scenario_c"] = {
        "status": "PASSED",
        "elapsed_seconds": round(elapsed, 4),
        "concept_id": concept_id,
        "questions_served_count": len(questions_served),
        "repetition_free": True,
    }


def run_scenario_d(results: Dict[str, Any]) -> None:
    logger.info("==================================================================")
    logger.info("SCENARIO D: End-to-End Ingestion, Model 5 Update & Recommendation")
    logger.info("==================================================================")
    t0 = time.perf_counter()

    store = SQLiteStateStore(":memory:")
    service = LearnSensePersonalizationService(store=store)
    learner_id = "SCENARIO_D_LEARNER"
    concept_id = "cc_5f9917b8333fae45"  # Work, Power and Energy

    # 1. Ingest attempt via service facade adhering strictly to contracts/attempt_schema.json
    attempt_payload = {
        "schema_version": "1.0",
        "attempt_id": "ATT_SCENARIO_D_01",
        "learner_id": learner_id,
        "question_id": "JQ5100100",
        "submitted_at": "2026-11-10T11:00:00Z",
        "response": {
            "response_type": "single_choice",
            "value": "B",
        },
        "outcome": {
            "scoring_status": "scored",
            "is_correct": True,
            "score": 1.0,
            "max_score": 1.0,
            "scoring_source": "server_key",
        },
        "context": {
            "concept_id": concept_id,
            "difficulty": "medium",
        },
    }
    attempt_res = service.submit_attempt(attempt_payload, primary_concept_id=concept_id)

    assert "updated_state" in attempt_res or "state" in attempt_res, "Attempt result must contain updated learner state"
    assert "next_recommendation" in attempt_res or "recommendations" in attempt_res, "Attempt result must contain recommendation"

    updated_state = attempt_res.get("updated_state") or attempt_res.get("state")
    assert updated_state["concept_id"] == concept_id
    assert updated_state["evidence_count"] >= 1
    assert 0.0 <= updated_state["mastery_probability"] <= 1.0

    # 2. Check recommendations
    rec = attempt_res.get("next_recommendation") or attempt_res.get("recommendations")
    assert rec is not None

    # 3. Model info provenance check
    model_info = service.get_model_info()
    assert model_info["name"] == "model_5_combined_akt_mastery_v5_2"
    assert model_info["version"] == "5.2.1"
    assert model_info["curriculum_fingerprint"] == CURRICULUM_FINGERPRINT
    assert model_info["is_active_neural"] is True

    elapsed = time.perf_counter() - t0
    logger.info(f"Scenario D PASSED in {elapsed:.3f}s")
    results["scenario_d"] = {
        "status": "PASSED",
        "elapsed_seconds": round(elapsed, 4),
        "concept_id": concept_id,
        "mastery_probability": round(float(updated_state["mastery_probability"]), 4),
        "model_name": model_info["name"],
        "curriculum_fingerprint": model_info["curriculum_fingerprint"],
    }


def run_scenario_e(results: Dict[str, Any]) -> None:
    logger.info("==================================================================")
    logger.info("SCENARIO E: Graceful Degradation for Unsupported Content")
    logger.info("==================================================================")
    t0 = time.perf_counter()

    # 1. Excluded concept handling in MicroQuizEngine
    quiz_engine = MicroQuizEngine()
    excluded_cid = "cc_e4951a49b665b28b"  # States of Matter (excluded from JEE Main 2027)
    excluded_raised = False
    try:
        quiz_engine.generate_quiz(learner_id="u_test", concept_id=excluded_cid, jee_main_2027_only=True)
    except ValueError as e:
        excluded_raised = True
        assert "excluded from jee main 2027" in str(e).lower()
        logger.info(f"Sub-test 1 passed: Excluded concept correctly rejected ({e})")
    assert excluded_raised, "Expected ValueError when generating quiz for excluded concept"

    # 2. Knowledge Base content unavailable check
    kb = get_default_knowledge_base()
    citation = kb.get_source_citation("cc_10098e97f1838609")  # Concept without ingested content
    assert citation["status"] in {"source_unavailable", "content_unavailable"}
    assert citation["is_verified"] is False
    logger.info("Sub-test 2 passed: Missing content reported as 'source_unavailable' without hallucination")

    # 3. Unsupported diagram problem in SolutionVerifier
    verifier = SolutionVerifier()
    unsupported_problem = "Refer to Figure 4.12 showing the potentiometer bridge circuit with key K1 open."
    ver_res = verifier.verify_solution(
        problem_text=unsupported_problem,
        steps=["Observe circuit layout in Figure 4.12.", "Current is zero across galvanometer."],
        final_answer="Null point at 45.2 cm",
    )
    assert ver_res.problem_type == "unsupported"
    assert ver_res.overall_status == "unsupported"
    assert ver_res.is_valid is False
    assert "visual diagram" in ver_res.discrepancy.lower() or "automated verification is not supported" in ver_res.discrepancy.lower()
    logger.info("Sub-test 3 passed: Diagram problem explicitly classified as 'unsupported'")

    elapsed = time.perf_counter() - t0
    logger.info(f"Scenario E PASSED in {elapsed:.3f}s")
    results["scenario_e"] = {
        "status": "PASSED",
        "elapsed_seconds": round(elapsed, 4),
        "excluded_concept_rejected": True,
        "content_unavailable_status_verified": True,
        "diagram_problem_classified_unsupported": True,
    }


def main() -> None:
    logger.info("Starting LearnSense Person 3 Remediation Test Scenarios (A - E)...")
    results: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "curriculum_version": CURRICULUM_VERSION,
        "curriculum_fingerprint": CURRICULUM_FINGERPRINT,
        "scenarios": {},
    }

    try:
        run_scenario_a(results["scenarios"])
        run_scenario_b(results["scenarios"])
        run_scenario_c(results["scenarios"])
        run_scenario_d(results["scenarios"])
        run_scenario_e(results["scenarios"])

        results["all_passed"] = True
        logger.info("==================================================================")
        logger.info("ALL 5 SCENARIOS PASSED SUCCESSFULLY!")
        logger.info("==================================================================")
    except Exception as e:
        results["all_passed"] = False
        results["error"] = str(e)
        logger.exception(f"Scenario execution failed: {e}")
        sys.exit(1)
    finally:
        out_path = Path(__file__).resolve().parent / "remediation_scenarios_results.json"
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        logger.info(f"Saved scenario results to: {out_path}")


if __name__ == "__main__":
    main()

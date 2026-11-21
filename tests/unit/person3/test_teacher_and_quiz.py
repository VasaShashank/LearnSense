"""LearnSense Person 3 — Unit and Integration Tests for Teacher Portal and Micro-Quiz Engine.

Tests:
1. IndependentTeacherPlanner generates structured, time-budgeted lesson plans with prerequisite activation, exposition, worked examples, and misconception refutation.
2. CohortTeacherManager aggregates Knowledge Tracing states, generates misconception heatmaps, and tailors lesson plans dynamically to cohort weaknesses.
3. MicroQuizEngine generates exactly 4-question formative checks with distinct distractors.
4. MicroQuizEngine provides instant per-option feedback ("Correct! ...", "Not quite. ..."), handles hints, and scores (e.g. 3/4).
5. API endpoints for teacher portal and micro-quiz pass successfully.
"""

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.micro_quiz import MicroQuizEngine
from src.service import LearnSensePersonalizationService
from src.teacher import CohortTeacherManager, IndependentTeacherPlanner


import os
from src.storage import SQLiteStateStore

@pytest.fixture
def service():
    store = SQLiteStateStore(":memory:")
    return LearnSensePersonalizationService(store=store)


@pytest.fixture
def client(service):
    os.environ["LEARNSENSE_API_KEY"] = "learnsense_dev_secret_key_2026"
    os.environ["LEARNSENSE_ALLOW_TEST_KEY"] = "true"
    app = create_app(service=service)
    return TestClient(app)


DEV_AUTH_HEADERS = {"Authorization": "Bearer learnsense_dev_secret_key_2026"}


# -----------------------------------------------------------------------------
# 1. Independent Teacher Tests
# -----------------------------------------------------------------------------

def test_independent_teacher_plan_generation(service):
    planner = service.independent_planner
    plan = planner.generate_plan(concept_id="PHY_KIN", total_minutes=60)

    assert plan.persona == "independent_teacher"
    assert plan.concept_id == "PHY_KIN"
    assert plan.total_duration_minutes == 60
    assert len(plan.segments) == 5

    # Check segment types
    segment_types = [s.segment_type for s in plan.segments]
    assert "prerequisite_bridge" in segment_types
    assert "concept_exposition" in segment_types
    assert "worked_example" in segment_types
    assert "misconception_refutation" in segment_types
    assert "formative_check" in segment_types

    # Ensure misconception refutations contain authentic distractor clarifications
    refut_seg = next(s for s in plan.segments if s.segment_type == "misconception_refutation")
    assert len(refut_seg.common_pitfalls_to_address) > 0
    assert "trap" in refut_seg.common_pitfalls_to_address[0]
    assert "clarification" in refut_seg.common_pitfalls_to_address[0]


# -----------------------------------------------------------------------------
# 2. B2B Cohort Teacher Tests
# -----------------------------------------------------------------------------

def test_cohort_teacher_analytics_and_plan(service):
    cohort_mgr = service.cohort_teacher_manager
    learner_ids = [f"student_{i}" for i in range(1, 11)]

    # Seed mock states
    for i, lid in enumerate(learner_ids):
        p_l = 0.30 if i < 3 else (0.60 if i < 7 else 0.90)
        service.state_service.process_attempt(lid, "PHY_KIN", attempt_id=f"INIT_{lid}", is_correct=(p_l > 0.5))

    report = cohort_mgr.analyze_cohort(
        class_id="SEC_A",
        class_name="Grade 11 Mechanics",
        learner_ids=learner_ids,
        concept_ids=["PHY_KIN"],
        state_service=service.state_service,
        misconception_tracker=service.misconception_tracker,
    )

    assert report.class_id == "SEC_A"
    assert report.student_count == 10
    analytics = report.concept_analytics["PHY_KIN"]
    assert analytics.student_count == 10
    assert analytics.at_risk_count >= 1

    # Generate dynamic cohort-adapted lesson plan
    adapted_plan = cohort_mgr.generate_cohort_teaching_plan(
        class_id="SEC_A",
        class_name="Grade 11 Mechanics",
        concept_id="PHY_KIN",
        learner_ids=learner_ids,
        state_service=service.state_service,
        misconception_tracker=service.misconception_tracker,
    )

    assert adapted_plan.persona == "b2b_cohort_teacher"
    assert adapted_plan.cohort_summary["student_count"] == 10
    assert "guided_remediation_group" in adapted_plan.differentiation_strategies
    assert "accelerated_extension_group" in adapted_plan.differentiation_strategies


# -----------------------------------------------------------------------------
# 3. Micro-Quiz Engine Tests (TurboLearn / ChatGPT Style)
# -----------------------------------------------------------------------------

def test_micro_quiz_generation_and_evaluation():
    engine = MicroQuizEngine()
    session = engine.generate_quiz(learner_id="test_user", concept_id="PHY_KIN")

    assert len(session.items) == 4
    assert session.is_completed is False

    # Check safe student projection
    safe_dict = session.to_dict()
    assert len(safe_dict["items"]) == 4
    for it in safe_dict["items"]:
        assert "options" in it
        assert all("is_correct" not in opt for opt in it["options"])

    # Submit Q1 correctly (Option B for PHY_KIN Q1 is correct)
    q1 = session.items[0]
    res1 = engine.evaluate_single_answer(session.quiz_id, q1.item_id, "B")
    assert res1.is_correct is True
    assert "Correct!" in res1.feedback_text

    # Submit Q2 incorrectly (Option A is incorrect)
    q2 = session.items[1]
    res2 = engine.evaluate_single_answer(session.quiz_id, q2.item_id, "A")
    assert res2.is_correct is False
    assert "Not quite." in res2.feedback_text
    assert "gravity" in res2.minute_difference_explanation.lower()

    # Hints
    hint1 = engine.get_hint(session.quiz_id, q1.item_id, hint_level=1)
    assert hint1["hint_level"] == 1
    assert len(hint1["hint_text"]) > 0

    # Answer remaining questions to complete quiz
    engine.evaluate_single_answer(session.quiz_id, session.items[2].item_id, "B")  # Correct
    engine.evaluate_single_answer(session.quiz_id, session.items[3].item_id, "C")  # Correct

    updated_sess = engine.get_session(session.quiz_id)
    assert updated_sess.is_completed is True
    assert updated_sess.total_score == 3
    assert updated_sess.score_display == "3/4"

    # Reset (Try again)
    reset_sess = engine.reset_quiz(session.quiz_id)
    assert reset_sess.is_completed is False
    assert reset_sess.total_score == 0
    assert len(reset_sess.submitted_answers) == 0


# -----------------------------------------------------------------------------
# 4. API Endpoint Integration Tests
# -----------------------------------------------------------------------------

def test_api_teacher_and_quiz_endpoints(client):
    # Test Independent Teacher Plan API
    resp_ind = client.post(
        "/v1/teacher/independent/teaching-plan",
        json={"concept_id": "PHY_KIN", "total_minutes": 45},
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_ind.status_code == 200
    plan_data = resp_ind.json()
    assert plan_data["concept_id"] == "PHY_KIN"
    assert len(plan_data["segments"]) == 5

    # Test Cohort Analytics API
    resp_coh = client.post(
        "/v1/teacher/cohort/analytics",
        json={
            "class_id": "CLASS_TEST",
            "class_name": "Physics Batch 1",
            "learner_ids": ["stu_1", "stu_2"],
            "concept_ids": ["PHY_KIN"],
        },
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_coh.status_code == 200
    coh_data = resp_coh.json()
    assert coh_data["class_id"] == "CLASS_TEST"

    # Test Micro Quiz Generate API
    resp_quiz = client.post(
        "/v1/quiz/generate",
        json={"learner_id": "stu_1", "concept_id": "PHY_KIN"},
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_quiz.status_code == 200
    quiz_data = resp_quiz.json()
    quiz_id = quiz_data["quiz_id"]
    item_id = quiz_data["items"][0]["item_id"]

    # Test Micro Quiz Submit Answer API
    resp_ans = client.post(
        "/v1/quiz/submit-answer",
        json={"quiz_id": quiz_id, "item_id": item_id, "selected_option_id": "B"},
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_ans.status_code == 200
    ans_data = resp_ans.json()
    assert ans_data["is_correct"] is True
    assert "Correct!" in ans_data["feedback_text"]

    # Test Micro Quiz Hint API
    resp_hint = client.post(
        "/v1/quiz/hint",
        json={"quiz_id": quiz_id, "item_id": item_id, "hint_level": 1},
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_hint.status_code == 200
    assert "hint_text" in resp_hint.json()

    # Test 8-Question Adaptive Assessment Session API
    resp_cat_start = client.post(
        "/v1/assessments/adaptive-session/start",
        json={"learner_id": "stu_1", "concept_id": "PHY_KIN", "target_questions": 8},
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_cat_start.status_code == 200
    cat_session = resp_cat_start.json()
    cat_sess_id = cat_session["session_id"]
    assert cat_session["target_questions"] == 8

    # Fetch next question
    resp_cat_q = client.get(
        f"/v1/assessments/adaptive-session/{cat_sess_id}/next-question",
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_cat_q.status_code == 200
    cat_q_data = resp_cat_q.json()
    assert cat_q_data["question_number"] == 1
    assert cat_q_data["target_questions"] == 8
    cat_qid = cat_q_data["selected_question"]["question_id"]

    # Submit answer
    resp_cat_ans = client.post(
        f"/v1/assessments/adaptive-session/{cat_sess_id}/submit-answer",
        json={"question_id": cat_qid, "is_correct": True},
        headers=DEV_AUTH_HEADERS,
    )
    assert resp_cat_ans.status_code == 200
    updated_cat = resp_cat_ans.json()
    assert updated_cat["questions_administered_count"] == 1
    assert updated_cat["is_completed"] is False


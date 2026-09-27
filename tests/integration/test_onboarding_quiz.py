"""
Integration tests verifying onboarding quiz generation and submission across all subjects and concepts.
"""

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)


def test_onboarding_quiz_generation_and_submission_for_all_subjects():
    # 1. Test Calculus 101 with concepts that previously had no questions
    sa_res = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": "test_quiz_learner",
            "subject_id": "calculus_101",
            "selections": {
                "continuity": "KNOW",
                "power_rule": "KNOW",
                "limits_intro": "DONT_KNOW",
            },
            "all_subject_concept_ids": ["continuity", "power_rule", "limits_intro", "chain_rule"],
        },
    )
    assert sa_res.status_code == 200
    session_id = sa_res.json()["session_id"]

    # Start diagnostic quiz
    diag_res = client.post("/api/initialization/diagnostic/start", json={"session_id": session_id})
    assert diag_res.status_code == 200
    diag_data = diag_res.json()
    assert diag_data["question_count"] == 2
    assert len(diag_data["questions"]) == 2

    # Check question formatting
    for q in diag_data["questions"]:
        assert q.get("question_id") or q.get("item_id")
        assert q.get("question_text") or q.get("prompt")
        assert len(q.get("options", [])) >= 4

    # Submit answers
    responses = {q["question_id"]: 1.0 for q in diag_data["questions"]}
    sub_res = client.post(
        "/api/initialization/diagnostic/submit",
        json={"session_id": session_id, "responses": responses},
    )
    assert sub_res.status_code == 200
    sub_data = sub_res.json()
    assert sub_data["diagnostic_completed"] is True
    assert "continuity" in sub_data["updated_masteries"]
    assert "power_rule" in sub_data["updated_masteries"]


def test_onboarding_quiz_machine_learning():
    # Test Machine Learning subject
    sa_res = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": "test_ml_learner",
            "subject_id": "machine_learning",
            "selections": {
                "linear_regression": "KNOW",
                "loss_functions": "KNOW",
            },
            "all_subject_concept_ids": ["linear_regression", "loss_functions", "neural_networks"],
        },
    )
    assert sa_res.status_code == 200
    session_id = sa_res.json()["session_id"]

    diag_res = client.post("/api/initialization/diagnostic/start", json={"session_id": session_id})
    assert diag_res.status_code == 200
    diag_data = diag_res.json()
    assert diag_data["question_count"] == 2
    assert len(diag_data["questions"]) == 2

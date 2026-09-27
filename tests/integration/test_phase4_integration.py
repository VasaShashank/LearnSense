"""
Integration tests for Phase 4 API and adaptive learning loop.
"""

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)


def test_full_phase4_adaptive_loop_flow():
    # 1. Concept Self-Assessment
    sa_payload = {
        "learner_id": "learner_test_1",
        "subject_id": "subj_algebra",
        "selections": {
            "c_var": "KNOW",
            "c_eq": "DONT_KNOW",
        },
        "all_subject_concept_ids": ["c_var", "c_eq", "c_quad"]
    }
    resp = client.post("/phase4/initialization/self-assessment", json=sa_payload)
    assert resp.status_code == 200
    session_data = resp.json()
    assert session_data["know_concept_ids"] == ["c_var"]
    assert session_data["dont_know_concept_ids"] == ["c_eq"]
    assert session_data["unanswered_concept_ids"] == ["c_quad"]
    session_id = session_data["session_id"]

    # 2. Start Diagnostic for KNOW concepts
    resp_diag_start = client.post("/phase4/initialization/diagnostic/start", json={"session_id": session_id})
    assert resp_diag_start.status_code == 200
    diag_data = resp_diag_start.json()
    assert diag_data["know_concepts"] == ["c_var"]

    # 3. Submit Diagnostic Response
    resp_diag_sub = client.post(
        "/phase4/initialization/diagnostic/submit",
        json={"session_id": session_id, "responses": {}}
    )
    assert resp_diag_sub.status_code == 200

    # 4. Get Knowledge Gaps
    resp_gaps = client.get(
        "/phase4/learners/learner_test_1/gaps?subject_id=subj_algebra&concept_ids=c_var,c_eq,c_quad"
    )
    assert resp_gaps.status_code == 200
    gaps = resp_gaps.json()
    assert len(gaps) > 0

    # 5. Get Personalized Learning Path
    resp_path = client.get(
        "/phase4/learners/learner_test_1/path?subject_id=subj_algebra&concept_ids=c_var,c_eq,c_quad"
    )
    assert resp_path.status_code == 200
    path = resp_path.json()
    assert len(path["nodes"]) > 0

    # 6. Get Next Target
    resp_target = client.get(
        "/phase4/learners/learner_test_1/next-target?subject_id=subj_algebra&concept_ids=c_var,c_eq,c_quad"
    )
    assert resp_target.status_code == 200

    # 7. Submit Activity Response & Re-plan
    act_payload = {
        "learner_id": "learner_test_1",
        "subject_id": "subj_algebra",
        "concept_ids": ["c_eq"],
        "correctness": 1.0,
        "all_subject_concept_ids": ["c_var", "c_eq", "c_quad"]
    }
    resp_act = client.post("/phase4/learners/activity-response", json=act_payload)
    assert resp_act.status_code == 200
    act_data = resp_act.json()
    assert "c_eq" in act_data["updated_masteries"]

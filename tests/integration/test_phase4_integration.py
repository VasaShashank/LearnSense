"""
Integration tests for Phase 4 API and adaptive learning loop.

Uses the real ingested-calculus fixture so the question bank is grounded in actual
material. Tests verify the complete adaptive loop:
self-assessment → diagnostic → gaps → path → next target → activity response.
"""

import pytest
from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)


def test_full_phase4_adaptive_loop_flow(ingested_calculus):
    """
    Full Phase 4 flow via the canonical /api routes:
    self-assessment → diagnostic start → diagnostic submit →
    gaps → path → next target → activity response.
    """
    subject_id = ingested_calculus.document_id
    all_concept_ids = ingested_calculus.concept_ids
    know_ids = all_concept_ids[:1]    # mark one concept as KNOW
    dont_ids = all_concept_ids[1:2]   # mark one as DONT_KNOW

    selections = {cid: "KNOW" for cid in know_ids}
    selections.update({cid: "DONT_KNOW" for cid in dont_ids})

    learner_id = "learner_phase4_test_1"

    # 1. Concept Self-Assessment
    resp = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": learner_id,
            "subject_id": subject_id,
            "selections": selections,
            "all_subject_concept_ids": all_concept_ids,
        },
    )
    assert resp.status_code == 200, resp.text
    session_data = resp.json()
    assert set(session_data["know_concept_ids"]) == set(know_ids)
    assert set(session_data["dont_know_concept_ids"]) == set(dont_ids)
    session_id = session_data["session_id"]

    # 2. Start Diagnostic for KNOW concepts
    resp_diag_start = client.post(
        "/api/initialization/diagnostic/start", json={"session_id": session_id}
    )
    assert resp_diag_start.status_code == 200, resp_diag_start.text
    diag_data = resp_diag_start.json()
    assert diag_data["know_concepts"] == know_ids

    # P0 security: correct_answer must NOT appear in the question response
    for q in diag_data["questions"]:
        assert "correct_answer" not in q, (
            "P0 violation: correct_answer exposed to client in diagnostic question"
        )

    # 3. Submit Diagnostic Response
    responses = {q["question_id"]: 1.0 for q in diag_data["questions"]}
    resp_diag_sub = client.post(
        "/api/initialization/diagnostic/submit",
        json={"session_id": session_id, "responses": responses},
    )
    assert resp_diag_sub.status_code == 200, resp_diag_sub.text
    diag_sub_data = resp_diag_sub.json()
    assert diag_sub_data["diagnostic_completed"] is True

    # 4. Get Knowledge Gaps & Path
    gaps_res = client.get(
        f"/api/learners/{learner_id}/path-and-gaps?subject_id={subject_id}"
    )
    assert gaps_res.status_code == 200, gaps_res.text
    gaps_data = gaps_res.json()
    assert len(gaps_data["learning_path"]["nodes"]) > 0
    assert gaps_data["next_target"] is not None

    # 5. Submit Activity Response & Re-plan
    act_payload = {
        "learner_id": learner_id,
        "subject_id": subject_id,
        "concept_ids": dont_ids,
        "correctness": 1.0,
        "all_subject_concept_ids": all_concept_ids,
    }
    resp_act = client.post("/api/learners/activity-response", json=act_payload)
    assert resp_act.status_code == 200, resp_act.text
    act_data = resp_act.json()
    for cid in dont_ids:
        assert cid in act_data["updated_masteries"]
    assert act_data["updated_masteries"][dont_ids[0]] > 0.15

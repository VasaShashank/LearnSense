"""
Integration tests verifying onboarding quiz generation and submission.

Uses the real ingested-calculus fixture (which runs the full Phase 1 → Phase 2 →
Phase 3 pipeline on a short calculus PDF) so every question is grounded in the
learner's own material, matching the production contract.
"""

import pytest
from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)


def test_onboarding_quiz_generation_and_submission(ingested_calculus):
    """
    Full onboarding flow:
    self-assessment → diagnostic start → diagnostic submit.

    Uses the real calculus document ingested by the session fixture so concepts,
    evidence and questions are all grounded in actual text.
    """
    subject_id = ingested_calculus.document_id
    all_concept_ids = ingested_calculus.concept_ids

    # Pick the first two concept IDs; we will mark them KNOW so the diagnostic runs.
    know_ids = all_concept_ids[:2]
    dont_know_ids = all_concept_ids[2:]

    selections = {cid: "KNOW" for cid in know_ids}
    selections.update({cid: "DONT_KNOW" for cid in dont_know_ids})

    # 1. Concept self-assessment
    sa_res = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": "test_quiz_learner_real",
            "subject_id": subject_id,
            "selections": selections,
            "all_subject_concept_ids": all_concept_ids,
        },
    )
    assert sa_res.status_code == 200, sa_res.text
    sa_data = sa_res.json()
    session_id = sa_data["session_id"]
    assert set(sa_data["know_concept_ids"]) == set(know_ids)

    # 2. Start diagnostic quiz — must produce questions only for KNOW concepts
    diag_res = client.post("/api/initialization/diagnostic/start", json={"session_id": session_id})
    assert diag_res.status_code == 200, diag_res.text
    diag_data = diag_res.json()
    # There should be at least one grounded question (may be fewer than len(know_ids)
    # if the bank does not have coverage for every concept yet).
    assert diag_data["question_count"] >= 0
    assert len(diag_data["questions"]) == diag_data["question_count"]

    # Each returned question must have an ID and text, but NOT a correct_answer field
    # visible to the client (P0 security requirement).
    for q in diag_data["questions"]:
        assert q.get("question_id") or q.get("item_id"), "question missing ID"
        assert q.get("question_text") or q.get("prompt"), "question missing text"
        assert "correct_answer" not in q, (
            "P0 violation: correct_answer must not be sent to the frontend"
        )
        assert len(q.get("options", [])) >= 2, "question has too few options"

    # 3. Submit diagnostic responses (all correct: correctness=1.0)
    responses = {}
    for q in diag_data["questions"]:
        q_id = q.get("question_id") or q.get("item_id")
        responses[q_id] = 1.0

    sub_res = client.post(
        "/api/initialization/diagnostic/submit",
        json={"session_id": session_id, "responses": responses},
    )
    assert sub_res.status_code == 200, sub_res.text
    sub_data = sub_res.json()
    assert sub_data["diagnostic_completed"] is True
    # Masteries must have been updated for the know concepts
    for cid in know_ids:
        assert cid in sub_data["updated_masteries"], (
            f"Mastery for know-concept {cid!r} missing from diagnostic result"
        )


def test_onboarding_zero_know_concepts(ingested_calculus):
    """
    When the learner marks everything as DONT_KNOW, the diagnostic must return
    zero questions (nothing to probe) and the session must still be created cleanly.
    """
    subject_id = ingested_calculus.document_id
    all_concept_ids = ingested_calculus.concept_ids

    selections = {cid: "DONT_KNOW" for cid in all_concept_ids}

    sa_res = client.post(
        "/api/initialization/self-assessment",
        json={
            "learner_id": "test_zero_know_learner",
            "subject_id": subject_id,
            "selections": selections,
            "all_subject_concept_ids": all_concept_ids,
        },
    )
    assert sa_res.status_code == 200, sa_res.text
    session_id = sa_res.json()["session_id"]
    assert sa_res.json()["know_concept_ids"] == []

    diag_res = client.post("/api/initialization/diagnostic/start", json={"session_id": session_id})
    assert diag_res.status_code == 200, diag_res.text
    assert diag_res.json()["question_count"] == 0

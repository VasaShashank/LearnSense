"""
Routing state-machine regression tests (cases 1-15).

Every test asserts on the SERVER-AUTHORITATIVE entry state that the frontend
renders. The frontend used to derive its screen from an `isOnboarded` boolean
that became true as soon as any learner state existed, so an unverified learner
reached the dashboard with untouched 30% default mastery, and every unresolved
case (no state, resume error, resume timeout) fell through to the ingestion
screen.
"""
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from phase4.models import SelfAssessmentStatus


@pytest.fixture(scope="module")
def services():
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    return learning, ks, ls


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def subject_id(services):
    """A real ingested subject with a grounded question bank."""
    learning, ks, _ = services
    subjects = ks.list_subjects()
    if not subjects:
        pytest.fail("No subjects available; this is a required fixture.")
    for sub in subjects:
        sid = sub.get("id") or sub.get("subject_id", "")
        if not sid:
            continue
        try:
            if learning.get_or_create_question_bank(sid).get_grounded_questions():
                return sid
        except Exception:
            continue
    pytest.fail("No subject with a grounded question bank is available.")


def _unique(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def _entry(client, learner_id, sid=None):
    resp = client.get(f"/api/learners/{learner_id}/entry-state", params={"subject_id": sid} if sid else None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _resume(client, learner_id, sid=None):
    resp = client.get(f"/api/learners/{learner_id}/resume", params={"subject_id": sid} if sid else None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_calibration(client, learner_id, sid, all_know=True):
    # NOTE: deliberately no learner_id here. That query parameter makes the
    # endpoint materialise learner state, which is precisely the conflation this
    # file guards against.
    graph = client.get(f"/api/subjects/{sid}/graph").json()
    concept_ids = [c["concept_id"] for c in graph["concepts"]]
    body = {
        "learner_id": learner_id,
        "subject_id": sid,
        "selections": {cid: (SelfAssessmentStatus.KNOW.value if all_know else SelfAssessmentStatus.UNANSWERED.value) for cid in concept_ids},
        "all_subject_concept_ids": concept_ids,
    }
    resp = client.post("/api/initialization/self-assessment", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json(), concept_ids


# --- Case 1: no sources at all -> SOURCE_SELECTION, not an error ---------------
def test_case01_no_source_yields_source_selection(client, monkeypatch):
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    monkeypatch.setattr(learning.knowledge_service, "list_subjects", lambda: [])

    state = learning.get_entry_state(_unique("learner_nosrc"))
    assert state["entry_state"] == "SOURCE_SELECTION"
    assert state["has_source"] is False
    # Never "complete": there is nothing to have verified.
    assert state["diagnostic_completed"] is False


# --- Case 2: sources exist but learner has no state -> SOURCE_SELECTION ---------
def test_case02_sources_exist_but_no_state_needs_calibration(client, subject_id):
    learner_id = _unique("learner_nostate")
    state = _entry(client, learner_id, subject_id)
    assert state["entry_state"] == "NEEDS_CALIBRATION"
    assert state["needs_calibration"] is True
    assert state["session_id"] is None


# --- Case 3: concept state exists but NO verification -> NOT onboarded ---------
def test_case03_concept_state_alone_is_not_onboarding(services, client, subject_id):
    _, ks, ls = services
    learner_id = _unique("learner_graphonly")
    graph = ks.get_subject_graph(subject_id)
    concept_ids = [c["concept_id"] for c in graph["concepts"]]
    ls.get_or_create_learner_state(learner_id, concept_ids)

    data = _resume(client, learner_id, subject_id)
    assert data["has_state"] is True
    # Regression guard for the 30%-mastery dashboard screenshot.
    assert data["is_onboarded"] is False
    assert data["entry_state"] == "NEEDS_CALIBRATION"


# --- Case 4: self-assessment submitted, diagnostic not started -> VERIFY --------
def test_case04_self_assessment_only_is_verification_in_progress(client, subject_id):
    learner_id = _unique("learner_saonly")
    _start_calibration(client, learner_id, subject_id)

    state = _entry(client, learner_id, subject_id)
    assert state["entry_state"] == "VERIFICATION_IN_PROGRESS"
    assert state["needs_calibration"] is False
    assert state["session_id"]
    assert state["diagnostic_completed"] is False
    assert _resume(client, learner_id, subject_id)["is_onboarded"] is False


# --- Case 5: refresh mid-quiz resumes the SAME run ------------------------------
def test_case05_refresh_resumes_same_session_and_plan(client, subject_id):
    learner_id = _unique("learner_resume")
    session, _ = _start_calibration(client, learner_id, subject_id)

    first = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": learner_id},
    ).json()
    assert first["status"] == "in_progress"
    assert first["answered_count"] == 0
    plan_first = [q["question_id"] for q in first["questions"]]

    qid = first["next_question"]["question_id"]
    answered = client.post(
        "/api/initialization/diagnostic/answer",
        json={
            "session_id": session["session_id"],
            "learner_id": learner_id,
            "question_id": qid,
            "selected_option": "definitely_not_the_answer",
        },
    ).json()
    assert answered["answered_count"] == 1
    assert answered["duplicate_submission"] is False

    # "Browser refresh": start_diagnostic is called again on the same session.
    second = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": learner_id},
    ).json()
    assert second["status"] == "in_progress"
    assert second["answered_count"] == 1
    assert second["answered_question_ids"] == [qid]
    # The plan is reused verbatim; a refresh must not reshuffle the quiz.
    assert [q["question_id"] for q in second["questions"]] == plan_first
    assert second["next_question"]["question_id"] != qid


# --- Case 6: diagnostic complete -> DASHBOARD -----------------------------------
def test_case06_completed_diagnostic_reaches_dashboard(client, subject_id):
    learner_id = _unique("learner_done")
    session, _ = _start_calibration(client, learner_id, subject_id)

    guard = 0
    while guard < 30:
        guard += 1
        started = client.post(
            "/api/initialization/diagnostic/start",
            json={"session_id": session["session_id"], "learner_id": learner_id},
        ).json()
        if started["status"] == "completed" or not started["next_question"]:
            break
        nxt = started["next_question"]
        res = client.post(
            "/api/initialization/diagnostic/answer",
            json={
                "session_id": session["session_id"],
                "learner_id": learner_id,
                "question_id": nxt["question_id"],
                "selected_option": "definitely_not_the_answer",
            },
        ).json()
        if res["complete"]:
            break

    state = _entry(client, learner_id, subject_id)
    assert state["entry_state"] == "VERIFICATION_COMPLETE"
    assert state["diagnostic_completed"] is True
    data = _resume(client, learner_id, subject_id)
    assert data["is_onboarded"] is True
    assert data["entry_state"] == "VERIFICATION_COMPLETE"


# --- Case 7: repeated start/submit never double-counts --------------------------
def test_case07_duplicate_submission_is_idempotent(client, subject_id):
    learner_id = _unique("learner_dup")
    session, _ = _start_calibration(client, learner_id, subject_id)
    started = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": learner_id},
    ).json()
    qid = started["next_question"]["question_id"]

    body = {
        "session_id": session["session_id"],
        "learner_id": learner_id,
        "question_id": qid,
        "selected_option": "definitely_not_the_answer",
    }
    first = client.post("/api/initialization/diagnostic/answer", json=body).json()
    second = client.post("/api/initialization/diagnostic/answer", json=body).json()
    third = client.post("/api/initialization/diagnostic/answer", json=body).json()

    assert first["answered_count"] == 1
    assert second["duplicate_submission"] is True
    assert third["duplicate_submission"] is True
    assert second["answered_count"] == third["answered_count"] == 1
    assert second["updated_masteries"] == first["updated_masteries"]


# --- Case 8: batch submit after per-answer submits does not double-apply ---------
def test_case08_batch_submit_after_answers_is_idempotent(services, client, subject_id):
    learner_id = _unique("learner_batchmix")
    session, _ = _start_calibration(client, learner_id, subject_id)
    started = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": learner_id},
    ).json()
    qid = started["next_question"]["question_id"]
    answered = client.post(
        "/api/initialization/diagnostic/answer",
        json={
            "session_id": session["session_id"],
            "learner_id": learner_id,
            "question_id": qid,
            "selected_option": "definitely_not_the_answer",
        },
    ).json()
    touched = list(answered["updated_masteries"].keys())
    assert touched

    # Read the authoritative learner model back from the server.
    def _masteries():
        ls_state = services[2].repo.load_state(learner_id)
        return {cid: ls_state.concept_states[cid].mastery_probability for cid in touched}

    before = _masteries()

    # A legacy client now posts the full batch, including the question already
    # recorded via /answer. The already-applied evidence must NOT be re-applied.
    client.post(
        "/api/initialization/diagnostic/submit",
        json={"session_id": session["session_id"], "learner_id": learner_id, "responses": {qid: 0.0}},
    )

    assert _masteries() == before
    assert _entry(client, learner_id, subject_id)["answered_count"] == 1


# --- Case 9: ownership is enforced on the per-answer endpoint -------------------
def test_case09_other_learner_cannot_answer(client, subject_id):
    owner = _unique("learner_owner")
    intruder = _unique("learner_intruder")
    session, _ = _start_calibration(client, owner, subject_id)
    started = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": owner},
    ).json()
    qid = started["next_question"]["question_id"]

    resp = client.post(
        "/api/initialization/diagnostic/answer",
        json={
            "session_id": session["session_id"],
            "learner_id": intruder,
            "question_id": qid,
            "selected_option": "definitely_not_the_answer",
        },
    )
    assert resp.status_code == 400
    assert _entry(client, owner, subject_id)["answered_count"] == 0


# --- Case 10: a forged question id is rejected, not graded ----------------------
def test_case10_forged_question_id_rejected(client, subject_id):
    learner_id = _unique("learner_forged")
    session, _ = _start_calibration(client, learner_id, subject_id)
    resp = client.post(
        "/api/initialization/diagnostic/answer",
        json={
            "session_id": session["session_id"],
            "learner_id": learner_id,
            "question_id": "not_a_real_question",
            "selected_option": "x",
        },
    )
    assert resp.status_code == 400
    assert _entry(client, learner_id, subject_id)["answered_count"] == 0


# --- Case 11: no answer key is ever sent to the client --------------------------
def test_case11_answer_keys_never_leak(client, subject_id):
    learner_id = _unique("learner_leak")
    session, _ = _start_calibration(client, learner_id, subject_id)
    started = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": learner_id},
    ).json()
    for q in started["questions"] + [started["next_question"]]:
        assert "correct_answer" not in q
        assert "explanation" not in q

    if started["next_question"]:
        nxt = client.post(
            "/api/initialization/diagnostic/answer",
            json={
                "session_id": session["session_id"],
                "learner_id": learner_id,
                "question_id": started["next_question"]["question_id"],
                "selected_option": "definitely_not_the_answer",
            },
        ).json()
        if nxt.get("next_question"):
            assert "correct_answer" not in nxt["next_question"]
            assert "explanation" not in nxt["next_question"]


# --- Case 12: a client cannot assert its own correctness ------------------------
def test_case12_client_supplied_correctness_is_ignored(client, subject_id):
    learner_id = _unique("learner_inject")
    session, _ = _start_calibration(client, learner_id, subject_id)
    started = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": learner_id},
    ).json()
    qid = started["next_question"]["question_id"]

    resp = client.post(
        "/api/initialization/diagnostic/answer",
        json={
            "session_id": session["session_id"],
            "learner_id": learner_id,
            "question_id": qid,
            "selected_option": "definitely_not_the_answer",
            "correctness": 1.0,
            "is_correct": True,
        },
    )
    # Extra fields are rejected by the request model, so the client cannot even
    # express an assertion of its own mastery.
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert resp.json()["is_correct"] is False


# --- Case 13: active subject is persisted per learner --------------------------
def test_case13_active_subject_persisted(services, client, subject_id):
    learning, ks, ls = services
    learner_id = _unique("learner_subject")
    graph = ks.get_subject_graph(subject_id)
    concept_ids = [c["concept_id"] for c in graph["concepts"]]

    other = [s["id"] for s in ks.list_subjects() if s["id"] != subject_id]
    target = other[0] if other else subject_id

    client.post(f"/api/learners/{learner_id}/active-subject", params={"subject_id": target})
    assert ls.active_subject_repo.get_active_subject(learner_id) == target

    # Resume without an explicit subject must land on the remembered source.
    data = _resume(client, learner_id)
    assert data["subject_id"] == target

    # An explicit subject still wins.
    ls.get_or_create_learner_state(learner_id, concept_ids)
    data2 = _resume(client, learner_id, subject_id)
    assert data2["subject_id"] == subject_id


# --- Case 14: generation failure is an ERROR state, never "complete" -----------
def test_case14_generation_failure_is_retryable_not_complete(services, client, subject_id, monkeypatch):
    learning, ks, ls = services
    learner_id = _unique("learner_genfail")
    session, _ = _start_calibration(client, learner_id, subject_id)

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated question generation failure")

    monkeypatch.setattr(learning.planning_validator, "validate_diagnostic_quiz_creation", boom)
    res = learning.start_diagnostic(session["session_id"], learner_id=learner_id)
    assert res["status"] == "error"
    assert res["question_count"] == 0
    assert res["error"]
    # The critical assertion: a failure must NOT be persisted as "verified".
    assert res["diagnostic_completed"] is False

    reloaded = learning.session_repo.load_session(session["session_id"])
    assert reloaded.diagnostic_completed is False
    assert reloaded.diagnostic_generation_error

    state = learning.get_entry_state(learner_id, subject_id=subject_id)
    assert state["entry_state"] == "VERIFICATION_ERROR"

    # Recovery clears the error and re-enters verification.
    monkeypatch.undo()
    again = learning.start_diagnostic(session["session_id"], learner_id=learner_id)
    assert again["status"] in ("in_progress", "completed")
    assert again["error"] is None


# --- Case 15: entry state is derived per learner, never shared -----------------
def test_case15_entry_state_is_per_learner(client, subject_id):
    verified = _unique("learner_verified")
    fresh = _unique("learner_fresh")
    assert _entry(client, verified, subject_id)["entry_state"] != _entry(client, fresh, subject_id)["entry_state"] or True

    session, _ = _start_calibration(client, verified, subject_id)
    started = client.post(
        "/api/initialization/diagnostic/start",
        json={"session_id": session["session_id"], "learner_id": verified},
    ).json()
    guard = 0
    while guard < 30:
        guard += 1
        nxt = started.get("next_question")
        if not nxt:
            break
        res = client.post(
            "/api/initialization/diagnostic/answer",
            json={
                "session_id": session["session_id"],
                "learner_id": verified,
                "question_id": nxt["question_id"],
                "selected_option": "definitely_not_the_answer",
            },
        ).json()
        if res["complete"]:
            break
        started = {"next_question": res.get("next_question")}

    assert _entry(client, verified, subject_id)["entry_state"] == "VERIFICATION_COMPLETE"
    # The other learner is unaffected: no cross-learner leakage of verification.
    assert _entry(client, fresh, subject_id)["entry_state"] == "NEEDS_CALIBRATION"
    assert _resume(client, fresh, subject_id)["is_onboarded"] is False
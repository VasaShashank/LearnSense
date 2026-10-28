from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user, get_optional_current_user
from backend.routes import api


OWNER_ID = str(uuid.UUID("a20d9df0-2792-4fc2-9d94-20ac476863e0"))
OTHER_ID = str(uuid.UUID("bb1d9df0-2792-4fc2-9d94-20ac476863e0"))


@pytest.fixture
def client(monkeypatch):
    # Route tests must never initialize the local Supabase PostgreSQL pool.
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    monkeypatch.setattr(api.document_ownership, "is_owned_by", lambda _doc, _owner: True)
    monkeypatch.setattr(api.document_ownership, "list_owned_document_ids", lambda _owner: {"subject-1"})
    previous = dict(app.dependency_overrides)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def authenticate(user_id=OWNER_ID):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=user_id)
    app.dependency_overrides[get_optional_current_user] = lambda: AuthenticatedUser(id=user_id)


def test_core_learner_route_rejects_missing_authentication(client):
    response = client.get(f"/api/learners/{OWNER_ID}/progress", params={"subject_id": "subject-1"})
    assert response.status_code == 401


def test_progress_uses_verified_canonical_identity(client, monkeypatch):
    authenticate()
    seen = {}
    monkeypatch.setattr(
        api.learner_service,
        "get_learner_progress",
        lambda learner_id, subject_id: seen.update(learner_id=learner_id, subject_id=subject_id) or {"ok": True},
    )

    response = client.get(f"/api/learners/{OWNER_ID}/progress", params={"subject_id": "subject-1"})
    assert response.status_code == 200
    assert seen == {"learner_id": OWNER_ID, "subject_id": "subject-1"}


def test_cross_learner_progress_is_not_read(client, monkeypatch):
    authenticate()
    called = []
    monkeypatch.setattr(api.learner_service, "get_learner_progress", lambda *args: called.append(args))

    response = client.get(f"/api/learners/{OTHER_ID}/progress", params={"subject_id": "subject-1"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Learner resource not found."
    assert called == []


def test_non_uuid_verified_identity_fails_closed(client, monkeypatch):
    authenticate("demo_student")
    called = []
    monkeypatch.setattr(api.learner_service, "get_learner_progress", lambda *args: called.append(args))

    response = client.get(f"/api/learners/{OWNER_ID}/progress", params={"subject_id": "subject-1"})
    assert response.status_code == 401
    assert called == []


def test_activity_uses_authenticated_owner_for_idempotency_scope(client, monkeypatch):
    authenticate()
    seen = {}

    def fake_process(**kwargs):
        seen.update(kwargs)
        return {"duplicate_submission": False}

    monkeypatch.setattr(api.learning_service, "process_activity_response", fake_process)
    response = client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": OWNER_ID,
            "subject_id": "subject-1",
            "concept_ids": ["concept-1"],
            "question_id": "question-1",
            "selected_option": "answer",
            "request_id": "retry-1",
        },
    )
    assert response.status_code == 200
    assert seen["learner_id"] == OWNER_ID
    assert seen["request_id"] == "retry-1"


def test_activity_rejects_other_claimed_learner_before_service_call(client, monkeypatch):
    authenticate()
    called = []
    monkeypatch.setattr(api.learning_service, "process_activity_response", lambda **kwargs: called.append(kwargs))
    response = client.post(
        "/api/learners/activity-response",
        json={
            "learner_id": OTHER_ID,
            "subject_id": "subject-1",
            "concept_ids": ["concept-1"],
            "question_id": "question-1",
            "selected_option": "answer",
            "request_id": "retry-1",
        },
    )
    assert response.status_code == 404
    assert called == []


def test_tutor_uses_authenticated_learner_identity(client, monkeypatch):
    authenticate()
    seen = {}
    monkeypatch.setattr(
        api.tutor_service,
        "generate_contextual_response",
        lambda **kwargs: seen.update(kwargs) or {"ok": True},
    )
    response = client.post(
        "/api/tutor/interact",
        json={
            "learner_id": OWNER_ID,
            "subject_id": "subject-1",
            "concept_id": "concept-1",
            "intent": "HINT",
        },
    )
    assert response.status_code == 200
    assert seen["learner_id"] == OWNER_ID


def test_diagnostic_session_owner_is_checked_before_answer_call(client, monkeypatch):
    authenticate()
    monkeypatch.setattr(
        api.learning_service.session_repo,
        "load_session",
        lambda session_id: SimpleNamespace(
            session_id=session_id, learner_id=OTHER_ID, subject_id="subject-1"
        ),
    )
    called = []
    monkeypatch.setattr(api.learning_service, "submit_diagnostic_answer", lambda **kwargs: called.append(kwargs))

    response = client.post(
        "/api/initialization/diagnostic/answer",
        json={
            "session_id": "init_sess_secret",
            "learner_id": OWNER_ID,
            "question_id": "question-1",
            "selected_option": "answer",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Diagnostic session not found."
    assert called == []


def test_final_assessment_owner_gates_cached_submission_replay(client, monkeypatch):
    authenticate(OTHER_ID)
    repo_loads = []
    monkeypatch.setattr(
        api.learning_service.session_repo,
        "load_final_assessment",
        lambda assessment_id: repo_loads.append(assessment_id)
        or SimpleNamespace(
            assessment_id=assessment_id, learner_id=OWNER_ID, subject_id="subject-1"
        ),
    )
    service_calls = []
    monkeypatch.setattr(
        api.learning_service,
        "submit_final_assessment",
        lambda **kwargs: service_calls.append(kwargs) or {"duplicate_submission": True, "score_pct": 90},
    )

    denied = client.post(
        "/api/assessment/final/submit",
        json={
            "assessment_id": "final_assessment_1",
            "learner_id": OTHER_ID,
            "subject_id": "subject-1",
            "responses": {},
            "request_id": "shared-request",
        },
    )
    assert denied.status_code == 404
    assert service_calls == []

    authenticate(OWNER_ID)
    allowed = client.post(
        "/api/assessment/final/submit",
        json={
            "assessment_id": "final_assessment_1",
            "learner_id": OWNER_ID,
            "subject_id": "subject-1",
            "responses": {},
            "request_id": "shared-request",
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["score_pct"] == 90
    assert service_calls[0]["learner_id"] == OWNER_ID
    assert service_calls[0]["request_id"] == "shared-request"
    assert repo_loads == ["final_assessment_1", "final_assessment_1"]


def test_subject_graph_requires_authentication_and_uploader_ownership(client, monkeypatch):
    seen = []
    monkeypatch.setattr(api.knowledge_service, "get_subject_graph", lambda *args, **kwargs: seen.append(kwargs) or {"ok": True})

    anonymous = client.get("/api/subjects/subject-1/graph")
    assert anonymous.status_code == 401

    authenticate()
    owner_response = client.get("/api/subjects/subject-1/graph")
    assert owner_response.status_code == 200
    assert seen == [{"learner_masteries": {}}]


def test_personalized_resource_recommendations_require_matching_identity(client, monkeypatch):
    called = []
    monkeypatch.setattr(
        api.resource_service,
        "get_recommendations_for_concept",
        lambda **kwargs: called.append(kwargs) or [],
    )
    anonymous = client.get(
        "/api/subjects/subject-1/concepts/concept-1/resources",
        params={"learner_id": OWNER_ID},
    )
    assert anonymous.status_code == 401
    assert called == []

    authenticate()
    mismatch = client.get(
        "/api/subjects/subject-1/concepts/concept-1/resources",
        params={"learner_id": OTHER_ID},
    )
    assert mismatch.status_code == 404
    assert called == []

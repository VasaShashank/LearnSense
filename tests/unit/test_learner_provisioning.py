import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes import api
from backend.services.learner_service import LearnerService
from phase3.learner.models import ConceptState, LearnerState
from phase3.storage.learner_repository import LearnerStateRepository
from storage.repositories import ActiveSubjectRepository


OWNER_ID = str(uuid.UUID("a20d9df0-2792-4fc2-9d94-20ac476863e0"))
OTHER_ID = str(uuid.UUID("bb1d9df0-2792-4fc2-9d94-20ac476863e0"))


@pytest.fixture
def isolated_learner_service(tmp_path):
    return LearnerService(
        repo=LearnerStateRepository(str(tmp_path / "states")),
        active_subject_repo=ActiveSubjectRepository(str(tmp_path / "active")),
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    repo = LearnerStateRepository(str(tmp_path / "route-states"))
    monkeypatch.setattr(api.learner_service, "repo", repo)
    monkeypatch.setattr(api.document_ownership, "list_owned_document_ids", lambda _owner: set())
    monkeypatch.setattr(
        api.learning_service,
        "get_entry_state",
        lambda learner_id, visible_document_ids=None: {
            "learner_id": learner_id,
            "entry_state": "SOURCE_SELECTION",
            "subject_id": None,
        },
    )
    previous = dict(app.dependency_overrides)
    try:
        yield TestClient(app), repo
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_authenticated_user_can_initialize_own_learner(client):
    test_client, repo = client
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=OWNER_ID)

    response = test_client.post("/api/learners/me/initialize")

    assert response.status_code == 200
    assert response.json() == {
        "learner_id": OWNER_ID,
        "status": "ready",
        "created": True,
        "entry_state": "SOURCE_SELECTION",
        "subject_id": None,
    }
    state = repo.load_state(OWNER_ID)
    assert state is not None
    assert state.identity_provider == "supabase"
    assert state.concept_states == {}


def test_repeated_provisioning_preserves_existing_progress(isolated_learner_service):
    state, created = isolated_learner_service.provision_authenticated_learner(OWNER_ID)
    assert created is True
    state.concept_states["concept-1"] = ConceptState(
        concept_id="concept-1", mastery_probability=0.91, attempt_count=4, correct_count=3
    )
    isolated_learner_service.save_learner_state(state)

    repeated, created = isolated_learner_service.provision_authenticated_learner(OWNER_ID)

    assert created is False
    assert repeated.concept_states["concept-1"].mastery_probability == 0.91
    assert repeated.concept_states["concept-1"].attempt_count == 4


def test_client_cannot_select_another_identity_for_initialization(client):
    test_client, repo = client
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=OWNER_ID)

    response = test_client.post(
        "/api/learners/me/initialize", json={"learner_id": OTHER_ID}
    )

    assert response.status_code == 200
    assert response.json()["learner_id"] == OWNER_ID
    assert repo.load_state(OWNER_ID) is not None
    assert repo.load_state(OTHER_ID) is None


def test_legacy_persona_state_is_not_claimed_or_changed(isolated_learner_service):
    legacy = LearnerState(
        learner_id="student_alex",
        concept_states={"legacy-concept": ConceptState(concept_id="legacy-concept", attempt_count=2)},
    )
    isolated_learner_service.repo.save_state(legacy)

    state, created = isolated_learner_service.provision_authenticated_learner(OWNER_ID)

    assert created is True
    assert state.learner_id == OWNER_ID
    assert state.concept_states == {}
    preserved = isolated_learner_service.repo.load_state("student_alex")
    assert preserved is not None
    assert preserved.concept_states["legacy-concept"].attempt_count == 2


def test_preexisting_unmarked_uuid_state_fails_closed(isolated_learner_service):
    unverified = LearnerState(
        learner_id=OWNER_ID,
        concept_states={"old-concept": ConceptState(concept_id="old-concept", attempt_count=7)},
    )
    isolated_learner_service.repo.save_state(unverified)

    with pytest.raises(ValueError, match="trusted Supabase provenance"):
        isolated_learner_service.provision_authenticated_learner(OWNER_ID)

    preserved = isolated_learner_service.repo.load_state(OWNER_ID)
    assert preserved is not None
    assert preserved.identity_provider is None
    assert preserved.concept_states["old-concept"].attempt_count == 7


def test_missing_or_invalid_verified_identity_fails_closed(client):
    test_client, repo = client
    missing = test_client.post("/api/learners/me/initialize")
    assert missing.status_code == 401

    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id="student_alex")
    invalid = test_client.post("/api/learners/me/initialize")
    assert invalid.status_code == 401
    assert repo.load_state("student_alex") is None

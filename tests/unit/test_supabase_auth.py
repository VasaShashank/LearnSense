"""Tests for Supabase access-token validation and protected roster identity."""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeAsyncClient:
    response = None
    request = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers):
        type(self).request = {"url": url, "headers": headers}
        return type(self).response


def test_missing_token_is_rejected_before_provider_call(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(credentials=None))
    assert exc.value.status_code == 401


def test_valid_supabase_token_resolves_trusted_identity(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    FakeAsyncClient.response = FakeResponse(200, {"id": "trusted-user-123", "email": "user@example.com"})
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)

    user = asyncio.run(
        get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-access-token")
        )
    )

    assert user.id == "trusted-user-123"
    assert user.email == "user@example.com"
    assert FakeAsyncClient.request["url"] == "https://example.supabase.co/auth/v1/user"
    assert FakeAsyncClient.request["headers"]["Authorization"] == "Bearer test-access-token"
    assert FakeAsyncClient.request["headers"]["apikey"] == "test-publishable-key"


def test_invalid_supabase_token_is_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    FakeAsyncClient.response = FakeResponse(401, {"message": "Invalid token"})
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
            )
        )
    assert exc.value.status_code == 401


def test_missing_supabase_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")
            )
        )
    assert exc.value.status_code == 503


def test_roster_endpoint_rejects_missing_token():
    client = TestClient(app)
    response = client.get("/api/institutions/classes/class-123/roster")
    assert response.status_code == 401


def test_roster_uses_verified_identity_not_query_parameter(monkeypatch):
    client = TestClient(app)
    seen = {}

    def fake_get_class_roster(class_id, caller_user_id):
        seen["class_id"] = class_id
        seen["caller_user_id"] = caller_user_id
        return ["learner-1"]

    monkeypatch.setattr(
        "backend.routes.api.institution_service.get_class_roster",
        fake_get_class_roster,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-teacher-id", email="teacher@example.com"
    )
    try:
        response = client.get(
            "/api/institutions/classes/class-123/roster?caller_user_id=pretend-admin-id"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen == {"class_id": "class-123", "caller_user_id": "verified-teacher-id"}
    assert response.json()["roster"] == ["learner-1"]


def test_create_organization_requires_authentication():
    response = TestClient(app).post(
        "/api/institutions/organizations", json={"name": "Example Institute"}
    )
    assert response.status_code == 401


def test_create_organization_assigns_verified_creator_as_admin(monkeypatch):
    client = TestClient(app)
    seen = {}

    async def fake_create_organization_with_admin_async(name, domain, creator_user_id):
        seen.update(name=name, domain=domain, creator_user_id=creator_user_id)
        return {"org_id": "org-test", "name": name}

    monkeypatch.setattr(
        "backend.routes.api.institution_service.create_organization_with_admin_async",
        fake_create_organization_with_admin_async,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user", email="verified@example.com"
    )
    try:
        response = client.post(
            "/api/institutions/organizations",
            json={"name": "Example Institute", "domain": "example.edu"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen == {
        "name": "Example Institute",
        "domain": "example.edu",
        "creator_user_id": "verified-user",
    }


def test_add_membership_uses_verified_actor(monkeypatch):
    client = TestClient(app)
    seen = {}

    async def fake_add_membership_as_admin_async(
        org_id, acting_user_id, target_user_id, role
    ):
        seen.update(
            org_id=org_id,
            acting_user_id=acting_user_id,
            target_user_id=target_user_id,
            role=role,
        )
        return {"ok": True}

    monkeypatch.setattr(
        "backend.routes.api.institution_service.add_membership_as_admin_async",
        fake_add_membership_as_admin_async,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-admin", email="admin@example.com"
    )
    try:
        response = client.post(
            "/api/institutions/memberships",
            json={"org_id": "org-123", "user_id": "learner-456", "role": "LEARNER"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen["acting_user_id"] == "verified-admin"
    assert seen["target_user_id"] == "learner-456"


def test_list_organizations_is_scoped_to_verified_user(monkeypatch):
    client = TestClient(app)
    seen = {}

    async def fake_list_organizations_for_user_async(user_id):
        seen["user_id"] = user_id
        return [{"org_id": "org-allowed", "name": "Allowed"}]

    monkeypatch.setattr(
        "backend.routes.api.institution_service.list_organizations_for_user_async",
        fake_list_organizations_for_user_async,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user", email="user@example.com"
    )
    try:
        response = client.get("/api/institutions/organizations")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen["user_id"] == "verified-user"
    assert response.json()[0]["org_id"] == "org-allowed"



def test_class_listing_requires_authentication():
    response = TestClient(app).get("/api/institutions/classes")
    assert response.status_code == 401


def test_class_listing_is_scoped_to_verified_user(monkeypatch):
    client = TestClient(app)
    seen = {}

    async def fake_list_classes_for_user_async(user_id, org_id=None):
        seen.update(user_id=user_id, org_id=org_id)
        return [{"class_id": "class-visible", "org_id": "org-visible"}]

    monkeypatch.setattr(
        "backend.routes.api.institution_service.list_classes_for_user_async",
        fake_list_classes_for_user_async,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user", email="user@example.com"
    )
    try:
        response = client.get("/api/institutions/classes?org_id=org-visible")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen == {"user_id": "verified-user", "org_id": "org-visible"}


def test_enroll_endpoint_uses_verified_identity_not_request_body(monkeypatch):
    client = TestClient(app)
    seen = {}

    def fake_enroll_learner(class_id, learner_id, enroller_user_id):
        seen["class_id"] = class_id
        seen["learner_id"] = learner_id
        seen["enroller_user_id"] = enroller_user_id
        return {"ok": True}

    monkeypatch.setattr(
        "backend.routes.api.institution_service.enroll_learner",
        fake_enroll_learner,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-teacher-id", email="teacher@example.com"
    )
    try:
        response = client.post(
            "/api/institutions/classes/class-123/enroll",
            json={"learner_id": "learner-456", "enroller_user_id": "pretend-admin-id"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen["enroller_user_id"] == "verified-teacher-id"


def test_create_class_uses_verified_identity_not_request_body(monkeypatch):
    client = TestClient(app)
    seen = {}

    def fake_create_class(
        org_id, subject_id, title, teacher_ids, creator_user_id, enrolled_learner_ids
    ):
        seen["creator_user_id"] = creator_user_id
        return {"ok": True}

    monkeypatch.setattr(
        "backend.routes.api.institution_service.create_class",
        fake_create_class,
    )
    monkeypatch.setattr(
        "backend.routes.api.document_ownership.is_owned_by",
        lambda _document_id, _owner_id: True,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-teacher-id", email="teacher@example.com"
    )
    try:
        response = client.post(
            "/api/institutions/classes",
            json={
                "org_id": "org-123",
                "subject_id": "physics",
                "title": "Physics Class",
                "teacher_ids": ["verified-teacher-id"],
                "creator_user_id": "pretend-admin-id",
                "enrolled_learner_ids": [],
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert seen["creator_user_id"] == "verified-teacher-id"

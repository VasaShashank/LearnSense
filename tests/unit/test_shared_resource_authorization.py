from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes import api as api_route
from phase3.resources.models import ResourceRecord
from phase4.institution.models import UserRole


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _resource_payload(**extra):
    return {
        "resource_id": "res_auth_test",
        "url": "https://example.test/lesson",
        "title": "Shared lesson",
        **extra,
    }


def test_shared_resource_mutation_requires_authentication(client, monkeypatch):
    saved = []
    monkeypatch.setattr(api_route.resource_service, "save_resource", saved.append)

    response = client.post("/api/resources", json=_resource_payload())

    assert response.status_code == 401
    assert saved == []


@pytest.mark.parametrize("role", [UserRole.LEARNER])
def test_non_manager_cannot_mutate_shared_resources_even_with_spoofed_fields(
    client, monkeypatch, role
):
    async def organizations(_user_id):
        return [SimpleNamespace(org_id="org-member")]

    monkeypatch.setattr(
        api_route.institution_service,
        "list_organizations_for_user_async",
        organizations,
    )
    monkeypatch.setattr(
        api_route.institution_service,
        "get_membership",
        lambda _org_id, user_id: SimpleNamespace(
            user_id=user_id, is_active=True, role=role
        ),
    )
    saved = []
    monkeypatch.setattr(api_route.resource_service, "save_resource", saved.append)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-learner", email=None
    )

    response = client.post(
        "/api/resources",
        json=_resource_payload(user_id="pretend-admin", role="ADMIN"),
    )

    assert response.status_code == 403
    assert saved == []


@pytest.mark.parametrize("role", [UserRole.TEACHER, UserRole.ADMIN])
def test_active_teacher_or_admin_can_manage_global_resource_and_reads_stay_public(
    client, monkeypatch, role
):
    async def organizations(user_id):
        assert user_id == "verified-manager"
        return [SimpleNamespace(org_id="org-manager")]

    monkeypatch.setattr(
        api_route.institution_service,
        "list_organizations_for_user_async",
        organizations,
    )
    monkeypatch.setattr(
        api_route.institution_service,
        "get_membership",
        lambda org_id, user_id: SimpleNamespace(
            org_id=org_id, user_id=user_id, is_active=True, role=role
        ),
    )
    saved = []
    monkeypatch.setattr(api_route.resource_service, "save_resource", saved.append)
    resource = ResourceRecord.model_validate(_resource_payload())
    monkeypatch.setattr(api_route.resource_service, "get_resource", lambda _id: resource)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-manager", email=None
    )

    mutation = client.post("/api/resources", json=_resource_payload())
    public_read = client.get("/api/resources/res_auth_test")

    assert mutation.status_code == 200, mutation.text
    assert saved and saved[0].resource_id == "res_auth_test"
    assert public_read.status_code == 200
    assert public_read.json()["resource_id"] == "res_auth_test"


def test_shared_resource_mutation_rejects_unsafe_resource_id(client, monkeypatch):
    async def organizations(_user_id):
        return [SimpleNamespace(org_id="org-manager")]

    monkeypatch.setattr(
        api_route.institution_service,
        "list_organizations_for_user_async",
        organizations,
    )
    monkeypatch.setattr(
        api_route.institution_service,
        "get_membership",
        lambda *_args: SimpleNamespace(is_active=True, role=UserRole.TEACHER),
    )
    saved = []
    monkeypatch.setattr(api_route.resource_service, "save_resource", saved.append)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-manager", email=None
    )

    response = client.post(
        "/api/resources", json=_resource_payload(resource_id="../outside")
    )

    assert response.status_code == 400
    assert saved == []

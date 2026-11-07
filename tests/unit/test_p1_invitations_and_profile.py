import pytest
import uuid
from fastapi.testclient import TestClient
from backend.app import app
from backend.services.institution_service import InstitutionService, UserRole
from backend.auth import AuthenticatedUser, get_current_user

@pytest.fixture
def test_client():
    return TestClient(app)

def test_profile_update_and_retrieval(test_client, monkeypatch):
    user_id = str(uuid.uuid4())
    user_email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    auth_user = AuthenticatedUser(id=user_id, email=user_email)

    app.dependency_overrides[get_current_user] = lambda: auth_user
    try:
        # 1. GET /api/me provisions user
        res = test_client.get("/api/me")
        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == user_id
        assert data["email"] == user_email

        # 2. PATCH /api/me updates display_name
        patch_res = test_client.patch("/api/me", json={"display_name": "Dr. Ada Lovelace"})
        assert patch_res.status_code == 200
        patch_data = patch_res.json()
        assert patch_data["display_name"] == "Dr. Ada Lovelace"

        # 3. GET /api/me returns updated display_name
        res2 = test_client.get("/api/me")
        assert res2.status_code == 200
        assert res2.json()["display_name"] == "Dr. Ada Lovelace"
    finally:
        app.dependency_overrides.pop(get_current_user, None)

def test_invitation_lifecycle(test_client, monkeypatch):
    admin_id = str(uuid.uuid4())
    admin_email = f"admin_{uuid.uuid4().hex[:6]}@example.com"
    admin_user = AuthenticatedUser(id=admin_id, email=admin_email)

    invitee_id = str(uuid.uuid4())
    invitee_email = f"teacher_{uuid.uuid4().hex[:6]}@example.com"
    invitee_user = AuthenticatedUser(id=invitee_id, email=invitee_email)

    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        # Create an org
        org_res = test_client.post("/api/institutions/organizations", json={"name": f"Org_{uuid.uuid4().hex[:6]}"})
        assert org_res.status_code == 200
        org_id = org_res.json()["org_id"]

        # Admin creates invitation for teacher
        inv_res = test_client.post(
            f"/api/institutions/organizations/{org_id}/invitations",
            json={"email": invitee_email, "role": "TEACHER"}
        )
        assert inv_res.status_code == 200
        inv_data = inv_res.json()
        token = inv_data["token"]
        assert token is not None
        assert inv_data["email"] == invitee_email.lower()
        invitation_id = inv_data["invitation_id"]

        # List invitations
        list_res = test_client.get(f"/api/institutions/organizations/{org_id}/invitations")
        assert list_res.status_code == 200
        assert any(i["invitation_id"] == invitation_id for i in list_res.json())

        # Non-matching user fails to accept
        wrong_user = AuthenticatedUser(id=str(uuid.uuid4()), email="wrong@example.com")
        app.dependency_overrides[get_current_user] = lambda: wrong_user
        bad_accept = test_client.post(f"/api/institutions/invitations/{token}/accept")
        assert bad_accept.status_code == 403

        # Invitee accepts invitation
        app.dependency_overrides[get_current_user] = lambda: invitee_user
        accept_res = test_client.post(f"/api/institutions/invitations/{token}/accept")
        assert accept_res.status_code == 200
        assert accept_res.json()["accepted"] is True
        assert accept_res.json()["role"] == "TEACHER"

        # Check invitee now has TEACHER membership in the org
        me_res = test_client.get("/api/me")
        assert me_res.status_code == 200
        mems = me_res.json()["memberships"]
        assert any(m["org_id"] == org_id and m["role"] == "TEACHER" for m in mems)
    finally:
        app.dependency_overrides.pop(get_current_user, None)

def test_self_deactivation(test_client):
    user_id = str(uuid.uuid4())
    user_email = f"deact_{uuid.uuid4().hex[:6]}@example.com"
    auth_user = AuthenticatedUser(id=user_id, email=user_email)

    app.dependency_overrides[get_current_user] = lambda: auth_user
    try:
        # Provision
        test_client.get("/api/me")
        # Deactivate
        deact_res = test_client.post("/api/me/deactivate")
        assert deact_res.status_code == 200
        assert deact_res.json()["status"] == "disabled"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


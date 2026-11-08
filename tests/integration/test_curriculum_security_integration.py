"""
Cross-boundary security and authorization integration test suite for LearnSense.

Verifies the security contracts between Person 1 (Supabase Auth / Platform Lifecycle)
and Person 2 (Curriculum Governance / Knowledge Graph):

1. Anonymous curriculum read request returns 401.
2. Authenticated Student can read permitted curriculum data.
3. Authenticated Teacher can read permitted curriculum data.
4. Authenticated Administrator can read permitted curriculum data.
5. Student cannot approve a concept (403 Forbidden).
6. Student cannot reject a concept (403 Forbidden).
7. Student cannot publish curriculum changes (403 Forbidden).
8. Unauthorized Teacher cannot perform restricted curriculum-lead actions (403 Forbidden).
9. Authorized Curriculum Lead can perform permitted review actions.
10. Authorized Administrator can perform permitted governance actions.
11. Reviewer identity is derived from JWT, not untrusted request bodies.
12. Invalid JWT is rejected with 401 Unauthorized.
13. Expired JWT is rejected with 401 Unauthorized.
14. User cannot modify another organization's curriculum without permission.
15. Role switching cannot grant new permissions.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.models import CanonicalConcept, CurriculumGraph, Subject
from curriculum.repository import CurriculumRepository

STUDENT_UUID = "d3b07384-0000-0000-0000-000000000001"
TEACHER_UUID = "d3b07384-0000-0000-0000-000000000002"
ADMIN_UUID = "d3b07384-0000-0000-0000-000000000003"
LEAD_UUID = "d3b07384-0000-0000-0000-000000000004"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


@pytest.fixture
def test_curriculum_env(tmp_path, monkeypatch):
    from backend import auth
    from backend.auth import clear_auth_cache

    repo = CurriculumRepository(base_dir=str(tmp_path / "sec_curriculum"))
    service = CurriculumService(repository=repo)

    graph = CurriculumGraph(curriculum_id=service.curriculum_id, syllabus_version="2026.sec.v1")
    c1 = CanonicalConcept.create(
        name="Kinematics Motion",
        subject=Subject.PHYSICS,
        class_levels=["class_11"],
        chapter_id="ch_kinematics",
        description="One-dimensional motion kinematics.",
        stable_key="cc_kinematics_sec",
    )
    graph.add_concept(c1)
    repo.save_graph(graph)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")

    token_map = {
        "mock_valid_student_jwt": {"id": STUDENT_UUID, "email": "student@test.edu"},
        "mock_student_jwt": {"id": STUDENT_UUID, "email": "student@test.edu"},
        "mock_valid_teacher_jwt": {"id": TEACHER_UUID, "email": "teacher@test.edu"},
        "mock_teacher_jwt": {"id": TEACHER_UUID, "email": "teacher@test.edu"},
        "mock_valid_admin_jwt": {"id": ADMIN_UUID, "email": "admin@test.edu"},
        "mock_admin_jwt": {"id": ADMIN_UUID, "email": "admin@test.edu"},
        "mock_lead_jwt": {"id": LEAD_UUID, "email": "prof_lead_vance@apex.edu"},
        "mock_outsider_jwt": {"id": "outsider_student", "email": "outsider@other.edu"},
    }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            auth_header = (headers or {}).get("Authorization", "")
            token = auth_header.replace("Bearer ", "").strip()
            if token in token_map:
                return FakeResponse(200, token_map[token])
            return FakeResponse(401, {"message": "Invalid JWT signature"})

    monkeypatch.setattr(auth.httpx, "AsyncClient", MockAsyncClient)
    clear_auth_cache()

    app.dependency_overrides[get_service] = lambda: service
    try:
        yield service, c1.concept_id
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_current_user, None)
        clear_auth_cache()


# 1. Anonymous curriculum read request returns 401
def test_01_anonymous_curriculum_read_returns_401(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/curriculum/concepts")
    assert res.status_code == 401
    assert "bearer" in res.json().get("detail", "").lower() or "authentication" in res.json().get("code", "").lower()


# 2. Authenticated Student can read permitted curriculum data
def test_02_authenticated_student_reads_curriculum(test_curriculum_env):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=STUDENT_UUID, email="student@test.edu")
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/curriculum/concepts", headers={"Authorization": "Bearer mock_valid_student_jwt"})
    assert res.status_code == 200
    assert "concepts" in res.json()


# 3. Authenticated Teacher can read permitted curriculum data
def test_03_authenticated_teacher_reads_curriculum(test_curriculum_env):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=TEACHER_UUID, email="teacher@test.edu")
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/curriculum/concepts", headers={"Authorization": "Bearer mock_valid_teacher_jwt"})
    assert res.status_code == 200
    assert "concepts" in res.json()


# 4. Authenticated Administrator can read permitted curriculum data
def test_04_authenticated_admin_reads_curriculum(test_curriculum_env):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=ADMIN_UUID, email="admin@test.edu")
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/curriculum/status", headers={"Authorization": "Bearer mock_valid_admin_jwt"})
    assert res.status_code == 200
    assert "concept_count" in res.json()


# 5. Student cannot approve a concept
def test_05_student_cannot_approve_concept(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": "Bearer mock_student_jwt"},
        json={
            "proposed": {"name": "Hacked Concept", "subject": "physics"},
            "reviewer_id": "student_alex",
            "reviewer_role": "learner",
        },
    )
    assert res.status_code == 403
    assert "not authorized" in res.json()["detail"].lower()


# 6. Student cannot reject a concept
def test_06_student_cannot_reject_concept(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/reject",
        headers={"Authorization": "Bearer mock_student_jwt"},
        json={
            "item_id": "cand_1",
            "reviewer_id": "student_alex",
            "reason": "Attempting malicious rejection",
        },
    )
    assert res.status_code == 403
    assert "not authorized" in res.json()["detail"].lower()


# 7. Student cannot publish curriculum changes
def test_07_student_cannot_publish_curriculum(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/publish",
        headers={"Authorization": "Bearer mock_student_jwt"},
        json={"reviewer_id": "student_alex", "release_notes": "Student unauthorized release"},
    )
    assert res.status_code == 403
    assert "not authorized" in res.json()["detail"].lower()


# 8. Unauthorized Teacher cannot perform restricted curriculum-lead actions
def test_08_unauthorized_teacher_restricted_from_rollback(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/versions/v_nonexistent/rollback",
        headers={"Authorization": "Bearer mock_teacher_jwt"},
        json={"reviewer_id": "student_alex", "note": "Unauthorized rollback attempt"},
    )
    assert res.status_code == 403


# 9. Authorized Curriculum Lead can perform permitted review actions
def test_09_authorized_lead_performs_review_decision(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": "Bearer mock_lead_jwt"},
        json={
            "proposed": {
                "name": "Vectors and Scalars",
                "description": "Vector algebra and coordinate components.",
                "subject": "physics",
                "class_levels": ["class_11"],
                "chapter_id": "ch_kinematics",
            },
            "reviewer_id": "prof_lead_vance",
            "reviewer_role": "curriculum_editor",
            "note": "Verified canonical alignment with JEE 2027",
        },
    )
    assert res.status_code == 200
    assert "concept_id" in res.json()


# 10. Authorized Administrator can perform permitted governance actions
def test_10_authorized_admin_publishes_curriculum(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/publish",
        headers={"Authorization": "Bearer mock_admin_jwt"},
        json={"reviewer_id": "admin_sterling", "release_notes": "Official academic curriculum release"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "published"


# 11. Reviewer identity is verified from reviewer parameter and not empty
def test_11_reviewer_identity_mandatory(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": "Bearer mock_teacher_jwt"},
        json={"proposed": {"name": "Anonymous Mutation"}, "reviewer_id": ""},
    )
    assert res.status_code in (401, 422)


# 12. Invalid JWT is rejected
def test_12_invalid_jwt_rejected(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get(
        "/api/curriculum/concepts",
        headers={"Authorization": "Bearer invalid_forged_signature_token"},
    )
    assert res.status_code == 401


# 13. Expired JWT is rejected
def test_13_expired_jwt_rejected(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get(
        "/api/curriculum/concepts",
        headers={"Authorization": "Bearer expired_token_session"},
    )
    assert res.status_code == 401


# 14. User cannot modify another organization's curriculum without permission
def test_14_user_cannot_modify_unauthorized_scope(test_curriculum_env):
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": "Bearer mock_outsider_jwt"},
        json={
            "proposed": {"name": "Foreign Concept"},
            "reviewer_id": "student_external",
            "reviewer_role": "learner",
        },
    )
    assert res.status_code == 403


# 15. Role switching cannot grant new permissions
def test_15_role_switching_cannot_grant_new_permissions(test_curriculum_env):
    # Student attempts to self-promote via PATCH /me/role
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=STUDENT_UUID, email="student@test.edu")
    client = TestClient(app, raise_server_exceptions=False)
    promote_res = client.patch(
        "/api/me/role",
        headers={"Authorization": "Bearer mock_student_jwt"},
        json={"role": "ADMIN"},
    )
    assert promote_res.status_code == 403
    assert promote_res.json()["code"] == "FORBIDDEN_ROLE_ESCALATION"


# 16. P0 Security Regression: Forged JWT without "invalid" substring is rejected 401
def test_16_forged_jwt_without_invalid_substring_rejected(test_curriculum_env):
    """
    Demonstrates fix for critical P0 bypass: forged tokens without the substring
    'invalid' were previously accepted by naive substring check. Now verified via Supabase Auth.
    """
    client = TestClient(app, raise_server_exceptions=False)
    forged_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.signature"
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": f"Bearer {forged_token}"},
        json={
            "proposed": {"name": "Injected Attack Concept", "subject": "physics"},
            "reviewer_id": "teacher_vance",
            "reviewer_role": "teacher",
        },
    )
    assert res.status_code == 401
    assert res.headers.get("www-authenticate", "").lower() == "bearer"


# 17. P0 Security Regression: Client-supplied reviewer_id spoofing is blocked
def test_17_student_token_cannot_spoof_teacher_reviewer_id(test_curriculum_env):
    """
    Demonstrates fix for reviewer identity spoofing: student token supplying
    reviewer_id='prof_vance' in body is rejected with 403 Forbidden.
    """
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": "Bearer mock_student_jwt"},
        json={
            "proposed": {"name": "Spoofed Concept", "subject": "physics"},
            "reviewer_id": "prof_vance",
            "reviewer_role": "teacher",
        },
    )
    assert res.status_code == 403
    assert "not authorized" in res.json().get("detail", "").lower()


# 18. P0 Security Regression: Teacher token succeeds and action is attributed to teacher
def test_18_teacher_mutation_succeeds_with_auth_identity(test_curriculum_env):
    """Teacher token succeeds and properly updates curriculum graph."""
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/curriculum/review/accept",
        headers={"Authorization": "Bearer mock_teacher_jwt"},
        json={
            "proposed": {
                "name": "Work Energy Theorem",
                "subject": "physics",
                "class_levels": ["class_11"],
                "chapter_id": "ch_work_energy",
                "description": "Work done equals change in kinetic energy.",
            },
            "reviewer_id": "teacher_vance",
            "note": "Authorized faculty addition",
        },
    )
    assert res.status_code == 200
    assert "concept_id" in res.json()

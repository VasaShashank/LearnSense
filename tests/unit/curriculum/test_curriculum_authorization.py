"""
Comprehensive unit test suite for server-side authorization in curriculum governance (Person 2).

Verifies that:
- Unauthenticated requests with invalid tokens receive 401 Unauthorized.
- Unauthenticated requests with missing reviewer identity receive 401 Unauthorized.
- Learner requests (student persona IDs or learner role) receive 403 Forbidden.
- Authorized Teacher and Administrator requests succeed.
- Pre-rollback state archival preserves snapshots in version history.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.curriculum import get_service
from backend.services.curriculum_service import CurriculumService
from curriculum.models import CanonicalConcept, CurriculumGraph, Subject
from curriculum.repository import CurriculumRepository


@pytest.fixture
def auth_test_env(tmp_path):
    """Isolated curriculum environment with test concepts and relationships."""
    repo = CurriculumRepository(base_dir=str(tmp_path / "curriculum"))
    service = CurriculumService(repository=repo)

    graph = CurriculumGraph(curriculum_id=service.curriculum_id, syllabus_version="2026.auth.v1")
    c1 = CanonicalConcept.create(
        name="Kinematics 1D",
        subject=Subject.PHYSICS,
        class_levels=["class_11"],
        chapter_id="ch_kinematics",
        description="One-dimensional motion under constant acceleration.",
        stable_key="cc_kinematics_1d_auth",
    )
    c2 = CanonicalConcept.create(
        name="Newton Laws",
        subject=Subject.PHYSICS,
        class_levels=["class_11"],
        chapter_id="ch_newton",
        description="Classical dynamics and forces.",
        stable_key="cc_newton_laws_auth",
    )
    graph.add_concept(c1)
    graph.add_concept(c2)
    repo.save_graph(graph)

    app.dependency_overrides[get_service] = lambda: CurriculumService(repository=repo)
    try:
        yield service, c1.concept_id
    finally:
        app.dependency_overrides.pop(get_service, None)


class TestCurriculumAuthorization:
    """Verifies server-side authorization gates across all mutation endpoints."""

    def test_unauthenticated_request_with_invalid_token(self, auth_test_env):
        _, concept_id = auth_test_env
        client = TestClient(app)
        res = client.put(
            f"/api/curriculum/concepts/{concept_id}",
            headers={"Authorization": "Bearer invalid_token_xyz"},
            json={"name": "Hacked Name", "reviewer_id": "prof_vance", "note": "Hacking"},
        )
        assert res.status_code == 401
        assert "Invalid or expired access token" in res.json()["detail"]

    def test_missing_reviewer_identity_is_401(self, auth_test_env):
        _, concept_id = auth_test_env
        client = TestClient(app)
        res = client.put(
            f"/api/curriculum/concepts/{concept_id}",
            json={"name": "New Name", "reviewer_id": "", "note": "Missing identity"},
        )
        assert res.status_code == 401
        assert "Missing reviewer identity" in res.json()["detail"]

    def test_learner_request_to_edit_metadata_is_403_forbidden(self, auth_test_env):
        _, concept_id = auth_test_env
        client = TestClient(app)
        # Attempted mutation by student_alex (Learner)
        res = client.put(
            f"/api/curriculum/concepts/{concept_id}",
            json={
                "name": "Tampered Concept Name",
                "reviewer_id": "student_alex",
                "note": "Student attempting to edit canonical concept",
            },
        )
        assert res.status_code == 403
        assert "Learner 'student_alex' is not authorized" in res.json()["detail"]

        # Confirm persistent data was NOT modified
        concept_res = client.get(f"/api/curriculum/concepts/{concept_id}")
        assert concept_res.status_code == 200
        assert concept_res.json()["name"] == "Kinematics 1D"

    def test_learner_request_to_publish_curriculum_is_403_forbidden(self, auth_test_env):
        client = TestClient(app)
        res = client.post(
            "/api/curriculum/publish",
            json={
                "reviewer_id": "student_jordan",
                "release_notes": "Student trying to publish curriculum",
            },
        )
        assert res.status_code == 403
        assert "Learner 'student_jordan' is not authorized" in res.json()["detail"]

    def test_learner_request_to_rollback_is_403_forbidden(self, auth_test_env):
        client = TestClient(app)
        res = client.post(
            "/api/curriculum/versions/cv_dummy_version/rollback",
            json={
                "reviewer_id": "student_sam",
                "note": "Student trying to revert curriculum",
            },
        )
        assert res.status_code == 403
        assert "Learner 'student_sam' is not authorized" in res.json()["detail"]

    def test_learner_role_parameter_is_403_forbidden(self, auth_test_env):
        client = TestClient(app)
        res = client.post(
            "/api/curriculum/review/accept",
            json={
                "proposed": {
                    "name": "New Concept",
                    "subject": "physics",
                    "chapter_id": "ch_kinematics",
                },
                "reviewer_id": "someone_anonymous",
                "reviewer_role": "learner",
            },
        )
        assert res.status_code == 403
        assert "Role 'learner' is not authorized" in res.json()["detail"]

    def test_authorized_teacher_metadata_update_succeeds(self, auth_test_env):
        _, concept_id = auth_test_env
        client = TestClient(app)
        res = client.put(
            f"/api/curriculum/concepts/{concept_id}",
            json={
                "name": "Kinematics in One Dimension (Revised)",
                "description": "Refined kinematics definitions approved by faculty.",
                "reviewer_id": "prof_vance",
                "note": "Teacher approved syllabus update",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Kinematics in One Dimension (Revised)"
        assert data["description"] == "Refined kinematics definitions approved by faculty."

        # Verify persistence
        verify_res = client.get(f"/api/curriculum/concepts/{concept_id}")
        assert verify_res.status_code == 200
        assert verify_res.json()["name"] == "Kinematics in One Dimension (Revised)"

    def test_authorized_admin_publishing_and_rollback_with_pre_archival(self, auth_test_env):
        _, concept_id = auth_test_env
        client = TestClient(app)

        # 1. Admin publishes initial version
        pub_res = client.post(
            "/api/curriculum/publish",
            json={
                "reviewer_id": "admin_sterling",
                "release_notes": "Official semester curriculum release",
            },
        )
        assert pub_res.status_code == 200
        pub_data = pub_res.json()
        assert pub_data["status"] == "published"
        v1_id = pub_data["version_id"]

        # 2. Mutate state
        mut_res = client.put(
            f"/api/curriculum/concepts/{concept_id}",
            json={
                "name": "Experimental Mutation State",
                "reviewer_id": "prof_vance",
                "note": "Teacher testing experimental name",
            },
        )
        assert mut_res.status_code == 200

        # Check versions before rollback
        ver_before = client.get("/api/curriculum/versions").json()["versions"]
        count_before = len(ver_before)

        # 3. Admin rolls back to v1_id
        rb_res = client.post(
            f"/api/curriculum/versions/{v1_id}/rollback",
            json={
                "reviewer_id": "admin_sterling",
                "note": "Rollback experimental mutation",
            },
        )
        assert rb_res.status_code == 200
        assert rb_res.json()["status"] == "rolled_back"

        # 4. Verify pre-rollback archival: version ledger contains pre-rollback backup!
        ver_after = client.get("/api/curriculum/versions").json()["versions"]
        assert len(ver_after) == count_before + 1
        backup_snap = ver_after[-1]
        assert "Automatic pre-rollback backup" in backup_snap["note"]

        # 5. Verify restored state
        restored = client.get(f"/api/curriculum/concepts/{concept_id}").json()
        assert restored["name"] != "Experimental Mutation State"

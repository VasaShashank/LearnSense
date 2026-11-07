from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from phase3.errors import AuthorizationError
from phase4.institution.models import UserRole


def test_class_analytics_rejects_missing_authentication():
    response = TestClient(app).get("/api/classes/class-1/knowledge-state")
    assert response.status_code == 401


def test_assigned_teacher_can_read_class_analytics(monkeypatch):
    import backend.routes.api as api

    user = AuthenticatedUser(id="teacher-id", email="teacher@example.com")
    course_class = SimpleNamespace(
        class_id="class-1", org_id="org-1", subject_id="subject-1",
        title="Class", teacher_ids=[user.id],
    )
    monkeypatch.setattr(api.institution_service, "get_class", lambda _id: course_class)
    monkeypatch.setattr(api.document_ownership, "is_owned_by", lambda _doc, _user: True)
    monkeypatch.setattr(
        api.institution_service,
        "require_role",
        lambda _org, _user, _roles: SimpleNamespace(role=UserRole.TEACHER),
    )
    monkeypatch.setattr(api.institution_service, "get_class_roster", lambda *_a, **_k: ["learner-1"])
    monkeypatch.setattr(
        api.teacher_service,
        "get_class",
        lambda _id: {"subject_id": "subject-1", "enrolled_learner_ids": ["learner-1"]},
    )
    monkeypatch.setattr(
        api.teacher_service,
        "get_class_knowledge_state",
        lambda *_a, **_k: {"class_id": "class-1", "ok": True},
    )
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get("/api/classes/class-1/knowledge-state")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert response.json() == {"class_id": "class-1", "ok": True}


def test_cross_organization_or_unassigned_teacher_is_hidden(monkeypatch):
    import backend.routes.api as api

    user = AuthenticatedUser(id="other-teacher", email="teacher@example.com")
    course_class = SimpleNamespace(
        class_id="class-secret", org_id="org-1", subject_id="subject-1",
        title="Secret", teacher_ids=["assigned-teacher"],
    )
    monkeypatch.setattr(api.institution_service, "get_class", lambda _id: course_class)

    def deny(_org, _user, _roles):
        raise AuthorizationError("No membership")

    monkeypatch.setattr(api.institution_service, "require_role", deny)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get("/api/classes/class-secret/student-mastery")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 404
    assert "Secret" not in response.text


def test_legacy_global_insights_require_authentication():
    response = TestClient(app).get("/api/student-learning-insights")
    assert response.status_code == 401


def test_legacy_global_insights_fail_closed_for_authenticated_users():
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="teacher-id", email="teacher@example.com"
    )
    try:
        response = TestClient(app).get("/api/student-learning-insights")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403

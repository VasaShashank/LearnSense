"""Person 1 identity, membership and class-lifecycle APIs (JSON-mode real service).

Real InstitutionService/UserService/ownership/share repositories under tmp_path,
``get_current_user`` overridden per request, teacher analytics stubbed. The
PostgreSQL paths of the same operations are covered by
tests/integration/test_p1_postgres_live.py against a disposable database.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes import api as api_route
from backend.routes import documents as documents_route
from backend.services.institution_service import InstitutionService
from backend.services.learner_service import LearnerService
from backend.services.user_service import UserService
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.institution.models import UserRole
from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository

ADMIN, ADMIN2, TEACHER, TEACHER2, LEARNER, LEARNER2, OUTSIDER = (str(uuid.uuid4()) for _ in range(7))
DOC = "doc_p1_lifecycle"


@pytest.fixture
def env(monkeypatch, tmp_path):
    learners = LearnerStateRepository(str(tmp_path / "learners"))
    users = UserService(base_dir=str(tmp_path / "users"), pg_enabled=False)
    svc = InstitutionService(base_dir=str(tmp_path / "inst"), learner_state_repo=learners, user_service=users)
    assert svc._pg_enabled is False
    projections: dict = {}
    monkeypatch.setattr(svc, "_sync_class_to_teacher_storage", lambda cid, sid, title, roster: projections.__setitem__(
        cid, {"class_id": cid, "subject_id": sid, "class_name": title, "enrolled_learner_ids": list(roster)}))
    monkeypatch.setattr(svc, "_append_learner_to_teacher_storage",
                        lambda cid, lid: projections[cid]["enrolled_learner_ids"].append(lid))
    monkeypatch.setattr(svc, "_set_teacher_storage_roster",
                        lambda cid, roster: projections[cid].__setitem__("enrolled_learner_ids", list(roster)))

    for uid in (ADMIN, ADMIN2, TEACHER, TEACHER2, OUTSIDER):
        asyncio.run(users.ensure_user(uid, f"{uid[:4]}@example.test"))
    for lid in (LEARNER, LEARNER2):
        LearnerService(repo=learners).provision_authenticated_learner(lid)

    ownership = DocumentOwnershipRepository(str(tmp_path / "owners"))
    shares = DocumentShareRepository(str(tmp_path / "shares"))
    ownership.claim(DOC, TEACHER)

    org = asyncio.run(svc.create_organization_with_admin_async("Org One", None, ADMIN))
    other = asyncio.run(svc.create_organization_with_admin_async("Org Two", None, OUTSIDER))
    for uid, role in ((ADMIN2, UserRole.ADMIN), (TEACHER, UserRole.TEACHER), (TEACHER2, UserRole.TEACHER),
                      (LEARNER, UserRole.LEARNER), (LEARNER2, UserRole.LEARNER)):
        asyncio.run(svc.add_membership_as_admin_async(org.org_id, ADMIN, uid, role))
    cls = svc.create_class(org.org_id, DOC, "Class One", [TEACHER], TEACHER, [LEARNER, LEARNER2])

    teacher = SimpleNamespace(
        get_class=lambda cid: projections.get(cid),
        list_classes=lambda: list(projections.values()),
        get_class_knowledge_state=lambda cid, **_k: {"enrolled": list(projections[cid]["enrolled_learner_ids"])},
    )
    monkeypatch.setattr(api_route, "institution_service", svc)
    monkeypatch.setattr(api_route, "teacher_service", teacher)
    monkeypatch.setattr(api_route, "document_ownership", ownership)
    monkeypatch.setattr(api_route, "document_shares", shares)
    for access in (api_route.document_access, documents_route.document_access):
        monkeypatch.setattr(access, "ownership", ownership)
        monkeypatch.setattr(access, "shares", shares)
        monkeypatch.setattr(access, "institutions", svc)
    return SimpleNamespace(svc=svc, org=org, other=other, cls=cls, users=users, projections=projections,
                           ownership=ownership, tmp=tmp_path)


def call(user_id, method, path, email=None, **kwargs):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=user_id, email=email)
    try:
        return TestClient(app, raise_server_exceptions=False).request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def events(env, **filters):
    return asyncio.run(env.svc.audit.list_events(**filters))


def actions(env, **filters):
    return [e["action"] for e in events(env, **filters)]


# --- GET /api/me -------------------------------------------------------------------

def test_me_returns_only_the_callers_active_memberships_and_provisions_the_user(env):
    new_user = str(uuid.uuid4())
    response = call(new_user, "GET", "/api/me", email="new@example.test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"user_id": new_user, "email": "new@example.test", "account_status": "active", "memberships": []}
    assert env.users.get_user_json(new_user)["status"] == "active"   # provisioned idempotently
    assert call(new_user, "GET", "/api/me").status_code == 200

    teacher = call(TEACHER, "GET", "/api/me").json()
    assert [(m["org_id"], m["role"]) for m in teacher["memberships"]] == [(env.org.org_id, "TEACHER")]


def test_me_shows_different_roles_in_two_organizations(env):
    asyncio.run(env.svc.add_membership_as_admin_async(env.other.org_id, OUTSIDER, TEACHER, UserRole.ADMIN))
    roles = {(m["org_name"], m["role"]) for m in call(TEACHER, "GET", "/api/me").json()["memberships"]}
    assert roles == {("Org One", "TEACHER"), ("Org Two", "ADMIN")}
    # Admin of org two gives no rights in org one, and vice versa.
    assert call(TEACHER, "GET", f"/api/institutions/organizations/{env.org.org_id}/memberships").status_code == 403
    assert call(TEACHER, "GET", f"/api/institutions/organizations/{env.other.org_id}/memberships").status_code == 200


def test_me_excludes_deactivated_memberships(env):
    assert call(ADMIN, "DELETE", f"/api/institutions/organizations/{env.org.org_id}/memberships/{TEACHER}").status_code == 200
    assert call(TEACHER, "GET", "/api/me").json()["memberships"] == []


def test_me_rejects_non_canonical_identity_and_missing_token(env):
    assert call("student_alex", "GET", "/api/me").status_code == 401
    assert TestClient(app).get("/api/me").status_code == 401


def test_me_export_contains_p1_records(env):
    body = call(LEARNER, "GET", "/api/me/export").json()
    assert {m["org_id"] for m in body["memberships"]} == {env.org.org_id}
    assert body["enrollments"] == [{"class_id": env.cls.class_id, "status": "active",
                                    "enrolled_at": body["enrollments"][0]["enrolled_at"], "unenrolled_at": None}]
    assert call(TEACHER, "GET", "/api/me/export").json()["owned_document_ids"] == [DOC]
    admin_export = call(ADMIN, "GET", "/api/me/export").json()
    assert "org.created" in {e["action"] for e in admin_export["audit_events_as_actor"]}


# --- Member list ---------------------------------------------------------------------

def test_member_list_is_admin_only_paginated_and_ordered(env):
    path = f"/api/institutions/organizations/{env.org.org_id}/memberships"
    page = call(ADMIN, "GET", f"{path}?limit=2&offset=0").json()
    assert page["total"] == 6 and page["limit"] == 2 and page["offset"] == 0
    everyone = call(ADMIN, "GET", f"{path}?limit=50").json()["items"]
    assert [m["user_id"] for m in everyone] == sorted(m["user_id"] for m in everyone)
    assert page["items"] == everyone[:2]
    assert set(everyone[0]) == {"membership_id", "user_id", "role", "is_active"}  # no emails or account data
    for caller in (TEACHER, LEARNER, OUTSIDER):
        assert call(caller, "GET", path).status_code == 403
    assert call(ADMIN, "GET", f"{path}?limit=0").status_code == 422


def test_member_list_hides_inactive_unless_requested_and_gives_same_403_for_unknown_org(env):
    call(ADMIN, "DELETE", f"/api/institutions/organizations/{env.org.org_id}/memberships/{LEARNER2}")
    path = f"/api/institutions/organizations/{env.org.org_id}/memberships"
    assert LEARNER2 not in {m["user_id"] for m in call(ADMIN, "GET", path).json()["items"]}
    inactive = {m["user_id"]: m["is_active"] for m in call(ADMIN, "GET", f"{path}?include_inactive=true").json()["items"]}
    assert inactive[LEARNER2] is False
    other_tenant = call(OUTSIDER, "GET", path)
    unknown = call(OUTSIDER, "GET", "/api/institutions/organizations/org_doesnotexist/memberships")
    assert other_tenant.status_code == unknown.status_code == 403
    assert other_tenant.json() == unknown.json()


# --- Organizations and staff identity ------------------------------------------------------

def test_duplicate_organization_name_is_409_case_insensitive(env):
    response = call(TEACHER, "POST", "/api/institutions/organizations", json={"name": "  org ONE "})
    assert response.status_code == 409
    assert response.json()["code"] == "ORGANIZATION_NAME_TAKEN"
    assert env.org.org_id not in response.text


def test_new_organization_makes_the_verified_caller_admin_and_is_audited(env):
    response = call(TEACHER2, "POST", "/api/institutions/organizations", json={"name": "Fresh Org"})
    assert response.status_code == 200, response.text
    org_id = response.json()["org_id"]
    assert env.svc.get_membership(org_id, TEACHER2).role == UserRole.ADMIN
    assert actions(env, org_id=org_id) == ["org.created"]


@pytest.mark.parametrize("target", ["prof_vance", "not-a-uuid", str(uuid.uuid4())])
@pytest.mark.parametrize("role", ["TEACHER", "ADMIN"])
def test_staff_roles_require_a_provisioned_canonical_user(env, target, role):
    response = call(ADMIN, "POST", "/api/institutions/memberships",
                    json={"org_id": env.org.org_id, "user_id": target, "role": role})
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_PROVISIONED"
    assert env.svc.get_membership(env.org.org_id, target) is None


def test_disabled_user_cannot_be_given_a_staff_role(env):
    asyncio.run(env.users.set_status(TEACHER2, "disabled", reason="test", actor_user_id="operator"))
    response = call(ADMIN, "POST", "/api/institutions/memberships",
                    json={"org_id": env.org.org_id, "user_id": TEACHER2, "role": "ADMIN"})
    assert response.status_code == 404


def test_unprovisioned_learner_grant_is_404_and_provisioned_learner_succeeds(env):
    stranger = str(uuid.uuid4())
    response = call(ADMIN, "POST", "/api/institutions/memberships",
                    json={"org_id": env.org.org_id, "user_id": stranger, "role": "LEARNER"})
    assert response.status_code == 404 and response.json()["code"] == "USER_NOT_PROVISIONED"


def test_membership_changes_are_audited_and_no_op_upserts_are_not(env):
    org = env.org.org_id
    call(ADMIN, "POST", "/api/institutions/memberships", json={"org_id": org, "user_id": TEACHER2, "role": "ADMIN"})
    call(ADMIN, "POST", "/api/institutions/memberships", json={"org_id": org, "user_id": TEACHER2, "role": "ADMIN"})
    call(ADMIN, "DELETE", f"/api/institutions/organizations/{org}/memberships/{TEACHER2}")
    call(ADMIN, "POST", "/api/institutions/memberships", json={"org_id": org, "user_id": TEACHER2, "role": "TEACHER"})
    trail = [e["action"] for e in reversed(events(env, target_id=TEACHER2))]
    assert trail == ["membership.created", "membership.role_changed", "membership.deactivated",
                     "membership.reactivated"]


def test_denied_operations_write_no_audit_events(env):
    before = len(events(env, org_id=env.org.org_id))
    org = env.org.org_id
    assert call(TEACHER, "DELETE", f"/api/institutions/organizations/{org}/memberships/{LEARNER}").status_code == 403
    assert call(OUTSIDER, "POST", "/api/institutions/memberships",
                json={"org_id": org, "user_id": OUTSIDER, "role": "ADMIN"}).status_code == 403
    assert call(OUTSIDER, "DELETE", f"/api/institutions/classes/{env.cls.class_id}/enrollments/{LEARNER}").status_code == 404
    assert call(TEACHER, "PUT", f"/api/institutions/classes/{env.cls.class_id}/teachers",
                json={"teacher_ids": [TEACHER2]}).status_code == 404
    assert len(events(env, org_id=org)) == before


# --- Unenrollment -----------------------------------------------------------------------

def test_assigned_teacher_unenrolls_learner_softly_and_access_is_revoked(env):
    cid = env.cls.class_id
    assert call(TEACHER, "POST", f"/api/classes/{cid}/materials/{DOC}/share").status_code == 200
    assert api_route.document_access.can_read(DOC, LEARNER)

    response = call(TEACHER, "DELETE", f"/api/institutions/classes/{cid}/enrollments/{LEARNER}")
    assert response.status_code == 200, response.text
    assert response.json() == {"class_id": cid, "learner_id": LEARNER, "status": "unenrolled"}

    assert call(TEACHER, "GET", f"/api/institutions/classes/{cid}/roster").json()["roster"] == [LEARNER2]
    assert env.projections[cid]["enrolled_learner_ids"] == [LEARNER2]
    assert not api_route.document_access.can_read(DOC, LEARNER)
    assert api_route.document_access.can_read(DOC, LEARNER2)
    record = env.svc._json_read_enrollment(env.svc.enrollments_dir / f"enr_{cid}_{LEARNER}.json")
    assert record["status"] == "unenrolled" and record["unenrolled_by"] == TEACHER   # history kept
    assert env.svc.get_membership(env.org.org_id, LEARNER).is_active                 # org membership kept
    assert "class.enrollment.removed" in actions(env, target_id=f"{cid}:{LEARNER}")


def test_unenroll_is_idempotent_and_reenroll_reactivates(env):
    cid = env.cls.class_id
    path = f"/api/institutions/classes/{cid}/enrollments/{LEARNER}"
    assert call(ADMIN, "DELETE", path).json()["status"] == "unenrolled"
    assert call(ADMIN, "DELETE", path).json()["status"] == "already_unenrolled"
    again = call(ADMIN, "POST", f"/api/institutions/classes/{cid}/enroll", json={"learner_id": LEARNER})
    assert again.status_code == 200 and again.json()["status"] == "active"
    assert set(call(ADMIN, "GET", f"/api/institutions/classes/{cid}/roster").json()["roster"]) == {LEARNER, LEARNER2}
    trail = [e["action"] for e in reversed(events(env, target_id=f"{cid}:{LEARNER}"))]
    assert trail == ["class.enrollment.removed", "class.enrollment.reactivated"]


def test_unenroll_denials_and_missing_enrollment(env):
    cid = env.cls.class_id
    never = str(uuid.uuid4())
    missing = call(ADMIN, "DELETE", f"/api/institutions/classes/{cid}/enrollments/{never}")
    assert missing.status_code == 404 and missing.json()["code"] == "ENROLLMENT_NOT_FOUND"
    for caller in (TEACHER2, LEARNER, OUTSIDER):   # unassigned teacher, learner, other tenant
        response = call(caller, "DELETE", f"/api/institutions/classes/{cid}/enrollments/{LEARNER}")
        assert response.status_code == 404 and response.json()["code"] == "CLASS_NOT_FOUND"
    assert LEARNER in call(ADMIN, "GET", f"/api/institutions/classes/{cid}/roster").json()["roster"]


# --- Teacher reassignment ---------------------------------------------------------------

def test_admin_reassigns_teachers_and_access_follows(env):
    cid = env.cls.class_id
    response = call(ADMIN, "PUT", f"/api/institutions/classes/{cid}/teachers", json={"teacher_ids": [TEACHER2]})
    assert response.status_code == 200, response.text
    assert response.json()["teacher_ids"] == [TEACHER2]
    assert call(TEACHER2, "GET", f"/api/institutions/classes/{cid}/roster").status_code == 200
    assert call(TEACHER, "GET", f"/api/institutions/classes/{cid}/roster").status_code == 404
    event = events(env, target_id=cid)[0]
    assert event["action"] == "class.teachers.updated"
    assert event["details"] == {"before": [TEACHER], "after": [TEACHER2]}


def test_teacher_reassignment_validation_and_denials(env):
    cid = env.cls.class_id
    path = f"/api/institutions/classes/{cid}/teachers"
    for invalid in ([OUTSIDER], [LEARNER], ["prof_vance"]):
        response = call(ADMIN, "PUT", path, json={"teacher_ids": invalid})
        assert response.status_code == 400 and response.json()["code"] == "INVALID_ASSIGNMENT"
    for caller in (TEACHER, OUTSIDER):
        assert call(caller, "PUT", path, json={"teacher_ids": [TEACHER2]}).status_code == 404
    assert call(ADMIN, "PUT", "/api/institutions/classes/cls_missing/teachers", json={"teacher_ids": []}).status_code == 404
    assert env.svc.get_class(cid).teacher_ids == [TEACHER]


# --- Concealment and the error envelope ---------------------------------------------------

@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "/roster", None),
    ("POST", "/enroll", {"learner_id": LEARNER}),
    ("PUT", "/teachers", {"teacher_ids": []}),
])
def test_missing_and_foreign_class_responses_are_identical(env, method, suffix, body):
    kwargs = {"json": body} if body is not None else {}
    foreign = call(OUTSIDER, method, f"/api/institutions/classes/{env.cls.class_id}{suffix}", **kwargs)
    missing = call(OUTSIDER, method, f"/api/institutions/classes/cls_nope{suffix}", **kwargs)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    for leaked in (env.org.org_id, OUTSIDER, "TEACHER", "ADMIN", "LEARNER"):
        assert leaked not in foreign.text


def test_authorization_errors_use_the_envelope_without_identifiers(env):
    response = call(TEACHER, "DELETE", f"/api/institutions/organizations/{env.org.org_id}/memberships/{LEARNER}")
    body = response.json()
    assert response.status_code == 403
    assert set(body) == {"error", "code", "message", "recoverable", "details", "detail"}
    assert body["error"] == "AUTHORIZATION_ERROR" and body["details"] == {}
    assert TEACHER not in response.text and env.org.org_id not in response.text


def test_unauthenticated_and_validation_errors_use_the_envelope(env):
    unauth = TestClient(app).get("/api/me")
    assert unauth.json()["error"] == "AUTHENTICATION_ERROR"
    assert unauth.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert unauth.json()["detail"] == "Missing bearer access token"          # legacy field kept
    invalid = call(ADMIN, "POST", "/api/institutions/memberships", json={"org_id": env.org.org_id})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert isinstance(invalid.json()["detail"], list)                         # legacy list kept


# --- Export privacy (S2) ----------------------------------------------------------------

def test_deactivated_admin_with_a_valid_token_cannot_export_other_members_ids(env):
    """ADMIN created the org, added every member and was later deactivated by ADMIN2.
    The token is still valid, so /api/me/export works, but it must not hand back
    the identifiers of the people ADMIN once managed."""
    org = env.org.org_id
    assert call(ADMIN2, "DELETE", f"/api/institutions/organizations/{org}/memberships/{ADMIN}").status_code == 200
    assert call(ADMIN, "GET", f"/api/institutions/organizations/{org}/memberships").status_code == 403  # access gone

    response = call(ADMIN, "GET", "/api/me/export")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["memberships"] == [{**body["memberships"][0], "org_id": org, "is_active": False}]
    actions = [e["action"] for e in body["audit_events_as_actor"]]
    assert "org.created" in actions and actions.count("membership.created") == 5   # own history kept
    for other in (ADMIN2, TEACHER, TEACHER2, LEARNER, LEARNER2, OUTSIDER):
        assert other not in response.text, "third-party identifier leaked through the export"
    redacted = [e for e in body["audit_events_as_actor"] if e["action"] == "membership.created"]
    assert all(e["redacted"] and e["target_id"] is None for e in redacted)
    assert all(e["details"] == {"role": e["details"]["role"]} for e in redacted)


def test_teacher_export_keeps_class_history_without_learner_ids(env):
    body = call(TEACHER, "GET", "/api/me/export").json()
    created = [e for e in body["audit_events_as_actor"] if e["action"] == "class.created"]
    assert len(created) == 1
    assert created[0]["target_id"] == env.cls.class_id and created[0]["redacted"] is True
    assert "enrolled_learner_ids" not in created[0]["details"] and "teacher_ids" not in created[0]["details"]
    text = str(body["audit_events_as_actor"])
    assert LEARNER not in text and LEARNER2 not in text
    assert body["owned_document_ids"] == [DOC]                 # personal data unaffected


def test_export_event_projection_rules():
    from backend.services.institution_service import _export_audit_event

    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    base = {"event_id": "e1", "occurred_at": "t", "actor_user_id": me, "org_id": "org_1"}
    own = _export_audit_event({**base, "action": "membership.role_changed", "target_type": "membership",
                               "target_id": me, "details": {"role": "TEACHER", "previous_role": "ADMIN"}}, me)
    assert own["target_id"] == me and own["redacted"] is False and own["details"]["previous_role"] == "ADMIN"
    theirs = _export_audit_event({**base, "action": "membership.created", "target_type": "membership",
                                  "target_id": other, "details": {"role": "LEARNER"}}, me)
    assert theirs["target_id"] is None and theirs["redacted"] is True
    enrollment = _export_audit_event({**base, "action": "class.enrollment.removed", "target_type": "enrollment",
                                      "target_id": f"cls_1:{other}",
                                      "details": {"class_id": "cls_1", "learner_id": other}}, me)
    assert enrollment["target_id"] == "cls_1" and enrollment["details"] == {"class_id": "cls_1"}
    share = _export_audit_event({**base, "action": "document.share.granted", "target_type": "document",
                                 "target_id": "doc_mine", "details": {"class_id": "cls_1"}}, me)
    assert share["target_id"] == "doc_mine" and share["redacted"] is False
    teachers = _export_audit_event({**base, "action": "class.teachers.updated", "target_type": "class",
                                    "target_id": "cls_1", "details": {"before": [other], "after": [me]}}, me)
    assert teachers["details"] == {} and teachers["redacted"] is True
    assert other not in str([theirs, enrollment, share, teachers])


# --- F7: one concealment code for every class-scoped route --------------------------------

@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "/knowledge-state", None),
    ("GET", "/student-mastery", None),
    ("GET", "/student-learning-insights", None),
    ("POST", "/teaching-optimizer/plan", {}),
    ("POST", "/interventions/iv1/approve", {}),
    ("POST", "/interventions/iv1/evaluate", {"target_concept_id": "k"}),
    ("POST", f"/materials/{DOC}/share", None),
])
def test_class_analytics_and_sharing_conceal_with_class_not_found(env, method, suffix, body):
    kwargs = {"json": body} if body is not None else {}
    foreign = call(OUTSIDER, method, f"/api/classes/{env.cls.class_id}{suffix}", **kwargs)
    missing = call(OUTSIDER, method, f"/api/classes/cls_nope{suffix}", **kwargs)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["code"] == "CLASS_NOT_FOUND"
    assert foreign.json()["message"] == foreign.json()["detail"] == "Class not found."   # unchanged text


def test_class_analytics_subject_mismatch_uses_the_same_code(env):
    response = call(TEACHER, "GET", f"/api/classes/{env.cls.class_id}/knowledge-state?subject_id=other_doc")
    assert response.status_code == 404 and response.json()["code"] == "CLASS_NOT_FOUND"


# --- F8: Role-escalation prevention and authorized role-switching ---------------------------

def test_student_cannot_escalate_to_teacher(env):
    response = call(LEARNER, "PATCH", "/api/me/role", json={"role": "TEACHER"})
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN_ROLE_ESCALATION"
    assert "TEACHER" in data["detail"] or "TEACHER" in data["message"]


def test_student_cannot_escalate_to_admin(env):
    response = call(LEARNER, "PATCH", "/api/me/role", json={"role": "ADMIN"})
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN_ROLE_ESCALATION"
    assert "ADMIN" in data["detail"] or "ADMIN" in data["message"]


def test_teacher_cannot_escalate_to_admin(env):
    response = call(TEACHER, "PATCH", "/api/me/role", json={"role": "ADMIN"})
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN_ROLE_ESCALATION"


def test_authorized_multi_role_admin_switches_between_assigned_roles(env):
    # Admin switches active view to TEACHER
    res_teacher = call(ADMIN, "PATCH", "/api/me/role", json={"role": "TEACHER"})
    assert res_teacher.status_code == 200
    assert res_teacher.json()["active_role"] == "TEACHER"

    # Admin switches active view to LEARNER
    res_learner = call(ADMIN, "PATCH", "/api/me/role", json={"role": "LEARNER"})
    assert res_learner.status_code == 200
    assert res_learner.json()["active_role"] == "LEARNER"

    # Verify that underlying DB membership was NOT modified or downgraded
    mems = asyncio.run(env.svc.list_memberships_for_user_async(ADMIN))
    assert any(m["role"] == UserRole.ADMIN for m in mems)


def test_teacher_can_switch_to_learner_view_without_membership_loss(env):
    res = call(TEACHER, "PATCH", "/api/me/role", json={"role": "LEARNER"})
    assert res.status_code == 200
    assert res.json()["active_role"] == "LEARNER"

    # Verify underlying DB membership still retains TEACHER
    mems = asyncio.run(env.svc.list_memberships_for_user_async(TEACHER))
    assert any(m["role"] == UserRole.TEACHER for m in mems)


def test_missing_or_invalid_jwt_rejected_on_role_patch(env):
    client = TestClient(app, raise_server_exceptions=False)
    # Missing authorization header
    res_missing = client.patch("/api/me/role", json={"role": "TEACHER"})
    assert res_missing.status_code == 401

    # Invalid authorization header
    res_invalid = client.patch(
        "/api/me/role",
        headers={"Authorization": "Bearer invalid.mock.token"},
        json={"role": "TEACHER"}
    )
    assert res_invalid.status_code == 401


def test_role_switch_across_different_organization_memberships(env):
    # TEACHER is in 'Org One', NOT in 'Org Two'
    res_wrong_org = call(TEACHER, "PATCH", "/api/me/role", json={"role": "TEACHER", "org_name": "Org Two"})
    assert res_wrong_org.status_code == 403
    assert res_wrong_org.json()["code"] == "FORBIDDEN_ORG_MEMBERSHIP"

    # OUTSIDER is ADMIN in 'Org Two', but NOT in 'Org One'
    res_outsider_org_one = call(OUTSIDER, "PATCH", "/api/me/role", json={"role": "ADMIN", "org_name": "Org One"})
    assert res_outsider_org_one.status_code == 403
    assert res_outsider_org_one.json()["code"] == "FORBIDDEN_ORG_MEMBERSHIP"

    # OUTSIDER in 'Org Two' succeeds
    res_outsider_org_two = call(OUTSIDER, "PATCH", "/api/me/role", json={"role": "ADMIN", "org_name": "Org Two"})
    assert res_outsider_org_two.status_code == 200
    assert res_outsider_org_two.json()["active_role"] == "ADMIN"


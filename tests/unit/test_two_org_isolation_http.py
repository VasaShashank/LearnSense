"""HTTP-level two-organization negative tests.

Org A and org B each have an admin, a teacher, a class, a learner and an uploaded
document. Requests are made as org B principals (and as a same-org learner)
against org A's resources. Positive controls prove the fixture is wired so a
denial is meaningful rather than the result of a broken setup.

Uses the real InstitutionService (JSON mode, tmp_path), real ownership/share/job
repositories (tmp_path) and ``get_current_user`` dependency overrides. No Supabase,
PostgreSQL or repository ``storage/`` writes are involved.
"""

from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes import api as api_route
from backend.routes import documents as documents_route
from backend.services.institution_service import InstitutionService
from backend.services.learner_service import LearnerService
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.institution.models import UserRole
from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository
from storage.job_repository import JobRepository

ADMIN_A, TEACHER_A, LEARNER_A = (str(uuid.uuid4()) for _ in range(3))
ADMIN_B, TEACHER_B, LEARNER_B = (str(uuid.uuid4()) for _ in range(3))
DOC_A, DOC_B = "doc_org_a_material", "doc_org_b_material"
DENIED = (403, 404)


@pytest.fixture
def env(monkeypatch, tmp_path):
    # Importing backend.app loads DATABASE_URL from .env into os.environ. These tests
    # must be strictly offline: clear it, and make any pool acquisition fail loudly.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEARNSENSE_REQUIRE_PG", raising=False)

    async def _no_pool():
        raise AssertionError("two-org tests must never acquire a PostgreSQL pool")

    monkeypatch.setattr("backend.db.pg_connection.get_pg_pool", _no_pool)

    learners = LearnerStateRepository(str(tmp_path / "learners"))
    svc = InstitutionService(
        base_dir=str(tmp_path / "institutions"), learner_state_repo=learners
    )
    assert svc._pg_enabled is False, "refusing to run against PostgreSQL"
    # Keep the legacy analytics projection out of the repository's storage/ tree.
    projections: dict = {}

    def sync(class_id, subject_id, title, roster):
        projections[class_id] = {
            "class_id": class_id,
            "subject_id": subject_id,
            "class_name": title,
            "enrolled_learner_ids": list(roster),
        }

    def append(class_id, learner_id):
        projections[class_id]["enrolled_learner_ids"].append(learner_id)

    monkeypatch.setattr(svc, "_sync_class_to_teacher_storage", sync)
    monkeypatch.setattr(svc, "_append_learner_to_teacher_storage", append)

    ownership = DocumentOwnershipRepository(str(tmp_path / "owners"))
    shares = DocumentShareRepository(str(tmp_path / "shares"))
    jobs = JobRepository(str(tmp_path / "jobs"))
    ownership.claim(DOC_A, TEACHER_A)
    ownership.claim(DOC_B, TEACHER_B)

    for lid in (LEARNER_A, LEARNER_B):
        LearnerService(repo=learners).provision_authenticated_learner(lid)

    org_a = svc.create_organization("Org A")
    org_b = svc.create_organization("Org B")
    for org, admin, teacher, learner in (
        (org_a, ADMIN_A, TEACHER_A, LEARNER_A),
        (org_b, ADMIN_B, TEACHER_B, LEARNER_B),
    ):
        svc.add_membership(org.org_id, admin, UserRole.ADMIN)
        svc.add_membership(org.org_id, teacher, UserRole.TEACHER)
        svc.add_membership(org.org_id, learner, UserRole.LEARNER)
    class_a = svc.create_class(
        org_a.org_id, DOC_A, "Class A", [TEACHER_A], TEACHER_A, [LEARNER_A]
    )
    class_b = svc.create_class(
        org_b.org_id, DOC_B, "Class B", [TEACHER_B], TEACHER_B, [LEARNER_B]
    )

    # Teacher analytics spy: any call means authorization let the request through.
    calls: list = []

    def spy(name, result=None):
        def fn(*_a, **_k):
            calls.append(name)
            return result if result is not None else {"leaked": name}
        return fn

    teacher = SimpleNamespace(
        get_class=lambda cid: projections.get(cid),
        list_classes=lambda: list(projections.values()),
        load_intervention_plan=lambda _iid: SimpleNamespace(class_id=class_a.class_id),
        get_class_knowledge_state=spy("knowledge_state"),
        get_class_students_mastery=spy("student_mastery"),
        get_student_learning_insights=spy("insights"),
        create_intervention_plan=spy("plan"),
        approve_intervention_plan=spy("approve"),
        evaluate_intervention=spy("evaluate"),
    )

    monkeypatch.setattr(api_route, "institution_service", svc)
    monkeypatch.setattr(api_route, "document_ownership", ownership)
    monkeypatch.setattr(api_route, "document_shares", shares)
    monkeypatch.setattr(api_route, "job_repo", jobs)
    monkeypatch.setattr(api_route, "teacher_service", teacher)
    for access in (api_route.document_access, documents_route.document_access):
        monkeypatch.setattr(access, "ownership", ownership)
        monkeypatch.setattr(access, "shares", shares)
        monkeypatch.setattr(access, "institutions", svc)
    monkeypatch.setattr(documents_route, "ownership", ownership)
    monkeypatch.setattr(documents_route, "shares", shares)
    monkeypatch.setattr(
        documents_route.db,
        "get_document_job",
        lambda doc_id: {
            "owner_id": TEACHER_A if doc_id == DOC_A else TEACHER_B,
            "document_id": doc_id,
            "status": "completed",
            "page_count": 1,
            "processed_pages": 1,
        },
    )

    job = jobs.create_job("job_a", "a.pdf", owner_id=TEACHER_A)
    job["document_id"] = DOC_A
    job["status"] = "processing"
    jobs.save_job(job)

    return SimpleNamespace(
        svc=svc, ownership=ownership, shares=shares, jobs=jobs, calls=calls,
        class_a=class_a, class_b=class_b, org_a=org_a, org_b=org_b,
    )


def _call(user_id, method, path, **kwargs):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id, email=None
    )
    try:
        return TestClient(app, raise_server_exceptions=False).request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# --- Fixture sanity (positive controls) ------------------------------------

def test_positive_controls_org_a_principals_can_use_org_a_resources(env):
    cid = env.class_a.class_id
    roster = _call(TEACHER_A, "GET", f"/api/institutions/classes/{cid}/roster")
    assert roster.status_code == 200, roster.text
    assert roster.json()["roster"] == [LEARNER_A]

    analytics = _call(TEACHER_A, "GET", f"/api/classes/{cid}/knowledge-state")
    assert analytics.status_code == 200, analytics.text
    assert env.calls == ["knowledge_state"]

    assert _call(ADMIN_A, "GET", f"/api/institutions/classes/{cid}/roster").status_code == 200


# --- Roster ----------------------------------------------------------------

@pytest.mark.parametrize("caller", [TEACHER_B, ADMIN_B, LEARNER_B, LEARNER_A, str(uuid.uuid4())])
def test_roster_of_org_a_class_is_denied_to_non_staff_and_other_org(env, caller):
    response = _call(caller, "GET", f"/api/institutions/classes/{env.class_a.class_id}/roster")
    assert response.status_code in DENIED, response.text
    assert "roster" not in response.json()
    if caller != LEARNER_A:  # the error body echoes the caller's own ID
        assert LEARNER_A not in response.text


def test_class_listings_do_not_include_other_orgs_classes(env):
    for caller in (TEACHER_B, ADMIN_B):
        listed = _call(caller, "GET", "/api/institutions/classes")
        assert listed.status_code == 200
        ids = {c["class_id"] for c in listed.json()}
        assert env.class_a.class_id not in ids
        assert env.class_b.class_id in ids

        filtered = _call(
            caller, "GET", f"/api/institutions/classes?org_id={env.org_a.org_id}"
        )
        assert filtered.json() == []

        orgs = _call(caller, "GET", "/api/institutions/organizations").json()
        assert env.org_a.org_id not in {o["org_id"] for o in orgs}

        legacy = _call(caller, "GET", "/api/classes").json()
        assert env.class_a.class_id not in {c["class_id"] for c in legacy}


# --- Enrollment and membership ----------------------------------------------

@pytest.mark.parametrize("caller", [TEACHER_B, ADMIN_B, LEARNER_B, TEACHER_A])
def test_cross_org_learner_cannot_be_enrolled_in_org_a_class(env, caller):
    """Org-B actors cannot enroll anyone in A; A's teacher cannot import B's learner."""
    cid = env.class_a.class_id
    response = _call(
        caller, "POST", f"/api/institutions/classes/{cid}/enroll",
        json={"learner_id": LEARNER_B},
    )
    assert response.status_code in DENIED + (400,), response.text
    assert response.status_code != 200
    assert env.svc.get_class_roster(cid, TEACHER_A) == [LEARNER_A]


def test_org_b_teacher_cannot_enroll_own_learner_into_org_a_class(env):
    response = _call(
        TEACHER_B, "POST", f"/api/institutions/classes/{env.class_a.class_id}/enroll",
        json={"learner_id": LEARNER_A},
    )
    assert response.status_code in DENIED, response.text


def test_org_b_admin_cannot_grant_membership_in_org_a(env):
    response = _call(
        ADMIN_B, "POST", "/api/institutions/memberships",
        json={"org_id": env.org_a.org_id, "user_id": ADMIN_B, "role": "ADMIN"},
    )
    assert response.status_code in DENIED, response.text
    assert env.svc.get_membership(env.org_a.org_id, ADMIN_B) is None


def test_org_b_teacher_cannot_create_class_in_org_a(env):
    for path, body in (
        ("/api/institutions/classes", {
            "org_id": env.org_a.org_id, "subject_id": DOC_B,
            "title": "Hijack", "teacher_ids": [TEACHER_B],
        }),
        ("/api/classes", {
            "org_id": env.org_a.org_id, "subject_id": DOC_B,
            "class_name": "Hijack", "teacher_ids": [TEACHER_B],
        }),
    ):
        response = _call(TEACHER_B, "POST", path, json=body)
        assert response.status_code in DENIED, f"{path}: {response.text}"
    assert [c.title for c in env.svc.list_classes(env.org_a.org_id)] == ["Class A"]


# --- Document sharing --------------------------------------------------------

def _no_grants(env):
    return env.shares.list_all() == []


def test_sharing_is_denied_across_org_and_ownership_boundaries(env):
    a, b = env.class_a.class_id, env.class_b.class_id
    attempts = [
        (TEACHER_B, DOC_B, a),   # own document into someone else's class
        (TEACHER_B, DOC_A, b),   # someone else's document into own class
        (TEACHER_B, DOC_A, a),   # someone else's document into someone else's class
        (TEACHER_A, DOC_A, b),   # owner, but not assigned to that class
        (ADMIN_B, DOC_B, a),
        (LEARNER_A, DOC_A, a),   # same-org learner, not a teacher
    ]
    for user, doc, cls in attempts:
        response = _call(user, "POST", f"/api/classes/{cls}/materials/{doc}/share")
        assert response.status_code in DENIED, f"{user} {doc}->{cls}: {response.text}"
    assert _no_grants(env)


def test_org_b_cannot_revoke_org_a_share_and_learner_b_never_gains_access(env):
    a = env.class_a.class_id
    shared = _call(TEACHER_A, "POST", f"/api/classes/{a}/materials/{DOC_A}/share")
    assert shared.status_code == 200, shared.text

    # Positive control: the enrolled org-A learner is granted read access, org-B is not.
    assert api_route.document_access.can_read(DOC_A, LEARNER_A)
    assert not api_route.document_access.can_read(DOC_A, LEARNER_B)
    assert not api_route.document_access.can_read(DOC_A, TEACHER_B)

    for user in (TEACHER_B, ADMIN_B, LEARNER_B):
        response = _call(user, "DELETE", f"/api/classes/{a}/materials/{DOC_A}/share")
        assert response.status_code in DENIED, response.text
    assert len(env.shares.list_all()) == 1


def test_org_b_principals_cannot_read_or_use_org_a_document_via_routes(env):
    a = env.class_a.class_id
    assert _call(TEACHER_A, "POST", f"/api/classes/{a}/materials/{DOC_A}/share").status_code == 200
    for user in (TEACHER_B, LEARNER_B):
        for path in (
            f"/documents/{DOC_A}/status",
            f"/documents/{DOC_A}",
            f"/documents/{DOC_A}/structured",
            f"/api/subjects/{DOC_A}/graph",
            f"/api/subjects/{DOC_A}/concepts/c1/content",
            f"/api/learners/{user}/progress?subject_id={DOC_A}",
        ):
            response = _call(user, "GET", path)
            assert response.status_code == 404, f"{user} GET {path}: {response.status_code}"
        assert _call(user, "POST", f"/documents/{DOC_A}/cancel").status_code == 404
    listed = _call(TEACHER_B, "GET", "/api/subjects").json()
    assert DOC_A not in {s.get("subject_id") or s.get("id") for s in listed}


# --- Upload jobs -------------------------------------------------------------

def test_org_b_cannot_poll_or_cancel_org_a_upload_job(env):
    for user in (TEACHER_B, LEARNER_B):
        assert _call(user, "GET", "/api/sources/upload/status/job_a").status_code == 404
        assert _call(user, "POST", "/api/sources/upload/cancel/job_a").status_code == 404
    assert env.jobs.load_job("job_a")["cancelled"] is False

    # Positive control: the uploader can see it.
    assert _call(TEACHER_A, "GET", "/api/sources/upload/status/job_a").status_code == 200


# --- Class analytics ---------------------------------------------------------

ANALYTICS = [
    ("GET", "/api/classes/{c}/knowledge-state", None),
    ("GET", "/api/classes/{c}/student-mastery", None),
    ("GET", "/api/classes/{c}/student-learning-insights", None),
    ("POST", "/api/classes/{c}/teaching-optimizer/plan", {}),
    ("POST", "/api/classes/{c}/interventions/iv1/approve", {}),
    ("POST", "/api/classes/{c}/interventions/iv1/evaluate", {"target_concept_id": "k"}),
]


@pytest.mark.parametrize("method,template,body", ANALYTICS, ids=[a[1] for a in ANALYTICS])
@pytest.mark.parametrize(
    "caller", [TEACHER_B, ADMIN_B, LEARNER_B, LEARNER_A], ids=["teacher_b", "admin_b", "learner_b", "learner_a"]
)
def test_class_analytics_denied_outside_class_staff(env, method, template, body, caller):
    response = _call(
        caller, method, template.format(c=env.class_a.class_id),
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code in DENIED, response.text
    assert env.calls == [], "analytics service was invoked despite denial"
    assert "leaked" not in response.text

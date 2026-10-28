from types import SimpleNamespace
import uuid
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import AuthenticatedUser, get_current_user
from backend.routes import api as api_route
from backend.routes import documents as documents_route
from phase3.errors import AuthorizationError
from phase4.institution.models import UserRole
from backend.services.institution_service import InstitutionService
from phase3.learner.models import LearnerState
from phase3.storage.learner_repository import LearnerStateRepository
from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository
from storage.job_repository import JobRepository


OWNER = "930d3312-b6e9-4eed-bbf2-3ab690ea326a"
LEARNER = "58cbe066-938f-4a33-9697-e4e8a551df5b"
OUTSIDER = "6db63aab-84ab-4d46-b076-45f4213e0a96"
CLASS_ID = "cls_share_test"
DOCUMENT_ID = "doc_share_test"


class FakeInstitutionService:
    def __init__(self):
        self.course_class = SimpleNamespace(
            class_id=CLASS_ID,
            org_id="org_share_test",
            subject_id="course-subject",
            teacher_ids=[OWNER],
        )
        self.enrolled = {LEARNER}

    def get_class(self, class_id):
        return self.course_class if class_id == CLASS_ID else None

    def require_role(self, org_id, user_id, roles):
        if org_id != "org_share_test" or user_id != OWNER or UserRole.TEACHER not in roles:
            raise AuthorizationError("not an assigned teacher")
        return SimpleNamespace(role=UserRole.TEACHER, is_active=True)

    def is_active_learner_enrolled(self, class_id, user_id):
        return class_id == CLASS_ID and user_id in self.enrolled


def _as_user(user_id):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id, email=None
    )


@pytest.fixture
def sharing_env(monkeypatch, tmp_path):
    ownership = DocumentOwnershipRepository(str(tmp_path / "owners"))
    shares = DocumentShareRepository(str(tmp_path / "shares"))
    institutions = FakeInstitutionService()
    jobs = JobRepository(str(tmp_path / "jobs"))
    monkeypatch.setattr(api_route, "document_ownership", ownership)
    monkeypatch.setattr(api_route, "document_shares", shares)
    monkeypatch.setattr(api_route, "job_repo", jobs)
    monkeypatch.setattr(api_route, "institution_service", institutions)
    monkeypatch.setattr(api_route.document_access, "ownership", ownership)
    monkeypatch.setattr(api_route.document_access, "shares", shares)
    monkeypatch.setattr(api_route.document_access, "institutions", institutions)
    monkeypatch.setattr(documents_route, "ownership", ownership)
    monkeypatch.setattr(documents_route, "shares", shares)
    monkeypatch.setattr(documents_route.document_access, "ownership", ownership)
    monkeypatch.setattr(documents_route.document_access, "shares", shares)
    monkeypatch.setattr(documents_route.document_access, "institutions", institutions)
    monkeypatch.setattr(
        documents_route.db,
        "get_document_job",
        lambda _document_id: {
            "owner_id": OWNER,
            "document_id": DOCUMENT_ID,
            "status": "completed",
            "page_count": 1,
            "processed_pages": 1,
        },
    )
    ownership.claim(DOCUMENT_ID, OWNER)
    return SimpleNamespace(
        ownership=ownership,
        shares=shares,
        institutions=institutions,
        jobs=jobs,
        tmp_path=tmp_path,
    )


def test_missing_authentication_cannot_share_material():
    response = TestClient(app).post(
        f"/api/classes/{CLASS_ID}/materials/{DOCUMENT_ID}/share"
    )
    assert response.status_code == 401


def test_assigned_teacher_shares_and_revokes_with_enrolled_learner_access(
    sharing_env, monkeypatch
):
    env = sharing_env
    assert not api_route.document_access.can_read(DOCUMENT_ID, LEARNER)
    _as_user(OWNER)
    try:
        shared = TestClient(app).post(
            f"/api/classes/{CLASS_ID}/materials/{DOCUMENT_ID}/share"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert shared.status_code == 200, shared.text
    assert shared.json()["status"] == "shared"

    docs_root = env.tmp_path / "documents"
    asset_dir = docs_root / DOCUMENT_ID / "assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / "figure.png").write_bytes(b"png-bytes")
    monkeypatch.setattr(
        documents_route.storage,
        "get_document_dir",
        lambda _document_id: docs_root / DOCUMENT_ID,
    )
    monkeypatch.setattr(
        documents_route.storage,
        "load_structured_document",
        lambda _document_id: {
            "document_id": DOCUMENT_ID,
            "pages": [{"page_index": 0, "text": "shared page"}],
        },
    )
    listed = {}
    monkeypatch.setattr(
        api_route.source_service,
        "list_sources",
        lambda visible_document_ids, owner_scope: listed.update(
            visible_document_ids=visible_document_ids, owner_scope=owner_scope
        ) or [],
    )

    job_id = str(uuid.uuid4())
    job = env.jobs.create_job(job_id, "lesson.pdf", owner_id=OWNER)
    job["document_id"] = DOCUMENT_ID
    job["status"] = "done"
    job["result"] = {"document_id": DOCUMENT_ID}
    env.jobs.save_job(job)

    _as_user(LEARNER)
    try:
        client = TestClient(app)
        structured = client.get(f"/documents/{DOCUMENT_ID}/structured")
        page = client.get(f"/documents/{DOCUMENT_ID}/pages/0")
        asset = client.get(f"/documents/{DOCUMENT_ID}/assets/figure.png")
        doc_status = client.get(f"/documents/{DOCUMENT_ID}/status")
        source_status = client.get(f"/api/sources/upload/status/{job_id}")
        doc_cancel = client.post(f"/documents/{DOCUMENT_ID}/cancel")
        source_cancel = client.post(f"/api/sources/upload/cancel/{job_id}")
        source_list = client.get("/api/sources")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert structured.status_code == 200
    assert page.status_code == 200 and page.json()["text"] == "shared page"
    assert asset.status_code == 200 and asset.content == b"png-bytes"
    assert doc_status.status_code == 200
    assert source_status.status_code == 200
    assert source_status.json()["document_id"] == DOCUMENT_ID
    assert doc_cancel.status_code == 404
    assert source_cancel.status_code == 404
    assert env.jobs.load_owned_job(job_id, OWNER)["status"] == "done"
    assert source_list.status_code == 200
    assert DOCUMENT_ID in listed["visible_document_ids"]
    assert listed["owner_scope"] == LEARNER
    assert DOCUMENT_ID in api_route.document_access.accessible_document_ids(LEARNER)

    _as_user(OUTSIDER)
    try:
        client = TestClient(app)
        assert client.get(f"/documents/{DOCUMENT_ID}/structured").status_code == 404
        assert client.get(f"/documents/{DOCUMENT_ID}/pages/0").status_code == 404
        assert client.get(f"/documents/{DOCUMENT_ID}/assets/figure.png").status_code == 404
        assert client.get(f"/documents/{DOCUMENT_ID}/status").status_code == 404
        assert client.get(f"/api/sources/upload/status/{job_id}").status_code == 404
        assert client.post(f"/documents/{DOCUMENT_ID}/cancel").status_code == 404
        assert client.post(f"/api/sources/upload/cancel/{job_id}").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert env.jobs.load_owned_job(job_id, OWNER)["status"] == "done"

    _as_user(OWNER)
    try:
        revoked = TestClient(app).delete(
            f"/api/classes/{CLASS_ID}/materials/{DOCUMENT_ID}/share"
        )
        owner_read = TestClient(app).get(f"/documents/{DOCUMENT_ID}/structured")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert owner_read.status_code == 200
    assert not api_route.document_access.can_read(DOCUMENT_ID, LEARNER)

    _as_user(LEARNER)
    try:
        client = TestClient(app)
        after_revoke = client.get(f"/documents/{DOCUMENT_ID}/structured")
        after_revoke_job = client.get(f"/api/sources/upload/status/{job_id}")
        after_revoke_sources = client.get("/api/sources")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert after_revoke.status_code == 404
    assert after_revoke_job.status_code == 404
    assert after_revoke_sources.status_code == 200
    assert DOCUMENT_ID not in listed["visible_document_ids"]


@pytest.mark.parametrize("actor,document_owner", [("unassigned-teacher", OWNER), (OWNER, "other-owner")])
def test_unassigned_teacher_or_non_owner_cannot_share(
    sharing_env, actor, document_owner, monkeypatch
):
    env = sharing_env
    if document_owner != OWNER:
        env.ownership = DocumentOwnershipRepository(
            str(env.tmp_path / "replacement-owners")
        )
        env.ownership.claim(DOCUMENT_ID, document_owner)
        monkeypatch.setattr(api_route, "document_ownership", env.ownership)
    if actor == "unassigned-teacher":
        original = env.institutions.require_role

        def require_role(org_id, user_id, roles):
            if user_id == actor:
                raise AuthorizationError("not assigned")
            return original(org_id, user_id, roles)

        monkeypatch.setattr(env.institutions, "require_role", require_role)

    _as_user(actor)
    try:
        response = TestClient(app).post(
            f"/api/classes/{CLASS_ID}/materials/{DOCUMENT_ID}/share"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 404
    assert env.shares.list_for_document(DOCUMENT_ID) == []


def test_ownerless_legacy_material_cannot_be_shared_or_read(sharing_env):
    env = sharing_env
    legacy_id = "doc_legacy_share"
    _as_user(OWNER)
    try:
        response = TestClient(app).post(
            f"/api/classes/{CLASS_ID}/materials/{legacy_id}/share"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 404
    assert not api_route.document_access.can_read(legacy_id, LEARNER)


def test_arbitrary_or_missing_class_cannot_receive_a_share(sharing_env):
    _as_user(OWNER)
    try:
        response = TestClient(app).post(
            f"/api/classes/cls_not_assigned/materials/{DOCUMENT_ID}/share"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 404
    assert sharing_env.shares.list_for_document(DOCUMENT_ID) == []


def test_uploader_can_revoke_after_losing_class_assignment(sharing_env):
    env = sharing_env
    env.shares.grant(DOCUMENT_ID, CLASS_ID, OWNER, OWNER)
    env.institutions.course_class = None
    _as_user(OWNER)
    try:
        response = TestClient(app).delete(
            f"/api/classes/{CLASS_ID}/materials/{DOCUMENT_ID}/share"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert env.shares.list_for_document(DOCUMENT_ID) == []


def test_share_grants_are_persistent_idempotent_and_revoke_only_target_class(tmp_path):
    repo = DocumentShareRepository(str(tmp_path / "shares"))
    first = repo.grant(DOCUMENT_ID, CLASS_ID, OWNER, OWNER)
    repeated = repo.grant(DOCUMENT_ID, CLASS_ID, OWNER, OWNER)
    other = repo.grant(DOCUMENT_ID, "cls_other", OWNER, OWNER)
    reopened = DocumentShareRepository(str(tmp_path / "shares"))

    assert repeated == first
    assert {item["class_id"] for item in reopened.list_for_document(DOCUMENT_ID)} == {
        CLASS_ID,
        "cls_other",
    }
    assert reopened.revoke(DOCUMENT_ID, CLASS_ID, OWNER)
    assert not reopened.revoke(DOCUMENT_ID, CLASS_ID, OWNER)
    assert reopened.list_for_document(DOCUMENT_ID) == [other]


def test_json_institution_access_requires_active_learner_membership_and_enrollment(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    monkeypatch.chdir(tmp_path)
    learner_repo = LearnerStateRepository(str(tmp_path / "learner_states"))
    learner_repo.save_state(LearnerState(learner_id=LEARNER, identity_provider="supabase"))
    service = InstitutionService(
        base_dir=str(tmp_path / "institutions"), learner_state_repo=learner_repo
    )
    organization = service.create_organization("Share Test Organization")
    service.add_membership(organization.org_id, OWNER, UserRole.TEACHER)
    service.add_membership(organization.org_id, LEARNER, UserRole.LEARNER)
    course_class = service.create_class(
        org_id=organization.org_id,
        subject_id="subject-share-test",
        title="Share Test Class",
        teacher_ids=[OWNER],
        creator_user_id=OWNER,
    )
    enrollment_path = service.enrollments_dir / f"enr_{course_class.class_id}_{LEARNER}.json"
    enrollment_path.write_text(
        json.dumps({
            "enrollment_id": "enr_test",
            "class_id": course_class.class_id,
            "learner_id": LEARNER,
        }),
        encoding="utf-8",
    )

    assert service.is_active_learner_enrolled(course_class.class_id, LEARNER)
    assert not service.is_active_learner_enrolled(course_class.class_id, OUTSIDER)

    membership_path = service.members_dir / f"{organization.org_id}_{LEARNER}.json"
    membership = json.loads(membership_path.read_text(encoding="utf-8"))
    membership["is_active"] = False
    membership_path.write_text(json.dumps(membership), encoding="utf-8")
    assert not service.is_active_learner_enrolled(course_class.class_id, LEARNER)

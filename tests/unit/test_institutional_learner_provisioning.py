import asyncio
import json
import uuid

import pytest

from backend.services.institution_service import InstitutionService
from backend.services.learner_service import LearnerService
from phase3.errors import AuthorizationError
from phase3.learner.models import LearnerState
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.institution.models import UserRole


LEARNER_ID = str(uuid.UUID("a20d9df0-2792-4fc2-9d94-20ac476863e0"))
OTHER_ID = str(uuid.UUID("bb1d9df0-2792-4fc2-9d94-20ac476863e0"))


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("LEARNSENSE_REQUIRE_PG", "0")
    repo = LearnerStateRepository(str(tmp_path / "learners"))
    svc = InstitutionService(
        base_dir=str(tmp_path / "institutions"), learner_state_repo=repo
    )
    # Prevent the compatibility projection from writing under repository storage/classes.
    monkeypatch.setattr(svc, "_sync_class_to_teacher_storage", lambda *_args: None)
    monkeypatch.setattr(svc, "_append_learner_to_teacher_storage", lambda *_args: None)
    return svc, repo


def _admin(svc, org_id="org_test"):
    svc.add_membership(org_id, "verified-admin", UserRole.ADMIN)


def _provision(repo, learner_id=LEARNER_ID):
    return LearnerService(repo=repo).provision_authenticated_learner(learner_id)


def _class(svc, org_id, learner_ids=None):
    svc.add_membership(org_id, "verified-teacher", UserRole.TEACHER)
    return svc.create_class(
        org_id=org_id,
        subject_id="subject-test",
        title="Test class",
        teacher_ids=["verified-teacher"],
        creator_user_id="verified-teacher",
        enrolled_learner_ids=learner_ids or [],
    )


def test_admin_can_grant_learner_membership_to_provisioned_uuid(service):
    svc, repo = service
    org = svc.create_organization("Test organization")
    _admin(svc, org.org_id)
    _provision(repo)

    membership = asyncio.run(
        svc.add_membership_as_admin_async(
            org.org_id, "verified-admin", LEARNER_ID, UserRole.LEARNER
        )
    )

    assert membership.user_id == LEARNER_ID
    assert membership.role == UserRole.LEARNER


@pytest.mark.parametrize("target_id", ["student_alex", "not-a-uuid", str(uuid.uuid4())])
def test_learner_membership_rejects_non_uuid_or_unprovisioned_target(service, target_id):
    svc, _repo = service
    org = svc.create_organization("Test organization")
    _admin(svc, org.org_id)

    with pytest.raises(AuthorizationError):
        asyncio.run(
            svc.add_membership_as_admin_async(
                org.org_id, "verified-admin", target_id, UserRole.LEARNER
            )
        )

    assert svc.get_membership(org.org_id, target_id) is None


def test_learner_membership_rejects_unmarked_legacy_uuid_record(service):
    svc, repo = service
    org = svc.create_organization("Test organization")
    _admin(svc, org.org_id)
    repo.save_state(LearnerState(learner_id=LEARNER_ID))

    with pytest.raises(AuthorizationError):
        asyncio.run(
            svc.add_membership_as_admin_async(
                org.org_id, "verified-admin", LEARNER_ID, UserRole.LEARNER
            )
        )

    assert svc.get_membership(org.org_id, LEARNER_ID) is None
    assert repo.load_state(LEARNER_ID).identity_provider is None


def test_provenance_identity_mismatch_fails_closed(service):
    svc, repo = service
    org = svc.create_organization("Test organization")
    _admin(svc, org.org_id)
    wrong_path = repo.get_path(LEARNER_ID)
    wrong_path.write_text(
        json.dumps({"learner_id": OTHER_ID, "identity_provider": "supabase"}),
        encoding="utf-8",
    )

    with pytest.raises(AuthorizationError):
        asyncio.run(
            svc.add_membership_as_admin_async(
                org.org_id, "verified-admin", LEARNER_ID, UserRole.LEARNER
            )
        )

    assert svc.get_membership(org.org_id, LEARNER_ID) is None


def test_non_admin_cannot_grant_membership_even_for_provisioned_target(service):
    svc, repo = service
    org = svc.create_organization("Test organization")
    svc.add_membership(org.org_id, "not-admin", UserRole.TEACHER)
    _provision(repo)

    with pytest.raises(AuthorizationError, match="Only an active organization admin"):
        asyncio.run(
            svc.add_membership_as_admin_async(
                org.org_id, "not-admin", LEARNER_ID, UserRole.LEARNER
            )
        )

    assert svc.get_membership(org.org_id, LEARNER_ID) is None


def test_teacher_can_enroll_provisioned_learner(service):
    svc, repo = service
    org = svc.create_organization("Test organization")
    svc.add_membership(org.org_id, "verified-teacher", UserRole.TEACHER)
    svc.add_membership(org.org_id, LEARNER_ID, UserRole.LEARNER)
    _provision(repo)
    course_class = _class(svc, org.org_id)

    enrollment = svc.enroll_learner(
        course_class.class_id, LEARNER_ID, enroller_user_id="verified-teacher"
    )

    assert enrollment.learner_id == LEARNER_ID


@pytest.mark.parametrize("target_id", [LEARNER_ID, "student_alex"])
def test_enrollment_rejects_unprovisioned_or_non_uuid_learner(service, target_id):
    svc, _repo = service
    org = svc.create_organization("Test organization")
    svc.add_membership(org.org_id, "verified-teacher", UserRole.TEACHER)
    svc.add_membership(org.org_id, target_id, UserRole.LEARNER)
    course_class = _class(svc, org.org_id)

    with pytest.raises(AuthorizationError):
        svc.enroll_learner(
            course_class.class_id, target_id, enroller_user_id="verified-teacher"
        )


def test_unassigned_teacher_cannot_enroll_even_provisioned_learner(service):
    svc, repo = service
    org = svc.create_organization("Test organization")
    svc.add_membership(org.org_id, "assigned-teacher", UserRole.TEACHER)
    svc.add_membership(org.org_id, "other-teacher", UserRole.TEACHER)
    svc.add_membership(org.org_id, LEARNER_ID, UserRole.LEARNER)
    _provision(repo)
    course_class = svc.create_class(
        org_id=org.org_id,
        subject_id="subject-test",
        title="Test class",
        teacher_ids=["assigned-teacher"],
        creator_user_id="assigned-teacher",
    )

    with pytest.raises(AuthorizationError, match="not assigned"):
        svc.enroll_learner(
            course_class.class_id, LEARNER_ID, enroller_user_id="other-teacher"
        )


def test_initial_class_roster_rejects_unprovisioned_learner(service):
    svc, _repo = service
    org = svc.create_organization("Test organization")
    svc.add_membership(org.org_id, "verified-teacher", UserRole.TEACHER)
    svc.add_membership(org.org_id, LEARNER_ID, UserRole.LEARNER)

    with pytest.raises(AuthorizationError):
        _class(svc, org.org_id, learner_ids=[LEARNER_ID])

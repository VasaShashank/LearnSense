import json
import sqlite3
import uuid

import pytest

from phase3.learner.models import LearnerState
from phase3.storage.learner_repository import LearnerStateRepository
from backend.services.learning_service import LearningService
from storage.id_validation import validate_canonical_learner_id, validate_storage_id
from storage.idempotency import DurableIdempotencyTracker
from storage.repositories import ActiveSubjectRepository, SessionRepository
from phase4.models import FinalAssessmentSession
from phase5.validation.learner_state_validator import IdempotencyTracker


@pytest.mark.parametrize("bad_id", ["../escape", "..", "a/b", r"a\b", "", "has.dot", "x" * 129])
def test_storage_repositories_reject_malformed_ids_before_filesystem_access(tmp_path, bad_id):
    learner_repo = LearnerStateRepository(str(tmp_path / "learners"))
    session_repo = SessionRepository(str(tmp_path / "sessions"))
    active_repo = ActiveSubjectRepository(str(tmp_path / "active"))

    with pytest.raises(ValueError):
        learner_repo.get_path(bad_id)
    with pytest.raises(ValueError):
        session_repo.get_path(bad_id)
    with pytest.raises(ValueError):
        active_repo._get_path(bad_id)


def test_storage_paths_are_resolved_under_configured_roots(tmp_path):
    learner_root = tmp_path / "learners"
    session_root = tmp_path / "sessions"
    learner_repo = LearnerStateRepository(str(learner_root))
    session_repo = SessionRepository(str(session_root))

    learner_path = learner_repo.get_path("legacy_demo_01")
    session_path = session_repo.get_path("init_sess_01")
    assert learner_path.is_relative_to(learner_root.resolve())
    assert session_path.is_relative_to(session_root.resolve())
    assert session_repo.get_path("final_assessment_01").is_relative_to(session_root.resolve())


def test_active_subject_ids_do_not_strip_into_collisions_and_keep_valid_legacy_file(tmp_path):
    repo = ActiveSubjectRepository(str(tmp_path / "states"))
    path_a = repo.set_active_subject("learner_a", "subject_a")
    path_b = repo.set_active_subject("learner-a", "subject_b")
    assert path_a != path_b
    assert repo.get_active_subject("learner_a") == "subject_a"
    assert repo.get_active_subject("learner-a") == "subject_b"
    assert path_a.name == "active_subject_learner_a.json"

    with pytest.raises(ValueError):
        repo.set_active_subject("learner.a", "subject_c")


def test_conflicting_legacy_active_subject_file_is_not_overwritten(tmp_path):
    root = tmp_path / "states"
    repo = ActiveSubjectRepository(str(root))
    # This models an old sanitized collision (for example, legacy "learner.a"
    # sharing a filename with valid "learnera"). The stored identity is checked.
    conflicting = root / "active_subject_learnera.json"
    conflicting.write_text(json.dumps({"learner_id": "learner.a", "subject_id": "old"}), encoding="utf-8")
    with pytest.raises(ValueError, match="different learner"):
        repo.set_active_subject("learnera", "new")
    assert json.loads(conflicting.read_text(encoding="utf-8"))["subject_id"] == "old"


def test_learner_state_valid_legacy_demo_id_still_round_trips(tmp_path):
    repo = LearnerStateRepository(str(tmp_path / "states"))
    repo.save_state(LearnerState(learner_id="student_alex"))
    assert repo.load_state("student_alex").learner_id == "student_alex"


def test_saving_session_rejects_malformed_embedded_learner_id(tmp_path):
    repo = SessionRepository(str(tmp_path / "sessions"))
    session = FinalAssessmentSession(
        assessment_id="final_safe_path",
        learner_id="../outside",
        subject_id="subject-one",
    )
    with pytest.raises(ValueError, match="learner_id"):
        repo.save_final_assessment(session)
    assert not list((tmp_path / "sessions").glob("*.json"))


def test_canonical_learner_uuid_is_separate_from_legacy_demo_ids():
    canonical = str(uuid.uuid4())
    assert validate_canonical_learner_id(canonical) == canonical
    assert validate_storage_id("student_alex", name="learner_id") == "student_alex"
    with pytest.raises(ValueError):
        validate_canonical_learner_id("student_alex")
    with pytest.raises(ValueError):
        validate_canonical_learner_id(canonical.upper())


def test_scoped_idempotency_blocks_cross_owner_replay_and_preserves_same_owner_retry(tmp_path):
    tracker = DurableIdempotencyTracker(str(tmp_path / "idempotency.sqlite"))
    payload = {"score_pct": 91, "private_result": "owner-one"}
    tracker.mark_scoped_processed(
        "request-1", owner_id="owner-one", resource_id="assessment-1",
        operation="final_submit", response_payload=payload,
    )

    assert tracker.is_scoped_duplicate(
        "request-1", owner_id="owner-one", resource_id="assessment-1", operation="final_submit"
    )
    assert tracker.get_scoped_cached_response(
        "request-1", owner_id="owner-one", resource_id="assessment-1", operation="final_submit"
    ) == payload
    assert not tracker.is_scoped_duplicate(
        "request-1", owner_id="owner-two", resource_id="assessment-1", operation="final_submit"
    )
    assert tracker.get_scoped_cached_response(
        "request-1", owner_id="owner-two", resource_id="assessment-1", operation="final_submit"
    ) is None
    assert not tracker.is_scoped_duplicate(
        "request-1", owner_id="owner-one", resource_id="assessment-2", operation="final_submit"
    )
    assert not tracker.is_scoped_duplicate(
        "request-1", owner_id="owner-one", resource_id="assessment-1", operation="activity_response"
    )


def test_scoped_cache_schema_addition_preserves_legacy_records(tmp_path):
    db_path = str(tmp_path / "legacy.sqlite")
    old_tracker = DurableIdempotencyTracker(db_path)
    old_tracker.mark_processed("legacy-request", learner_id="legacy-learner", response_payload={"ok": True})

    upgraded = DurableIdempotencyTracker(db_path)
    assert upgraded.is_duplicate("legacy-request")
    assert upgraded.get_cached_response("legacy-request") == {"ok": True}
    assert upgraded.get_scoped_cached_response(
        "legacy-request", owner_id="legacy-learner", resource_id="unknown",
        operation="unknown",
    ) is None

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(idempotency_records)")}
        scoped_count = conn.execute("SELECT COUNT(*) FROM scoped_idempotency_records").fetchone()[0]
    assert columns == {"token", "learner_id", "response_json", "created_at", "expires_at"}
    assert scoped_count == 0


def test_final_assessment_checks_persisted_owner_before_cache_replay(tmp_path):
    session = FinalAssessmentSession(
        assessment_id="final_owner_check",
        learner_id="owner-one",
        subject_id="subject-one",
    )

    class SessionRepo:
        load_calls = 0

        def load_final_assessment(self, assessment_id):
            self.load_calls += 1
            assert assessment_id == session.assessment_id
            return session

    session_repo = SessionRepo()
    tracker = IdempotencyTracker(db_path=str(tmp_path / "service-idempotency.sqlite"))
    cached_payload = {"assessment_id": session.assessment_id, "score_pct": 88.0}
    tracker.mark_scoped_processed(
        "shared-request", owner_id=session.learner_id, resource_id=session.assessment_id,
        operation="final_assessment_submit", response_payload=cached_payload,
    )
    service = LearningService(
        session_repo=session_repo,
        question_bank_repo=object(),
        learner_service=object(),
        knowledge_service=object(),
        idempotency_tracker=tracker,
    )

    with pytest.raises(ValueError, match="does not belong"):
        service.submit_final_assessment(
            assessment_id=session.assessment_id,
            learner_id="owner-two",
            subject_id=session.subject_id,
            responses={},
            request_id="shared-request",
        )
    assert session_repo.load_calls == 1

    replay = service.submit_final_assessment(
        assessment_id=session.assessment_id,
        learner_id="owner-one",
        subject_id=session.subject_id,
        responses={},
        request_id="shared-request",
    )
    assert replay["duplicate_submission"] is True
    assert replay["score_pct"] == 88.0

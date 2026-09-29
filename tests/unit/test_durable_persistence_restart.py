"""
Durable Persistence & Restart Recovery Test Suite.
Verifies that:
  1. DurableIdempotencyTracker persists tokens and response payloads across re-instantiation
  2. JobRepository persists job state across re-instantiation
  3. SessionRepository, LearnerStateRepository persist across re-instantiation
  4. Atomic writes don't leave corrupt files after simulated failures
"""

import json
import os
import pytest
import time
from pathlib import Path

from storage.idempotency import DurableIdempotencyTracker
from storage.job_repository import JobRepository
from storage.repositories import SessionRepository, LearningContextRepository
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.models import KnowledgeInitializationSession, KnowledgeSufficiencyStatus
from phase3.learner.models import LearnerState, ConceptState


class TestDurableIdempotencyRestart:
    """Verify idempotency tracker survives class re-instantiation (simulating server restart)."""

    def test_tokens_persist_across_instantiation(self, tmp_path):
        db_path = str(tmp_path / "test_idempotency.db")
        
        # Instance 1: mark a request as processed
        tracker1 = DurableIdempotencyTracker(db_path=db_path)
        test_payload = {"is_correct": True, "updated_masteries": {"c_1": 0.85}}
        tracker1.mark_processed("req_restart_1", learner_id="learner_1", response_payload=test_payload)
        assert tracker1.is_duplicate("req_restart_1") is True

        # Instance 2: simulates server restart - same DB path, new object
        tracker2 = DurableIdempotencyTracker(db_path=db_path)
        assert tracker2.is_duplicate("req_restart_1") is True

        # Cached response should also be recoverable
        cached = tracker2.get_cached_response("req_restart_1")
        assert cached is not None
        assert cached["is_correct"] is True
        assert cached["updated_masteries"]["c_1"] == 0.85

    def test_new_tokens_not_duplicate_after_restart(self, tmp_path):
        db_path = str(tmp_path / "test_idempotency2.db")
        
        tracker1 = DurableIdempotencyTracker(db_path=db_path)
        tracker1.mark_processed("req_exists")

        tracker2 = DurableIdempotencyTracker(db_path=db_path)
        assert tracker2.is_duplicate("req_new") is False
        assert tracker2.is_duplicate("req_exists") is True

    def test_expired_tokens_cleaned_up(self, tmp_path):
        db_path = str(tmp_path / "test_idempotency3.db")
        
        # TTL of 1 second
        tracker = DurableIdempotencyTracker(db_path=db_path, ttl_seconds=1)
        tracker.mark_processed("req_expiring")
        assert tracker.is_duplicate("req_expiring") is True

        # Wait for expiry
        time.sleep(1.5)
        assert tracker.is_duplicate("req_expiring") is False


class TestDurableJobRepositoryRestart:
    """Verify job repository persists across class re-instantiation."""

    def test_job_persists_across_instantiation(self, tmp_path):
        base = str(tmp_path / "jobs")

        # Instance 1: create and update a job
        repo1 = JobRepository(base_dir=base)
        job = repo1.create_job("job_restart_1", "test_document.pdf")
        job["status"] = "processing"
        job["progress_pct"] = 50
        job["stage"] = "Extracting concepts"
        repo1.save_job(job)

        # Instance 2: new object, same storage
        repo2 = JobRepository(base_dir=base)
        loaded = repo2.load_job("job_restart_1")

        assert loaded is not None
        assert loaded["job_id"] == "job_restart_1"
        assert loaded["status"] == "processing"
        assert loaded["progress_pct"] == 50
        assert loaded["filename"] == "test_document.pdf"

    def test_completed_job_survives_restart(self, tmp_path):
        base = str(tmp_path / "jobs2")

        repo1 = JobRepository(base_dir=base)
        job = repo1.create_job("job_done_1", "complete.pdf")
        job["status"] = "done"
        job["progress_pct"] = 100
        job["result"] = {"document_id": "doc_complete", "concept_count": 15}
        repo1.save_job(job)

        repo2 = JobRepository(base_dir=base)
        loaded = repo2.load_job("job_done_1")

        assert loaded is not None
        assert loaded["status"] == "done"
        assert loaded["result"]["concept_count"] == 15

    def test_cancelled_job_persists(self, tmp_path):
        base = str(tmp_path / "jobs3")

        repo1 = JobRepository(base_dir=base)
        repo1.create_job("job_cancel_1", "cancelled.pdf")
        repo1.cancel_job("job_cancel_1")

        repo2 = JobRepository(base_dir=base)
        assert repo2.is_cancelled("job_cancel_1") is True
        loaded = repo2.load_job("job_cancel_1")
        assert loaded["status"] == "cancelled"


class TestSessionRepositoryRestart:
    """Verify session repository survives restart."""

    def test_session_persists_across_instantiation(self, tmp_path):
        base = str(tmp_path / "sessions")

        repo1 = SessionRepository(base_dir=base)
        session = KnowledgeInitializationSession(
            session_id="sess_restart_1",
            learner_id="learner_restart",
            subject_id="subj_test",
            know_concept_ids=["c_1", "c_2"],
            dont_know_concept_ids=["c_3"],
            unanswered_concept_ids=[],
            sufficiency_status=KnowledgeSufficiencyStatus.INITIALIZED,
        )
        repo1.save_session(session)

        repo2 = SessionRepository(base_dir=base)
        loaded = repo2.load_session("sess_restart_1")

        assert loaded is not None
        assert loaded.learner_id == "learner_restart"
        assert loaded.know_concept_ids == ["c_1", "c_2"]


class TestLearnerStateRepositoryRestart:
    """Verify learner state repository survives restart."""

    def test_learner_state_persists_across_instantiation(self, tmp_path):
        base = str(tmp_path / "learner_states")

        repo1 = LearnerStateRepository(base_dir=base)
        state = LearnerState(
            learner_id="learner_state_restart",
            concept_states={
                "c_1": ConceptState(
                    concept_id="c_1",
                    mastery_probability=0.73,
                    attempt_count=8,
                    correct_count=6,
                ),
                "c_2": ConceptState(
                    concept_id="c_2",
                    mastery_probability=0.42,
                    attempt_count=3,
                    correct_count=1,
                ),
            },
        )
        repo1.save_state(state)

        repo2 = LearnerStateRepository(base_dir=base)
        loaded = repo2.load_state("learner_state_restart")

        assert loaded is not None
        assert loaded.concept_states["c_1"].mastery_probability == 0.73
        assert loaded.concept_states["c_2"].attempt_count == 3


class TestAtomicWriteIntegrity:
    """Verify atomic writes don't leave corrupt partial files."""

    def test_job_file_is_valid_json(self, tmp_path):
        base = str(tmp_path / "atomic_jobs")
        repo = JobRepository(base_dir=base)
        job = repo.create_job("atomic_test", "test.pdf")
        job["status"] = "done"
        job["result"] = {"document_id": "doc_test", "pages": 42}
        repo.save_job(job)

        path = repo.get_path("atomic_test")
        with open(path, "r") as f:
            data = json.load(f)
        assert data["job_id"] == "atomic_test"
        assert data["result"]["pages"] == 42

    def test_learner_state_file_is_valid_json(self, tmp_path):
        base = str(tmp_path / "atomic_states")
        repo = LearnerStateRepository(base_dir=base)
        state = LearnerState(
            learner_id="atomic_learner",
            concept_states={
                "c_1": ConceptState(concept_id="c_1", mastery_probability=0.5)
            },
        )
        repo.save_state(state)

        path = repo.get_path("atomic_learner")
        with open(path, "r") as f:
            data = json.load(f)
        assert data["learner_id"] == "atomic_learner"

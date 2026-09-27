"""
Phase 7 Idempotency and Concurrency Test Suite.
Verifies Phase 5 IdempotencyTracker and duplicate submission prevention across concurrent requests.
"""

import pytest
from phase5.validation.learner_state_validator import IdempotencyTracker
from backend.services.learning_service import LearningService


def test_idempotency_tracker_basic():
    tracker = IdempotencyTracker()
    request_id = "req_123456_abc"

    assert tracker.is_duplicate(request_id) is False
    tracker.mark_processed(request_id)
    assert tracker.is_duplicate(request_id) is True


def test_duplicate_activity_response_prevention():
    service = LearningService()
    learner_id = "learner_idem_test"
    subject_id = "subj_algebra"
    concept_ids = ["c_var"]
    all_concepts = ["c_var", "c_eq"]
    req_id = "unique_req_999"

    # First submission
    resp1 = service.process_activity_response(
        learner_id=learner_id,
        subject_id=subject_id,
        concept_ids=concept_ids,
        correctness=1.0,
        all_subject_concept_ids=all_concepts,
        request_id=req_id,
    )
    assert resp1["duplicate_submission"] is False

    # Second submission with same request_id
    resp2 = service.process_activity_response(
        learner_id=learner_id,
        subject_id=subject_id,
        concept_ids=concept_ids,
        correctness=1.0,
        all_subject_concept_ids=all_concepts,
        request_id=req_id,
    )
    assert resp2["duplicate_submission"] is True
    # Mastery probabilities should be identical
    assert resp1["updated_masteries"]["c_var"] == resp2["updated_masteries"]["c_var"]

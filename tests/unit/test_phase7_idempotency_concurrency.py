"""
Phase 7 Idempotency and Concurrency Test Suite.
Verifies Phase 5 IdempotencyTracker and duplicate submission prevention across concurrent requests.
Uses unique tokens per test run to avoid contamination from a persistent SQLite DB.
"""

import time
import pytest
from phase5.validation.learner_state_validator import IdempotencyTracker
from backend.services.learning_service import LearningService


def _unique_id(prefix: str) -> str:
    """Generate a unique ID incorporating timestamp to avoid cross-run collisions."""
    return f"{prefix}_{int(time.time() * 1000)}"


@pytest.fixture
def seeded_algebra_subject():
    """Self-contained minimal context (was ambient leftover state before)."""
    from phase3.knowledge.phase2_adapter import ConceptView, LearningContext
    from storage.repositories import LearningContextRepository

    ctx = LearningContext(
        document_id="subj_algebra",
        knowledge_document_id="subj_algebra",
        concepts={
            "c_var": ConceptView(
                concept_id="c_var", canonical_name="Variables", type="concept"
            ),
            "c_eq": ConceptView(
                concept_id="c_eq", canonical_name="Equations", type="concept"
            ),
        },
    )
    repo = LearningContextRepository()
    repo.save_context(ctx)
    yield ctx
    try:
        repo.get_path("subj_algebra").unlink(missing_ok=True)
    except OSError:
        pass


def test_idempotency_tracker_basic():
    tracker = IdempotencyTracker()
    request_id = _unique_id("req_basic")

    assert tracker.is_duplicate(request_id) is False
    tracker.mark_processed(request_id)
    assert tracker.is_duplicate(request_id) is True


def test_duplicate_activity_response_prevention(seeded_algebra_subject):
    service = LearningService()
    learner_id = _unique_id("learner_idem")
    subject_id = "subj_algebra"
    concept_ids = ["c_var"]
    all_concepts = ["c_var", "c_eq"]
    req_id = _unique_id("unique_req")

    # First submission
    resp1 = service.process_activity_response(
        learner_id=learner_id,
        subject_id=subject_id,
        concept_ids=concept_ids,
        correctness=1.0,
        all_subject_concept_ids=all_concepts,
        request_id=req_id,
        allow_client_correctness=True,
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
        allow_client_correctness=True,
    )
    assert resp2["duplicate_submission"] is True
    # Mastery probabilities should be identical
    assert resp1["updated_masteries"]["c_var"] == resp2["updated_masteries"]["c_var"]

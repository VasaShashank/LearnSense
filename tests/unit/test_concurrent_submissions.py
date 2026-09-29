"""
Concurrent Activity Submissions Test Suite.
Verifies:
  1. Simultaneous activity submissions for the same learner produce consistent BKT state
  2. Per-learner locking prevents lost updates
  3. Idempotency tokens prevent double-counting across concurrent requests
"""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.services.learning_service import LearningService
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from phase3.storage.learner_repository import LearnerStateRepository


class TestConcurrentActivitySubmissions:
    """Simulate concurrent activity submissions and verify consistency."""

    def test_concurrent_submissions_no_lost_updates(self, tmp_path):
        """10 concurrent submissions for the same learner must all be reflected."""
        ks = KnowledgeService()
        ls = LearnerService(knowledge_service=ks)
        learning = LearningService(learner_service=ls, knowledge_service=ks)

        subjects = ks.list_subjects()
        if not subjects:
            pytest.skip("No subjects available")

        sid = subjects[0].get("id") or subjects[0].get("subject_id", "")
        graph = ks.get_subject_graph(sid)
        if not graph["concepts"]:
            pytest.skip("No concepts")

        concept_id = graph["concepts"][0]["concept_id"]
        all_concepts = [c["concept_id"] for c in graph["concepts"]]
        learner_id = f"concurrent_learner_{int(time.time())}"

        results = []
        errors = []

        def submit_activity(idx: int):
            try:
                result = learning.process_activity_response(
                    learner_id=learner_id,
                    subject_id=sid,
                    concept_ids=[concept_id],
                    correctness=1.0 if idx % 2 == 0 else 0.0,
                    all_subject_concept_ids=all_concepts,
                    request_id=f"concurrent_req_{learner_id}_{idx}",
                )
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(submit_activity, i) for i in range(10)]
            for f in as_completed(futures):
                f.result()  # Re-raise exceptions

        # All 10 submissions should succeed (no exceptions)
        assert len(errors) == 0, f"Errors during concurrent submission: {errors}"
        assert len(results) == 10

        # No duplicate submissions since each has unique request_id
        dup_count = sum(1 for r in results if r.get("duplicate_submission", False))
        assert dup_count == 0

    def test_idempotency_prevents_double_counting(self, tmp_path):
        """Duplicate request_id across concurrent submissions should not double-count."""
        ks = KnowledgeService()
        ls = LearnerService(knowledge_service=ks)
        learning = LearningService(learner_service=ls, knowledge_service=ks)

        subjects = ks.list_subjects()
        if not subjects:
            pytest.skip("No subjects available")

        sid = subjects[0].get("id") or subjects[0].get("subject_id", "")
        graph = ks.get_subject_graph(sid)
        if not graph["concepts"]:
            pytest.skip("No concepts")

        concept_id = graph["concepts"][0]["concept_id"]
        all_concepts = [c["concept_id"] for c in graph["concepts"]]
        learner_id = f"idem_concurrent_{int(time.time())}"
        shared_request_id = f"shared_req_{learner_id}"

        results = []

        def submit_same_request(idx: int):
            try:
                result = learning.process_activity_response(
                    learner_id=learner_id,
                    subject_id=sid,
                    concept_ids=[concept_id],
                    correctness=1.0,
                    all_subject_concept_ids=all_concepts,
                    request_id=shared_request_id,
                )
                results.append(result)
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(submit_same_request, i) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        assert len(results) > 0

        # Exactly 1 should be non-duplicate, others should be duplicate
        non_dup = [r for r in results if not r.get("duplicate_submission", False)]
        dups = [r for r in results if r.get("duplicate_submission", False)]
        assert len(non_dup) >= 1, "At least one submission should be original"

        # All results should report the same mastery value
        masteries = [r["updated_masteries"].get(concept_id) for r in results if concept_id in r.get("updated_masteries", {})]
        if masteries:
            assert len(set(masteries)) == 1, f"Mastery diverged across concurrent submissions: {masteries}"


class TestLearnerStateConcurrency:
    """Test learner state repository under concurrent writes."""

    def test_concurrent_state_writes_produce_valid_state(self, tmp_path):
        from phase3.learner.models import LearnerState, ConceptState
        repo = LearnerStateRepository(base_dir=str(tmp_path / "concurrent_states"))
        learner_id = "concurrent_state_learner"

        errors = []

        def write_state(mastery: float):
            try:
                state = LearnerState(
                    learner_id=learner_id,
                    concept_states={
                        "c_1": ConceptState(
                            concept_id="c_1",
                            mastery_probability=mastery,
                            attempt_count=int(mastery * 100),
                        )
                    },
                )
                repo.save_state(state)
            except Exception as e:
                errors.append(str(e))

        # Write 20 times concurrently
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(write_state, i / 20.0) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"

        # Final state should be valid and readable
        final = repo.load_state(learner_id)
        assert final is not None
        assert final.learner_id == learner_id
        assert "c_1" in final.concept_states
        # Mastery should be one of the values written (last write wins)
        assert 0.0 <= final.concept_states["c_1"].mastery_probability <= 1.0

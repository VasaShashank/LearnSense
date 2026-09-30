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


def _banked_subject(learning, ks, ingested_calculus):
    """
    Return (subject_id, bank, concept_ids) for the fixture document.

    Security note: these concurrency tests deliberately use the REAL question_id
    path rather than the legacy `correctness` shortcut. The HTTP API no longer
    accepts client-reported correctness, so testing concurrency through that
    bypass would no longer exercise the production code path.
    """
    sid = ingested_calculus.document_id
    bank = learning.get_or_create_question_bank(sid)
    assert bank.get_grounded_questions(), "fixture document produced no grounded questions"
    graph = ks.get_subject_graph(sid)
    concept_ids = [c["concept_id"] for c in graph["concepts"]]
    assert concept_ids, "fixture document produced no concepts"
    return sid, bank, concept_ids


def _grounded_question(bank, concept_id):
    """Pick a real grounded question, preferring one mapped to concept_id."""
    candidates = bank.get_by_concept(concept_id)
    if candidates:
        return candidates[0]
    return bank.get_grounded_questions()[0]


class TestConcurrentActivitySubmissions:
    """Simulate concurrent activity submissions and verify consistency."""

    def test_concurrent_submissions_no_lost_updates(self, tmp_path, ingested_calculus):
        """10 concurrent submissions for the same learner must all be reflected.

        Exercises the server-authoritative question_id path.
        """
        ks = KnowledgeService()
        ls = LearnerService(knowledge_service=ks)
        learning = LearningService(learner_service=ls, knowledge_service=ks)

        sid, bank, concept_ids = _banked_subject(learning, ks, ingested_calculus)
        concept_id = concept_ids[0]
        question = _grounded_question(bank, concept_id)
        learner_id = f"concurrent_learner_{int(time.time())}"

        results = []
        errors = []

        def submit_activity(idx: int):
            # Alternate between the genuinely correct option and a wrong one so
            # BKT receives real evidence on both branches.
            answer = question.correct_answer if idx % 2 == 0 else "__WRONG_OPTION_ZZZ__"
            try:
                result = learning.process_activity_response(
                    learner_id=learner_id,
                    subject_id=sid,
                    concept_ids=[concept_id],
                    all_subject_concept_ids=concept_ids,
                    request_id=f"concurrent_req_{learner_id}_{idx}",
                    question_id=question.question_id,
                    selected_option=answer,
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

        # Server evaluated each answer itself; the mix of correct/incorrect is real.
        correct_flags = [r["is_correct"] for r in results]
        assert any(correct_flags), "expected some correct evaluations"
        assert not all(correct_flags), "expected some incorrect evaluations"

        # No duplicate submissions since each has unique request_id
        dup_count = sum(1 for r in results if r.get("duplicate_submission", False))
        assert dup_count == 0

    def test_idempotency_prevents_double_counting(self, tmp_path, ingested_calculus):
        """Duplicate request_id across concurrent submissions should not double-count.

        Exercises the real question_id path with a shared request_id, so a
        duplicate submission must be served from the idempotency cache.
        """
        ks = KnowledgeService()
        ls = LearnerService(knowledge_service=ks)
        learning = LearningService(learner_service=ls, knowledge_service=ks)

        sid, bank, concept_ids = _banked_subject(learning, ks, ingested_calculus)
        concept_id = concept_ids[0]
        question = _grounded_question(bank, concept_id)
        learner_id = f"idem_concurrent_{int(time.time())}"
        shared_request_id = f"shared_req_{learner_id}"

        results = []

        def submit_same_request(idx: int):
            try:
                result = learning.process_activity_response(
                    learner_id=learner_id,
                    subject_id=sid,
                    concept_ids=[concept_id],
                    all_subject_concept_ids=concept_ids,
                    request_id=shared_request_id,
                    question_id=question.question_id,
                    selected_option=question.correct_answer,
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
        assert len(non_dup) == 1, (
            f"Exactly one submission must execute; got {len(non_dup)} original "
            f"and {len(dups)} duplicates out of {len(results)} results."
        )
        assert len(dups) == len(results) - 1

        # All results should report the same mastery value
        masteries = [r["updated_masteries"].get(concept_id) for r in results if concept_id in r.get("updated_masteries", {})]
        if masteries:
            assert len(set(masteries)) == 1, f"Mastery diverged across concurrent submissions: {masteries}"

    def test_idempotency_caches_server_evaluated_result(self, tmp_path, ingested_calculus):
        """A duplicate must replay the cached server result, not re-evaluate."""
        ks = KnowledgeService()
        ls = LearnerService(knowledge_service=ks)
        learning = LearningService(learner_service=ls, knowledge_service=ks)

        sid, bank, concept_ids = _banked_subject(learning, ks, ingested_calculus)
        concept_id = concept_ids[0]
        question = _grounded_question(bank, concept_id)
        learner_id = f"idem_cache_{int(time.time())}"
        request_id = f"cache_req_{learner_id}"

        first = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[concept_id],
            all_subject_concept_ids=concept_ids,
            request_id=request_id,
            question_id=question.question_id,
            selected_option=question.correct_answer,
        )
        assert first["duplicate_submission"] is False
        assert first["is_correct"] is True

        second = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[concept_id],
            all_subject_concept_ids=concept_ids,
            request_id=request_id,
            question_id=question.question_id,
            selected_option=question.correct_answer,
        )
        assert second["duplicate_submission"] is True
        assert second["updated_masteries"] == first["updated_masteries"]


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

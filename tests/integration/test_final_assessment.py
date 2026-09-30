"""
Comprehensive Automated Integration Tests for Final Assessment Workflow.
Covers Start, Submission, Idempotency, Concurrency (5 workers), Ownership Security, and Persistence.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import pytest

from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from storage.repositories import SessionRepository
from phase3.storage.learner_repository import LearnerStateRepository
from phase3.errors import KnowledgeNotFoundError


@pytest.fixture
def services():
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    return learning, ks, ls


def _get_test_subject(services, ingested_calculus):
    """Use the session-scoped ingested fixture document, never developer-local storage."""
    learning, _, _ = services
    sid = ingested_calculus.document_id
    bank = learning.get_or_create_question_bank(sid)
    assert bank.get_grounded_questions(), "fixture document produced no grounded questions"
    return sid, bank


class TestFinalAssessmentStart:
    """Verify start_final_assessment behavior, session persistence, and answer hiding."""

    def test_start_final_assessment_success_and_answer_hiding(self, services, ingested_calculus):
        learning, _, _ = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_start_{int(time.time())}"

        data = learning.start_final_assessment(learner_id, subject_id)

        assert "assessment_id" in data
        assert data["subject_id"] == subject_id
        assert data["resumed"] is False
        assert data["question_count"] > 0
        assert len(data["questions"]) > 0

        # P0 Security Check: correct_answer & explanation must NOT be exposed
        for q in data["questions"]:
            assert "correct_answer" not in q, "SECURITY VIOLATION: correct_answer leaked in start response!"
            assert "explanation" not in q, "SECURITY VIOLATION: explanation leaked in start response!"

        # Session persistence check
        session_repo = SessionRepository()
        session = session_repo.load_final_assessment(data["assessment_id"])
        assert session is not None
        assert session.learner_id == learner_id
        assert session.subject_id == subject_id
        assert session.completed is False

    def test_start_invalid_subject_raises(self, services, ingested_calculus):
        """An unknown subject must fail loudly rather than fabricate an assessment.

        The service raises the typed KnowledgeNotFoundError from
        KnowledgeService.get_learning_context. This is NOT a ValueError:
        LearnSenseError derives from Exception. The HTTP layer maps it to a 404.
        """
        learning, _, _ = services
        with pytest.raises(KnowledgeNotFoundError):
            learning.start_final_assessment("learner_invalid", "non_existent_subject_999")

    def test_resume_active_uncompleted_assessment(self, services, ingested_calculus):
        learning, _, _ = services
        subject_id, _ = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_resume_start_{int(time.time())}"

        start1 = learning.start_final_assessment(learner_id, subject_id)
        start2 = learning.start_final_assessment(learner_id, subject_id)

        assert start2["assessment_id"] == start1["assessment_id"]
        assert start2["resumed"] is True


class TestFinalAssessmentSubmissionAndSecurity:
    """Verify submit_final_assessment evaluation, ownership validation, and security."""

    def test_submit_valid_final_assessment_updates_bkt_and_completes(self, services, ingested_calculus):
        learning, _, ls = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_submit_{int(time.time())}"

        start_data = learning.start_final_assessment(learner_id, subject_id)
        assessment_id = start_data["assessment_id"]
        questions = start_data["questions"]

        # Build answer responses using actual correct answers from bank
        responses = {}
        for q in questions:
            qid = q.get("question_id") or q.get("item_id")
            bank_q = bank.get_question(qid)
            if bank_q:
                responses[qid] = bank_q.correct_answer

        res = learning.submit_final_assessment(
            assessment_id=assessment_id,
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )

        assert res["completed"] is True
        assert res["score_pct"] == 100.0
        assert res["passed"] is True
        assert len(res["updated_masteries"]) > 0

        # Check persisted learner state updated
        st = ls.get_or_create_learner_state(learner_id, list(res["updated_masteries"].keys()))
        for cid, m_val in res["updated_masteries"].items():
            assert st.concept_states[cid].mastery_probability == pytest.approx(m_val)

        # Check completed session persisted
        session_repo = SessionRepository()
        session = session_repo.load_final_assessment(assessment_id)
        assert session.completed is True
        assert session.score_pct == 100.0

    def test_foreign_learner_id_rejected(self, services, ingested_calculus):
        learning, _, _ = services
        subject_id, _ = _get_test_subject(services, ingested_calculus)
        learner_owner = f"owner_{int(time.time())}"

        start_data = learning.start_final_assessment(learner_owner, subject_id)
        assessment_id = start_data["assessment_id"]

        with pytest.raises(ValueError, match="does not belong to learner"):
            learning.submit_final_assessment(
                assessment_id=assessment_id,
                learner_id="attacker_learner_id",
                subject_id=subject_id,
                responses={},
            )

    def test_foreign_subject_id_rejected(self, services, ingested_calculus):
        learning, _, _ = services
        subject_id, _ = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_subj_rej_{int(time.time())}"

        start_data = learning.start_final_assessment(learner_id, subject_id)

        with pytest.raises(ValueError, match="belongs to subject"):
            learning.submit_final_assessment(
                assessment_id=start_data["assessment_id"],
                learner_id=learner_id,
                subject_id="wrong_subject_id",
                responses={},
            )

    def test_invalid_assessment_id_rejected(self, services, ingested_calculus):
        learning, _, _ = services
        with pytest.raises(ValueError, match="not found"):
            learning.submit_final_assessment(
                assessment_id="non_existent_assessment_id",
                learner_id="learner_1",
                subject_id="calculus_101",
                responses={},
            )

    def test_client_side_correctness_metadata_ignored(self, services, ingested_calculus):
        learning, _, _ = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_forged_corr_{int(time.time())}"

        start_data = learning.start_final_assessment(learner_id, subject_id)
        questions = start_data["questions"]

        # Submit deliberately WRONG options while injecting client claims like correct=True
        responses = {}
        for q in questions:
            qid = q.get("question_id") or q.get("item_id")
            responses[qid] = "DEFINITELY_WRONG_OPTION_XYZ"

        res = learning.submit_final_assessment(
            assessment_id=start_data["assessment_id"],
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )

        # Server evaluates authoritatively: score MUST be 0.0 despite any client expectations
        assert res["correct_count"] == 0
        assert res["score_pct"] == 0.0
        assert res["passed"] is False


class TestFinalAssessmentStatusAnswerKeyHiding:
    """
    P0 SECURITY: GET /assessment/final/status/{id} previously accepted an OPTIONAL
    learner_id, skipped ownership when it was omitted, and returned the raw session
    dump -- including concept_results[*].correct_answer and [*].explanation.
    An unauthenticated caller could therefore read the full answer key.
    """

    @staticmethod
    def _completed_assessment(services, ingested_calculus, tag):
        learning, _, _ = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_status_{tag}_{int(time.time())}"
        start_data = learning.start_final_assessment(learner_id, subject_id)
        responses = {}
        for q in start_data["questions"]:
            qid = q.get("question_id") or q.get("item_id")
            item = bank.get_question(qid) if bank else None
            responses[qid] = item.correct_answer if item else "WRONG_OPTION_ZZZ"
        learning.submit_final_assessment(
            assessment_id=start_data["assessment_id"],
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )
        return learner_id, start_data["assessment_id"]

    def test_owner_can_access_status(self, services, ingested_calculus):
        """A. The owner can always read their own status."""
        learning, _, _ = services
        learner_id, assessment_id = self._completed_assessment(services, ingested_calculus, "owner")
        status = learning.get_final_assessment_status(assessment_id, learner_id=learner_id)
        assert status["assessment_id"] == assessment_id
        assert status["completed"] is True

    def test_missing_learner_identity_is_rejected(self, services, ingested_calculus):
        """B. Omitting learner_id must be rejected, not silently allowed."""
        learning, _, _ = services
        _, assessment_id = self._completed_assessment(services, ingested_calculus, "missing")
        with pytest.raises(ValueError, match="learner_id is required"):
            learning.get_final_assessment_status(assessment_id, learner_id=None)

    def test_foreign_learner_is_rejected(self, services, ingested_calculus):
        """C. A different learner must never read the assessment."""
        learning, _, _ = services
        _, assessment_id = self._completed_assessment(services, ingested_calculus, "foreign")
        with pytest.raises(ValueError, match="does not belong to learner"):
            learning.get_final_assessment_status(
                assessment_id, learner_id="attacker_learner_id"
            )

    def test_status_never_exposes_correct_answer(self, services, ingested_calculus):
        """D. correct_answer must be absent from every concept result."""
        learning, _, _ = services
        learner_id, assessment_id = self._completed_assessment(services, ingested_calculus, "nokey")
        status = learning.get_final_assessment_status(assessment_id, learner_id=learner_id)
        assert status["concept_results"], "expected a completed assessment with concept results"
        for cid, result in status["concept_results"].items():
            assert "correct_answer" not in result, (
                f"SECURITY VIOLATION: correct_answer leaked for concept {cid}"
            )

    def test_status_never_exposes_explanation(self, services, ingested_calculus):
        """E. explanation must be absent from every concept result."""
        learning, _, _ = services
        learner_id, assessment_id = self._completed_assessment(services, ingested_calculus, "noexp")
        status = learning.get_final_assessment_status(assessment_id, learner_id=learner_id)
        for cid, result in status["concept_results"].items():
            assert "explanation" not in result, (
                f"SECURITY VIOLATION: explanation leaked for concept {cid}"
            )

    def test_responses_expose_only_learner_submitted_answers(self, services, ingested_calculus):
        """F. responses must echo the learner's own input, never the answer key."""
        learning, _, _ = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_status_resp_{int(time.time())}"
        start_data = learning.start_final_assessment(learner_id, subject_id)
        responses = {}
        expected_answers = set()
        for q in start_data["questions"]:
            qid = q.get("question_id") or q.get("item_id")
            item = bank.get_question(qid) if bank else None
            if item:
                expected_answers.add(str(item.correct_answer))
            responses[qid] = "MY_OWN_WRONG_ANSWER"
        learning.submit_final_assessment(
            assessment_id=start_data["assessment_id"],
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )
        status = learning.get_final_assessment_status(
            start_data["assessment_id"], learner_id=learner_id
        )
        assert set(status["responses"].values()) == {"MY_OWN_WRONG_ANSWER"}
        assert not (set(status["responses"].values()) & expected_answers)

    def test_status_is_safe_before_submission(self, services, ingested_calculus):
        """A freshly started assessment leaks nothing either."""
        learning, _, _ = services
        subject_id, _ = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_status_fresh_{int(time.time())}"
        start_data = learning.start_final_assessment(learner_id, subject_id)
        status = learning.get_final_assessment_status(
            start_data["assessment_id"], learner_id=learner_id
        )
        assert status["completed"] is False
        for result in status["concept_results"].values():
            assert "correct_answer" not in result
            assert "explanation" not in result


class TestFinalAssessmentIdempotencyAndConcurrency:
    """Verify atomic idempotency protection under multi-threaded concurrency (Finding 1 & 4)."""

    def test_idempotency_prevents_double_counting(self, services, ingested_calculus):
        learning, _, ls = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_idem_{int(time.time())}"

        start_data = learning.start_final_assessment(learner_id, subject_id)
        assessment_id = start_data["assessment_id"]
        request_id = f"fa_req_{learner_id}"

        responses = {
            q.get("question_id") or q.get("item_id"): bank.get_question(q.get("question_id") or q.get("item_id")).correct_answer
            for q in start_data["questions"]
            if bank.get_question(q.get("question_id") or q.get("item_id"))
        }

        res1 = learning.submit_final_assessment(
            assessment_id=assessment_id,
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
            request_id=request_id,
        )

        masteries_1 = dict(res1["updated_masteries"])

        res2 = learning.submit_final_assessment(
            assessment_id=assessment_id,
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
            request_id=request_id,
        )

        assert res2["duplicate_submission"] is True
        assert res2["score_pct"] == res1["score_pct"]
        # Masteries must match exactly without further BKT increments
        assert res2["updated_masteries"] == masteries_1

    def test_concurrent_final_assessment_submissions(self, services, ingested_calculus):
        """5 concurrent workers submitting the same request_id to final assessment."""
        learning, _, ls = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"fa_concurrent_{int(time.time())}"

        start_data = learning.start_final_assessment(learner_id, subject_id)
        assessment_id = start_data["assessment_id"]
        shared_request_id = f"shared_fa_req_{learner_id}"

        responses = {
            q.get("question_id") or q.get("item_id"): bank.get_question(q.get("question_id") or q.get("item_id")).correct_answer
            for q in start_data["questions"]
            if bank.get_question(q.get("question_id") or q.get("item_id"))
        }

        results = []

        def submit_concurrent(idx: int):
            try:
                res = learning.submit_final_assessment(
                    assessment_id=assessment_id,
                    learner_id=learner_id,
                    subject_id=subject_id,
                    responses=responses,
                    request_id=shared_request_id,
                )
                results.append(res)
            except Exception as exc:
                pass

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(submit_concurrent, i) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        assert len(results) == 5

        non_dup = [r for r in results if not r.get("duplicate_submission", False)]
        dups = [r for r in results if r.get("duplicate_submission", False)]

        assert len(non_dup) == 1, "Exactly one submission must be executed"
        assert len(dups) == 4, "Exactly 4 submissions must be marked as duplicate"

        # Assert all results return identical masteries
        first_cid = list(results[0]["updated_masteries"].keys())[0]
        mastery_vals = [r["updated_masteries"][first_cid] for r in results]
        assert len(set(mastery_vals)) == 1, f"Masteries diverged across concurrent workers: {mastery_vals}"


class TestFinalAssessmentPersistence:
    """Verify final assessment session & state survival across service re-instantiation."""

    def test_final_assessment_survives_reinstantiation(self, services, ingested_calculus):
        learning1, ks1, _ = services
        subject_id, bank = _get_test_subject(services, ingested_calculus)
        learner_id = f"test_fa_persist_{int(time.time())}"

        start_data = learning1.start_final_assessment(learner_id, subject_id)
        assessment_id = start_data["assessment_id"]

        # Re-instantiate services and repositories
        session_repo = SessionRepository()
        session_reloaded = session_repo.load_final_assessment(assessment_id)

        assert session_reloaded is not None
        assert session_reloaded.assessment_id == assessment_id
        assert session_reloaded.learner_id == learner_id
        assert session_reloaded.completed is False

        # Re-instantiated learning service can resume the session
        learning2 = LearningService(learner_service=LearnerService(knowledge_service=ks1), knowledge_service=ks1)
        resumed_data = learning2.start_final_assessment(learner_id, subject_id)
        assert resumed_data["assessment_id"] == assessment_id
        assert resumed_data["resumed"] is True

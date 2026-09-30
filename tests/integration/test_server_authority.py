"""
P0 Security Regression Tests: Server Authority & Ownership Enforcement.

These tests exercise the REAL HTTP surface (FastAPI TestClient) and the real
production service call paths, proving the fixes for the demonstrated
vulnerabilities found in the evidence audit:

  1. CLIENT-SUPPLIED CORRECTNESS BYPASS
     POST /api/learners/activity-response accepted `correctness: 1.0` with no
     question_id and applied authoritative BKT credit. A client could forge mastery.

  2. DIAGNOSTIC OWNERSHIP BYPASS
     start_diagnostic / submit_diagnostic accepted an OPTIONAL learner_id and only
     compared it `if learner_id and ...`. Omitting it skipped ownership entirely,
     letting any caller start AND submit another learner's diagnostic.

  3. FINAL ASSESSMENT ANSWER-KEY LEAK
     GET /api/assessment/final/status/{id} took an OPTIONAL learner_id and returned
     the raw session dump, including concept_results[*].correct_answer and
     [*].explanation, to any unauthenticated caller.

These are genuine regression tests: each one fails against the pre-fix code.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService


@pytest.fixture(scope="module")
def services():
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    return learning, ks, ls


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def subject_with_bank(services, ingested_calculus):
    """Use the session-scoped ingested fixture document, never developer-local storage."""
    learning, ks, _ = services
    sid = ingested_calculus.document_id
    bank = learning.get_or_create_question_bank(sid)
    assert bank.get_grounded_questions(), "fixture document produced no grounded questions"
    return sid, bank


def _unique(prefix):
    return f"{prefix}_{int(time.time() * 1000)}"


# ---------------------------------------------------------------------------
# 1. CLIENT-SUPPLIED CORRECTNESS BYPASS
# ---------------------------------------------------------------------------

class TestClientCorrectnessBypassIsClosed:
    """
    A client must never be able to assert its own correctness or forge mastery.
    The authoritative path is question_id -> server retrieves the question ->
    server evaluates the submitted answer -> BKT update.
    """

    def test_a_question_id_plus_selected_answer_works(self, client, subject_with_bank, services):
        """A. The real question_id path works end-to-end over HTTP."""
        subject_id, bank = subject_with_bank
        _, ks, _ = services
        graph = ks.get_subject_graph(subject_id)
        concept_id = graph["concepts"][0]["concept_id"]
        question = bank.get_grounded_questions()[0]
        learner_id = _unique("sec_activity_ok")

        resp = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": learner_id,
                "subject_id": subject_id,
                "concept_ids": [concept_id],
                "question_id": question.question_id,
                "selected_option": question.correct_answer,
                "request_id": _unique("req_ok"),
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["duplicate_submission"] is False
        # The server evaluated the answer itself.
        assert body["is_correct"] is True
        assert concept_id in body["updated_masteries"]

    def test_b_correct_answer_is_evaluated_server_side(self, client, subject_with_bank, services):
        """B. Submitting the true answer yields is_correct=True from the server."""
        subject_id, bank = subject_with_bank
        _, ks, _ = services
        concept_id = ks.get_subject_graph(subject_id)["concepts"][0]["concept_id"]
        question = bank.get_grounded_questions()[0]

        resp = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": _unique("sec_correct_yes"),
                "subject_id": subject_id,
                "concept_ids": [concept_id],
                "question_id": question.question_id,
                "selected_option": question.correct_answer,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_correct"] is True

    def test_c_incorrect_answer_is_evaluated_server_side(self, client, subject_with_bank, services):
        """C. Submitting a wrong answer yields is_correct=False from the server."""
        subject_id, bank = subject_with_bank
        _, ks, _ = services
        concept_id = ks.get_subject_graph(subject_id)["concepts"][0]["concept_id"]
        question = bank.get_grounded_questions()[0]

        wrong = "__definitely_not_the_correct_answer__"
        resp = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": _unique("sec_correct_no"),
                "subject_id": subject_id,
                "concept_ids": [concept_id],
                "question_id": question.question_id,
                "selected_option": wrong,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_correct"] is False

    def test_d_request_without_question_id_is_rejected(self, client, subject_with_bank, services):
        """D. No question_id and no correctness -> 400, not a silent success."""
        subject_id, _ = subject_with_bank
        _, ks, _ = services
        concept_id = ks.get_subject_graph(subject_id)["concepts"][0]["concept_id"]

        resp = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": _unique("sec_no_qid"),
                "subject_id": subject_id,
                "concept_ids": [concept_id],
            },
        )
        assert resp.status_code == 400
        assert "question_id" in resp.json()["detail"]

    def test_e_correctness_one_without_question_id_is_rejected(self, client, subject_with_bank, services):
        """
        E. THE EXPLOIT. correctness=1.0 with no question_id must be refused.
        This is the exact request that previously returned 200 and moved BKT.
        """
        subject_id, _ = subject_with_bank
        _, ks, _ = services
        concept_id = ks.get_subject_graph(subject_id)["concepts"][0]["concept_id"]

        resp = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": _unique("sec_forge"),
                "subject_id": subject_id,
                "concept_ids": [concept_id],
                "correctness": 1.0,
            },
        )
        assert resp.status_code == 400, (
            f"SECURITY VIOLATION: client-reported correctness was accepted: {resp.text}"
        )
        assert "question_id" in resp.json()["detail"]

    def test_f_client_cannot_forge_mastery(self, services, subject_with_bank, client):
        """
        F. A rejected forgery must leave BKT completely untouched.
        Pre-fix, mastery jumped 0.3 -> 0.6657 on a single forged request.
        """
        subject_id, _ = subject_with_bank
        _, ks, ls = services
        graph = ks.get_subject_graph(subject_id)
        concept_ids = [c["concept_id"] for c in graph["concepts"]]
        learner_id = _unique("sec_forge_state")

        state = ls.get_or_create_learner_state(learner_id, concept_ids)
        concept_id = concept_ids[0]
        before = state.concept_states[concept_id].mastery_probability

        for _ in range(3):
            resp = client.post(
                "/api/learners/activity-response",
                json={
                    "learner_id": learner_id,
                    "subject_id": subject_id,
                    "concept_ids": [concept_id],
                    "correctness": 1.0,
                },
            )
            assert resp.status_code == 400

        after_state = ls.get_or_create_learner_state(learner_id, concept_ids)
        after = after_state.concept_states[concept_id].mastery_probability
        assert after == before, (
            f"SECURITY VIOLATION: forged requests changed mastery {before} -> {after}"
        )

    def test_g_service_rejects_client_correctness_when_not_allowed(self, services, subject_with_bank):
        """
        G. The service-level guard: allow_client_correctness=False blocks the
        bypass even if a caller reaches the service directly.
        """
        learning, _, _ = services
        subject_id, _ = subject_with_bank
        _, ks, _ = services
        concept_id = ks.get_subject_graph(subject_id)["concepts"][0]["concept_id"]

        with pytest.raises(ValueError, match="Client-reported correctness"):
            learning.process_activity_response(
                learner_id=_unique("sec_service_guard"),
                subject_id=subject_id,
                concept_ids=[concept_id],
                correctness=1.0,
                allow_client_correctness=False,
            )

    def test_h_correctness_ignored_when_question_id_present(self, client, subject_with_bank, services):
        """
        H. If a question_id IS supplied, any client correctness claim is ignored and
        the server's own evaluation wins.
        """
        subject_id, bank = subject_with_bank
        _, ks, _ = services
        concept_id = ks.get_subject_graph(subject_id)["concepts"][0]["concept_id"]
        question = bank.get_grounded_questions()[0]

        resp = client.post(
            "/api/learners/activity-response",
            json={
                "learner_id": _unique("sec_claim_vs_truth"),
                "subject_id": subject_id,
                "concept_ids": [concept_id],
                "question_id": question.question_id,
                "selected_option": "__wrong_answer__",
                "correctness": 1.0,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_correct"] is False, (
            "SECURITY VIOLATION: client correctness overrode server evaluation"
        )


# ---------------------------------------------------------------------------
# 2. DIAGNOSTIC OWNERSHIP
# ---------------------------------------------------------------------------

class TestDiagnosticOwnership:
    """
    learner_id is an explicit caller-supplied identity, NOT authentication.
    But it can no longer be omitted where ownership matters.
    """

    @staticmethod
    def _session(services, ingested_calculus, tag):
        """Build a self-assessment session on the fixture document."""
        learning, ks, _ = services
        subject_id = ingested_calculus.document_id
        graph = ks.get_subject_graph(subject_id)
        concept_ids = [c["concept_id"] for c in graph["concepts"]]
        learner_id = _unique(f"diag_{tag}")
        session = learning.submit_self_assessment(
            learner_id=learner_id,
            subject_id=subject_id,
            selections={cid: "KNOW" for cid in concept_ids},
            all_concept_ids=concept_ids,
        )
        return learner_id, session.session_id

    def test_a_valid_learner_can_start_diagnostic(self, client, services, ingested_calculus):
        """A. The owner can start their own diagnostic."""
        learner_id, session_id = self._session(services, ingested_calculus, "owner")
        resp = client.post(
            "/api/initialization/diagnostic/start",
            json={"session_id": session_id, "learner_id": learner_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "questions" in body
        for q in body["questions"]:
            assert "correct_answer" not in q
            assert "explanation" not in q

    def test_b_missing_learner_identity_is_rejected(self, client, services, ingested_calculus):
        """B. Omitting learner_id is a 422 (required field) / 400, never a bypass."""
        _, session_id = self._session(services, ingested_calculus, "missing")
        resp = client.post(
            "/api/initialization/diagnostic/start",
            json={"session_id": session_id},
        )
        assert resp.status_code in (400, 422), (
            f"SECURITY VIOLATION: missing learner identity accepted: {resp.status_code}"
        )

    def test_c_foreign_learner_cannot_start_diagnostic(self, client, services, ingested_calculus):
        """C. A different learner is refused."""
        _, session_id = self._session(services, ingested_calculus, "foreign")
        resp = client.post(
            "/api/initialization/diagnostic/start",
            json={"session_id": session_id, "learner_id": "attacker_learner"},
        )
        assert resp.status_code in (400, 403), (
            f"SECURITY VIOLATION: foreign learner started a diagnostic: {resp.text}"
        )

    def test_d_foreign_learner_cannot_submit_diagnostic(self, client, services, ingested_calculus):
        """D. A different learner cannot submit and mutate the owner's state."""
        learner_id, session_id = self._session(services, ingested_calculus, "submitter")
        resp = client.post(
            "/api/initialization/diagnostic/submit",
            json={
                "session_id": session_id,
                "responses": {},
                "learner_id": "attacker_learner",
            },
        )
        assert resp.status_code in (400, 403), (
            f"SECURITY VIOLATION: foreign learner submitted a diagnostic: {resp.text}"
        )

    def test_e_owner_can_submit_diagnostic(self, client, services, ingested_calculus):
        """E. The owner can still submit successfully."""
        learner_id, session_id = self._session(services, ingested_calculus, "valid_submit")
        start = client.post(
            "/api/initialization/diagnostic/start",
            json={"session_id": session_id, "learner_id": learner_id},
        )
        assert start.status_code == 200, start.text
        resp = client.post(
            "/api/initialization/diagnostic/submit",
            json={"session_id": session_id, "responses": {}, "learner_id": learner_id},
        )
        assert resp.status_code == 200, resp.text
        assert "diagnostic_completed" in resp.json()

    def test_f_service_requires_learner_id(self, services, ingested_calculus):
        """F. The service itself refuses a missing identity (defence in depth)."""
        learning, _, _ = services
        _, session_id = self._session(services, ingested_calculus, "service_guard")
        with pytest.raises(ValueError, match="learner_id is required"):
            learning.start_diagnostic(session_id, learner_id=None)
        with pytest.raises(ValueError, match="learner_id is required"):
            learning.submit_diagnostic(session_id, {}, learner_id=None)


# ---------------------------------------------------------------------------
# 3. FINAL ASSESSMENT STATUS ANSWER-KEY LEAK
# ---------------------------------------------------------------------------

class TestFinalAssessmentStatusOverHttp:
    """The answer key must be unreachable over the real HTTP endpoint."""

    @staticmethod
    def _completed(services, ingested_calculus, tag):
        learning, ks, _ = services
        subject_id = ingested_calculus.document_id
        bank = learning.get_or_create_question_bank(subject_id)
        learner_id = _unique(f"status_{tag}")
        start = learning.start_final_assessment(learner_id, subject_id)
        responses = {}
        for q in start["questions"]:
            qid = q.get("question_id") or q.get("item_id")
            item = bank.get_question(qid)
            responses[qid] = item.correct_answer if item else "WRONG_ZZZ"
        learning.submit_final_assessment(
            assessment_id=start["assessment_id"],
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )
        return learner_id, start["assessment_id"]

    def test_a_owner_can_access_status(self, client, services, ingested_calculus):
        """A. The owner reads their own status successfully."""
        learner_id, assessment_id = self._completed(services, ingested_calculus, "owner")
        resp = client.get(f"/api/assessment/final/status/{assessment_id}",
                          params={"learner_id": learner_id})
        assert resp.status_code == 200, resp.text
        assert resp.json()["assessment_id"] == assessment_id

    def test_b_missing_learner_identity_is_rejected(self, client, services, ingested_calculus):
        """B. No learner_id -> 422 (required query param). Pre-fix this was 200."""
        _, assessment_id = self._completed(services, ingested_calculus, "missing")
        resp = client.get(f"/api/assessment/final/status/{assessment_id}")
        assert resp.status_code in (400, 422), (
            f"SECURITY VIOLATION: status readable without identity: {resp.status_code}"
        )

    def test_c_foreign_learner_is_rejected(self, client, services, ingested_calculus):
        """C. A different learner is refused."""
        _, assessment_id = self._completed(services, ingested_calculus, "foreign")
        resp = client.get(f"/api/assessment/final/status/{assessment_id}",
                          params={"learner_id": "attacker_learner"})
        assert resp.status_code in (400, 403, 404), (
            f"SECURITY VIOLATION: foreign learner read status: {resp.text}"
        )

    def test_d_and_e_no_answer_key_in_response(self, client, services, ingested_calculus):
        """D+E. Neither correct_answer nor explanation may appear anywhere."""
        learner_id, assessment_id = self._completed(services, ingested_calculus, "nokey")
        resp = client.get(f"/api/assessment/final/status/{assessment_id}",
                          params={"learner_id": learner_id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for cid, result in (body.get("concept_results") or {}).items():
            assert "correct_answer" not in result, f"correct_answer leaked for {cid}"
            assert "explanation" not in result, f"explanation leaked for {cid}"
        # And the raw JSON must not contain the keys anywhere at all.
        raw = resp.text
        assert '"correct_answer"' not in raw
        assert '"explanation"' not in raw

    def test_f_responses_do_not_expose_authoritative_answers(self, client, services, ingested_calculus):
        """F. responses echo only what the learner submitted."""
        learning, ks, _ = services
        subject_id = ingested_calculus.document_id
        bank = learning.get_or_create_question_bank(subject_id)
        learner_id = _unique("status_resp")
        start = learning.start_final_assessment(learner_id, subject_id)
        responses = {}
        for q in start["questions"]:
            qid = q.get("question_id") or q.get("item_id")
            responses[qid] = "MY_OWN_ANSWER_TEXT"
        learning.submit_final_assessment(
            assessment_id=start["assessment_id"],
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )
        resp = client.get(f"/api/assessment/final/status/{start['assessment_id']}",
                          params={"learner_id": learner_id})
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["responses"].values()) == {"MY_OWN_ANSWER_TEXT"}

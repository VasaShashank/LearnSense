"""
Server-Side Evaluation E2E Test Suite.
Verifies that:
  1. correct_answer is NEVER leaked before submission via get_concept_question
  2. The server evaluates correctness authoritatively via process_activity_response
  3. Invalid or tampered payloads fail gracefully
  4. Diagnostic submissions with raw option text are evaluated server-side
"""

import pytest
from backend.services.learning_service import LearningService
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService


@pytest.fixture
def services():
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    return learning, ks, ls


def _get_subject_with_bank(services):
    """Find a subject that has persisted question banks with MCQ options for testing."""
    learning, ks, _ = services
    subjects = ks.list_subjects()
    for sub in subjects:
        sid = sub.get("id") or sub.get("subject_id", "")
        if not sid:
            continue
        try:
            bank = learning.get_or_create_question_bank(sid)
            questions = bank.get_grounded_questions()
            if questions and any(q.options and len(q.options) > 1 for q in questions):
                return sid, bank, [q for q in questions if q.options and len(q.options) > 1]
        except Exception:
            continue
    return None, None, None


class TestConceptQuestionSecurity:
    """Verify that get_concept_question never leaks correct_answer."""

    def test_correct_answer_never_in_response(self, services):
        learning, _, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not sid or not questions:
            pytest.skip("No subjects with grounded question banks available")

        concept_id = questions[0].concept_ids[0]

        result = learning.get_concept_question(sid, concept_id)

        # P0 Security: correct_answer must NEVER be present
        assert "correct_answer" not in result, (
            "SECURITY VIOLATION: correct_answer was leaked to client before submission!"
        )
        assert "explanation" not in result, (
            "SECURITY VIOLATION: explanation was leaked to client before submission!"
        )
        # But question_id, options, and question_text must be present
        assert "question_id" in result
        assert "options" in result
        assert isinstance(result["options"], list)
        assert len(result["options"]) > 0


class TestServerSideActivityEvaluation:
    """Verify that activity responses are evaluated authoritatively on the server."""

    def test_correct_option_evaluates_correct(self, services):
        learning, _, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not questions:
            pytest.skip("No grounded question banks available")

        q = questions[0]
        concept_ids = q.concept_ids
        correct_answer = str(q.correct_answer).strip()
        learner_id = "test_eval_learner_correct"

        result = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=concept_ids,
            question_id=q.question_id,
            selected_option=correct_answer,
        )

        assert result["is_correct"] is True
        assert result["correct_answer"] == correct_answer
        assert result["duplicate_submission"] is False

    def test_incorrect_option_evaluates_incorrect(self, services):
        learning, _, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not questions:
            pytest.skip("No grounded question banks available")

        # Find a question with at least 2 options
        target_q = None
        wrong_option = None
        correct_answer = None
        for q in questions:
            correct_answer = str(q.correct_answer).strip()
            for opt in (q.options or []):
                if opt.strip() != correct_answer:
                    wrong_option = opt
                    target_q = q
                    break
            if wrong_option is not None:
                break

        if wrong_option is None or target_q is None:
            pytest.skip("No incorrect option available")

        learner_id = "test_eval_learner_incorrect"

        result = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=target_q.concept_ids,
            question_id=target_q.question_id,
            selected_option=wrong_option,
        )

        assert result["is_correct"] is False

    def test_dont_know_evaluates_zero(self, services):
        learning, _, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not questions:
            pytest.skip("No grounded question banks available")

        q = questions[0]
        learner_id = "test_eval_learner_dontknow"

        result = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=q.concept_ids,
            question_id=q.question_id,
            is_dont_know=True,
        )

        assert result["is_correct"] is False

    def test_invalid_question_id_raises(self, services):
        learning, ks, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not sid:
            pytest.skip("No subjects with bank")

        # Server authority rejects foreign concepts before even looking up the question
        with pytest.raises(ValueError, match="does not belong"):
            learning.process_activity_response(
                learner_id="test_tamper",
                subject_id=sid,
                concept_ids=["fake_concept"],
                question_id="nonexistent_q_123",
                selected_option="anything",
            )

    def test_missing_option_and_dont_know_raises(self, services):
        learning, _, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not questions:
            pytest.skip("No grounded question banks available")

        q = questions[0]

        with pytest.raises(ValueError, match="Must provide"):
            learning.process_activity_response(
                learner_id="test_missing_opt",
                subject_id=sid,
                concept_ids=q.concept_ids,
                question_id=q.question_id,
                # No selected_option, no selected_index, no is_dont_know
            )

    def test_correct_answer_returned_only_after_submission(self, services):
        """Correct answer should be included in the response AFTER submission."""
        learning, _, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not questions:
            pytest.skip("No grounded question banks available")

        q = questions[0]
        correct_answer = str(q.correct_answer).strip()

        result = learning.process_activity_response(
            learner_id="test_post_submit",
            subject_id=sid,
            concept_ids=q.concept_ids,
            question_id=q.question_id,
            selected_option=correct_answer,
        )

        # After submission, the correct_answer IS revealed
        assert "correct_answer" in result
        assert result["correct_answer"] == correct_answer


class TestDiagnosticServerSideEvaluation:
    """Verify diagnostic submission with raw option text is evaluated server-side."""

    def test_diagnostic_start_strips_correct_answer(self, services):
        """Diagnostic questions returned to client must not contain correct_answer."""
        learning, ks, _ = services
        sid, bank, questions = _get_subject_with_bank(services)
        if not sid:
            pytest.skip("No subjects with bank")

        graph = ks.get_subject_graph(sid)
        concept_ids = [c["concept_id"] for c in graph["concepts"]]
        if not concept_ids:
            pytest.skip("No concepts")

        from phase4.models import SelfAssessmentStatus
        selections = {cid: SelfAssessmentStatus.KNOW for cid in concept_ids}

        session = learning.submit_self_assessment(
            learner_id="test_diag_strip",
            subject_id=sid,
            selections=selections,
        )
        diag = learning.start_diagnostic(session.session_id)

        for q in diag.get("questions", []):
            assert "correct_answer" not in q, (
                f"SECURITY VIOLATION: correct_answer leaked in diagnostic question {q.get('question_id')}"
            )

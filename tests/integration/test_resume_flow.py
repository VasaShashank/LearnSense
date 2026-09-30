"""
Integration Test Suite for Learner State Resume Flow and GET /learners/{id}/resume API.
Covers new learners, initialized state, active final assessment resume, completed assessment status, and persistence across re-instantiation.
"""

import time
import pytest
from backend.services.knowledge_service import KnowledgeService
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService


@pytest.fixture
def services():
    ks = KnowledgeService()
    ls = LearnerService(knowledge_service=ks)
    learning = LearningService(learner_service=ls, knowledge_service=ks)
    return learning, ks, ls


def _get_valid_subject(ks, learning=None):
    """
    Return a subject that can actually produce a grounded question bank.

    The previous implementation returned ``subjects[0]`` unconditionally. Several
    committed subjects carry a LearningContext but no StructuredDocument (e.g.
    calculus_101, machine_learning, subj_algebra, subj_calculus), so selecting the
    first entry made every final-assessment test in this file fail with
    QuestionBankError. A missing required fixture must FAIL, not SKIP.
    """
    subjects = ks.list_subjects()
    if not subjects:
        pytest.fail("No subjects available. This is a required fixture, not an optional one.")

    if learning is not None:
        for sub in subjects:
            sid = sub.get("id") or sub.get("subject_id", "")
            if not sid:
                continue
            try:
                bank = learning.get_or_create_question_bank(sid)
                if bank.get_grounded_questions():
                    return sid
            except Exception:
                continue
        pytest.fail(
            "No subject with a grounded question bank is available. "
            "This is a required fixture, not an optional one."
        )

    return subjects[0].get("id") or subjects[0].get("subject_id", "")


class TestLearnerResumeFlow:
    """Verify LearnerService.resume_learner_state and resume behavior across all lifecycle phases."""

    def test_new_learner_resume_returns_no_state(self, services, ingested_calculus):
        _, _, ls = services
        new_learner_id = f"new_learner_{int(time.time())}"

        data = ls.resume_learner_state(new_learner_id)

        assert data["learner_id"] == new_learner_id
        assert data["has_state"] is False
        assert data["is_onboarded"] is False
        assert data["progress"] is None
        assert data["active_assessment_id"] is None

    def test_onboarded_learner_resume_returns_state_and_progress(self, services, ingested_calculus):
        learning, ks, ls = services
        subject_id = ingested_calculus.document_id
        learner_id = f"onboarded_learner_{int(time.time())}"

        # Initialize learner state via self-assessment
        graph = ks.get_subject_graph(subject_id)
        concept_ids = [c["concept_id"] for c in graph["concepts"]]
        ls.get_or_create_learner_state(learner_id, concept_ids)

        data = ls.resume_learner_state(learner_id, subject_id=subject_id)

        assert data["learner_id"] == learner_id
        assert data["has_state"] is True
        assert data["is_onboarded"] is True
        assert data["subject_id"] == subject_id
        assert data["progress"] is not None
        assert "average_mastery" in data["progress"]

    def test_active_uncompleted_final_assessment_resumed(self, services, ingested_calculus):
        learning, ks, ls = services
        subject_id = ingested_calculus.document_id
        learner_id = f"learner_fa_active_{int(time.time())}"

        # Start final assessment
        start_res = learning.start_final_assessment(learner_id, subject_id)
        assessment_id = start_res["assessment_id"]

        data = ls.resume_learner_state(learner_id, subject_id=subject_id)

        assert data["has_state"] is True
        assert data["is_onboarded"] is True
        assert data["active_assessment_id"] == assessment_id

    def test_completed_final_assessment_not_reported_as_active(self, services, ingested_calculus):
        learning, ks, ls = services
        subject_id = ingested_calculus.document_id
        learner_id = f"learner_fa_completed_{int(time.time())}"

        start_res = learning.start_final_assessment(learner_id, subject_id)
        assessment_id = start_res["assessment_id"]

        # Submit final assessment to complete it
        bank = learning.get_or_create_question_bank(subject_id)
        responses = {
            q.get("question_id") or q.get("item_id"): bank.get_question(q.get("question_id") or q.get("item_id")).correct_answer
            for q in start_res["questions"]
            if bank.get_question(q.get("question_id") or q.get("item_id"))
        }

        learning.submit_final_assessment(
            assessment_id=assessment_id,
            learner_id=learner_id,
            subject_id=subject_id,
            responses=responses,
        )

        data = ls.resume_learner_state(learner_id, subject_id=subject_id)

        assert data["has_state"] is True
        assert data["is_onboarded"] is True
        # Completed assessment must NOT be returned as active_assessment_id
        assert data["active_assessment_id"] is None

    def test_resume_persists_across_reinstantiation(self, services, ingested_calculus):
        learning1, ks1, ls1 = services
        subject_id = ingested_calculus.document_id
        learner_id = f"learner_persist_resume_{int(time.time())}"

        start_res = learning1.start_final_assessment(learner_id, subject_id)
        assessment_id = start_res["assessment_id"]

        # Re-instantiate services
        ks2 = KnowledgeService()
        ls2 = LearnerService(knowledge_service=ks2)

        data = ls2.resume_learner_state(learner_id, subject_id=subject_id)

        assert data["learner_id"] == learner_id
        assert data["has_state"] is True
        assert data["active_assessment_id"] == assessment_id

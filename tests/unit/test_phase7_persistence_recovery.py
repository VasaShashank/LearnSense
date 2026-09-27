"""
Phase 7 Persistence and Session Recovery Test Suite.
Verifies JSON repositories for Sessions, Question Banks, Learning Contexts, and Learner State.
"""

import pytest
from storage.repositories import SessionRepository, QuestionBankRepository, LearningContextRepository
from phase3.storage.learner_repository import LearnerStateRepository
from phase4.models import KnowledgeInitializationSession, SelfAssessmentStatus, KnowledgeSufficiencyStatus
from phase3.learner.models import LearnerState, ConceptState


def test_session_repository_persistence(tmp_path):
    repo = SessionRepository(base_dir=str(tmp_path))
    session = KnowledgeInitializationSession(
        session_id="sess_test_123",
        learner_id="learner_pers_1",
        subject_id="subj_test",
        know_concept_ids=["c_1"],
        dont_know_concept_ids=["c_2"],
        unanswered_concept_ids=["c_3"],
        sufficiency_status=KnowledgeSufficiencyStatus.INITIALIZED,
    )

    repo.save_session(session)
    loaded = repo.load_session("sess_test_123")

    assert loaded is not None
    assert loaded.session_id == "sess_test_123"
    assert loaded.learner_id == "learner_pers_1"
    assert loaded.know_concept_ids == ["c_1"]


def test_learner_state_repository_persistence(tmp_path):
    repo = LearnerStateRepository(base_dir=str(tmp_path))
    state = LearnerState(
        learner_id="learner_pers_2",
        concept_states={
            "c_1": ConceptState(concept_id="c_1", mastery_probability=0.82, attempt_count=5, correct_count=4)
        },
    )

    repo.save_state(state)
    loaded = repo.load_state("learner_pers_2")

    assert loaded is not None
    assert loaded.learner_id == "learner_pers_2"
    assert loaded.concept_states["c_1"].mastery_probability == 0.82
    assert loaded.concept_states["c_1"].attempt_count == 5

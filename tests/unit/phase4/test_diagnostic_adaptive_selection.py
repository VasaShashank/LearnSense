"""
Unit tests for the adaptive diagnostic selector and per-answer application.

The key property proven here: the next verification question is chosen from the
learner's LIVE BKT state, not from a list fixed at quiz start. Two concepts with
identical verification priority therefore swap order once one of them has been
probed, purely because the information-gain term changed.
"""
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase4.knowledge_initialization.diagnostic_orchestrator import DiagnosticOrchestrator
from phase4.models import (
    ConceptSelfAssessment,
    ConfidenceLevel,
    KnowledgeInitializationSession,
    SelfAssessmentStatus,
)


def _sa(concept_id: str, status: SelfAssessmentStatus, conf: ConfidenceLevel) -> ConceptSelfAssessment:
    return ConceptSelfAssessment(concept_id=concept_id, status=status, confidence=conf)


def _q(qid: str, concept_ids, difficulty: float = 0.5) -> QuestionBankItem:
    return QuestionBankItem(
        question_id=qid,
        chapter_id="ch",
        concept_ids=list(concept_ids),
        question_text=f"{qid}?",
        options=["o1", "o2"],
        correct_answer="o1",
        explanation="grounded",
        difficulty=difficulty,
    )


def _tie_priority_session() -> KnowledgeInitializationSession:
    """Two KNOW+MEDIUM concepts: identical verification priority (0.8), cap 2."""
    return KnowledgeInitializationSession(
        session_id="ses_tie",
        learner_id="l_test",
        subject_id="subj_test",
        self_assessments={
            "c_x": _sa("c_x", SelfAssessmentStatus.KNOW, ConfidenceLevel.MEDIUM),
            "c_y": _sa("c_y", SelfAssessmentStatus.KNOW, ConfidenceLevel.MEDIUM),
        },
        know_concept_ids=["c_x", "c_y"],
        dont_know_concept_ids=[],
        unanswered_concept_ids=[],
        confidences={"c_x": ConfidenceLevel.MEDIUM, "c_y": ConfidenceLevel.MEDIUM},
    )


def _tie_priority_bank() -> QuestionBank:
    bank = QuestionBank(document_id="subj_test", chapter_id="ch")
    bank.add_question(_q("q_x", ["c_x"]))
    bank.add_question(_q("q_y", ["c_y"]))
    return bank


class TestAdaptiveSelection:
    def test_first_question_breaks_ties_deterministically(self):
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        bank = _tie_priority_bank()
        learner_state = LearnerState(learner_id="l_test")

        picked = [
            orch.select_next_diagnostic_question(session, bank, learner_state).question_id
            for _ in range(3)
        ]
        # Unprobed state is symmetric across c_x/c_y, so selection must be stable.
        assert picked == ["q_x", "q_x", "q_x"]

    def test_wrong_answer_changes_the_next_question(self):
        """The whole point: selection reacts to the previous answer."""
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        bank = _tie_priority_bank()
        learner_state = LearnerState(learner_id="l_test")

        first = orch.select_next_diagnostic_question(session, bank, learner_state)
        assert first.question_id == "q_x"

        orch.apply_diagnostic_response(session, learner_state, bank, "q_x", 0.0)

        second = orch.select_next_diagnostic_question(session, bank, learner_state)
        # A wrong answer raised c_x's uncertainty, so the selector now probes the
        # still-unprobed c_y instead of re-probing c_x.
        assert second.question_id == "q_y"

    def test_already_asked_question_is_never_reselected(self):
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        bank = _tie_priority_bank()
        learner_state = LearnerState(learner_id="l_test")

        for qid in ("q_x", "q_y"):
            orch.apply_diagnostic_response(session, learner_state, bank, qid, 1.0)

        assert orch.select_next_diagnostic_question(session, bank, learner_state) is None

    def test_stops_at_max_questions(self):
        """The max-question cap is the binding stopping condition here."""
        orch = DiagnosticOrchestrator()
        max_q = orch.config.DIAGNOSTIC_MAX_QUESTIONS

        # Enough distinct concepts/questions that only the cap can stop the run.
        concept_ids = [f"c_{i:02d}" for i in range(max_q + 5)]
        session = KnowledgeInitializationSession(
            session_id="ses_max",
            learner_id="l_test",
            subject_id="subj_test",
            self_assessments={
                cid: _sa(cid, SelfAssessmentStatus.KNOW, ConfidenceLevel.MEDIUM)
                for cid in concept_ids
            },
            know_concept_ids=list(concept_ids),
            confidences={cid: ConfidenceLevel.MEDIUM for cid in concept_ids},
        )
        bank = QuestionBank(document_id="subj_test", chapter_id="ch")
        for cid in concept_ids:
            bank.add_question(_q(f"q_{cid}", [cid]))
        learner_state = LearnerState(learner_id="l_test")

        for i in range(max_q):
            item = orch.select_next_diagnostic_question(session, bank, learner_state)
            assert item is not None, f"stopped early at {i}"
            orch.apply_diagnostic_response(session, learner_state, bank, item.question_id, 1.0)

        assert len(session.diagnostic_responses) == max_q
        assert orch.select_next_diagnostic_question(session, bank, learner_state) is None

    def test_dont_know_concepts_are_never_probed(self):
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        session.self_assessments["c_dk"] = _sa(
            "c_dk", SelfAssessmentStatus.DONT_KNOW, ConfidenceLevel.HIGH
        )
        session.dont_know_concept_ids = ["c_dk"]
        bank = _tie_priority_bank()
        bank.add_question(_q("q_dk", ["c_dk"]))
        learner_state = LearnerState(learner_id="l_test")

        pool_ids = {i.question_id for i in orch.diagnostic_candidate_pool(session, bank)}
        assert "q_dk" not in pool_ids
        assert pool_ids == {"q_x", "q_y"}

    def test_per_concept_cap_is_respected(self):
        orch = DiagnosticOrchestrator()
        session = KnowledgeInitializationSession(
            session_id="ses_cap",
            learner_id="l_test",
            subject_id="subj_test",
            self_assessments={
                "c_h": _sa("c_h", SelfAssessmentStatus.KNOW, ConfidenceLevel.HIGH),
            },
            know_concept_ids=["c_h"],
            confidences={"c_h": ConfidenceLevel.HIGH},
        )
        bank = QuestionBank(document_id="subj_test", chapter_id="ch")
        bank.add_question(_q("q_h1", ["c_h"]))
        bank.add_question(_q("q_h2", ["c_h"]))
        bank.add_question(_q("q_h3", ["c_h"]))
        learner_state = LearnerState(learner_id="l_test")

        # KNOW+HIGH is capped at one quick check.
        first = orch.select_next_diagnostic_question(session, bank, learner_state)
        assert first is not None
        orch.apply_diagnostic_response(session, learner_state, bank, first.question_id, 1.0)
        assert orch.select_next_diagnostic_question(session, bank, learner_state) is None


class TestPerAnswerApplication:
    def test_response_updates_bkt_once(self):
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        bank = _tie_priority_bank()
        learner_state = LearnerState(learner_id="l_test")

        updates = orch.apply_diagnostic_response(session, learner_state, bank, "q_x", 1.0)
        assert updates is not None
        assert session.diagnostic_responses == {"q_x": 1.0}
        assert session.diagnostic_answered_count == 1

        cs = learner_state.concept_states["c_x"]
        mastery_after_one = cs.mastery_probability
        assert cs.attempt_count == 1

        # A duplicate delivery must not move the model again.
        again = orch.apply_diagnostic_response(session, learner_state, bank, "q_x", 1.0)
        assert again is None
        assert cs.attempt_count == 1
        assert cs.mastery_probability == mastery_after_one

    def test_audit_record_captures_what_the_learner_chose(self):
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        bank = _tie_priority_bank()
        learner_state = LearnerState(learner_id="l_test")

        orch.apply_diagnostic_response(session, learner_state, bank, "q_x", 0.0)
        record = session.diagnostic_answer_records["q_x"]
        assert record["concept_ids"] == ["c_x"]
        assert record["correctness"] == 0.0
        assert "recorded_at" in record

    def test_unknown_question_is_not_applied(self):
        orch = DiagnosticOrchestrator()
        session = _tie_priority_session()
        bank = _tie_priority_bank()
        learner_state = LearnerState(learner_id="l_test")

        assert orch.apply_diagnostic_response(session, learner_state, bank, "forged", 1.0) is None
        assert session.diagnostic_responses == {}
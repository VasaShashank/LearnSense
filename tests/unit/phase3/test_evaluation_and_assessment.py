"""
Unit Tests for Phase 3 Evaluation, Assessment Policy, and Information Gain.
"""

import pytest
from phase3.assessment.adaptive_policy import ChapterAssessmentEngine
from phase3.assessment.information_gain import InformationGainPolicy
from phase3.evaluation.evaluator import AnswerEvaluator
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem, QuestionType


def test_answer_evaluator():
    evaluator = AnswerEvaluator()

    mcq_res = evaluator.evaluate("mcq", "Option B", "Option B")
    assert mcq_res.is_correct is True
    assert mcq_res.correctness_score == 1.0

    mcq_fail = evaluator.evaluate("mcq", "Option A", "Option B")
    assert mcq_fail.is_correct is False

    num_res = evaluator.evaluate("numerical", 3.1415, 3.14, tolerance_percent=0.01)
    assert num_res.is_correct is True


def test_information_gain_selection():
    lstate = LearnerState(learner_id="learner_ig_1")
    # Low mastery concept -> high uncertainty
    lstate.get_concept_state("c_hard").uncertainty = 0.9
    lstate.get_concept_state("c_easy").uncertainty = 0.1

    q_hard = QuestionBankItem(
        question_id="q_hard_1",
        question_text="Hard question on c_hard",
        concept_ids=["c_hard"],
        correct_answer="Option A",
        information_value=2.0,
    )
    q_easy = QuestionBankItem(
        question_id="q_easy_1",
        question_text="Easy question on c_easy",
        concept_ids=["c_easy"],
        correct_answer="Option B",
        information_value=0.5,
    )

    policy = InformationGainPolicy()
    score_hard = policy.calculate_information_gain(q_hard, lstate)
    score_easy = policy.calculate_information_gain(q_easy, lstate)

    assert score_hard.total_score > score_easy.total_score

    selected = policy.select_next_question([q_easy, q_hard], lstate, asked_question_ids=set())
    assert selected.question_id == "q_hard_1"

"""Unit tests for src.adaptive_assessment module."""

import math
from pathlib import Path
import json
import pytest
from jsonschema import Draft202012Validator

from src.bkt import BKTParameters
from src.adaptive_assessment import (
    AdaptiveAssessmentSelector,
    compute_expected_information_gain,
    load_question_bank_from_csv,
)

CONTRACTS_DIR = next((d / "contracts" for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent / "contracts")


def test_hand_calculated_expected_information_gain():
    """Verify compute_expected_information_gain matches exact analytical hand calculation.
    
    Analytical Derivation:
        Parameters: L = 0.5, G = 0.2, S = 0.1
        1. Prior Entropy:
           H(Z) = - 0.5*log2(0.5) - 0.5*log2(0.5) = 1.0 bit.
        2. Pre-response prediction:
           P(R=1) = L*(1-S) + (1-L)*G = 0.5*0.9 + 0.5*0.2 = 0.45 + 0.10 = 0.55.
           P(R=0) = 1 - 0.55 = 0.45.
        3. Posteriors:
           L_{R=1} = 0.45 / 0.55 = 9/11 ≈ 0.818181818...
           L_{R=0} = (0.5 * 0.1) / 0.45 = 0.05 / 0.45 = 1/9 ≈ 0.111111111...
        4. Posterior Entropies:
           H(Z|R=1) = - (9/11 * log2(9/11) + 2/11 * log2(2/11)) ≈ 0.6840384 bits.
           H(Z|R=0) = - (1/9 * log2(1/9) + 8/9 * log2(8/9)) ≈ 0.5032583 bits.
        5. Expected Posterior Entropy:
           E[H(Z|R)] = 0.55 * 0.6840384 + 0.45 * 0.5032583 ≈ 0.3762211 + 0.2264662 = 0.6026873 bits.
        6. Expected Information Gain:
           IG = H(Z) - E[H(Z|R)] = 1.0 - 0.6026873 ≈ 0.3973127 bits.
    """
    params = BKTParameters(p_l0=0.5, p_t=0.05, p_g=0.2, p_s=0.1)
    eval_res = compute_expected_information_gain(
        prior_mastery=0.5,
        parameters=params,
        estimated_time_seconds=60,
    )

    # 1. Prior entropy
    assert abs(eval_res.prior_entropy - 1.0) < 1e-6
    # 2. Response prediction
    assert abs(eval_res.p_correct - 0.55) < 1e-6
    # 3. Posteriors
    assert abs(eval_res.posterior_mastery_correct - (9.0 / 11.0)) < 1e-6
    assert abs(eval_res.posterior_mastery_incorrect - (1.0 / 9.0)) < 1e-6
    # 4. Expected Information Gain
    expected_ig = 0.3973127
    assert abs(eval_res.information_gain - expected_ig) < 1e-5
    # 5. Non-negativity
    assert eval_res.information_gain >= 0.0


def test_information_gain_vs_response_probability():
    """Verify that Expected Information Gain is NOT confused with P(correct).
    
    A question with P(correct) = 0.95 (very easy, well-known) yields low information gain,
    whereas an informative diagnostic question near maximum uncertainty yields high information gain.
    """
    params = BKTParameters(p_l0=0.5, p_t=0.05, p_g=0.2, p_s=0.1)

    # State near maximal uncertainty (p = 0.5)
    eval_uncertain = compute_expected_information_gain(0.5, params)
    # State with well-established mastery (p = 0.95)
    eval_mastered = compute_expected_information_gain(0.95, params)

    # The uncertain state MUST have strictly higher information gain than the mastered state
    assert eval_uncertain.information_gain > eval_mastered.information_gain
    # But the mastered state has higher P(correct)
    assert eval_mastered.p_correct > eval_uncertain.p_correct


def test_question_bank_loading():
    """Verify question bank loading from CSV."""
    q_bank = load_question_bank_from_csv()
    assert len(q_bank) >= 1000
    q_id = "JQ5100001" if "JQ5100001" in q_bank else next(iter(q_bank.keys()))
    assert q_id in q_bank
    sample = q_bank[q_id]
    assert sample.primary_concept_id != ""
    assert sample.difficulty in {"easy", "medium", "hard"}


def test_question_schema_compliance():
    """Verify question projection conforms to contracts/question_schema.json without answer keys."""
    schema_path = CONTRACTS_DIR / "question_schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema)

    q_bank = load_question_bank_from_csv()
    q_id = "JQ5100001" if "JQ5100001" in q_bank else next(iter(q_bank.keys()))
    sample = q_bank[q_id]
    payload = sample.to_contract_dict()

    errors = list(validator.iter_errors(payload))
    assert len(errors) == 0, f"Schema validation errors: {[e.message for e in errors]}"

    # Confirm NO answer keys or solution keys are present in client payload
    assert "correct_answer" not in payload
    assert "solution_key" not in payload
    assert "server_key" not in payload


def test_candidate_selection_under_uncertainty():
    """Verify selector chooses an eligible candidate maximizing information gain."""
    selector = AdaptiveAssessmentSelector()
    res = selector.select_next_question(
        target_concept_id="PHY_KIN",
        learner_mastery_vector={"PHY_KIN": 0.50},
        objective="progress",
    )

    assert res.selected_question is not None
    assert res.is_fallback is False
    assert res.information_gain > 0.0
    kin_id = selector.knowledge_graph._resolve_id("PHY_KIN")
    assert res.selected_question.primary_concept_id in {"PHY_KIN", kin_id}


def test_prerequisite_gating_and_diagnostic_exception():
    """Verify blocked candidates when prerequisites unmet, unless objective is diagnostic."""
    selector = AdaptiveAssessmentSelector()

    # Target: PHY_NLM (requires PHY_KIN). Learner has unassessed PHY_KIN.
    # In 'progress' objective, assessment is blocked
    res_progress = selector.select_next_question(
        target_concept_id="PHY_NLM",
        learner_mastery_vector={},
        objective="progress",
    )
    assert res_progress.selected_question is None
    assert res_progress.is_fallback is True
    assert "blocked" in res_progress.selection_rationale.lower()

    # In 'diagnostic' objective, diagnostic exception is permitted
    res_diag = selector.select_next_question(
        target_concept_id="PHY_NLM",
        learner_mastery_vector={},
        objective="diagnostic",
    )
    assert res_diag.selected_question is not None
    assert res_diag.is_fallback is False


def test_repetition_suppression():
    """Verify recently attempted questions are suppressed in favor of fresh items."""
    selector = AdaptiveAssessmentSelector()

    res_1 = selector.select_next_question("PHY_KIN", objective="progress")
    q1_id = res_1.selected_question.question_id

    # Suppress q1_id in next selection
    res_2 = selector.select_next_question(
        "PHY_KIN",
        recent_question_ids=[q1_id],
        objective="progress",
    )
    q2_id = res_2.selected_question.question_id
    assert q1_id != q2_id


def test_deterministic_tie_breaking():
    """Verify identical inputs yield the exact same question deterministically."""
    selector = AdaptiveAssessmentSelector()

    res_a = selector.select_next_question("CHE_MOL", objective="progress")
    res_b = selector.select_next_question("CHE_MOL", objective="progress")

    assert res_a.selected_question.question_id == res_b.selected_question.question_id
    assert abs(res_a.information_gain - res_b.information_gain) < 1e-9


def test_fallback_when_concept_unknown():
    """Verify safe fallback when concept is completely unknown."""
    selector = AdaptiveAssessmentSelector()
    res = selector.select_next_question("UNKNOWN_NON_EXISTENT_CONCEPT")
    assert res.selected_question is None
    assert res.is_fallback is True
    assert res.fallback_recommendation is not None


def test_calibrated_item_parameters_differentiate_eig():
    """Verify that calibrated item parameters yield distinct EIGs across questions.
    
    Fixes P1 finding where all candidate questions under a concept received identical EIGs
    and defaulted to question-ID sorting.
    """
    from src.adaptive_assessment import derive_calibrated_item_parameters, QuestionItem
    
    base_params = BKTParameters(p_l0=0.3, p_t=0.1, p_g=0.2, p_s=0.1)
    
    q_easy_mcq = QuestionItem(
        question_id="Q_EASY_MCQ",
        primary_concept_id="PHY_KIN",
        concept_ids=["PHY_KIN"],
        subject="Physics",
        chapter="Kinematics",
        difficulty="easy",
        numeric_difficulty=0.25,
        option_count=4,
        question_type="single_choice",
        estimated_time_seconds=60,
    )
    
    q_hard_mcq = QuestionItem(
        question_id="Q_HARD_MCQ",
        primary_concept_id="PHY_KIN",
        concept_ids=["PHY_KIN"],
        subject="Physics",
        chapter="Kinematics",
        difficulty="hard",
        numeric_difficulty=0.75,
        option_count=4,
        question_type="single_choice",
        estimated_time_seconds=120,
    )
    
    q_numeric = QuestionItem(
        question_id="Q_NUMERIC",
        primary_concept_id="PHY_KIN",
        concept_ids=["PHY_KIN"],
        subject="Physics",
        chapter="Kinematics",
        difficulty="medium",
        numeric_difficulty=0.50,
        option_count=4,
        question_type="numeric",
        estimated_time_seconds=100,
    )
    
    p_easy = derive_calibrated_item_parameters(base_params, q_easy_mcq)
    p_hard = derive_calibrated_item_parameters(base_params, q_hard_mcq)
    p_num = derive_calibrated_item_parameters(base_params, q_numeric)
    
    # Verify psychometric parameter distinctions
    # Numeric question guessing must be dramatically lower than MCQ
    assert p_num.p_g < p_easy.p_g
    # Hard MCQ must have higher slip than easy MCQ
    assert p_hard.p_s > p_easy.p_s
    
    # Compute EIGs under identical prior (e.g. 0.50)
    eig_easy = compute_expected_information_gain(0.50, p_easy, estimated_time_seconds=60)
    eig_hard = compute_expected_information_gain(0.50, p_hard, estimated_time_seconds=120)
    eig_num = compute_expected_information_gain(0.50, p_num, estimated_time_seconds=100)
    
    # EIGs must be distinct, not identical
    assert abs(eig_easy.information_gain - eig_hard.information_gain) > 1e-4
    assert abs(eig_easy.information_gain - eig_num.information_gain) > 1e-4
    assert abs(eig_hard.information_gain - eig_num.information_gain) > 1e-4
    
    # Test with selector on real question bank
    selector = AdaptiveAssessmentSelector()
    kin_id = selector.knowledge_graph._resolve_id("PHY_KIN")
    kin_questions = selector._concept_index.get("PHY_KIN", []) or selector._concept_index.get(kin_id, [])
    assert len(kin_questions) > 1
    
    # Verify candidate questions have distinct calibrated parameters
    params_set = {
        (
            round(derive_calibrated_item_parameters(base_params, q).p_g, 4),
            round(derive_calibrated_item_parameters(base_params, q).p_s, 4),
        )
        for q in kin_questions
    }
    assert len(params_set) > 1, "Expected multiple distinct parameter calibrations among PHY_KIN candidates"


def test_adaptive_assessment_session_reaches_around_8_questions():
    """Verify that AdaptiveAssessmentSession administers ~8 questions across progressive phases.
    
    Ensures that instead of stopping prematurely at 2-3 items on high initial mastery,
    the CAT evaluates student performance across:
    - Phase 1: Baseline Calibration (Items 1-2)
    - Phase 2: Frontier Discrimination (Items 3-5)
    - Phase 3: Robustness Stress-Test (Items 6-7)
    - Phase 4: Confirmatory Check (Item 8)
    """
    selector = AdaptiveAssessmentSelector()
    session = selector.create_session(
        learner_id="learner_deep_probe_01",
        concept_id="PHY_KIN",
        target_questions=8,
        min_questions=8,
        max_questions=10,
    )

    assert session.target_questions == 8
    assert not session.is_completed

    administered_ids = []
    # Simulate an 8-question session
    for step in range(8):
        q_data = selector.get_next_session_question(session.session_id)
        assert not q_data["is_completed"], f"Session completed prematurely at question {step + 1}"
        assert q_data["question_number"] == step + 1
        assert q_data["target_questions"] == 8

        selected_q = q_data["selected_question"]
        qid = selected_q["question_id"]
        assert qid not in administered_ids, f"Question {qid} was repeated!"
        administered_ids.append(qid)

        # Check phase names as step advances
        if step < 2:
            assert q_data["phase"] == "Phase 1: Baseline Calibration"
            assert q_data["objective"] == "diagnostic"
        elif step < 5:
            assert q_data["phase"] == "Phase 2: Frontier Discrimination"
            assert q_data["objective"] == "progress"
        elif step < 7:
            assert q_data["phase"] == "Phase 3: Robustness Stress-Test"
            assert q_data["objective"] == "mastery_check"
        else:
            assert q_data["phase"] == "Phase 4: Confirmatory Check"

        # Simulate answers: mostly correct with one realistic slip
        is_correct = False if step == 2 else True
        resp = selector.record_session_response(
            session_id=session.session_id,
            question_id=qid,
            is_correct=is_correct,
        )

        if step < 7:
            assert not resp["is_completed"]
        else:
            assert resp["is_completed"]

    # Verify session completion at exactly 8 questions
    assert len(session.administered_questions) == 8
    assert session.is_completed
    assert session.final_mastery_tier in {"Mastered (High Proficiency)", "Proficient"}

    # Calling next_question after completion returns completion message
    final_call = selector.get_next_session_question(session.session_id)
    assert final_call["is_completed"]
    assert final_call["selected_question"] is None



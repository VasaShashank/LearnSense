"""Unit tests for src.recommendation module."""

from pathlib import Path
import json
import pytest
from jsonschema import Draft202012Validator

from src.recommendation import RecommendationEngine
from src.state import LearnerStateService

CONTRACTS_DIR = next((d / "contracts" for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent / "contracts")


@pytest.fixture
def rec_validator() -> Draft202012Validator:
    schema_path = CONTRACTS_DIR / "recommendation_schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    return Draft202012Validator(schema)


def test_recommendation_schema_compliance(rec_validator):
    """Verify recommendation payloads strictly validate against contracts/recommendation_schema.json."""
    engine = RecommendationEngine()
    service = LearnerStateService()

    rec = engine.recommend_next_activity("REC_S1", service, focus_concept_id="PHY_KIN")
    payload = rec.to_contract_payload()

    errors = list(rec_validator.iter_errors(payload))
    assert len(errors) == 0, f"Schema validation errors: {[e.message for e in errors]}"


def test_prerequisite_remediation_priority(rec_validator):
    """Verify unmet prerequisite triggers Priority 90 remediation recommendation."""
    engine = RecommendationEngine()
    service = LearnerStateService()

    # Target: PHY_NLM (requires PHY_KIN). Student has no knowledge of PHY_KIN.
    rec = engine.recommend_next_activity("REC_S2", service, focus_concept_id="PHY_NLM")
    assert rec.priority == 90
    assert "prerequisite_gap" in rec.reason_codes
    assert rec.target["target_id"] in {"PHY_KIN", "cc_3e003bf9b038a36b"}  # Must target prerequisite Kinematics
    assert rec.kind in {"learn_concept", "review_concept"}

    errors = list(rec_validator.iter_errors(rec.to_contract_payload()))
    assert len(errors) == 0


def test_recent_error_streak_remediation(rec_validator):
    """Verify consecutive errors trigger worked_example scaffolding (Priority 85)."""
    engine = RecommendationEngine()
    service = LearnerStateService()

    # Learner fails two consecutive attempts on PHY_KIN
    service.process_attempt("REC_S3", "PHY_KIN", "ATT_FAIL_1", is_correct=False)
    service.process_attempt("REC_S3", "PHY_KIN", "ATT_FAIL_2", is_correct=False)

    rec = engine.recommend_next_activity("REC_S3", service, focus_concept_id="PHY_KIN")
    assert rec.priority == 85
    assert "recent_error_pattern" in rec.reason_codes
    assert rec.kind == "worked_example"
    assert rec.target["target_id"] == "PHY_KIN"

    errors = list(rec_validator.iter_errors(rec.to_contract_payload()))
    assert len(errors) == 0


def test_unassessed_concept_learning_recommendation(rec_validator):
    """Verify unassessed concept without prerequisite issues triggers learn_concept (Priority 70)."""
    engine = RecommendationEngine()
    service = LearnerStateService()

    # PHY_KIN is a root concept (no prerequisites). Learner has 0 evidence.
    rec = engine.recommend_next_activity("REC_S4", service, focus_concept_id="PHY_KIN")
    assert rec.priority == 70
    assert rec.kind == "learn_concept"
    assert rec.target["target_id"] == "PHY_KIN"

    errors = list(rec_validator.iter_errors(rec.to_contract_payload()))
    assert len(errors) == 0


def test_developing_concept_practice_recommendation(rec_validator):
    """Verify developing knowledge state triggers adaptive practice_question (Priority 60)."""
    engine = RecommendationEngine()
    service = LearnerStateService()

    # Establish developing knowledge state (e.g. 1 correct attempt)
    service.process_attempt("REC_S5", "PHY_KIN", "ATT_OK_1", is_correct=True)

    rec = engine.recommend_next_activity("REC_S5", service, focus_concept_id="PHY_KIN")
    assert rec.priority == 60
    assert rec.kind == "practice_question"
    assert rec.target["target_type"] == "question"
    assert "expected_information_gain" in rec.metadata

    errors = list(rec_validator.iter_errors(rec.to_contract_payload()))
    assert len(errors) == 0


def test_mastered_concept_curriculum_advancement(rec_validator):
    """Verify mastered concept triggers advancement to next curriculum objective (Priority 50)."""
    engine = RecommendationEngine()
    service = LearnerStateService()

    # Elevate PHY_KIN to mastery with multiple correct attempts
    for i in range(4):
        service.process_attempt("REC_S6", "PHY_KIN", f"ATT_M_{i}", is_correct=True)

    state = service.get_state("REC_S6", "PHY_KIN")
    assert state.mastery_probability >= 0.80

    rec = engine.recommend_next_activity("REC_S6", service, focus_concept_id="PHY_KIN")
    assert rec.priority == 50
    # Must advance to downstream dependent concept (PHY_NLM)
    assert rec.target["target_id"] in {"PHY_NLM", "cc_e070c64d30e5e623"}
    assert "curriculum_sequence" in rec.reason_codes

    errors = list(rec_validator.iter_errors(rec.to_contract_payload()))
    assert len(errors) == 0


def test_spaced_review_surfaces_even_when_target_concept_unassessed(rec_validator):
    """Verify overdue spaced repetition review (Priority 80) surfaces even when focus concept is unassessed.
    
    Fixes FINDING-RECOM-01 (P2 Medium):
    Prevents the priority inversion where an overdue review for a previously mastered concept
    was suppressed merely because the learner had not yet started or mastered their current target concept.
    """
    import datetime

    engine = RecommendationEngine()
    service = LearnerStateService()
    lid = "REC_SPACED_UNASSESSED"

    # 1. Learner previously mastered PHY_KIN 20 days ago
    past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=20)).isoformat()
    for i in range(3):
        service.process_attempt(
            learner_id=lid,
            concept_id="PHY_KIN",
            attempt_id=f"ATT_PAST_{i}",
            is_correct=True,
            submitted_at=past_time,
        )

    # 2. Learner now targets a new, completely unassessed concept (CHE_MOL)
    unassessed_state = service.get_or_initialize_state(lid, "CHE_MOL")
    assert unassessed_state.evidence_count == 0

    # 3. Request next recommendation with focus_concept_id="CHE_MOL"
    rec = engine.recommend_next_activity(
        learner_id=lid,
        state_service=service,
        focus_concept_id="CHE_MOL",
    )

    # 4. Overdue spaced review for PHY_KIN must take precedence (Priority 80 > Priority 70)
    assert rec.priority == 80
    assert rec.kind == "review_concept"
    assert rec.target["target_id"] == "PHY_KIN"
    assert "spaced_review_due" in rec.reason_codes

    errors = list(rec_validator.iter_errors(rec.to_contract_payload()))
    assert len(errors) == 0


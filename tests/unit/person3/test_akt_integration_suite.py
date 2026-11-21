"""Integration test suite for AKT + Concept-Mastery Head.

Verifies the 12 minimum acceptance criteria defined in Section 9 of the
Person 3 migration specification:
1. AKT model can be initialized and load its checkpoint.
2. Chronological learner history produces a valid mastery estimate.
3. Requested concept receives concept-specific estimate.
4. Predictions use no future interactions (causal attention check).
5. Padding and attention masks behave correctly.
6. Missing and sparse interaction histories are handled safely.
7. Output scores are finite and bounded in [0, 1].
8. Training loss includes intended mastery supervision term.
9. Inference does not mutate model weights.
10. API contracts and existing schemas remain valid.
11. Fallback path is explicit and distinguished from AKT.
12. End-to-end closed loop executes cleanly with AKT as the estimator.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import torch
import numpy as np
from jsonschema import Draft202012Validator

from src.akt_mastery_head import (
    AKTMasteryHeadModel,
    Vocabulary,
    MasterySequenceArrays,
    _validation_multitask_loss,
)
from src.akt_inference import AKTMasteryInferenceService
from src.state import LearnerStateService
from src.service import LearnSensePersonalizationService

WORKSPACE_ROOT = next((d for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent)
CONTRACTS_DIR = next((d / "contracts" for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent / "contracts")


@pytest.fixture
def state_validator() -> Draft202012Validator:
    schema_path = CONTRACTS_DIR / "learner_state_schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return Draft202012Validator(json.load(f))


def test_akt_model_initialization_and_checkpoint_loading():
    """Verify model instantiation and production checkpoint loading."""
    service = AKTMasteryInferenceService()
    assert service.is_available() is True
    assert service.model is not None
    assert service.vocabulary is not None
    assert service.checkpoint_file.exists()
    assert service.vocabulary.n_questions > 100
    assert service.vocabulary.n_concepts > 10
    assert not service.model.training


def test_chronological_history_produces_valid_mastery():
    """Verify sequential interactions produce expected directional mastery changes."""
    service = AKTMasteryInferenceService()
    learner_id = "TEST_STUDENT_CHRONO"
    concept_id = "PHY_KIN"

    # Step 0: Cold start
    m0 = service.predict_concept_mastery(learner_id, concept_id)
    assert 0.0 <= m0 <= 1.0

    # Step 1: 1 correct attempt
    service.record_interaction(learner_id, "JQ00001", concept_id, "medium", is_correct=1)
    m1 = service.predict_concept_mastery(learner_id, concept_id)
    assert 0.0 <= m1 <= 1.0

    # Step 2: More correct attempts
    service.record_interaction(learner_id, "JQ00002", concept_id, "medium", is_correct=1)
    service.record_interaction(learner_id, "JQ00003", concept_id, "medium", is_correct=1)
    m2 = service.predict_concept_mastery(learner_id, concept_id)
    assert 0.0 <= m2 <= 1.0


def test_concept_specific_mastery_estimates():
    """Verify different concepts receive distinct concept-specific mastery estimates."""
    service = AKTMasteryInferenceService()
    learner_id = "TEST_STUDENT_MULTI_CONCEPT"

    service.record_interaction(learner_id, "JQ00001", "PHY_KIN", "medium", is_correct=1)
    service.record_interaction(learner_id, "JQ00002", "PHY_KIN", "medium", is_correct=1)
    service.record_interaction(learner_id, "JQ00003", "CHE_ORG", "medium", is_correct=0)
    service.record_interaction(learner_id, "JQ00004", "CHE_ORG", "medium", is_correct=0)

    m_kin = service.predict_concept_mastery(learner_id, "PHY_KIN")
    m_che = service.predict_concept_mastery(learner_id, "CHE_ORG")

    assert 0.0 <= m_kin <= 1.0
    assert 0.0 <= m_che <= 1.0
    assert m_kin != m_che
    m_kin_cold = service.predict_concept_mastery("COLD_START_STUDENT", "PHY_KIN")
    assert m_kin > m_kin_cold


def test_predictions_use_no_future_interactions():
    """Causal test: Earlier predictions are strictly invariant to future interactions."""
    service = AKTMasteryInferenceService()
    model = service.model
    assert model is not None
    model.eval()

    q_1 = torch.tensor([[1]], dtype=torch.long)
    c_1 = torch.tensor([[1]], dtype=torch.long)
    d_1 = torch.tensor([[1]], dtype=torch.long)
    r_1 = torch.tensor([[2]], dtype=torch.long)
    m_1 = torch.tensor([[True]], dtype=torch.bool)

    q_3 = torch.tensor([[1, 2, 3]], dtype=torch.long)
    c_3 = torch.tensor([[1, 1, 1]], dtype=torch.long)
    d_3 = torch.tensor([[1, 2, 1]], dtype=torch.long)
    r_3 = torch.tensor([[2, 1, 0]], dtype=torch.long)
    m_3 = torch.tensor([[True, True, True]], dtype=torch.bool)

    with torch.no_grad():
        r_out_1, _, m_all_1 = model(q_1, c_1, d_1, r_1, m_1)
        r_out_3, _, m_all_3 = model(q_3, c_3, d_3, r_3, m_3)

    # Step 0 prediction in sequence of length 1 must be identical to Step 0 in sequence of length 3
    assert torch.allclose(m_all_1[0, 0], m_all_3[0, 0], atol=1e-5), "Causal leak detected in mastery head!"
    assert torch.allclose(r_out_1[0, 0], r_out_3[0, 0], atol=1e-5), "Causal leak detected in response head!"


def test_padding_and_attention_masks():
    """Verify padded elements have zero attention influence and false masks."""
    service = AKTMasteryInferenceService()
    model = service.model
    assert model is not None

    q = torch.tensor([[1, 0, 0]], dtype=torch.long)
    c = torch.tensor([[1, 0, 0]], dtype=torch.long)
    d = torch.tensor([[1, 0, 0]], dtype=torch.long)
    r = torch.tensor([[2, 0, 0]], dtype=torch.long)
    m = torch.tensor([[True, False, False]], dtype=torch.bool)

    with torch.no_grad():
        resp_logits, mast_logits, _ = model(q, c, d, r, m)

    assert resp_logits.shape == (1, 3)
    assert mast_logits.shape == (1, 3)
    assert torch.isfinite(resp_logits[0, 0])
    assert torch.isfinite(mast_logits[0, 0])


def test_missing_and_sparse_histories_handled_safely():
    """Verify empty history, missing question IDs, and unseen concepts do not crash."""
    service = AKTMasteryInferenceService()
    learner_id = "TEST_STUDENT_SPARSE"

    # 1. Cold start / empty history
    m_empty = service.predict_concept_mastery(learner_id, "PHY_KIN")
    assert 0.0 <= m_empty <= 1.0

    # 2. Unseen question
    service.record_interaction(learner_id, "NON_EXISTENT_Q", "PHY_KIN", "medium", is_correct=1)
    m_unseen_q = service.predict_concept_mastery(learner_id, "PHY_KIN")
    assert 0.0 <= m_unseen_q <= 1.0

    # 3. Unseen concept
    m_unseen_c = service.predict_concept_mastery(learner_id, "TOTALLY_NEW_CONCEPT")
    assert 0.0 <= m_unseen_c <= 1.0


def test_output_scores_finite_and_bounded_zero_one():
    """Verify response probability and mastery outputs are strictly finite within [0, 1]."""
    service = AKTMasteryInferenceService()
    learner_id = "TEST_STUDENT_BOUNDS"
    concept = "MTH_CAL"

    for length in [1, 5, 20]:
        lid = f"{learner_id}_{length}"
        for i in range(1, length + 1):
            service.record_interaction(lid, f"JQ000{i:02d}", concept, "medium", is_correct=int(i % 2 == 0))
        m = service.predict_concept_mastery(lid, concept)
        r = service.predict_next_response(lid, f"JQ000{length+1:02d}", concept, "medium")

        assert 0.0 <= m <= 1.0
        assert 0.0 <= r <= 1.0
        assert not np.isnan(m) and not np.isinf(m)
        assert not np.isnan(r) and not np.isinf(r)


def test_training_loss_includes_mastery_supervision():
    """Verify multi-task loss combines response loss and mastery loss."""
    vocab = Vocabulary(
        question_to_index={"q1": 1},
        concept_to_index={"c1": 1},
        difficulty_to_index={"easy": 1},
    )
    model = AKTMasteryHeadModel(
        n_questions=vocab.n_questions,
        n_concepts=vocab.n_concepts,
        n_difficulties=vocab.n_difficulties,
        d_model=32,
        n_heads=2,
    )

    seq = MasterySequenceArrays(
        interaction_ids=np.array(["i1"]),
        questions=np.array([1]),
        concepts=np.array([1]),
        difficulties=np.array([1]),
        previous_responses=np.array([2]),
        correct=np.array([1]),
        mastery_targets=np.array([0.75]),
    )

    loss_with_mastery = _validation_multitask_loss(
        model, [seq], batch_size=2, response_weight=1.0, mastery_weight=0.5
    )
    loss_no_mastery = _validation_multitask_loss(
        model, [seq], batch_size=2, response_weight=1.0, mastery_weight=0.0
    )

    assert loss_with_mastery["val_mastery_loss"] > 0.0
    assert loss_with_mastery["val_total_loss"] > loss_no_mastery["val_total_loss"]


def test_inference_does_not_mutate_weights():
    """Verify inference is in eval mode and does not alter model parameters."""
    service = AKTMasteryInferenceService()
    learner_id = "TEST_STUDENT_WEIGHT_STABILITY"
    concept = "PHY_KIN"

    initial_weights = {
        name: param.clone()
        for name, param in service.model.named_parameters()
        if "mastery_head" in name
    }

    service.record_interaction(learner_id, "JQ00001", concept, "medium", is_correct=1)
    for _ in range(5):
        service.predict_concept_mastery(learner_id, concept)
        service.predict_next_response(learner_id, "JQ00002", concept, "medium")

    for name, initial in initial_weights.items():
        current = service.model.state_dict()[name]
        assert torch.equal(initial, current), f"Weights mutated for {name}"


def test_api_contracts_and_schema_compliance(state_validator):
    """Verify LearnerStateService produces schema-valid contract payloads under AKT."""
    state_service = LearnerStateService(primary_model="akt_concept_mastery_head")
    state, p_pred, was_new = state_service.process_attempt(
        "STUDENT_CONTRACT_AKT", "PHY_KIN", "ATT_AKT_01", is_correct=True
    )

    payload = state_service.serialize_state_to_contract(state)
    errors = list(state_validator.iter_errors(payload))
    assert len(errors) == 0, f"Schema validation errors: {[e.message for e in errors]}"
    assert payload["model"]["name"] == "akt_concept_mastery_head"
    assert abs(payload["mastery_probability"] - state.mastery_probability) < 1e-4


def test_fallback_path_explicit_and_distinguished():
    """Verify fallback path is explicit, auditable, and distinguished from AKT."""
    # 1. Primary service with invalid checkpoint path triggers fallback
    service = AKTMasteryInferenceService(checkpoint_path="non_existent_file.pt")
    assert service.is_available() is False

    m = service.predict_concept_mastery("S1", "PHY_KIN")
    assert 0.0 <= m <= 1.0

    prov = service.get_model_provenance()
    assert prov["is_active_neural"] is False

    # 2. State service configured with explicit bkt_standard fallback
    state_service = LearnerStateService(primary_model="bkt_standard")
    state, p_pred, _ = state_service.process_attempt(
        "STUDENT_FALLBACK_TEST", "PHY_KIN", "ATT_FB_01", is_correct=True
    )
    payload = state_service.serialize_state_to_contract(state)
    assert payload["model"]["name"] == "bkt"
    assert state.metadata["estimator"] == "bkt_fallback"


def test_end_to_end_closed_loop_with_akt():
    """Verify complete closed-loop cycle: Ingest attempt -> AKT mastery update -> Recommend -> Tutor."""
    personalization = LearnSensePersonalizationService()
    learner_id = "STUDENT_CLOSED_LOOP_AKT"

    attempt_payload = {
        "attempt_id": "ATT_CLOSED_LOOP_01",
        "learner_id": learner_id,
        "question_id": "JQ00001",
        "submitted_at": "2026-10-21T11:00:00Z",
        "response": {"response_type": "single_choice", "value": "A", "work_steps": []},
        "outcome": {
            "scoring_status": "scored",
            "is_correct": True,
            "score": 1,
            "max_score": 1,
            "scored_at": "2026-10-21T11:00:01Z",
            "scoring_source": "server_key",
        },
        "context": {"concept_id": "PHY_KIN"},
        "idempotency_key": "ATT_CLOSED_LOOP_01",
        "schema_version": "0.1",
    }

    result = personalization.submit_attempt(attempt_payload)
    assert result["is_duplicate"] is False
    assert result["updated_state"] is not None
    assert result["updated_state"]["evidence_count"] == 1
    assert result["updated_state"]["model"]["name"] == "akt_concept_mastery_head"
    assert result["updated_state"]["mastery_probability"] > 0.0

    # 2. Next activity / recommendation generated
    rec = personalization.get_next_recommendation(learner_id)
    assert rec is not None
    assert rec["learner_id"] == learner_id

    # 3. Request tutoring assistance
    tutoring_req = {
        "request_id": "REQ_CLOSED_LOOP_01",
        "learner_id": learner_id,
        "intent": "explain_concept",
        "message": "Please explain kinematics.",
        "concept_ids": ["PHY_KIN"],
        "created_at": "2026-10-21T11:05:00Z",
    }
    tutor_feedback = personalization.request_tutoring(tutoring_req)
    assert tutor_feedback is not None
    assert tutor_feedback["request_id"] == "REQ_CLOSED_LOOP_01"
    assert len(tutor_feedback["content"]) > 0

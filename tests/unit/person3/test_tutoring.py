"""Unit tests for src.tutoring module."""

from pathlib import Path
import json
import pytest
from jsonschema import Draft202012Validator

from src.tutoring import TutoringEngine, TutoringRequest, TutoringResponse

CONTRACTS_DIR = next((d / "contracts" for d in Path(__file__).resolve().parents if (d / "contracts").is_dir()), Path(__file__).resolve().parent.parent / "contracts")


@pytest.fixture
def tutor_validators() -> tuple[Draft202012Validator, Draft202012Validator]:
    req_path = CONTRACTS_DIR / "tutoring_request_schema.json"
    resp_path = CONTRACTS_DIR / "tutoring_response_schema.json"

    with open(req_path, "r", encoding="utf-8") as f:
        req_schema = json.load(f)
    with open(resp_path, "r", encoding="utf-8") as f:
        resp_schema = json.load(f)

    return Draft202012Validator(req_schema), Draft202012Validator(resp_schema)


def test_conceptual_explanation_mode(tutor_validators):
    """Verify explanation mode returns grounded content matching schema."""
    req_val, resp_val = tutor_validators
    engine = TutoringEngine()

    req = TutoringRequest(
        request_id="TREQ_01",
        learner_id="LEARNER_T1",
        intent="explain_concept",
        message="Please explain Kinematics and acceleration equations.",
        concept_ids=["PHY_KIN"],
        preferred_depth="detailed",
    )

    resp = engine.deliver_tutoring(req)
    assert resp.mode == "explanation"
    assert "Kinematics" in resp.content
    assert len(resp.steps) >= 2
    assert resp.concept_ids == ["PHY_KIN"]

    # Verify real NCERT citation
    assert "NCERT" in resp.content
    assert "Chapter 3" in resp.content

    payload = resp.to_contract_payload()
    errors = list(resp_val.iter_errors(payload))
    assert len(errors) == 0, f"Schema errors: {[e.message for e in errors]}"


def test_socratic_guidance_mode(tutor_validators):
    """Verify Socratic guidance asks targeted questions without revealing complete solution."""
    _, resp_val = tutor_validators
    engine = TutoringEngine()

    req = TutoringRequest(
        request_id="TREQ_02",
        learner_id="LEARNER_T2",
        intent="solve_with_guidance",
        message="How do I solve this incline plane problem?",
        concept_ids=["PHY_NLM"],
    )

    resp = engine.deliver_tutoring(req)
    assert resp.mode == "guided_question"
    assert "Guiding Question" in resp.content
    assert resp.next_action == "answer_question"

    payload = resp.to_contract_payload()
    errors = list(resp_val.iter_errors(payload))
    assert len(errors) == 0


def test_progressive_hints_escalation(tutor_validators):
    """Verify progressive hints escalate through levels 1, 2, and 3."""
    _, resp_val = tutor_validators
    engine = TutoringEngine()

    # Level 1 Hint: directional
    req_l1 = TutoringRequest(
        request_id="TREQ_H1",
        learner_id="LEARNER_T3",
        intent="hint",
        message="Give me a hint.",
        concept_ids=["PHY_WPE"],
        context={"hint_level": 1},
    )
    resp_l1 = engine.deliver_tutoring(req_l1)
    assert resp_l1.mode == "hint"
    assert "Level 1" in resp_l1.content

    # Level 2 Hint: formula
    req_l2 = TutoringRequest(
        request_id="TREQ_H2",
        learner_id="LEARNER_T3",
        intent="hint",
        message="I need more help.",
        concept_ids=["PHY_WPE"],
        context={"hint_level": 2},
    )
    resp_l2 = engine.deliver_tutoring(req_l2)
    assert "Level 2" in resp_l2.content
    assert "W =" in resp_l2.content or "Delta K" in resp_l2.content

    # Level 3 Hint: concrete execution
    req_l3 = TutoringRequest(
        request_id="TREQ_H3",
        learner_id="LEARNER_T3",
        intent="hint",
        message="Still stuck on the algebra.",
        concept_ids=["PHY_WPE"],
        context={"hint_level": 3},
    )
    resp_l3 = engine.deliver_tutoring(req_l3)
    assert "Level 3" in resp_l3.content

    # Schema validation
    for r in [resp_l1, resp_l2, resp_l3]:
        errors = list(resp_val.iter_errors(r.to_contract_payload()))
        assert len(errors) == 0


def test_worked_example_delivery(tutor_validators):
    """Verify worked example delivery contains ordered steps with justifications."""
    _, resp_val = tutor_validators
    engine = TutoringEngine()

    req = TutoringRequest(
        request_id="TREQ_04",
        learner_id="LEARNER_T4",
        intent="practice",
        message="Show me a complete worked problem on mole concept.",
        concept_ids=["CHE_MOL"],
    )

    resp = engine.deliver_tutoring(req)
    assert resp.mode == "worked_example"
    assert len(resp.steps) >= 3
    # Verify ordered step indices
    for i, step in enumerate(resp.steps):
        assert step.step_index == i
        assert len(step.content) > 0

    payload = resp.to_contract_payload()
    errors = list(resp_val.iter_errors(payload))
    assert len(errors) == 0


def test_attempt_feedback_and_misconception_handling(tutor_validators):
    """Verify diagnostic feedback cautions against misconceptions without harsh dogmatism."""
    _, resp_val = tutor_validators
    engine = TutoringEngine()

    # Incorrect student attempt
    req = TutoringRequest(
        request_id="TREQ_05",
        learner_id="LEARNER_T5",
        intent="check_work",
        message="I calculated that distance equals displacement on a curved path.",
        concept_ids=["PHY_KIN"],
        context={"is_correct": False, "submitted_answer": "d = s"},
    )

    resp = engine.deliver_tutoring(req)
    assert resp.mode == "feedback"
    assert "Diagnostic Hypothesis" in resp.content
    assert "Why this matters" in resp.content
    assert resp.next_action == "review_concept"

    payload = resp.to_contract_payload()
    errors = list(resp_val.iter_errors(payload))
    assert len(errors) == 0


def test_answer_key_leakage_guardrail():
    """Verify answer key leakage detection and redaction guardrail."""
    engine = TutoringEngine()

    # Craft a mock response with simulated answer key leak
    leaky_resp = TutoringResponse(
        response_id="RESP_LEAK",
        request_id="REQ_LEAK",
        mode="feedback",
        content="Good try! However, the correct answer is C and server_key = C.",
        steps=[],
        concept_ids=["PHY_KIN"],
    )

    engine._enforce_answer_key_guardrail(leaky_resp)

    # Must be sanitized
    assert "the correct answer is C" not in leaky_resp.content
    assert "server_key" not in leaky_resp.content
    assert "REDACTED" in leaky_resp.content
    assert "answer_key_leakage_prevented" in leaky_resp.safety_flags


def test_score_only_vs_derivation_feedback():
    """Verify honest separation between score-only evaluation and intermediate derivation analysis.
    
    Fixes P1 finding where feedback claimed to verify derivation steps that were never submitted.
    """
    engine = TutoringEngine()

    # Case A: Score-only (no derivation submitted)
    req_no_steps = TutoringRequest(
        request_id="TREQ_SCORE_ONLY",
        learner_id="LEARNER_T6",
        intent="check_work",
        message="I chose option B",
        concept_ids=["PHY_KIN"],
        context={"is_correct": False, "submitted_answer": "B"},
    )
    resp_no_steps = engine.deliver_tutoring(req_no_steps)
    assert resp_no_steps.metadata["feedback_basis"] == "score_only"
    assert resp_no_steps.metadata["derivation_analyzed"] is False
    assert "derivation steps were not submitted" in resp_no_steps.content.lower()
    assert "derivation steps are sound" not in resp_no_steps.content.lower()

    # Case B: Derivation steps provided
    req_with_steps = TutoringRequest(
        request_id="TREQ_WITH_STEPS",
        learner_id="LEARNER_T7",
        intent="check_work",
        message="Here is my working",
        concept_ids=["PHY_KIN"],
        context={
            "is_correct": False,
            "submitted_answer": "v = 20 m/s",
            "work_steps": [
                {"step_index": 0, "text": "Step 1: Identified initial velocity u = 0"},
                {"step_index": 1, "text": "Step 2: Applied v^2 = u^2 + 2as with a = -9.8"},
                {"step_index": 2, "text": "Step 3: Substituted s = 10m giving v = 14 m/s"},
            ],
            "has_work_steps": True,
        },
    )
    resp_with_steps = engine.deliver_tutoring(req_with_steps)
    assert resp_with_steps.metadata["feedback_basis"] == "derivation_and_outcome"
    assert resp_with_steps.metadata["derivation_analyzed"] is True
    assert "intermediate steps" in resp_with_steps.content.lower()
    assert "3 steps evaluated" in resp_with_steps.content


def test_derivation_analysis_rejects_unrelated_working():
    """Verify system does NOT mark derivation_analyzed=True merely because work_steps is nonempty.
    
    If submitted steps do not match recognized governing equations or definitions for the concept,
    the system must refuse to claim successful derivation analysis and fall back to cautious feedback.
    """
    engine = TutoringEngine()

    req_bogus_steps = TutoringRequest(
        request_id="TREQ_BOGUS_STEPS",
        learner_id="LEARNER_T7B",
        intent="check_work",
        message="I wrote some thoughts",
        concept_ids=["PHY_KIN"],
        context={
            "is_correct": False,
            "submitted_answer": "B",
            "work_steps": [
                {"step_index": 0, "text": "I guessed option B because it felt right"},
                {"step_index": 1, "text": "I have no idea about physics equations"},
                {"step_index": 2, "text": "random thought without math or variables"},
            ],
            "has_work_steps": True,
        },
    )
    resp = engine.deliver_tutoring(req_bogus_steps)
    assert resp.metadata["derivation_analyzed"] is False
    assert resp.metadata["feedback_basis"] == "score_only_with_unverified_steps"
    assert resp.metadata["derivation_eval_reason"] == "unrecognized_steps_no_governing_equations_matched"
    assert "could not be verified against the governing equations" in resp.content or "did not match recognized governing equations" in resp.content


def test_source_grounding_verified_vs_unverified():
    """Verify authentic source citations without synthetic placeholders like JEE-CANONICAL-SYLLABUS."""
    engine = TutoringEngine()

    # Verified concept
    req_verified = TutoringRequest(
        request_id="TREQ_VERIF",
        learner_id="LEARNER_T8",
        intent="explain_concept",
        message="Explain kinematics",
        concept_ids=["PHY_KIN"],
    )
    resp_verified = engine.deliver_tutoring(req_verified)
    cit_v = resp_verified.metadata.get("source_citation", {})
    assert cit_v.get("status") == "verified"
    assert "NCERT" in cit_v.get("source_id", "")

    # Unverified / unknown concept
    req_unverified = TutoringRequest(
        request_id="TREQ_UNVERIF",
        learner_id="LEARNER_T9",
        intent="explain_concept",
        message="Explain unknown topic",
        concept_ids=["NON_EXISTENT_CONCEPT_XYZ"],
    )
    resp_unverified = engine.deliver_tutoring(req_unverified)
    cit_u = resp_unverified.metadata.get("source_citation", {})
    assert cit_u.get("status") == "source_unavailable"
    assert cit_u.get("is_verified") is False
    assert "JEE-CANONICAL-SYLLABUS" not in str(cit_u)


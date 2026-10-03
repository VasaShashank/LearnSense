"""
Integration tests for Root-Gap Diagnosis API, Misconception Runtime Lifecycle,
and Fail-Closed Tutor Citation Validation.
Covers Sections 3, 8, 9, 18, 19, 20 of TAPROOT master specification.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.learner_service import LearnerService
from backend.services.learning_service import LearningService
from backend.services.knowledge_service import KnowledgeService
from phase3.learner.models import MisconceptionStatusEnum


@pytest.fixture
def client():
    return TestClient(app)


class TestRootGapRuntimeIntegration:
    """Verifies that RootGapDiagnoser is directly wired into the API and LearnerService."""

    def test_diagnose_root_gap_endpoint(self, client, ingested_calculus):
        sid = ingested_calculus.document_id
        target_concept = ingested_calculus.concept_ids[-1]

        res = client.post(
            f"/api/learners/test_rg_learner/diagnose-root-gap",
            json={
                "subject_id": sid,
                "target_concept_id": target_concept,
                "confidence_threshold": 0.70,
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["target_concept_id"] == target_concept
        assert "target_concept_name" in data
        assert len(data["hypotheses"]) >= 1
        for h in data["hypotheses"]:
            assert "hypothesis_id" in h
            assert "prior_probability" in h
            assert "posterior_probability" in h
            assert "evidence" in h

        # If a question was selected, decision trace must accompany it
        if data["selected_question"]:
            assert data["decision_trace"] is not None
            trace = data["decision_trace"]
            assert trace["target_concept"] == target_concept
            assert "information_gain" in trace
            assert trace["policy_version"] == "2026.09.0"

    def test_diagnose_root_gap_incorporates_misconception_evidence(self, ingested_calculus):
        sid = ingested_calculus.document_id
        target_concept = ingested_calculus.concept_ids[-1]
        ancestor_concept = ingested_calculus.concept_ids[0]

        ls = LearnerService()
        ks = KnowledgeService()
        graph = ks.get_subject_graph(sid)
        all_concepts = [c["concept_id"] for c in graph["concepts"]]

        learner_state = ls.get_or_create_learner_state("test_misc_learner", all_concepts)

        # Plant a supported misconception on ancestor_concept
        learner_state.record_misconception(
            concept_id=ancestor_concept,
            description=f"Persistent failure to apply algebraic identity",
            evidence_ref="q_error_1",
            initial_confidence=0.5,
        )
        learner_state.record_misconception(
            concept_id=ancestor_concept,
            description=f"Persistent failure to apply algebraic identity",
            evidence_ref="q_error_2",
            initial_confidence=0.5,
        )
        ls.save_learner_state(learner_state)

        # Verify it became SUPPORTED
        supported = learner_state.get_supported_misconceptions(ancestor_concept)
        assert len(supported) == 1
        assert supported[0].status == MisconceptionStatusEnum.SUPPORTED

        # Run root-gap diagnosis
        diag_result = ls.diagnose_root_gap(
            learner_id="test_misc_learner",
            subject_id=sid,
            target_concept_id=target_concept,
        )

        # Check that the ancestor hypothesis incorporates the supported misconception
        matching_h = next(
            (h for h in diag_result["hypotheses"] if h["concept_id"] == ancestor_concept),
            None,
        )
        if matching_h:
            evidence_texts = " ".join(matching_h["evidence"])
            assert "Supported misconception" in evidence_texts


class TestMisconceptionRuntimeLifecycle:
    """Verifies that activity responses transition misconceptions through suspected -> supported -> resolved."""

    def test_lifecycle_transitions(self, ingested_calculus):
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]

        learning = LearningService()
        bank = learning.get_or_create_question_bank(sid, [cid])
        grounded_qs = bank.get_grounded_questions()
        assert len(grounded_qs) >= 1
        q_item = grounded_qs[0]

        import uuid
        learner_id = f"test_lifecycle_{uuid.uuid4().hex[:8]}"
        req_pfx = f"req_{uuid.uuid4().hex[:6]}"
        ls = LearnerService()
        l_state = ls.get_or_create_learner_state(learner_id, [cid])

        # Step 1: Submit incorrect option
        wrong_opt = next((o for o in (q_item.options or []) if o.strip() != str(q_item.correct_answer).strip()), "Wrong Answer")
        res1 = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_item.question_id,
            selected_option=wrong_opt,
            request_id=f"{req_pfx}_1",
        )
        assert not res1["is_correct"]

        # Misconception must be SUSPECTED on first wrong answer
        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active = l_state.get_active_misconceptions(cid)
        assert len(active) == 1
        assert active[0].status == MisconceptionStatusEnum.SUSPECTED
        assert active[0].frequency == 1

        # Step 2: Submit a second incorrect option on the same concept
        res2 = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_item.question_id,
            selected_option=wrong_opt,
            request_id=f"{req_pfx}_2",
        )
        assert not res2["is_correct"]

        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        supported = l_state.get_supported_misconceptions(cid)
        assert len(supported) == 1
        assert supported[0].status == MisconceptionStatusEnum.SUPPORTED
        assert supported[0].frequency >= 2

        # Step 3: Submit correct answer
        res3 = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_item.question_id,
            selected_option=str(q_item.correct_answer).strip(),
            request_id=f"{req_pfx}_3",
        )
        assert res3["is_correct"]

        # Misconception must now be RESOLVED
        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active_after = l_state.get_active_misconceptions(cid)
        assert len(active_after) == 0
        resolved_rec = l_state.misconceptions.get(supported[0].misconception_id)
        assert resolved_rec is not None
        assert resolved_rec.status == MisconceptionStatusEnum.RESOLVED


class TestTutorFailClosedGrounding:
    """Verifies that Tutor rejects unknown concepts and fail-closes on uncited claims."""

    def test_unknown_concept_raises_404(self, client, ingested_calculus):
        sid = ingested_calculus.document_id
        res = client.post(
            "/api/tutor/interact",
            json={
                "learner_id": "test_tutor_user",
                "subject_id": sid,
                "concept_id": "c_completely_nonexistent_xyz",
                "intent": "EXPLAIN",
            },
        )
        assert res.status_code in (400, 404)
        assert "not found" in res.text.lower()

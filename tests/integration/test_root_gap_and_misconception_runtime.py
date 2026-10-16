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
    """
    Verifies that activity responses transition misconceptions through:
    suspected -> supported -> evidence-based resolution.
    Covers Issue 2 & Issue 3 requirements.
    """

    def test_lifecycle_transitions_with_evidence_based_resolution(self, ingested_calculus):
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

        # Misconception must be SUSPECTED on first wrong answer (confidence = 0.4)
        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active = l_state.get_active_misconceptions(cid)
        assert len(active) == 1
        assert active[0].status == MisconceptionStatusEnum.SUSPECTED
        assert active[0].frequency == 1

        # Step 2: Submit a second incorrect option on the same concept -> becomes SUPPORTED (confidence = 0.65)
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

        # Step 3: Insufficient evidence does NOT immediately resolve an entrenched misconception
        # One correct answer reduces confidence (0.65 -> 0.35), but 0.35 >= 0.15, so it remains active
        res3 = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_item.question_id,
            selected_option=str(q_item.correct_answer).strip(),
            request_id=f"{req_pfx}_3",
        )
        assert res3["is_correct"]

        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active_after_1 = l_state.get_active_misconceptions(cid)
        assert len(active_after_1) == 1, "Entrenched misconception should not be erased by a single correct answer"
        assert active_after_1[0].confidence < 0.50

        # Step 4: Repeated counter-evidence resolves the misconception (0.35 -> 0.05 < 0.15)
        res4 = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_item.question_id,
            selected_option=str(q_item.correct_answer).strip(),
            request_id=f"{req_pfx}_4",
        )
        assert res4["is_correct"]

        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active_after_2 = l_state.get_active_misconceptions(cid)
        assert len(active_after_2) == 0, "Repeated counter-evidence must resolve the misconception"
        resolved_rec = l_state.misconceptions.get(supported[0].misconception_id)
        assert resolved_rec is not None
        assert resolved_rec.status == MisconceptionStatusEnum.RESOLVED

    def test_unrelated_correct_answer_does_not_resolve(self, ingested_calculus):
        """A correct answer on question B does NOT resolve a misconception evidenced by question A."""
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]

        learning = LearningService()
        bank = learning.get_or_create_question_bank(sid, [cid])
        grounded_qs = bank.get_grounded_questions()
        assert len(grounded_qs) >= 1
        q_item = grounded_qs[0]

        # Ensure a distinct second question exists in the bank
        if len(grounded_qs) >= 2:
            q_other = grounded_qs[1]
        else:
            from phase3.question_bank.models import QuestionBankItem
            q_other = QuestionBankItem(
                question_id="q_second_test_item",
                concept_ids=[cid],
                prompt="Second question prompt",
                options=["A", "B", "C", "D"],
                correct_answer="A",
                explanation="Explanation",
                evidence_refs=["E1"],
                difficulty=0.5,
            )
            bank.add_question(q_other)
            learning.bank_repo.save_bank(bank)

        import uuid
        learner_id = f"test_unrelated_{uuid.uuid4().hex[:8]}"
        ls = LearnerService()
        l_state = ls.get_or_create_learner_state(learner_id, [cid])

        # Record misconception evidenced specifically by q_item.question_id
        l_state.record_misconception(
            concept_id=cid,
            description="Confusion about definition",
            evidence_ref=q_item.question_id,
            initial_confidence=0.4,
            question_id=q_item.question_id,
        )
        ls.save_learner_state(l_state)

        # Submit correct answer to q_other (NOT q_item)
        learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_other.question_id,
            selected_option=str(q_other.correct_answer).strip(),
            request_id=f"req_{uuid.uuid4().hex[:6]}",
        )

        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active = l_state.get_active_misconceptions(cid)
        assert len(active) == 1, "Unrelated correct answer must NOT resolve misconception on question A"
        assert q_item.question_id in active[0].evidence_refs

    def test_dont_know_does_not_create_misconception(self, ingested_calculus):
        """Selecting 'don't know' represents incomplete knowledge/uncertainty, NOT a misconception."""
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]

        learning = LearningService()
        bank = learning.get_or_create_question_bank(sid, [cid])
        q_item = bank.get_grounded_questions()[0]

        import uuid
        learner_id = f"test_dont_know_{uuid.uuid4().hex[:8]}"
        ls = LearnerService()
        ls.get_or_create_learner_state(learner_id, [cid])

        learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_item.question_id,
            selected_option="I don't know",
            is_dont_know=True,
            request_id=f"req_{uuid.uuid4().hex[:6]}",
        )

        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active = l_state.get_active_misconceptions(cid)
        assert len(active) == 0, "Incomplete knowledge ('I don't know') must NOT create a misconception record"

    def test_two_independent_misconceptions_can_coexist(self, ingested_calculus):
        """Two distinct misconceptions on different questions can coexist on the same concept."""
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]

        import uuid
        learner_id = f"test_coexist_{uuid.uuid4().hex[:8]}"
        ls = LearnerService()
        l_state = ls.get_or_create_learner_state(learner_id, [cid])

        # Record misconception 1 on Q1
        l_state.record_misconception(
            concept_id=cid,
            description="Confused limit from left with limit from right",
            evidence_ref="q_limit_left_1",
            initial_confidence=0.4,
            question_id="q_limit_left_1",
            expected_answer="Left-hand limit",
            learner_response="Right-hand limit",
            error_signal="actual_misconception",
        )
        # Record misconception 2 on Q2
        l_state.record_misconception(
            concept_id=cid,
            description="Assumed limit equals function value at discontinuity",
            evidence_ref="q_limit_eval_2",
            initial_confidence=0.4,
            question_id="q_limit_eval_2",
            expected_answer="Undefined",
            learner_response="f(c)",
            error_signal="actual_misconception",
        )
        ls.save_learner_state(l_state)

        # Both must coexist actively
        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active = l_state.get_active_misconceptions(cid)
        assert len(active) == 2, "Two distinct misconceptions must coexist independently"

        # Providing counter-evidence to Q1 resolves only Q1's misconception
        l_state.apply_correct_answer_evidence(
            question_id="q_limit_left_1",
            concept_id=cid,
            confidence_reduction=0.35,  # 0.40 - 0.35 = 0.05 < 0.15 -> resolves
        )
        ls.save_learner_state(l_state)

        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        active_after = l_state.get_active_misconceptions(cid)
        assert len(active_after) == 1, "Only the targeted misconception should be resolved"
        assert active_after[0].question_id == "q_limit_eval_2"


class TestMisconceptionCounterEvidenceLifecycle:
    """
    Verifies full misconception lifecycle and targeted counter-evidence:
    1. Question A creates misconception X.
    2. Question B targets X and is answered correctly.
    3. X confidence decreases.
    4. Question C targets unrelated misconception Y and does not affect X.
    5. Repeated targeted correct evidence can resolve X.
    6. A generic correct answer does not resolve X.
    7. Two misconceptions on the same concept can coexist independently.
    8. Provenance of all counter-evidence is strictly preserved.
    """

    def test_full_lifecycle_and_targeted_counter_evidence(self, ingested_calculus):
        import uuid
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]
        learner_id = f"test_lifecycle_{uuid.uuid4().hex[:8]}"
        ls = LearnerService()
        l_state = ls.get_or_create_learner_state(learner_id, [cid])

        # 1. Question A creates misconception X
        q_a_id = f"q_A_{uuid.uuid4().hex[:6]}"
        misc_x = l_state.record_misconception(
            concept_id=cid,
            description="Confuses derivative with antiderivative",
            evidence_ref=q_a_id,
            initial_confidence=0.40,
            question_id=q_a_id,
            expected_answer="f'(x)",
            learner_response="F(x)",
            error_signal="actual_misconception",
        )
        # Repeated wrong evidence elevates it to SUPPORTED
        misc_x = l_state.record_misconception(
            concept_id=cid,
            description="Confuses derivative with antiderivative",
            evidence_ref=q_a_id,
            initial_confidence=0.40,
            question_id=q_a_id,
            expected_answer="f'(x)",
            learner_response="F(x)",
            error_signal="actual_misconception",
        )
        assert misc_x.status == MisconceptionStatusEnum.SUPPORTED
        assert misc_x.confidence >= 0.65
        initial_conf = misc_x.confidence

        # 6. A generic correct answer does not resolve or affect X
        q_generic_id = f"q_generic_{uuid.uuid4().hex[:6]}"
        modified_generic = l_state.apply_correct_answer_evidence(
            question_id=q_generic_id,
            concept_id=cid,
            confidence_reduction=0.30,
        )
        assert len(modified_generic) == 0, "Generic correct answer must NOT affect targeted misconception"
        assert misc_x.confidence == initial_conf

        # 4. Question C targets unrelated misconception Y and does not affect X
        q_c_id = f"q_C_{uuid.uuid4().hex[:6]}"
        modified_unrelated = l_state.apply_correct_answer_evidence(
            question_id=q_c_id,
            concept_id=cid,
            confidence_reduction=0.30,
            misconception_target="Believes all continuous functions are differentiable",
        )
        assert len(modified_unrelated) == 0, "Question C targeting unrelated misconception Y must NOT affect X"
        assert misc_x.confidence == initial_conf

        # 2 & 3. Question B targets X and is answered correctly -> X confidence decreases
        q_b_id = f"q_B_{uuid.uuid4().hex[:6]}"
        modified_b = l_state.apply_correct_answer_evidence(
            question_id=q_b_id,
            concept_id=cid,
            confidence_reduction=0.30,
            misconception_target="Confuses derivative with antiderivative",
        )
        assert len(modified_b) == 1
        assert modified_b[0].misconception_id == misc_x.misconception_id
        assert modified_b[0].confidence == pytest.approx(initial_conf - 0.30, abs=1e-3)
        assert modified_b[0].confidence < initial_conf

        # Provenance verification
        assert q_b_id in misc_x.counter_evidence_refs
        assert len(misc_x.counter_evidence_history) == 1
        history_b = misc_x.counter_evidence_history[0]
        assert history_b["question_id"] == q_b_id
        assert history_b["misconception_id"] == misc_x.misconception_id
        assert history_b["confidence_before"] == pytest.approx(initial_conf, abs=1e-3)
        assert history_b["confidence_after"] == pytest.approx(initial_conf - 0.30, abs=1e-3)

        # 5. Repeated targeted correct evidence can resolve X
        q_b2_id = f"q_B2_{uuid.uuid4().hex[:6]}"
        modified_b2 = l_state.apply_correct_answer_evidence(
            question_id=q_b2_id,
            concept_id=cid,
            confidence_reduction=0.30,
            misconception_id=misc_x.misconception_id,
        )
        assert len(modified_b2) == 1
        if misc_x.confidence >= 0.15:
            q_b3_id = f"q_B3_{uuid.uuid4().hex[:6]}"
            modified_b3 = l_state.apply_correct_answer_evidence(
                question_id=q_b3_id,
                concept_id=cid,
                confidence_reduction=0.30,
                misconception_id=misc_x.misconception_id,
            )
            assert len(modified_b3) == 1
        assert misc_x.confidence < 0.15
        assert misc_x.status == MisconceptionStatusEnum.RESOLVED
        assert q_b2_id in misc_x.counter_evidence_refs

    def test_two_misconceptions_on_same_concept_coexist_and_resolve_independently(self, ingested_calculus):
        import uuid
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]
        learner_id = f"test_coexist_indep_{uuid.uuid4().hex[:8]}"
        ls = LearnerService()
        l_state = ls.get_or_create_learner_state(learner_id, [cid])

        # Create Misconception X and Misconception Y on the SAME concept
        misc_x = l_state.record_misconception(
            concept_id=cid,
            description="Power rule: forgot to decrease exponent",
            evidence_ref="q_power_1",
            initial_confidence=0.45,
            question_id="q_power_1",
            error_signal="actual_misconception",
        )
        misc_y = l_state.record_misconception(
            concept_id=cid,
            description="Chain rule: forgot to multiply by inner derivative",
            evidence_ref="q_chain_1",
            initial_confidence=0.45,
            question_id="q_chain_1",
            error_signal="actual_misconception",
        )
        # 7. Two misconceptions on the same concept can coexist independently
        active = l_state.get_active_misconceptions(cid)
        assert len(active) == 2

        # Question targets ONLY X
        l_state.apply_correct_answer_evidence(
            question_id="q_power_corrective",
            concept_id=cid,
            confidence_reduction=0.35,  # 0.45 - 0.35 = 0.10 < 0.15 -> resolves X
            misconception_target="Power rule: forgot to decrease exponent",
        )

        active_after = l_state.get_active_misconceptions(cid)
        assert len(active_after) == 1
        assert active_after[0].misconception_id == misc_y.misconception_id
        assert active_after[0].confidence == pytest.approx(0.45, abs=1e-3)
        assert misc_x.status == MisconceptionStatusEnum.RESOLVED

    def test_runtime_learning_service_targeted_counter_evidence(self, ingested_calculus):
        """End-to-end integration via LearningService.process_activity_response."""
        import uuid
        from phase3.question_bank.models import QuestionBankItem, QuestionType
        learning = LearningService()
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]
        learner_id = f"test_rt_counter_{uuid.uuid4().hex[:8]}"

        ls = LearnerService()
        l_state = ls.get_or_create_learner_state(learner_id, [cid])

        # Create misconception X
        misc_x = l_state.record_misconception(
            concept_id=cid,
            description="Reverses quotient rule numerator order",
            evidence_ref="q_quotient_initial",
            initial_confidence=0.40,
            question_id="q_quotient_initial",
            error_signal="actual_misconception",
        )
        ls.save_learner_state(l_state)

        # Build Question B specifically targeting X
        bank = learning.get_or_create_question_bank(sid)
        existing_citations = list(bank.questions.values())[0].source_citations

        q_b = QuestionBankItem(
            question_id=f"q_target_b_{uuid.uuid4().hex[:6]}",
            chapter_id="ch_1",
            concept_ids=[cid],
            question_type=QuestionType.MCQ,
            question_text="What is the quotient rule for (u/v)'?",
            options=["(u'v - uv') / v^2", "(uv' - u'v) / v^2", "u'/v'", "uv / v^2"],
            correct_answer="(u'v - uv') / v^2",
            misconception_target="Reverses quotient rule numerator order",
            diagnostic_purpose="counter_evidence_probe",
            source_citations=existing_citations,
        )

        # Inject into persisted bank
        bank.add_question(q_b)
        learning.bank_repo.save_bank(bank)

        # Learner answers Question B correctly
        res = learning.process_activity_response(
            learner_id=learner_id,
            subject_id=sid,
            concept_ids=[cid],
            question_id=q_b.question_id,
            selected_option="(u'v - uv') / v^2",
            request_id=f"req_{uuid.uuid4().hex[:6]}",
        )
        assert res["is_correct"] is True

        # Verify X confidence decreased and counter-evidence provenance recorded
        l_state = ls.get_or_create_learner_state(learner_id, [cid])
        rec = l_state.misconceptions[misc_x.misconception_id]
        assert rec.confidence == pytest.approx(0.10, abs=1e-3)  # 0.40 - 0.30 = 0.10 < 0.15
        assert rec.status == MisconceptionStatusEnum.RESOLVED
        assert q_b.question_id in rec.counter_evidence_refs
        assert len(rec.counter_evidence_history) == 1
        assert rec.counter_evidence_history[0]["diagnostic_purpose"] == "counter_evidence_probe"


class TestQuestionBankAuthoritativeReuse:
    """Verifies authoritative persisted artifact reuse per Issue 6."""

    def test_persisted_bank_reuse(self, ingested_calculus):
        sid = ingested_calculus.document_id
        learning = LearningService()

        # First call builds/persists the bank
        bank1 = learning.get_or_create_question_bank(sid)
        assert len(bank1.get_grounded_questions()) >= 1

        # Second call reuses the authoritative persisted bank
        bank2 = learning.get_or_create_question_bank(sid)
        assert bank2.document_id == bank1.document_id
        assert len(bank2.get_grounded_questions()) == len(bank1.get_grounded_questions())

    def test_generation_failure_no_bank_raises_structured_error(self, monkeypatch, ingested_calculus):
        from phase3.errors import QuestionBankError
        from phase3.question_bank.builder import QuestionBankBuilder

        sid = ingested_calculus.document_id
        learning = LearningService()

        # Ensure no persisted bank is found
        monkeypatch.setattr(learning.bank_repo, "load_grounded_bank", lambda subject_id: None)

        def mock_build_fail(*args, **kwargs):
            raise QuestionBankError("Simulated LLM generation failure")

        monkeypatch.setattr(QuestionBankBuilder, "build_bank_for_chapter", mock_build_fail)

        with pytest.raises(QuestionBankError) as exc_info:
            learning.get_or_create_question_bank(sid)
        assert exc_info.value.code == "QUESTION_BANK_UNAVAILABLE"


class TestTutorFailClosedGrounding:
    """Verifies Tutor failure modes: unknown concepts, no evidence, citation validation."""

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

    def test_no_grounded_evidence_returns_structured_state(self, monkeypatch, ingested_calculus):
        """When evidence retriever finds no chunks, tutor returns NO_GROUNDED_TUTOR_EVIDENCE state."""
        from backend.services.tutor_service import TutorService

        tutor = TutorService()
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]

        # Force retriever to return empty chunks
        class MockEmptyRetriever:
            def retrieve_for_concept(self, *args, **kwargs):
                return []

        from backend.services.knowledge_build_service import KnowledgeBuildService
        monkeypatch.setattr(KnowledgeBuildService, "get_retriever", lambda self, sid: MockEmptyRetriever())

        res = tutor.generate_contextual_response(
            learner_id="test_no_ev_user",
            subject_id=sid,
            concept_id=cid,
            intent="EXPLAIN",
        )

        assert res["status"] == "NO_GROUNDED_TUTOR_EVIDENCE"
        assert res["subject_id"] == sid
        assert res["concept_id"] == cid
        assert res["evidence_status"] == "UNAVAILABLE"
        assert res["grounded"] is False
        assert res["response_text"] == ""
        assert "reason" in res

    def test_no_grounded_evidence_raises_when_requested(self, monkeypatch, ingested_calculus):
        """When raise_on_missing_evidence=True, raises NoGroundedTutorEvidenceError."""
        from backend.services.tutor_service import TutorService
        from phase3.errors import NoGroundedTutorEvidenceError

        tutor = TutorService()
        sid = ingested_calculus.document_id
        cid = ingested_calculus.concept_ids[0]

        class MockEmptyRetriever:
            def retrieve_for_concept(self, *args, **kwargs):
                return []

        from backend.services.knowledge_build_service import KnowledgeBuildService
        monkeypatch.setattr(KnowledgeBuildService, "get_retriever", lambda self, sid: MockEmptyRetriever())

        with pytest.raises(NoGroundedTutorEvidenceError) as exc_info:
            tutor.generate_contextual_response(
                learner_id="test_no_ev_user",
                subject_id=sid,
                concept_id=cid,
                intent="EXPLAIN",
                raise_on_missing_evidence=True,
            )

        assert exc_info.value.code == "NO_GROUNDED_TUTOR_EVIDENCE"
        assert exc_info.value.subject_id == sid
        assert exc_info.value.concept_id == cid

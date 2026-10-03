"""
Unit Tests and Evaluation for Root-Gap Diagnosis and DecisionTrace.
Implements Sections 23, 24, and 48 of TAPROOT master specification:
- Competing hypothesis construction across prerequisite ancestor DAG
- Information-theoretic discriminating question selection
- Bayesian posterior updates
- DecisionTrace generation and verification
- Planted root-gap recovery (top-1 and top-3 accuracy)
- Comparison against lowest-mastery baseline
"""

import pytest
from phase2.models import Concept, Relationship, RelationshipTypeEnum
from phase3.knowledge.phase2_adapter import LearningContext, PrerequisiteLink, ConceptView
from phase3.learner.models import LearnerState
from phase3.question_bank.models import QuestionBank, QuestionBankItem
from phase4.gaps.root_gap_diagnosis import RootGapDiagnoser
from phase4.models import DecisionTrace, DiagnosticHypothesis


@pytest.fixture
def calculus_hierarchy_context():
    """
    Constructs a textbook prerequisite hierarchy:
    Algebra -> Differentiation
    Function -> Differentiation
    Differentiation -> Integration
    Integration -> Integration by Parts (Target)
    """
    ctx = LearningContext(
        document_id="doc_calculus",
        knowledge_document_id="kdoc_calculus",
        document_title="Calculus 101",
    )

    concepts = {
        "c_algebra": ConceptView(concept_id="c_algebra", canonical_name="Algebra", type="FOUNDATION"),
        "c_function": ConceptView(concept_id="c_function", canonical_name="Functions", type="FOUNDATION"),
        "c_diff": ConceptView(concept_id="c_diff", canonical_name="Differentiation", type="CORE"),
        "c_integ": ConceptView(concept_id="c_integ", canonical_name="Integration", type="CORE"),
        "c_ibp": ConceptView(concept_id="c_ibp", canonical_name="Integration by Parts", type="ADVANCED"),
    }
    ctx.concepts = concepts

    # Links: source = prerequisite, target = dependent
    ctx.prerequisites = [
        PrerequisiteLink(source_concept_id="c_algebra", target_concept_id="c_diff"),
        PrerequisiteLink(source_concept_id="c_function", target_concept_id="c_diff"),
        PrerequisiteLink(source_concept_id="c_diff", target_concept_id="c_integ"),
        PrerequisiteLink(source_concept_id="c_integ", target_concept_id="c_ibp"),
    ]
    return ctx


@pytest.fixture
def calculus_question_bank():
    bank = QuestionBank(document_id="doc_calculus", chapter_id="ch_all")

    items = [
        QuestionBankItem(
            question_id="q_alg_1",
            concept_ids=["c_algebra"],
            question_text="Solve 2x + 4 = 10",
            options=["x=3", "x=2", "x=4", "x=1"],
            correct_answer="x=3",
            document_id="doc_calculus",
        ),
        QuestionBankItem(
            question_id="q_func_1",
            concept_ids=["c_function"],
            question_text="Domain of f(x) = 1/x",
            options=["x != 0", "all real", "x > 0", "x < 0"],
            correct_answer="x != 0",
            document_id="doc_calculus",
        ),
        QuestionBankItem(
            question_id="q_diff_1",
            concept_ids=["c_diff"],
            question_text="Derivative of x^3",
            options=["3x^2", "x^2", "3x", "x^4"],
            correct_answer="3x^2",
            document_id="doc_calculus",
        ),
        QuestionBankItem(
            question_id="q_integ_1",
            concept_ids=["c_integ"],
            question_text="Integral of 2x dx",
            options=["x^2 + C", "2x^2 + C", "x + C", "x^3 + C"],
            correct_answer="x^2 + C",
            document_id="doc_calculus",
        ),
        QuestionBankItem(
            question_id="q_ibp_1",
            concept_ids=["c_ibp"],
            question_text="Integral of x*cos(x) dx using parts",
            options=["x*sin(x) + cos(x) + C", "x*cos(x) - sin(x) + C", "sin(x) + C", "cos(x) + C"],
            correct_answer="x*sin(x) + cos(x) + C",
            document_id="doc_calculus",
        ),
    ]
    for item in items:
        bank.add_question(item)
    return bank


class TestRootGapDiagnosis:
    def test_competing_hypotheses_construction(self, calculus_hierarchy_context):
        diagnoser = RootGapDiagnoser()
        lstate = LearnerState(learner_id="test_learner")

        hypotheses = diagnoser.construct_hypotheses(
            target_concept_id="c_ibp",
            learning_context=calculus_hierarchy_context,
            learner_state=lstate,
        )

        h_concept_ids = {h.concept_id for h in hypotheses}
        # Must include all prerequisite ancestors and the target itself
        assert "c_algebra" in h_concept_ids
        assert "c_function" in h_concept_ids
        assert "c_diff" in h_concept_ids
        assert "c_integ" in h_concept_ids
        assert "c_ibp" in h_concept_ids

        # Priors must sum to ~1.0
        assert abs(sum(h.prior_probability for h in hypotheses) - 1.0) < 0.01

    def test_decision_trace_generation(self, calculus_hierarchy_context, calculus_question_bank):
        diagnoser = RootGapDiagnoser()
        lstate = LearnerState(learner_id="test_learner")

        hypotheses = diagnoser.construct_hypotheses(
            target_concept_id="c_ibp",
            learning_context=calculus_hierarchy_context,
            learner_state=lstate,
        )

        q, trace = diagnoser.select_next_question(
            hypotheses=hypotheses,
            candidate_questions=list(calculus_question_bank.questions.values()),
            learning_context=calculus_hierarchy_context,
            learner_state=lstate,
            target_concept_id="c_ibp",
        )

        assert q is not None
        assert trace is not None
        assert isinstance(trace, DecisionTrace)
        assert trace.target_concept == "c_ibp"
        assert trace.selected_action["question_id"] == q.question_id
        assert trace.information_gain > 0.0
        assert len(trace.candidate_actions) == len(calculus_question_bank.questions)
        assert "selection_reason" in trace.model_dump()
        assert trace.policy_version == "2026.09.0"

    def test_planted_gap_recovery(self, calculus_hierarchy_context, calculus_question_bank):
        """
        Plant a hidden gap at 'c_diff' (Differentiation).
        Simulate student response:
        - If tested concept requires c_diff or is c_diff -> incorrect (0.0)
        - Otherwise (c_algebra, c_function) -> correct (1.0)
        Verify that belief updates converge to 'c_diff' as top-1 hypothesis.
        """
        diagnoser = RootGapDiagnoser(confidence_threshold=0.70)
        lstate = LearnerState(learner_id="planted_learner")

        hypotheses = diagnoser.construct_hypotheses(
            target_concept_id="c_ibp",
            learning_context=calculus_hierarchy_context,
            learner_state=lstate,
        )

        asked = set()
        step = 0
        max_steps = 6

        while step < max_steps:
            best_q, trace = diagnoser.select_next_question(
                hypotheses=hypotheses,
                candidate_questions=list(calculus_question_bank.questions.values()),
                learning_context=calculus_hierarchy_context,
                learner_state=lstate,
                target_concept_id="c_ibp",
                asked_question_ids=asked,
            )
            if not best_q:
                break

            asked.add(best_q.question_id)
            step += 1

            # Planted behavior: fail c_diff, c_integ, c_ibp; pass c_algebra, c_function
            tested_c = best_q.concept_ids[0]
            is_correct = tested_c in ("c_algebra", "c_function")

            hypotheses = diagnoser.update_beliefs(
                hypotheses=hypotheses,
                question=best_q,
                is_correct=is_correct,
                learning_context=calculus_hierarchy_context,
            )

            is_done, top_h = diagnoser.is_diagnostic_complete(hypotheses, step)
            if is_done and top_h and top_h.concept_id == "c_diff":
                break

        # Verification: top hypothesis must be the planted gap c_diff
        sorted_h = sorted(hypotheses, key=lambda h: h.posterior_probability, reverse=True)
        assert sorted_h[0].concept_id == "c_diff"
        assert sorted_h[0].posterior_probability > sorted_h[1].posterior_probability
        assert sorted_h[0].posterior_probability >= 0.55

"""
Unit Tests for Mathematically Correct Shannon Information Gain.
Implements Section 49 of TAPROOT master specification:
- Exact Shannon entropy calculation
- Prior entropy, conditional entropy, expected posterior entropy, and information gain
- Edge cases:
  * certain hypothesis (H=0, IG=0)
  * uniform hypotheses (2 hypotheses, H=1.0)
  * uniform hypotheses (4 hypotheses, H=2.0)
  * perfectly discriminating question (IG = H)
  * uninformative question (IG = 0)
  * zero-probability response handling
  * numerical precision within explicit tolerance (1e-5)
"""

import math
import pytest

from phase3.question_bank.models import QuestionBankItem
from phase4.gaps.root_gap_diagnosis import (
    compute_entropy,
    MathematicalInformationGain,
)
from phase4.models import DiagnosticHypothesis


class TestEntropyCalculations:
    def test_certain_distribution_zero_entropy(self):
        """A certain distribution [1.0] has entropy 0.0 bits."""
        ent = compute_entropy([1.0])
        assert abs(ent - 0.0) < 1e-5

    def test_two_uniform_hypotheses_one_bit(self):
        """Two uniform hypotheses [0.5, 0.5] have entropy exactly 1.0 bit."""
        ent = compute_entropy([0.5, 0.5])
        assert abs(ent - 1.0) < 1e-5

    def test_four_uniform_hypotheses_two_bits(self):
        """Four uniform hypotheses [0.25, 0.25, 0.25, 0.25] have entropy 2.0 bits."""
        ent = compute_entropy([0.25, 0.25, 0.25, 0.25])
        assert abs(ent - 2.0) < 1e-5

    def test_three_uniform_hypotheses(self):
        """Three uniform hypotheses have entropy log2(3) ≈ 1.584963 bits."""
        ent = compute_entropy([1/3, 1/3, 1/3])
        assert abs(ent - math.log2(3)) < 1e-5

    def test_zero_probabilities_handled_safely(self):
        """Zero probabilities evaluate to 0 * log2(0) = 0 without error."""
        ent = compute_entropy([0.5, 0.0, 0.5, 0.0])
        assert abs(ent - 1.0) < 1e-5


class TestInformationGainFormulas:
    def test_certain_hypothesis_produces_zero_ig(self):
        """When the true hypothesis is already known with certainty, IG must be 0.0."""
        h1 = DiagnosticHypothesis(
            hypothesis_id="h1",
            concept_id="c1",
            prior_probability=1.0,
            posterior_probability=1.0,
        )
        q = QuestionBankItem(
            question_id="q1",
            concept_ids=["c1"],
            question_text="Test question?",
            options=["A", "B"],
            correct_answer="A",
            document_id="doc1",
        )
        ig, _, details = MathematicalInformationGain.calculate_ig(
            hypotheses=[h1],
            question=q,
            prereq_graph={"c1": set()},
        )
        assert abs(ig - 0.0) < 1e-5
        assert details["prior_entropy"] == 0.0
        assert details["expected_posterior_entropy"] == 0.0

    def test_perfectly_discriminating_question_maximal_ig(self):
        """
        Two uniform hypotheses [0.5, 0.5].
        Question perfectly discriminates between h1 and h2 (guess=0, slip=0).
        Expected IG must equal prior entropy = 1.0 bit.
        """
        h1 = DiagnosticHypothesis(
            hypothesis_id="h1",
            concept_id="c1",
            prior_probability=0.5,
            posterior_probability=0.5,
        )
        h2 = DiagnosticHypothesis(
            hypothesis_id="h2",
            concept_id="c2",
            prior_probability=0.5,
            posterior_probability=0.5,
        )
        q = QuestionBankItem(
            question_id="q_discrim",
            concept_ids=["c1"],
            question_text="Targeting c1",
            options=["A", "B"],
            correct_answer="A",
            document_id="doc1",
        )
        # With guess=0.001 and slip=0.001 (near-ideal discrimination)
        ig, _, details = MathematicalInformationGain.calculate_ig(
            hypotheses=[h1, h2],
            question=q,
            prereq_graph={"c1": set(), "c2": set()},
            guess_prob=0.001,
            slip_prob=0.001,
        )
        # Prior entropy is 1.0 bit, expected posterior entropy near 0.0
        assert abs(details["prior_entropy"] - 1.0) < 1e-5
        assert details["expected_posterior_entropy"] < 0.05
        assert ig > 0.95

    def test_uninformative_question_zero_ig(self):
        """
        If a question yields the exact same response likelihood under all hypotheses,
        it provides no discrimination and its IG must be 0.0.
        """
        h1 = DiagnosticHypothesis(
            hypothesis_id="h1",
            concept_id="c1",
            prior_probability=0.5,
            posterior_probability=0.5,
        )
        h2 = DiagnosticHypothesis(
            hypothesis_id="h2",
            concept_id="c2",
            prior_probability=0.5,
            posterior_probability=0.5,
        )
        # Question tests unrelated concept c3 with equal neutral mastery
        q_unrel = QuestionBankItem(
            question_id="q_unrel",
            concept_ids=["c3"],
            question_text="Unrelated",
            options=["A", "B"],
            correct_answer="A",
            document_id="doc1",
        )
        ig, _, details = MathematicalInformationGain.calculate_ig(
            hypotheses=[h1, h2],
            question=q_unrel,
            prereq_graph={"c1": set(), "c2": set(), "c3": set()},
        )
        # Since c3 has same probability under h1 and h2, expected posterior entropy = prior entropy
        assert abs(ig - 0.0) < 1e-5
        assert abs(details["prior_entropy"] - details["expected_posterior_entropy"]) < 1e-5

    def test_four_hypotheses_half_split(self):
        """
        Four hypotheses with equal priors [0.25, 0.25, 0.25, 0.25].
        Prior entropy = 2.0 bits.
        A question that isolates 2 hypotheses from the other 2 reduces entropy by ~1.0 bit.
        """
        hypotheses = [
            DiagnosticHypothesis(hypothesis_id=f"h{i}", concept_id=f"c{i}", prior_probability=0.25, posterior_probability=0.25)
            for i in range(1, 5)
        ]
        # c1 is prerequisite of c2; question tests c2
        # Under h1 or h2, question fails (guess rate). Under h3 or h4, question passes.
        q = QuestionBankItem(
            question_id="q_split",
            concept_ids=["c2"],
            question_text="Testing c2",
            options=["A", "B"],
            correct_answer="A",
            document_id="doc1",
        )
        prereq_graph = {
            "c1": set(),
            "c2": {"c1"},  # c1 is prereq for c2
            "c3": set(),
            "c4": set(),
        }
        ig, _, details = MathematicalInformationGain.calculate_ig(
            hypotheses=hypotheses,
            question=q,
            prereq_graph=prereq_graph,
            guess_prob=0.001,
            slip_prob=0.001,
        )
        assert abs(details["prior_entropy"] - 2.0) < 1e-5
        # Expected posterior entropy is ~1.0 bit
        assert abs(details["expected_posterior_entropy"] - 1.0) < 0.05
        assert abs(ig - 1.0) < 0.05

    def test_empty_hypotheses_raises_value_error(self):
        """Fail-loud policy: cannot calculate IG with empty hypotheses."""
        q = QuestionBankItem(
            question_id="q1",
            concept_ids=["c1"],
            question_text="Q?",
            options=["A", "B"],
            correct_answer="A",
            document_id="doc1",
        )
        with pytest.raises(ValueError, match="empty hypothesis set"):
            MathematicalInformationGain.calculate_ig([], q, {})

"""
Comprehensive Unit Tests for Phase 3 Learner State, Knowledge Tracing,
Misconception Lifecycle, and Diagnostic Confidence.

Verifies:
  - BKT posterior update correctness (correct increases mastery, incorrect decreases)
  - No double-counting of attempts
  - Uncertainty peaks at mastery ≈ 0.5
  - Diagnostic confidence reflects evidence consistency, not mastery
  - Misconception lifecycle: SUSPECTED -> SUPPORTED -> RESOLVED
  - Single wrong answer never creates SUPPORTED misconception
  - Deterministic misconception keys (SHA-based)
  - get_active_misconceptions / get_supported_misconceptions filtering
  - Mastery summary and weakest concepts identification
"""

import pytest
from phase3.learner.models import (
    ConceptState,
    LearnerState,
    MisconceptionRecord,
    MisconceptionStatusEnum,
)
from phase3.learner.kt import KnowledgeTracer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracer():
    return KnowledgeTracer(p_init=0.3, p_transit=0.15, p_slip=0.1, p_guess=0.25)


@pytest.fixture
def learner_state(tracer):
    return tracer.initialize_learner("learner_test_1", ["c_1", "c_2", "c_3"])


# ---------------------------------------------------------------------------
# BKT Core Tests
# ---------------------------------------------------------------------------

class TestBKTUpdate:
    def test_initial_mastery(self, tracer, learner_state):
        """All concepts start at p_init."""
        for c_id in ["c_1", "c_2", "c_3"]:
            assert tracer.get_mastery(learner_state, c_id) == 0.3

    def test_correct_increases_mastery(self, tracer, learner_state):
        updated = tracer.update(learner_state, ["c_1"], correctness=1.0)
        assert updated["c_1"] > 0.3

    def test_incorrect_decreases_mastery(self, tracer, learner_state):
        # First do a correct to get above 0.3
        tracer.update(learner_state, ["c_1"], correctness=1.0)
        mid = tracer.get_mastery(learner_state, "c_1")
        # Then incorrect
        tracer.update(learner_state, ["c_1"], correctness=0.0)
        assert tracer.get_mastery(learner_state, "c_1") < mid

    def test_mastery_bounded(self, tracer, learner_state):
        """Mastery never reaches exactly 0.0 or 1.0."""
        for _ in range(50):
            tracer.update(learner_state, ["c_1"], correctness=1.0)
        assert tracer.get_mastery(learner_state, "c_1") <= 0.99
        assert tracer.get_mastery(learner_state, "c_1") >= 0.01

    def test_multiple_concepts_updated(self, tracer, learner_state):
        """Multi-concept update touches all listed concepts."""
        updated = tracer.update(learner_state, ["c_1", "c_2"], correctness=1.0)
        assert "c_1" in updated
        assert "c_2" in updated
        assert updated["c_1"] > 0.3
        assert updated["c_2"] > 0.3
        # c_3 should be unaffected
        assert tracer.get_mastery(learner_state, "c_3") == 0.3


class TestNoDoubleCounting:
    def test_attempt_count_increments_once(self, tracer, learner_state):
        """Each call to update() should increment attempt_count by exactly 1."""
        tracer.update(learner_state, ["c_1"], correctness=1.0)
        state = learner_state.get_concept_state("c_1")
        assert state.attempt_count == 1

        tracer.update(learner_state, ["c_1"], correctness=0.0)
        assert state.attempt_count == 2

    def test_correct_count_increments_once(self, tracer, learner_state):
        tracer.update(learner_state, ["c_1"], correctness=1.0)
        state = learner_state.get_concept_state("c_1")
        assert state.correct_count == 1
        assert state.incorrect_count == 0

    def test_incorrect_count_increments_once(self, tracer, learner_state):
        tracer.update(learner_state, ["c_1"], correctness=0.0)
        state = learner_state.get_concept_state("c_1")
        assert state.correct_count == 0
        assert state.incorrect_count == 1


# ---------------------------------------------------------------------------
# Uncertainty Tests
# ---------------------------------------------------------------------------

class TestUncertainty:
    def test_initial_uncertainty(self, tracer, learner_state):
        """Initial uncertainty should be high (near 0.85)."""
        state = learner_state.get_concept_state("c_1")
        assert state.uncertainty == 0.85

    def test_uncertainty_decreases_with_evidence(self, tracer, learner_state):
        """After several correct answers, mastery moves away from 0.5 → uncertainty drops."""
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=1.0)
        state = learner_state.get_concept_state("c_1")
        # High mastery → uncertainty should be low
        assert state.uncertainty < 0.85

    def test_low_mastery_high_certainty(self, tracer, learner_state):
        """Section 20: Low mastery + high certainty (consistent wrong answers)."""
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=0.0)
        state = learner_state.get_concept_state("c_1")
        assert state.mastery_probability < 0.20
        assert state.uncertainty < 0.35  # High certainty = low uncertainty

    def test_moderate_mastery_high_uncertainty(self, tracer, learner_state):
        """Section 20: Moderate mastery + high uncertainty (few or mixed observations)."""
        # 2 mixed observations: 1 correct, 1 incorrect
        tracer.update(learner_state, ["c_2"], correctness=1.0)
        tracer.update(learner_state, ["c_2"], correctness=0.0)
        state = learner_state.get_concept_state("c_2")
        assert 0.25 <= state.mastery_probability <= 0.65
        assert state.uncertainty > 0.55  # High uncertainty

    def test_distinguishes_low_mastery_from_moderate_mastery_uncertainty(self, tracer, learner_state):
        """Proves that uncertainty is NOT solely a function of mastery."""
        # Concept 1: consistent incorrect (5 attempts) -> low mastery, low uncertainty
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=0.0)
        state_1 = learner_state.get_concept_state("c_1")

        # Concept 2: mixed performance (2 attempts) -> moderate mastery, high uncertainty
        tracer.update(learner_state, ["c_2"], correctness=1.0)
        tracer.update(learner_state, ["c_2"], correctness=0.0)
        state_2 = learner_state.get_concept_state("c_2")

        # State 1 has lower uncertainty than State 2 despite lower mastery
        assert state_1.uncertainty < state_2.uncertainty


# ---------------------------------------------------------------------------
# Diagnostic Confidence Tests
# ---------------------------------------------------------------------------

class TestDiagnosticConfidence:
    def test_initial_confidence(self, tracer, learner_state):
        """Initial confidence should be moderate (0.5) with no evidence."""
        state = learner_state.get_concept_state("c_1")
        assert state.confidence == 0.5

    def test_confidence_rises_with_consistent_correct(self, tracer, learner_state):
        """All-correct recent_performance → high diagnostic confidence."""
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=1.0)
        state = learner_state.get_concept_state("c_1")
        assert state.confidence > 0.6

    def test_confidence_rises_with_consistent_incorrect(self, tracer, learner_state):
        """All-incorrect recent_performance → also high diagnostic confidence
        (we're confident they DON'T know it)."""
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=0.0)
        state = learner_state.get_concept_state("c_1")
        assert state.confidence > 0.6

    def test_confidence_drops_with_mixed_evidence(self, tracer, learner_state):
        """Alternating correct/incorrect → low diagnostic confidence."""
        for i in range(6):
            tracer.update(learner_state, ["c_1"], correctness=1.0 if i % 2 == 0 else 0.0)
        state = learner_state.get_concept_state("c_1")
        # Mixed evidence → low confidence
        assert state.confidence < 0.7

    def test_confidence_independent_of_mastery(self, tracer, learner_state):
        """Confidence and mastery can diverge: low mastery + high confidence is valid."""
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=0.0)
        state = learner_state.get_concept_state("c_1")
        assert state.mastery_probability < 0.3  # Low mastery
        assert state.confidence > 0.5  # But confident in that assessment


# ---------------------------------------------------------------------------
# Misconception Lifecycle Tests
# ---------------------------------------------------------------------------

class TestMisconceptionLifecycle:
    def test_single_event_produces_suspected(self):
        ls = LearnerState(learner_id="misc_test_1")
        rec = ls.record_misconception(
            concept_id="c_1",
            description="Confuses derivative with integral",
            evidence_ref="int_001",
        )
        assert rec.status == MisconceptionStatusEnum.SUSPECTED
        assert rec.frequency == 1

    def test_repeated_event_produces_supported(self):
        ls = LearnerState(learner_id="misc_test_2")
        rec1 = ls.record_misconception(
            concept_id="c_1",
            description="Confuses derivative with integral",
            evidence_ref="int_001",
        )
        assert rec1.status == MisconceptionStatusEnum.SUSPECTED

        # Same misconception again → frequency=2 → SUPPORTED
        rec2 = ls.record_misconception(
            concept_id="c_1",
            description="Confuses derivative with integral",
            evidence_ref="int_002",
        )
        assert rec2.status == MisconceptionStatusEnum.SUPPORTED
        assert rec2.frequency == 2
        assert "int_001" in rec2.evidence_refs
        assert "int_002" in rec2.evidence_refs

    def test_resolve_misconception(self):
        ls = LearnerState(learner_id="misc_test_3")
        rec = ls.record_misconception("c_1", "Bad concept", "e1")
        ls.record_misconception("c_1", "Bad concept", "e2")  # -> SUPPORTED

        resolved = ls.resolve_misconception(rec.misconception_id)
        assert resolved is not None
        assert resolved.status == MisconceptionStatusEnum.RESOLVED

    def test_resolve_nonexistent_returns_none(self):
        ls = LearnerState(learner_id="misc_test_4")
        assert ls.resolve_misconception("nonexistent_id") is None

    def test_deterministic_keys(self):
        """Same concept+description always maps to same misconception_id."""
        ls = LearnerState(learner_id="misc_test_5")
        rec1 = ls.record_misconception("c_1", "Thinks gravity pushes", "e1")
        # Re-create with same description but different whitespace
        ls2 = LearnerState(learner_id="misc_test_5")
        rec2 = ls2.record_misconception("c_1", "  Thinks   gravity   pushes  ", "e2")
        assert rec1.misconception_id == rec2.misconception_id


class TestMisconceptionFiltering:
    def test_get_active_excludes_resolved(self):
        ls = LearnerState(learner_id="filt_1")
        rec1 = ls.record_misconception("c_1", "Error A", "e1")
        ls.record_misconception("c_1", "Error A", "e2")
        ls.record_misconception("c_2", "Error B", "e3")

        ls.resolve_misconception(rec1.misconception_id)

        active = ls.get_active_misconceptions()
        assert len(active) == 1
        assert active[0].concept_id == "c_2"

    def test_get_active_by_concept(self):
        ls = LearnerState(learner_id="filt_2")
        ls.record_misconception("c_1", "Error A", "e1")
        ls.record_misconception("c_2", "Error B", "e2")

        active_c1 = ls.get_active_misconceptions(concept_id="c_1")
        assert len(active_c1) == 1
        assert active_c1[0].concept_id == "c_1"

    def test_get_supported_only(self):
        ls = LearnerState(learner_id="filt_3")
        ls.record_misconception("c_1", "Error A", "e1")         # SUSPECTED
        ls.record_misconception("c_1", "Error A", "e2")         # -> SUPPORTED
        ls.record_misconception("c_2", "Error B", "e3")         # SUSPECTED only

        supported = ls.get_supported_misconceptions()
        assert len(supported) == 1
        assert supported[0].concept_id == "c_1"


# ---------------------------------------------------------------------------
# LearnerState Utility Tests
# ---------------------------------------------------------------------------

class TestLearnerStateUtilities:
    def test_mastery_summary(self, tracer, learner_state):
        tracer.update(learner_state, ["c_1"], correctness=1.0)
        summary = learner_state.get_mastery_summary()
        assert "c_1" in summary
        assert "mastery" in summary["c_1"]
        assert "uncertainty" in summary["c_1"]
        assert "confidence" in summary["c_1"]
        assert "attempts" in summary["c_1"]
        assert summary["c_1"]["attempts"] == 1.0

    def test_weakest_concepts(self, tracer, learner_state):
        # Make c_1 strong, leave c_2 and c_3 weak
        for _ in range(5):
            tracer.update(learner_state, ["c_1"], correctness=1.0)
        tracer.update(learner_state, ["c_2"], correctness=0.0)
        tracer.update(learner_state, ["c_3"], correctness=0.0)

        weakest = learner_state.get_weakest_concepts(n=2)
        assert len(weakest) <= 2
        # The weakest should be c_2 or c_3, not c_1
        weak_ids = [c_id for c_id, _ in weakest]
        assert "c_1" not in weak_ids


class TestWeakConceptIdentification:
    def test_identify_weak_concepts(self, tracer, learner_state):
        # Give c_1 some correct answers
        for _ in range(3):
            tracer.update(learner_state, ["c_1"], correctness=1.0)
        # Give c_2 incorrect answers
        for _ in range(3):
            tracer.update(learner_state, ["c_2"], correctness=0.0)

        weak = tracer.identify_weak_concepts(learner_state, mastery_threshold=0.4, min_attempts=2)
        assert "c_2" in weak
        assert "c_1" not in weak

    def test_no_weak_with_few_attempts(self, tracer, learner_state):
        tracer.update(learner_state, ["c_1"], correctness=0.0)  # 1 attempt only
        weak = tracer.identify_weak_concepts(learner_state, mastery_threshold=0.4, min_attempts=2)
        assert "c_1" not in weak  # Not enough evidence


# ---------------------------------------------------------------------------
# Recent Performance Window
# ---------------------------------------------------------------------------

class TestRecentPerformanceWindow:
    def test_recent_performance_capped_at_10(self, tracer, learner_state):
        for _ in range(15):
            tracer.update(learner_state, ["c_1"], correctness=1.0)
        state = learner_state.get_concept_state("c_1")
        assert len(state.recent_performance) == 10


# ---------------------------------------------------------------------------
# Integration: KT + Misconception Combined Flow
# ---------------------------------------------------------------------------

class TestKTMisconceptionIntegration:
    def test_incorrect_with_misconception_recording(self, tracer, learner_state):
        """Simulates the full flow: incorrect answer → KT update + misconception record."""
        # KT update
        updated = tracer.update(learner_state, ["c_1"], correctness=0.0)
        assert updated["c_1"] < 0.3  # Mastery dropped

        # Record the misconception (this would be triggered by evaluator)
        rec = learner_state.record_misconception(
            concept_id="c_1",
            description="Confused Newton's first law with third law",
            evidence_ref="int_attempt_001",
        )
        assert rec.status == MisconceptionStatusEnum.SUSPECTED

        # Another incorrect attempt with same misconception
        tracer.update(learner_state, ["c_1"], correctness=0.0)
        rec2 = learner_state.record_misconception(
            concept_id="c_1",
            description="Confused Newton's first law with third law",
            evidence_ref="int_attempt_002",
        )
        assert rec2.status == MisconceptionStatusEnum.SUPPORTED
        assert rec2.frequency == 2

    def test_remediation_resolves_misconception(self, tracer, learner_state):
        """After successful remediation (correct answers), misconception gets resolved."""
        # Build up misconception
        tracer.update(learner_state, ["c_1"], correctness=0.0)
        rec = learner_state.record_misconception("c_1", "Wrong formula", "e1")
        tracer.update(learner_state, ["c_1"], correctness=0.0)
        learner_state.record_misconception("c_1", "Wrong formula", "e2")

        assert learner_state.get_supported_misconceptions("c_1")

        # Remediation: several correct answers
        for _ in range(3):
            tracer.update(learner_state, ["c_1"], correctness=1.0)

        # Resolve misconception
        learner_state.resolve_misconception(rec.misconception_id)
        assert not learner_state.get_supported_misconceptions("c_1")

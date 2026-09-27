"""
Phase 7 Learner State Mathematical Invariants Test Suite.
Verifies invariants across KnowledgeTracer and LearnerState:
- 0 <= mastery_probability <= 1
- 0 <= uncertainty <= 1
- attempt_count >= 0, correct_count >= 0
- correct_count <= attempt_count
"""

import pytest
from phase3.learner.kt import KnowledgeTracer
from phase3.learner.models import LearnerState, ConceptState
from phase5.validation.learner_state_validator import LearnerStateValidator


def test_learner_state_invariants():
    tracer = KnowledgeTracer()
    state = tracer.initialize_learner("learner_inv_1", ["c_1", "c_2"])

    # Perform updates
    tracer.update(state, ["c_1"], correctness=1.0)
    tracer.update(state, ["c_1"], correctness=0.0)

    validator = LearnerStateValidator()
    val_res = validator.validate_learner_state(state)

    assert val_res.is_valid is True

    # Check state bounds
    for c_id, cs in state.concept_states.items():
        assert 0.0 <= cs.mastery_probability <= 1.0
        assert 0.0 <= cs.uncertainty <= 1.0
        assert cs.attempt_count >= 0
        assert cs.correct_count >= 0
        assert cs.correct_count <= cs.attempt_count

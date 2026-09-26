"""
Unit Tests for Phase 3 Adapter and Learner State / Knowledge Tracing.
"""

import pytest
from phase2.models import (
    EducationalKnowledgeRepresentation,
    Concept,
    EducationalUnit,
    AssessableItem,
    ConfidenceBreakdown,
)
from phase3.knowledge.phase2_adapter import Phase2Adapter
from phase3.learner.models import LearnerState
from phase3.learner.kt import KnowledgeTracer


def test_phase2_adapter_conversion():
    ekr = EducationalKnowledgeRepresentation(
        knowledge_document_id="k_test_1",
        source_document_id="doc_test_1",
        concepts=[
            Concept(
                concept_id="c_calc_1",
                canonical_name="Derivative",
                confidence=ConfidenceBreakdown(value=0.95),
            )
        ],
        educational_units=[
            EducationalUnit(
                unit_id="u_def_1",
                unit_type="definition",
                section_id="sec_derivatives",
            )
        ],
        assessable_items=[
            AssessableItem(
                item_id="item_ex_1",
                unit_id="u_def_1",
                concept_ids=["c_calc_1"],
            )
        ],
    )

    ctx = Phase2Adapter.adapt(ekr)

    assert ctx.document_id == "doc_test_1"
    assert "c_calc_1" in ctx.concepts
    assert ctx.concepts["c_calc_1"].canonical_name == "Derivative"
    assert "u_def_1" in ctx.educational_units
    assert "item_ex_1" in ctx.assessable_items


def test_knowledge_tracing_updates():
    tracer = KnowledgeTracer(p_init=0.3, p_transit=0.15)
    lstate = tracer.initialize_learner("learner_101", ["c_calc_1"])

    assert tracer.get_mastery(lstate, "c_calc_1") == 0.3

    # Correct attempt
    updated = tracer.update(lstate, ["c_calc_1"], correctness=1.0)
    post_corr_mastery = updated["c_calc_1"]
    assert post_corr_mastery > 0.3

    # Incorrect attempt
    updated_2 = tracer.update(lstate, ["c_calc_1"], correctness=0.0)
    post_inc_mastery = updated_2["c_calc_1"]
    assert post_inc_mastery < post_corr_mastery

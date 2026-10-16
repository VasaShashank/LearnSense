"""
Unit tests for Teacher Knowledge State Aggregation and Teaching Optimizer (§10).
"""

import pytest
from phase3.knowledge.phase2_adapter import LearningContext, ConceptView, PrerequisiteLink
from phase3.learner.models import LearnerState, ConceptState
from phase4.teacher.optimizer import TeachingOptimizer
from phase4.teacher.models import InterventionStatus
from backend.services.teacher_service import TeacherService


def _mock_learning_context():
    ctx = LearningContext(
        document_id="subj_test_physics",
        knowledge_document_id="kd_physics",
        document_title="AP Physics Mechanics",
        concepts={
            "c_limits": ConceptView(
                concept_id="c_limits",
                canonical_name="Limits",
                type="concept",
                description="Foundation of calculus",
            ),
            "c_derivatives": ConceptView(
                concept_id="c_derivatives",
                canonical_name="Derivatives",
                type="concept",
                description="Rate of change",
            ),
            "c_chain_rule": ConceptView(
                concept_id="c_chain_rule",
                canonical_name="Chain Rule",
                type="concept",
                description="Composite function derivatives",
            ),
        },
        prerequisites=[
            PrerequisiteLink(
                source_concept_id="c_limits",
                target_concept_id="c_derivatives",
                confidence=1.0,
            ),
            PrerequisiteLink(
                source_concept_id="c_derivatives",
                target_concept_id="c_chain_rule",
                confidence=1.0,
            ),
        ],
    )
    return ctx


def _mock_learner_states():
    # 5 learners with diverse profiles
    states = []

    # Learner 1 & 2: Struggling with limits & derivatives
    for i in range(1, 3):
        st = LearnerState(
            learner_id=f"learner_{i}",
            concept_states={
                "c_limits": ConceptState(concept_id="c_limits", mastery_probability=0.25, attempt_count=3),
                "c_derivatives": ConceptState(concept_id="c_derivatives", mastery_probability=0.20, attempt_count=2),
                "c_chain_rule": ConceptState(concept_id="c_chain_rule", mastery_probability=0.15, attempt_count=1),
            },
        )
        states.append(st)

    # Learner 3 & 4: Mastered limits, struggling with chain rule
    for i in range(3, 5):
        st = LearnerState(
            learner_id=f"learner_{i}",
            concept_states={
                "c_limits": ConceptState(concept_id="c_limits", mastery_probability=0.85, attempt_count=5),
                "c_derivatives": ConceptState(concept_id="c_derivatives", mastery_probability=0.75, attempt_count=4),
                "c_chain_rule": ConceptState(concept_id="c_chain_rule", mastery_probability=0.35, attempt_count=3),
            },
        )
        states.append(st)

    # Learner 5: High mastery across all
    st5 = LearnerState(
        learner_id="learner_5",
        concept_states={
            "c_limits": ConceptState(concept_id="c_limits", mastery_probability=0.92, attempt_count=6),
            "c_derivatives": ConceptState(concept_id="c_derivatives", mastery_probability=0.88, attempt_count=5),
            "c_chain_rule": ConceptState(concept_id="c_chain_rule", mastery_probability=0.80, attempt_count=4),
        },
    )
    states.append(st5)

    return states


def test_aggregate_class_knowledge_state():
    ctx = _mock_learning_context()
    states = _mock_learner_states()

    class_state = TeachingOptimizer.aggregate_class_knowledge_state(
        class_id="cls_ap_physics",
        subject_id="subj_test_physics",
        learner_states=states,
        context=ctx,
    )

    assert class_state.class_id == "cls_ap_physics"
    assert class_state.total_enrolled == 5
    assert class_state.active_learners == 5

    # Check mastery distribution for chain rule
    cr_dist = class_state.concept_distributions["c_chain_rule"]
    assert cr_dist.sample_size == 5
    assert cr_dist.proportion_struggling >= 0.60  # 4 out of 5 struggling
    assert "learner_1" in cr_dist.struggling_learner_ids
    assert "learner_2" in cr_dist.struggling_learner_ids

    # Check prerequisite bottleneck detection
    assert len(class_state.prerequisite_gap_clusters) > 0
    top_gap = class_state.prerequisite_gap_clusters[0]
    assert top_gap.affected_learner_count >= 2


def test_generate_teaching_plan_with_prerequisite_bottleneck():
    ctx = _mock_learning_context()
    states = _mock_learner_states()

    class_state = TeachingOptimizer.aggregate_class_knowledge_state(
        class_id="cls_ap_physics",
        subject_id="subj_test_physics",
        learner_states=states,
        context=ctx,
    )

    plan = TeachingOptimizer.generate_teaching_plan(
        class_state=class_state,
        context=ctx,
        target_concept_id="c_derivatives",
        total_minutes=50,
    )

    assert plan.status == InterventionStatus.PROPOSED
    assert len(plan.actions) >= 2
    assert plan.total_class_duration_minutes == 50

    # Prerequisite revision action is generated because c_limits has root gaps
    action_types = [a.action_type for a in plan.actions]
    assert "REVISE_PREREQUISITE" in action_types
    assert "DIRECT_INSTRUCTION_AND_WORKED_EXAMPLES" in action_types
    assert "FORMATIVE_REASSESSMENT" in action_types

    # Differentiated groups created
    core_action = next(a for a in plan.actions if "DIRECT_INSTRUCTION" in a.action_type)
    assert len(core_action.student_groups) >= 2


def test_evaluate_intervention_outcome():
    ctx = _mock_learning_context()
    pre_states = _mock_learner_states()

    # Pre-intervention
    pre_state = TeachingOptimizer.aggregate_class_knowledge_state(
        class_id="cls_ap_physics",
        subject_id="subj_test_physics",
        learner_states=pre_states,
        context=ctx,
    )

    plan = TeachingOptimizer.generate_teaching_plan(
        class_state=pre_state,
        context=ctx,
        target_concept_id="c_derivatives",
    )

    # Post-intervention simulated states: learners improved
    post_states = _mock_learner_states()
    for st in post_states[:2]:
        st.concept_states["c_derivatives"].mastery_probability = 0.72

    post_state = TeachingOptimizer.aggregate_class_knowledge_state(
        class_id="cls_ap_physics",
        subject_id="subj_test_physics",
        learner_states=post_states,
        context=ctx,
    )

    outcome = TeachingOptimizer.evaluate_intervention_outcome(
        intervention=plan,
        pre_state=pre_state,
        post_state=post_state,
        target_concept_id="c_derivatives",
    )

    assert outcome.mastery_gain > 0.15
    assert outcome.remediation_effective is True
    assert outcome.post_struggling_count < outcome.pre_struggling_count

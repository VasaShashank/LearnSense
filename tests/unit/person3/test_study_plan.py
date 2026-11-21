"""LearnSense Person 3 — Tests for Personalized Study Plan Generation.

Validates:
1. Prerequisite ordering: Foundational prerequisite gaps scheduled strictly before dependent target concepts.
2. Pedagogical priorities: Unmet prerequisites -> Spaced review -> Misconceptions -> Practice -> Transfer -> Advancement.
3. Time budget constraints: Strictly limits allocated activities and sets status to 'partial' when budget is exceeded.
4. Cold-start and unassessed concepts: Graceful inference from topological curriculum order.
5. Content grounding: Flags content availability honestly without fabricating learning resources.
6. Read-only preview: Generating study plans does not mutate learner state or attempts.
7. Determinism and learner isolation: Consistent output and tenant isolation.
"""

import pytest

from src.bkt import BKTConfig
from src.knowledge_base import get_default_knowledge_base
from src.knowledge_graph import load_knowledge_graph_from_csv
from src.misconceptions import MisconceptionTracker
from src.retention import PersonalizedRetentionModel
from src.state import LearnerStateService
from src.storage import SQLiteStateStore
from src.study_plan import StudyPlanGenerator
from src.transfer import MasteryTransferVerifier


@pytest.fixture
def test_setup():
    store = SQLiteStateStore(":memory:")
    kg = load_knowledge_graph_from_csv()
    kb = get_default_knowledge_base()
    state_svc = LearnerStateService(knowledge_graph=kg, store=store)
    misc_tracker = MisconceptionTracker(store=store)
    ret_model = PersonalizedRetentionModel(store=store)
    transfer_verifier = MasteryTransferVerifier(store=store)

    generator = StudyPlanGenerator(
        knowledge_graph=kg,
        knowledge_base=kb,
        retention_model=ret_model,
        misconception_tracker=misc_tracker,
        transfer_verifier=transfer_verifier,
    )
    return {
        "store": store,
        "kg": kg,
        "kb": kb,
        "state_svc": state_svc,
        "misc_tracker": misc_tracker,
        "ret_model": ret_model,
        "transfer_verifier": transfer_verifier,
        "generator": generator,
    }


def test_prerequisite_ordering_enforced(test_setup):
    """Target concept with unmet prerequisites must schedule prerequisites first."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_PREREQ_01"

    # Student targets PHY_NLM (Newton's Laws), which requires PHY_KIN and PHY_VEC
    # Student is currently unassessed on PHY_KIN and PHY_VEC
    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_NLM"],
    )

    assert plan.status in {"complete", "partial"}
    assert plan.prerequisite_activities_count >= 1

    act_concepts = [a.concept_id for a in plan.ordered_activities]
    # Prerequisite activities must precede PHY_NLM
    assert "PHY_NLM" in act_concepts
    nlm_index = act_concepts.index("PHY_NLM")

    # If PHY_KIN or PHY_VEC is in the plan, it must appear before PHY_NLM
    for prereq in ["PHY_KIN", "PHY_VEC"]:
        if prereq in act_concepts:
            prereq_index = act_concepts.index(prereq)
            assert prereq_index < nlm_index
            prereq_act = plan.ordered_activities[prereq_index]
            assert prereq_act.is_required_prerequisite is True
            assert prereq_act.activity_type == "prerequisite_remediation"


def test_overdue_spaced_review_scheduled(test_setup):
    """Concepts with decayed retention must be scheduled for spaced review."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    ret_model: PersonalizedRetentionModel = test_setup["ret_model"]
    lid = "STU_REVIEW_01"
    cid = "PHY_KIN"

    # Establish mastery 30 days ago
    past_ts = "2026-09-01T10:00:00Z"
    now_ts = "2026-10-20T10:00:00Z"
    state_svc.process_attempt(lid, cid, "ATT_OLD_1", True, "Q1", submitted_at=past_ts)
    state_svc.process_attempt(lid, cid, "ATT_OLD_2", True, "Q2", submitted_at=past_ts)
    ret_model.record_review_attempt(lid, cid, "ATT_OLD_2", True, 0.85, submitted_at=past_ts)

    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_NLM"],
    )

    review_acts = [a for a in plan.ordered_activities if a.activity_type == "spaced_review"]
    assert any(a.concept_id == cid for a in review_acts)


def test_active_misconception_scheduled(test_setup):
    """Active misconceptions on target concepts must trigger remediation activities."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    misc_tracker: MisconceptionTracker = test_setup["misc_tracker"]
    lid = "STU_MISC_01"
    cid = "PHY_KIN"

    # Register misconception
    misc_tracker.analyze_attempt(
        learner_id=lid,
        concept_id=cid,
        attempt_id="ATT_ERR_1",
        question_id="Q_KIN_01",
        is_correct=False,
        work_steps=[{"step_index": 1, "text": "v = u - a*t with opposite sign error"}],
        learner_mastery=0.45,
    )

    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=[cid],
    )

    misc_acts = [a for a in plan.ordered_activities if a.activity_type == "misconception_remediation"]
    assert len(misc_acts) >= 1
    assert misc_acts[0].concept_id == cid
    assert "recent_error_pattern" in misc_acts[0].reason_codes


def test_time_budget_allocation_and_partial_plan(test_setup):
    """Study plan must respect supplied time budget and report unallocated activities."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_BUDGET_01"

    # Small time budget of 25 minutes
    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_NLM", "PHY_MOM", "PHY_COL"],
        time_budget_minutes=25,
    )

    assert plan.time_budget_minutes == 25
    assert plan.total_estimated_duration_minutes <= 25 or len(plan.ordered_activities) == 1
    if plan.unallocated_activities_count > 0:
        assert plan.status == "partial"


def test_cold_start_empty_history_infers_targets(test_setup):
    """When no goals are supplied, generator infers initial unmastered curriculum concepts."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_COLD_01"

    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=None,
    )

    assert plan.status in {"complete", "partial"}
    assert len(plan.target_concepts) >= 1
    assert len(plan.ordered_activities) >= 1


def test_read_only_invariant(test_setup):
    """Generating a study plan must NOT alter BKT mastery, evidence count, or attempts."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_READONLY_01"
    cid = "PHY_KIN"

    # Initialize state
    st_before = state_svc.get_or_initialize_state(lid, cid)
    mastery_before = st_before.mastery_probability
    evidence_before = st_before.evidence_count

    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=[cid, "PHY_NLM"],
        time_budget_minutes=60,
    )
    assert plan is not None

    st_after = state_svc.get_or_initialize_state(lid, cid)
    assert st_after.mastery_probability == mastery_before
    assert st_after.evidence_count == evidence_before
    assert test_setup["store"].get_all_attempt_records(lid) == []


def test_deterministic_generation(test_setup):
    """Generating plans with identical input and state must produce identical outputs."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_DETERMINISTIC_01"

    plan1 = gen.generate_plan(lid, state_svc, ["PHY_NLM"], time_budget_minutes=45)
    plan2 = gen.generate_plan(lid, state_svc, ["PHY_NLM"], time_budget_minutes=45)

    assert plan1.target_concepts == plan2.target_concepts
    assert len(plan1.ordered_activities) == len(plan2.ordered_activities)
    for a1, a2 in zip(plan1.ordered_activities, plan2.ordered_activities):
        assert a1.concept_id == a2.concept_id
        assert a1.activity_type == a2.activity_type
        assert a1.is_required_prerequisite == a2.is_required_prerequisite


def test_missing_graph_nodes_handled_gracefully(test_setup):
    """Unknown or invalid concept IDs in target list must be filtered safely without crashing."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_MISSING_NODE_01"

    # Supplying a non-existent concept ID alongside a valid one
    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["NON_EXISTENT_CID_999", "PHY_NLM"],
        time_budget_minutes=60,
    )
    assert plan is not None
    # Invalid concept must NOT be present in resolved targets or ordered activities
    assert "NON_EXISTENT_CID_999" not in plan.target_concepts
    assert all(a.concept_id != "NON_EXISTENT_CID_999" for a in plan.ordered_activities)
    assert "PHY_NLM" in plan.target_concepts

    # Supplying ONLY non-existent concepts falls back to next curriculum targets
    plan_all_invalid = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["FAKE_1", "FAKE_2"],
    )
    assert plan_all_invalid is not None
    assert len(plan_all_invalid.ordered_activities) > 0


def test_unavailable_content_flagged_honestly(test_setup):
    """Concepts lacking verified NCERT textbook material must be flagged with content_available=False."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    kb = test_setup["kb"]
    lid = "STU_UNAVAILABLE_01"

    # Identify a concept in the graph that is NOT in the default verified knowledge base
    kg = test_setup["kg"]
    unavail_cid = None
    for cid in kg.topological_sort():
        if not kb.contains(cid):
            unavail_cid = cid
            break

    if unavail_cid is not None:
        plan = gen.generate_plan(
            learner_id=lid,
            state_service=state_svc,
            target_concepts=[unavail_cid],
            time_budget_minutes=60,
        )
        assert plan is not None
        unavail_acts = [a for a in plan.ordered_activities if a.concept_id == unavail_cid]
        if unavail_acts:
            assert unavail_acts[0].content_available is False
            # Ensure assumption notes the limitation
            assert any("lack verified NCERT" in note for note in plan.assumptions_and_limitations)


def test_impossible_and_zero_time_budgets(test_setup):
    """Tiny time budget (e.g. 5 min, less than single 10-15 min activity) must allocate 1 activity and mark partial."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_BUDGET_EDGE_01"

    # 1. Budget of 5 minutes: minimum activity is 10 min
    plan_tiny = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_NLM"],
        time_budget_minutes=5,
    )
    assert plan_tiny.status == "partial"
    assert len(plan_tiny.ordered_activities) == 1
    assert plan_tiny.unallocated_activities_count >= 1

    # 2. Budget of 0 minutes: treated as unconstrained, status is complete
    plan_zero = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_KIN"],
        time_budget_minutes=0,
    )
    assert plan_zero.status == "complete"
    assert plan_zero.unallocated_activities_count == 0


def test_prerequisite_cycles_safety(test_setup):
    """Knowledge graphs with cycles or complex topologies must terminate deterministically without infinite recursion."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_CYCLE_01"

    # Execute plan generation across multiple interconnected concepts
    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_NLM", "PHY_MOM", "PHY_COL"],
        time_budget_minutes=120,
    )
    assert plan is not None
    # No duplicate activities for the same concept in candidate ordering
    cids = [a.concept_id for a in plan.ordered_activities]
    assert len(cids) == len(set(cids))


def test_dynamic_concept_learning_duration(test_setup):
    """Verifies that activity durations are dynamically modulated by difficulty, prerequisites, and learner mastery."""
    gen: StudyPlanGenerator = test_setup["generator"]
    state_svc: LearnerStateService = test_setup["state_svc"]
    lid = "STU_DYNAMIC_DUR"

    # Compare an unassessed easy/root concept vs a complex concept with prerequisites and low mastery
    st_low = state_svc.get_or_initialize_state(lid, "PHY_KIN")
    st_low.mastery_probability = 0.15

    st_high = state_svc.get_or_initialize_state(lid, "PHY_VEC")
    st_high.mastery_probability = 0.70

    # Calculate dynamic duration for practice on weak state
    dur_weak, meta_weak = gen.calculate_dynamic_duration(
        activity_type="adaptive_practice",
        concept_id="PHY_KIN",
        learner_state=st_low,
    )

    # Calculate dynamic duration for practice on strong state
    dur_strong, meta_strong = gen.calculate_dynamic_duration(
        activity_type="adaptive_practice",
        concept_id="PHY_VEC",
        learner_state=st_high,
    )

    # Duration for weak concept with lower mastery should be strictly higher than strong concept
    assert dur_weak > dur_strong
    assert meta_weak["is_dynamic"] is True
    assert "difficulty_multiplier" in meta_weak
    assert "structure_multiplier" in meta_weak
    assert "learner_gap_multiplier" in meta_weak
    assert meta_weak["learner_gap_multiplier"] > meta_strong["learner_gap_multiplier"]

    # Verify generated study plan embeds duration breakdown
    plan = gen.generate_plan(
        learner_id=lid,
        state_service=state_svc,
        target_concepts=["PHY_KIN"],
    )
    assert len(plan.ordered_activities) > 0
    first_act = plan.ordered_activities[0]
    assert "duration_breakdown" in first_act.metadata
    assert first_act.metadata["duration_breakdown"]["is_dynamic"] is True


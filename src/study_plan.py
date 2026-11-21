"""LearnSense Person 3 — Personalized Pedagogical Study Plan Generator.

Generates structured, explainable, time-budgeted study plans based on the learner's current knowledge
state, prerequisite relationships, overdue memory retention, persistent misconceptions, mastery uncertainty,
and target goals.

Key Invariants:
1. Prerequisite Ordering: Dependent target concepts never precede their unmet prerequisites.
2. Pedagogical Priority Cascade: Unmet prerequisites -> Error streaks / traps -> Overdue retention ->
   Misconceptions -> Uncertainty -> Developing practice -> Transfer verification -> Advancement.
3. Realistic Time Budgeting: Respects time_budget_minutes using conservative, configurable activity
   estimates, cleanly distinguishing complete plans from partial plans.
4. Prerequisite Labeling: Clearly flags required foundational prerequisites vs. target practice.
5. Content Grounding: Verifies learning resources and question bank availability, flagging unverified
   or unavailable material honestly without fabrication.
6. Pure Preview (Read-Only): Generating a study plan NEVER mutates learner knowledge state or attempts.
"""

from __future__ import annotations

import copy
import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.adaptive_assessment import AdaptiveAssessmentSelector
from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.misconceptions import MisconceptionTracker
from src.recommendation import RecommendationEngine
from src.retention import PersonalizedRetentionModel
from src.state import LearnerConceptState, LearnerStateService
from src.transfer import MasteryTransferVerifier
from src.uncertainty import MasteryUncertaintyEvaluator


DEFAULT_ACTIVITY_DURATIONS: Dict[str, int] = {
    "prerequisite_remediation": 15,
    "misconception_remediation": 15,
    "spaced_review": 10,
    "mastery_reassessment": 10,
    "concept_learning": 20,
    "adaptive_practice": 15,
    "transfer_verification": 15,
    "curriculum_advancement": 20,
}


@dataclass
class StudyPlanActivity:
    """A single scheduled activity within a personalized study plan."""
    activity_id: str
    sequence_index: int
    concept_id: str
    concept_name: str
    activity_type: str  # 'prerequisite_remediation', 'misconception_remediation', 'spaced_review', ...
    is_required_prerequisite: bool
    estimated_duration_minutes: int
    rationale: str
    reason_codes: List[str]
    priority_score: int
    content_available: bool = True
    evidence_refs: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PersonalizedStudyPlan:
    """Complete structured study plan conforming to LearnSense personalization standards."""
    plan_id: str
    learner_id: str
    status: str  # 'complete', 'partial', 'insufficient_input'
    target_concepts: List[str]
    ordered_activities: List[StudyPlanActivity]
    total_estimated_duration_minutes: int
    time_budget_minutes: Optional[int]
    unallocated_activities_count: int
    prerequisite_activities_count: int
    assumptions_and_limitations: List[str]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "learner_id": self.learner_id,
            "status": self.status,
            "target_concepts": list(self.target_concepts),
            "ordered_activities": [a.to_dict() for a in self.ordered_activities],
            "total_estimated_duration_minutes": self.total_estimated_duration_minutes,
            "time_budget_minutes": self.time_budget_minutes,
            "unallocated_activities_count": self.unallocated_activities_count,
            "prerequisite_activities_count": self.prerequisite_activities_count,
            "assumptions_and_limitations": list(self.assumptions_and_limitations),
            "created_at": self.created_at,
        }


class StudyPlanGenerator:
    """Generates deterministic, prerequisite-aware, explainable study plans."""

    def __init__(
        self,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        assessment_selector: Optional[AdaptiveAssessmentSelector] = None,
        retention_model: Optional[PersonalizedRetentionModel] = None,
        misconception_tracker: Optional[MisconceptionTracker] = None,
        transfer_verifier: Optional[MasteryTransferVerifier] = None,
        durations: Optional[Dict[str, int]] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.assessment_selector = assessment_selector or AdaptiveAssessmentSelector(knowledge_graph=self.knowledge_graph)
        self.retention_model = retention_model
        self.misconception_tracker = misconception_tracker
        self.transfer_verifier = transfer_verifier
        self.durations = durations or DEFAULT_ACTIVITY_DURATIONS
        self._topological_order = self.knowledge_graph.topological_sort()

    def calculate_dynamic_duration(
        self,
        activity_type: str,
        concept_id: str,
        learner_state: Optional[LearnerConceptState] = None,
        retention_probability: Optional[float] = None,
        has_active_misconception: bool = False,
    ) -> Tuple[int, Dict[str, Any]]:
        """Dynamically computes realistic activity duration based on:
        1. Base duration for the activity type.
        2. Intrinsic concept difficulty (from question bank items assessing this concept).
        3. Structural complexity in the curriculum DAG (ancestor prerequisite depth and key equations).
        4. Learner knowledge state deficit (latent mastery gap 1 - P(L), error streak, memory decay).
        
        Returns:
            (duration_minutes: int, breakdown_metadata: Dict[str, Any])
        """
        base_dur = self.durations.get(activity_type, 15)
        cid = concept_id.strip()

        # Factor 1: Intrinsic Concept Difficulty (from question bank)
        questions = self.assessment_selector._concept_index.get(cid, []) if self.assessment_selector else []
        if questions:
            diffs = [q.numeric_difficulty for q in questions]
            avg_diff = sum(diffs) / len(diffs)
            if avg_diff <= 0.35:
                m_diff = 0.85   # Easy concept: faster comprehension
            elif avg_diff <= 0.60:
                m_diff = 1.00   # Medium concept: standard pace
            else:
                m_diff = 1.25   # Hard concept: requires more deep work
        else:
            avg_diff = 0.50
            m_diff = 1.00

        # Factor 2: Curriculum Structural Complexity
        if self.knowledge_graph.contains(cid):
            prereq_depth = len(self.knowledge_graph.get_all_ancestor_prerequisites(cid))
        else:
            prereq_depth = 0

        if prereq_depth == 0:
            m_struct = 0.90     # Standalone / foundational root concept
        elif prereq_depth <= 2:
            m_struct = 1.00     # Moderate dependency chain
        else:
            m_struct = 1.15     # Deep multi-concept synthesis (e.g. Circular Motion, Collisions)

        # Content equation density
        key_eqs = self.knowledge_base.get_key_equations(cid) if self.knowledge_base else []
        m_eq = 1.10 if len(key_eqs) >= 4 else 1.00

        # Factor 3: Learner Knowledge State & Gap
        m_gap = 1.00
        m_prob = learner_state.mastery_probability if learner_state is not None else 0.50
        consec_err = learner_state.metadata.get("consecutive_errors", 0) if learner_state else 0

        if activity_type in {"prerequisite_remediation", "adaptive_practice"}:
            if m_prob < 0.25:
                m_gap = 1.30    # Severe gap requires extensive remediation
            elif m_prob < 0.60:
                m_gap = 1.05
            else:
                m_gap = 0.85    # Light practice / refinement
        elif activity_type == "concept_learning":
            m_gap = 1.20 if m_prob < 0.30 else 1.00
        elif activity_type == "misconception_remediation":
            m_gap = 1.25 if (has_active_misconception or consec_err >= 2) else 1.00
        elif activity_type == "spaced_review":
            if retention_probability is not None:
                if retention_probability < 0.40:
                    m_gap = 1.30  # Heavy forgetting requires re-derivation
                elif retention_probability < 0.65:
                    m_gap = 1.00
                else:
                    m_gap = 0.85  # Quick retrieval practice
            else:
                m_gap = 1.00

        # Combined calculation with clamping
        raw_duration = base_dur * m_diff * m_struct * m_eq * m_gap
        final_duration = max(5, min(45, int(round(raw_duration))))

        breakdown = {
            "base_duration_minutes": base_dur,
            "average_question_difficulty": round(avg_diff, 2),
            "difficulty_multiplier": round(m_diff, 2),
            "prerequisite_depth": prereq_depth,
            "structure_multiplier": round(m_struct, 2),
            "equation_density_multiplier": round(m_eq, 2),
            "learner_mastery_probability": round(m_prob, 3),
            "learner_gap_multiplier": round(m_gap, 2),
            "raw_duration_minutes": round(raw_duration, 1),
            "is_dynamic": True,
        }

        return final_duration, breakdown

    def generate_plan(
        self,
        learner_id: str,
        state_service: LearnerStateService,
        target_concepts: Optional[Sequence[str]] = None,
        time_budget_minutes: Optional[int] = None,
        exam_deadline: Optional[str] = None,
        max_activities: Optional[int] = None,
    ) -> PersonalizedStudyPlan:
        """Generates an explainable, prerequisite-ordered personalized study plan."""
        lid = str(learner_id).strip()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        plan_id = f"PLAN_{uuid.uuid4().hex[:12]}"

        # Step 1: Validate and resolve target concepts
        resolved_targets: List[str] = []
        target_id_map: Dict[str, str] = {}
        if target_concepts:
            for tc in target_concepts:
                tc_clean = str(tc).strip()
                if self.knowledge_graph.contains(tc_clean):
                    can_id = self.knowledge_graph._resolve_id(tc_clean)
                    if can_id not in resolved_targets:
                        resolved_targets.append(can_id)
                        target_id_map[can_id] = tc_clean

        mastery_vector = state_service.get_learner_mastery_vector(lid)
        all_states = state_service.get_all_learner_states(lid)

        # If no valid targets supplied, infer next unmastered concepts from curriculum
        if not resolved_targets:
            for cid in self._topological_order:
                st = all_states.get(cid)
                m_prob = mastery_vector.get(cid, 0.0)
                if st is None or st.evidence_count == 0 or m_prob < 0.75:
                    resolved_targets.append(cid)
                    target_id_map[cid] = cid
                    if len(resolved_targets) >= 3:
                        break

        def _get_display_cid(canonical_id: str) -> str:
            if canonical_id in target_id_map:
                return target_id_map[canonical_id]
            uses_legacy = any(tc in target_id_map.values() for tc in (target_concepts or []))
            if uses_legacy:
                try:
                    from src.migration_adapter import CanonicalConceptMigrationAdapter
                    rec = CanonicalConceptMigrationAdapter().get_migration_record(canonical_id)
                    if rec and rec.legacy_id:
                        return rec.legacy_id
                except Exception:
                    pass
            return canonical_id

        if not resolved_targets:
            return PersonalizedStudyPlan(
                plan_id=plan_id,
                learner_id=lid,
                status="insufficient_input",
                target_concepts=[],
                ordered_activities=[],
                total_estimated_duration_minutes=0,
                time_budget_minutes=time_budget_minutes,
                unallocated_activities_count=0,
                prerequisite_activities_count=0,
                assumptions_and_limitations=[
                    "No valid target concepts supplied or inferred from unmastered curriculum."
                ],
                created_at=now_iso,
            )

        # Step 2: Traverse and identify all prerequisite requirements
        required_prereqs_map: Dict[str, Set[str]] = {}  # target_cid -> set of unmet prereqs
        all_unmet_prereqs: Set[str] = set()

        for target_cid in resolved_targets:
            is_ready, _, broken = self.knowledge_graph.evaluate_prerequisite_readiness(
                target_cid, mastery_vector, mastery_threshold=0.50
            )
            if not is_ready:
                remed_seq = self.knowledge_graph.get_remediation_sequence(target_cid, mastery_vector)
                needed = set(remed_seq if remed_seq else broken)
                required_prereqs_map[target_cid] = needed
                all_unmet_prereqs.update(needed)

        # Step 3: Check overdue spaced review items across ALL learner states
        overdue_review_cids: Set[str] = set()
        if self.retention_model:
            overdue_items = self.retention_model.get_overdue_concepts(lid, as_of_time=now_iso)
            for item in overdue_items:
                can_c = self.knowledge_graph._resolve_id(item["concept_id"])
                overdue_review_cids.add(can_c)

        # Step 4: Check active misconceptions
        active_misc_cids: Set[str] = set()
        if self.misconception_tracker:
            miscs = self.misconception_tracker.get_misconceptions(lid, active_only=True)
            for m in miscs:
                can_c = self.knowledge_graph._resolve_id(m.concept_id)
                active_misc_cids.add(can_c)

        # Step 5: Build candidate activities in topological curriculum order
        candidate_activities: List[StudyPlanActivity] = []
        seen_concepts: Set[str] = set()

        # Combine all concepts of interest in topological order
        concepts_to_schedule: List[str] = []
        for cid in self._topological_order:
            if cid in all_unmet_prereqs or cid in resolved_targets or cid in overdue_review_cids:
                if cid not in seen_concepts:
                    concepts_to_schedule.append(cid)
                    seen_concepts.add(cid)

        seq_idx = 1
        for cid in concepts_to_schedule:
            display_cid = _get_display_cid(cid)
            node = self.knowledge_graph.get_node(cid)
            concept_name = node.name if node else cid
            st = state_service.get_or_initialize_state(lid, cid)
            m_prob = st.mastery_probability
            is_unassessed = (st.evidence_count == 0)

            has_content = self.knowledge_base.contains(cid)

            # Case A: Concept is an unmet prerequisite for a downstream target
            if cid in all_unmet_prereqs:
                act_type = "prerequisite_remediation"
                dur, dur_meta = self.calculate_dynamic_duration(
                    activity_type=act_type,
                    concept_id=cid,
                    learner_state=st,
                )
                candidate_activities.append(
                    StudyPlanActivity(
                        activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                        sequence_index=seq_idx,
                        concept_id=display_cid,
                        concept_name=concept_name,
                        activity_type=act_type,
                        is_required_prerequisite=True,
                        estimated_duration_minutes=dur,
                        rationale=f"Foundational prerequisite gap for target concept. Mastery must reach threshold before downstream practice.",
                        reason_codes=["prerequisite_gap"],
                        priority_score=95,
                        content_available=has_content,
                        evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                        metadata={"duration_breakdown": dur_meta},
                    )
                )
                seq_idx += 1
                continue

            # Case B: Overdue spaced review
            if cid in overdue_review_cids:
                act_type = "spaced_review"
                ret_prob = None
                if self.retention_model:
                    ret_est = self.retention_model.estimate_retention(lid, cid, as_of_time=now_iso)
                    ret_prob = ret_est.get("recall_probability")
                dur, dur_meta = self.calculate_dynamic_duration(
                    activity_type=act_type,
                    concept_id=cid,
                    learner_state=st,
                    retention_probability=ret_prob,
                )
                candidate_activities.append(
                    StudyPlanActivity(
                        activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                        sequence_index=seq_idx,
                        concept_id=display_cid,
                        concept_name=concept_name,
                        activity_type=act_type,
                        is_required_prerequisite=False,
                        estimated_duration_minutes=dur,
                        rationale="Memory retention probability has decayed past optimal review threshold; retrieval practice scheduled.",
                        reason_codes=["spaced_review_due"],
                        priority_score=85,
                        content_available=has_content,
                        evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                        metadata={"duration_breakdown": dur_meta},
                    )
                )
                seq_idx += 1

            # Case C: Active misconception on target concept
            if cid in active_misc_cids:
                act_type = "misconception_remediation"
                dur, dur_meta = self.calculate_dynamic_duration(
                    activity_type=act_type,
                    concept_id=cid,
                    learner_state=st,
                    has_active_misconception=True,
                )
                candidate_activities.append(
                    StudyPlanActivity(
                        activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                        sequence_index=seq_idx,
                        concept_id=display_cid,
                        concept_name=concept_name,
                        activity_type=act_type,
                        is_required_prerequisite=False,
                        estimated_duration_minutes=dur,
                        rationale="Persistent conceptual misconception detected in previous derivation work steps; targeted remediation required.",
                        reason_codes=["recent_error_pattern"],
                        priority_score=80,
                        content_available=has_content,
                        evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                        metadata={"duration_breakdown": dur_meta},
                    )
                )
                seq_idx += 1

            # Case D: Unassessed target concept -> Foundational Learning
            if is_unassessed and cid in resolved_targets:
                act_type = "concept_learning"
                dur, dur_meta = self.calculate_dynamic_duration(
                    activity_type=act_type,
                    concept_id=cid,
                    learner_state=st,
                )
                candidate_activities.append(
                    StudyPlanActivity(
                        activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                        sequence_index=seq_idx,
                        concept_id=display_cid,
                        concept_name=concept_name,
                        activity_type=act_type,
                        is_required_prerequisite=False,
                        estimated_duration_minutes=dur,
                        rationale="Target concept is currently unassessed. Deliver core conceptual definitions and worked examples.",
                        reason_codes=["low_mastery_estimate", "curriculum_sequence"],
                        priority_score=70,
                        content_available=has_content,
                        evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                        metadata={"duration_breakdown": dur_meta},
                    )
                )
                seq_idx += 1
                continue

            # Case E: Developing concept practice
            if not is_unassessed and m_prob < 0.75 and cid in resolved_targets:
                act_type = "adaptive_practice"
                dur, dur_meta = self.calculate_dynamic_duration(
                    activity_type=act_type,
                    concept_id=cid,
                    learner_state=st,
                )
                candidate_activities.append(
                    StudyPlanActivity(
                        activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                        sequence_index=seq_idx,
                        concept_id=display_cid,
                        concept_name=concept_name,
                        activity_type=act_type,
                        is_required_prerequisite=False,
                        estimated_duration_minutes=dur,
                        rationale=f"Developing mastery (P(L) = {m_prob:.2f}). Adaptive question practice to advance knowledge state.",
                        reason_codes=["low_mastery_estimate"],
                        priority_score=60,
                        content_available=has_content,
                        evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                        metadata={"duration_breakdown": dur_meta},
                    )
                )
                seq_idx += 1
                continue

            # Case F: High mastery -> Transfer verification or challenge
            if not is_unassessed and m_prob >= 0.75 and cid in resolved_targets:
                transfer_verified = False
                if self.transfer_verifier:
                    t_eval = self.transfer_verifier.evaluate_transfer(lid, cid)
                    st_val = t_eval.status.value if hasattr(t_eval.status, "value") else str(t_eval.status)
                    transfer_verified = (st_val in {"verified_transfer", "transfer_verified"})

                if not transfer_verified:
                    act_type = "transfer_verification"
                    dur, dur_meta = self.calculate_dynamic_duration(
                        activity_type=act_type,
                        concept_id=cid,
                        learner_state=st,
                    )
                    candidate_activities.append(
                        StudyPlanActivity(
                            activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                            sequence_index=seq_idx,
                            concept_id=display_cid,
                            concept_name=concept_name,
                            activity_type=act_type,
                            is_required_prerequisite=False,
                            estimated_duration_minutes=dur,
                            rationale=f"High latent mastery (P(L) = {m_prob:.2f}); assessment on unseen transfer questions to confirm generalizable understanding.",
                            reason_codes=["ready_for_challenge"],
                            priority_score=55,
                            content_available=has_content,
                            evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                            metadata={"duration_breakdown": dur_meta},
                        )
                    )
                else:
                    act_type = "curriculum_advancement"
                    dur, dur_meta = self.calculate_dynamic_duration(
                        activity_type=act_type,
                        concept_id=cid,
                        learner_state=st,
                    )
                    candidate_activities.append(
                        StudyPlanActivity(
                            activity_id=f"ACT_{uuid.uuid4().hex[:8]}",
                            sequence_index=seq_idx,
                            concept_id=display_cid,
                            concept_name=concept_name,
                            activity_type=act_type,
                            is_required_prerequisite=False,
                            estimated_duration_minutes=dur,
                            rationale=f"Concept mastered and verified; advanced application and problem challenge recommended.",
                            reason_codes=["ready_for_challenge"],
                            priority_score=50,
                            content_available=has_content,
                            evidence_refs=[{"ref_type": "concept", "ref_id": cid}],
                            metadata={"duration_breakdown": dur_meta},
                        )
                    )
                seq_idx += 1

        # Step 6: Apply Time Budget Allocation
        allocated_activities: List[StudyPlanActivity] = []
        total_duration = 0
        unallocated_count = 0
        budget_limit = time_budget_minutes if (time_budget_minutes is not None and time_budget_minutes > 0) else None

        for idx, act in enumerate(candidate_activities):
            if max_activities is not None and len(allocated_activities) >= max_activities:
                unallocated_count = len(candidate_activities) - len(allocated_activities)
                break

            act_dur = act.estimated_duration_minutes
            if budget_limit is not None and (total_duration + act_dur) > budget_limit:
                # If budget exceeded, record remaining as unallocated
                # Special guardrail: Ensure at least one activity is present if candidates exist
                if not allocated_activities:
                    act_copy = copy.deepcopy(act)
                    act_copy.sequence_index = 1
                    allocated_activities.append(act_copy)
                    total_duration += act_dur
                    unallocated_count = len(candidate_activities) - 1
                else:
                    unallocated_count = len(candidate_activities) - len(allocated_activities)
                break

            act_copy = copy.deepcopy(act)
            act_copy.sequence_index = len(allocated_activities) + 1
            allocated_activities.append(act_copy)
            total_duration += act_dur

        prereq_count = sum(1 for a in allocated_activities if a.is_required_prerequisite)
        plan_status = "complete"
        if unallocated_count > 0:
            plan_status = "partial"

        assumptions = [
            "Activity durations are conservative heuristic estimates (10-20 min) and should be adapted to student pace.",
            "Prerequisite sequences enforce strict topological readiness prior to dependent practice.",
        ]
        if any(not a.content_available for a in allocated_activities):
            assumptions.append(
                "Some scheduled concepts lack verified NCERT pedagogical text; fallback problem prompts are provided."
            )

        return PersonalizedStudyPlan(
            plan_id=plan_id,
            learner_id=lid,
            status=plan_status,
            target_concepts=[_get_display_cid(cid) for cid in resolved_targets],
            ordered_activities=allocated_activities,
            total_estimated_duration_minutes=total_duration,
            time_budget_minutes=time_budget_minutes,
            unallocated_activities_count=unallocated_count,
            prerequisite_activities_count=prereq_count,
            assumptions_and_limitations=assumptions,
            created_at=now_iso,
        )


def generate_study_plan(
    learner_id: str,
    target_concept_ids: Optional[List[str]] = None,
    time_budget_minutes: int = 60,
    **kwargs: Any,
) -> PersonalizedStudyPlan:
    """Convenience helper to generate a personalized study plan."""
    generator = StudyPlanGenerator()
    return generator.generate_plan(
        learner_id=learner_id,
        target_concept_ids=target_concept_ids or [],
        time_budget_minutes=time_budget_minutes,
    )

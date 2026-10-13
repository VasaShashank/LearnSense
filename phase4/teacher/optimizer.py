"""
Teaching Optimizer and Class Knowledge Aggregator Implementation (§10).
"""

from datetime import datetime, timezone
import statistics
import uuid
from typing import Dict, List, Optional

from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.models import LearnerState
from phase4.teacher.models import (
    ClassKnowledgeState,
    ConceptMasteryDistribution,
    PrerequisiteGapCluster,
    MisconceptionCluster,
    TeachingInterventionPlan,
    TeachingActionRecommendation,
    StudentInterventionGroup,
    InterventionStatus,
    InterventionOutcome,
)


class TeachingOptimizer:
    """
    Synthesizes aggregated learning intelligence for teachers and plans interventions.
    """

    @staticmethod
    def aggregate_class_knowledge_state(
        class_id: str,
        subject_id: str,
        learner_states: List[LearnerState],
        context: LearningContext,
    ) -> ClassKnowledgeState:
        total_enrolled = len(learner_states)
        active_learners = sum(1 for ls in learner_states if any(cs.attempt_count > 0 for cs in ls.concept_states.values()))

        distributions: Dict[str, ConceptMasteryDistribution] = {}
        all_masteries: List[float] = []

        # 1. Concept mastery distributions
        for cid, concept in context.concepts.items():
            mastery_vals = []
            attempts = []
            struggling_ids = []

            for ls in learner_states:
                cs = ls.concept_states.get(cid)
                if cs:
                    m = cs.mastery_probability
                    mastery_vals.append(m)
                    attempts.append(cs.attempt_count)
                    if m < 0.40:
                        struggling_ids.append(ls.learner_id)
                else:
                    mastery_vals.append(0.30)
                    attempts.append(0)
                    struggling_ids.append(ls.learner_id)

            if not mastery_vals:
                continue

            sorted_m = sorted(mastery_vals)
            n = len(sorted_m)
            mean_m = statistics.mean(sorted_m)
            median_m = statistics.median(sorted_m)
            p25 = sorted_m[int(0.25 * n)] if n > 0 else 0.30
            p75 = sorted_m[int(0.75 * n)] if n > 0 else 0.30
            mastered_cnt = sum(1 for m in sorted_m if m >= 0.70)
            struggling_cnt = len(struggling_ids)

            dist = ConceptMasteryDistribution(
                concept_id=cid,
                canonical_name=concept.canonical_name,
                sample_size=n,
                mean_mastery=round(mean_m, 3),
                median_mastery=round(median_m, 3),
                p25_mastery=round(p25, 3),
                p75_mastery=round(p75, 3),
                proportion_mastered=round(mastered_cnt / n, 3) if n > 0 else 0.0,
                proportion_struggling=round(struggling_cnt / n, 3) if n > 0 else 0.0,
                average_attempts=round(statistics.mean(attempts), 1) if attempts else 0.0,
                struggling_learner_ids=struggling_ids,
            )
            distributions[cid] = dist
            all_masteries.append(mean_m)

        # 2. Prerequisite gap bottleneck analysis
        gap_clusters: List[PrerequisiteGapCluster] = []
        for prereq in context.prerequisites:
            src_id = prereq.source_concept_id
            tgt_id = prereq.target_concept_id
            src_concept = context.concepts.get(src_id)
            tgt_concept = context.concepts.get(tgt_id)

            affected_count = 0
            for ls in learner_states:
                src_cs = ls.concept_states.get(src_id)
                tgt_cs = ls.concept_states.get(tgt_id)
                src_m = src_cs.mastery_probability if src_cs else 0.30
                tgt_m = tgt_cs.mastery_probability if tgt_cs else 0.30
                # Bottleneck: struggling with target concept while prerequisite is unmastered
                if tgt_m < 0.50 and src_m < 0.50:
                    affected_count += 1

            if affected_count > 0:
                severity = round(affected_count / total_enrolled, 2) if total_enrolled > 0 else 0.0
                gap_clusters.append(
                    PrerequisiteGapCluster(
                        target_concept_id=tgt_id,
                        target_concept_name=tgt_concept.canonical_name if tgt_concept else tgt_id,
                        prerequisite_concept_id=src_id,
                        prerequisite_concept_name=src_concept.canonical_name if src_concept else src_id,
                        affected_learner_count=affected_count,
                        severity=severity,
                    )
                )

        gap_clusters.sort(key=lambda g: g.affected_learner_count, reverse=True)

        # 3. Misconception cluster aggregation
        misc_counts: Dict[str, Dict[str, Any]] = {}
        for ls in learner_states:
            for m_id, m_hyp in getattr(ls, "misconceptions", {}).items():
                if m_id not in misc_counts:
                    misc_counts[m_id] = {
                        "concept_id": getattr(m_hyp, "concept_id", ""),
                        "description": getattr(m_hyp, "description", m_id),
                        "count": 0,
                    }
                misc_counts[m_id]["count"] += 1

        misconception_clusters: List[MisconceptionCluster] = []
        for m_id, info in misc_counts.items():
            prevalence = round(info["count"] / total_enrolled, 2) if total_enrolled > 0 else 0.0
            misconception_clusters.append(
                MisconceptionCluster(
                    misconception_id=m_id,
                    concept_id=info["concept_id"],
                    description=info["description"],
                    affected_learner_count=info["count"],
                    prevalence=prevalence,
                )
            )

        misconception_clusters.sort(key=lambda mc: mc.affected_learner_count, reverse=True)
        readiness = round(statistics.mean(all_masteries), 3) if all_masteries else 0.0

        return ClassKnowledgeState(
            class_id=class_id,
            subject_id=subject_id,
            subject_title=context.document_title or subject_id,
            total_enrolled=total_enrolled,
            active_learners=active_learners,
            concept_distributions=distributions,
            prerequisite_gap_clusters=gap_clusters,
            misconception_clusters=misconception_clusters,
            overall_class_readiness=readiness,
        )

    @classmethod
    def generate_teaching_plan(
        cls,
        class_state: ClassKnowledgeState,
        context: LearningContext,
        target_concept_id: Optional[str] = None,
        total_minutes: int = 50,
    ) -> TeachingInterventionPlan:
        # Determine target concept
        if not target_concept_id:
            if class_state.prerequisite_gap_clusters:
                target_concept_id = class_state.prerequisite_gap_clusters[0].target_concept_id
            elif class_state.concept_distributions:
                # Pick lowest mean mastery concept
                sorted_dists = sorted(class_state.concept_distributions.values(), key=lambda d: d.mean_mastery)
                target_concept_id = sorted_dists[0].concept_id
            else:
                target_concept_id = list(context.concepts.keys())[0] if context.concepts else "concept_1"

        target_concept = context.concepts.get(target_concept_id)
        target_name = target_concept.canonical_name if target_concept else target_concept_id
        target_dist = class_state.concept_distributions.get(target_concept_id)

        actions: List[TeachingActionRecommendation] = []
        time_remaining = total_minutes

        # Check if an upstream prerequisite bottleneck exists for this target concept
        relevant_prereq_gaps = [
            g for g in class_state.prerequisite_gap_clusters if g.target_concept_id == target_concept_id
        ]

        if relevant_prereq_gaps and relevant_prereq_gaps[0].affected_learner_count >= 1:
            top_gap = relevant_prereq_gaps[0]
            prereq_time = min(15, int(total_minutes * 0.30))
            time_remaining -= prereq_time

            actions.append(
                TeachingActionRecommendation(
                    priority=1,
                    action_type="REVISE_PREREQUISITE",
                    target_concept_id=top_gap.prerequisite_concept_id,
                    target_concept_name=top_gap.prerequisite_concept_name,
                    rationale=(
                        f"{top_gap.affected_learner_count} students ({int(top_gap.severity * 100)}% of cohort) "
                        f"have root gaps in prerequisite '{top_gap.prerequisite_concept_name}' "
                        f"which blocks mastery of '{target_name}'."
                    ),
                    allocated_time_minutes=prereq_time,
                    student_groups=[
                        StudentInterventionGroup(
                            group_name="Prerequisite Remediation Cohort",
                            instructional_focus=f"Targeted review of {top_gap.prerequisite_concept_name} fundamentals",
                            learner_ids=target_dist.struggling_learner_ids if target_dist else [],
                            suggested_resource=f"Foundational review worked examples for {top_gap.prerequisite_concept_name}",
                        )
                    ],
                    recommended_probe_concept_ids=[top_gap.prerequisite_concept_id],
                )
            )

        # Core Instruction Action
        instruction_time = min(25, int(time_remaining * 0.65))
        time_remaining -= instruction_time
        priority_idx = len(actions) + 1

        # Form differentiated groups
        struggling_learners = target_dist.struggling_learner_ids if target_dist else []
        all_learner_ids = [lid for d in class_state.concept_distributions.values() for lid in d.struggling_learner_ids]
        mastered_learners = [lid for lid in set(all_learner_ids) if lid not in struggling_learners]

        actions.append(
            TeachingActionRecommendation(
                priority=priority_idx,
                action_type="DIRECT_INSTRUCTION_AND_WORKED_EXAMPLES",
                target_concept_id=target_concept_id,
                target_concept_name=target_name,
                rationale=(
                    f"Core instruction on '{target_name}'. Class mastery mean is "
                    f"{target_dist.mean_mastery if target_dist else 0.30} with "
                    f"{len(struggling_learners)} students below 0.40 mastery threshold."
                ),
                allocated_time_minutes=instruction_time,
                student_groups=[
                    StudentInterventionGroup(
                        group_name="Guided Practice Cohort",
                        instructional_focus="Step-by-step worked examples with intuitive analogies",
                        learner_ids=struggling_learners,
                    ),
                    StudentInterventionGroup(
                        group_name="Independent Application Cohort",
                        instructional_focus="Challenging transfer problems and multi-step applications",
                        learner_ids=mastered_learners,
                    ),
                ],
                recommended_probe_concept_ids=[target_concept_id],
            )
        )

        # Formative Reassessment Action
        reassessment_time = max(5, time_remaining)
        actions.append(
            TeachingActionRecommendation(
                priority=len(actions) + 1,
                action_type="FORMATIVE_REASSESSMENT",
                target_concept_id=target_concept_id,
                target_concept_name=target_name,
                rationale="Conduct 3-item adaptive verification probe to measure post-intervention learning gain.",
                allocated_time_minutes=reassessment_time,
                student_groups=[],
                recommended_probe_concept_ids=[target_concept_id],
            )
        )

        plan_id = f"plan_{uuid.uuid4().hex[:10]}"
        return TeachingInterventionPlan(
            intervention_id=plan_id,
            class_id=class_state.class_id,
            subject_id=class_state.subject_id,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
            status=InterventionStatus.PROPOSED,
            target_learning_objective=f"Mastery Consolidation for {target_name}",
            total_class_duration_minutes=total_minutes,
            actions=actions,
        )

    @classmethod
    def evaluate_intervention_outcome(
        cls,
        intervention: TeachingInterventionPlan,
        pre_state: ClassKnowledgeState,
        post_state: ClassKnowledgeState,
        target_concept_id: str,
    ) -> InterventionOutcome:
        pre_dist = pre_state.concept_distributions.get(target_concept_id)
        post_dist = post_state.concept_distributions.get(target_concept_id)

        pre_mean = pre_dist.mean_mastery if pre_dist else 0.30
        post_mean = post_dist.mean_mastery if post_dist else 0.30
        gain = round(post_mean - pre_mean, 3)

        pre_struggling = len(pre_dist.struggling_learner_ids) if pre_dist else 0
        post_struggling = len(post_dist.struggling_learner_ids) if post_dist else 0
        effective = gain > 0.10 or (post_struggling < pre_struggling)

        summary = (
            f"Intervention for concept '{target_concept_id}' resulted in mastery increase "
            f"from {pre_mean:.2f} to {post_mean:.2f} (gain: +{gain:.2f}). "
            f"Struggling learners reduced from {pre_struggling} to {post_struggling}."
        )

        return InterventionOutcome(
            intervention_id=intervention.intervention_id,
            class_id=intervention.class_id,
            concept_id=target_concept_id,
            pre_intervention_mean_mastery=pre_mean,
            post_intervention_mean_mastery=post_mean,
            mastery_gain=gain,
            pre_struggling_count=pre_struggling,
            post_struggling_count=post_struggling,
            remediation_effective=effective,
            summary=summary,
        )

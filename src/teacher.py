"""LearnSense Person 3 — Teacher Portal and Dynamic Teaching Plan Engine.

Supports both pedagogical personas:
1. Independent Teacher: Individual educator coming directly to the platform to devise structured,
   pedagogically sound teaching plans using syllabus knowledge graph dependencies, core definitions,
   governing equations, and proactively targeted misconception refutations.
2. B2B Institutional / Classroom Teacher: Cohort maintenance where teachers view aggregated
   knowledge tracing (mastery distribution, at-risk students, class misconception clusters) and
   generate dynamic, cohort-adapted lesson plans and differentiated intervention strategies.
"""

from __future__ import annotations

import copy
import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.misconceptions import MisconceptionTracker, MisconceptionStatus
from src.state import LearnerConceptState, LearnerStateService


@dataclass
class LessonSegment:
    """A structured component within a teacher's dynamic lesson plan."""
    segment_index: int
    title: str
    segment_type: str  # 'prerequisite_bridge', 'concept_exposition', 'worked_example', 'misconception_refutation', 'formative_check', 'differentiated_practice'
    estimated_minutes: int
    learning_objectives: List[str]
    teacher_script_or_guidance: str
    key_equations_or_definitions: List[str]
    common_pitfalls_to_address: List[Dict[str, str]]
    check_for_understanding_prompts: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DynamicTeachingPlan:
    """A comprehensive teaching plan generated for an educator."""
    plan_id: str
    persona: str  # 'independent_teacher' | 'b2b_cohort_teacher'
    concept_id: str
    concept_name: str
    target_grade_or_course: str
    total_duration_minutes: int
    prerequisite_concepts: List[str]
    segments: List[LessonSegment]
    cohort_summary: Optional[Dict[str, Any]] = None
    differentiation_strategies: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "persona": self.persona,
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "target_grade_or_course": self.target_grade_or_course,
            "total_duration_minutes": self.total_duration_minutes,
            "prerequisite_concepts": list(self.prerequisite_concepts),
            "segments": [s.to_dict() for s in self.segments],
            "cohort_summary": copy.deepcopy(self.cohort_summary),
            "differentiation_strategies": copy.deepcopy(self.differentiation_strategies),
            "created_at": self.created_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }


@dataclass
class CohortConceptAnalytics:
    """Class-wide knowledge tracing breakdown for a single concept."""
    concept_id: str
    student_count: int
    mean_mastery: float
    mastered_count: int  # P(L) >= 0.75
    developing_count: int  # 0.40 <= P(L) < 0.75
    at_risk_count: int  # P(L) < 0.40
    active_misconceptions: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CohortClassroomReport:
    """Aggregate dashboard report for a B2B school/coaching classroom."""
    class_id: str
    class_name: str
    student_count: int
    concept_analytics: Dict[str, CohortConceptAnalytics]
    high_priority_interventions: List[Dict[str, Any]]
    class_misconception_heatmap: List[Dict[str, Any]]
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "student_count": self.student_count,
            "concept_analytics": {k: v.to_dict() for k, v in self.concept_analytics.items()},
            "high_priority_interventions": copy.deepcopy(self.high_priority_interventions),
            "class_misconception_heatmap": copy.deepcopy(self.class_misconception_heatmap),
            "generated_at": self.generated_at,
        }


class IndependentTeacherPlanner:
    """Generates structured lesson and teaching plans for independent educators.
    
    Draws directly from the Grounded Knowledge Base, Prerequisite DAG, and syllabus
    specifications to produce ready-to-teach lecture agendas, worked examples, and
    misconception refutations.
    """

    def __init__(
        self,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
    ) -> None:
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()

    def generate_plan(
        self,
        concept_id: str,
        total_minutes: int = 60,
        target_grade: str = "JEE Advanced / Grade 11-12",
        focus_areas: Optional[List[str]] = None,
    ) -> DynamicTeachingPlan:
        cid = concept_id.strip()
        prereqs = self.knowledge_graph.get_direct_prerequisites(cid) if self.knowledge_graph.contains(cid) else []
        definition = self.knowledge_base.get_definition(cid)
        principles = self.knowledge_base.get_core_principles(cid)
        equations = self.knowledge_base.get_key_equations(cid)
        misconceptions = self.knowledge_base.get_misconceptions(cid)
        worked_ex = self.knowledge_base.get_worked_example(cid) or {}
        citation = self.knowledge_base.get_source_citation(cid)

        # Time allocation budgeting
        bridge_time = min(10, max(5, int(total_minutes * 0.15)))
        exposition_time = min(25, max(15, int(total_minutes * 0.35)))
        worked_time = min(15, max(10, int(total_minutes * 0.20)))
        refutation_time = min(15, max(10, int(total_minutes * 0.20)))
        check_time = max(5, total_minutes - (bridge_time + exposition_time + worked_time + refutation_time))

        segments: List[LessonSegment] = []
        idx = 0

        # Segment 1: Prerequisite Activation
        prereq_names = ", ".join(prereqs) if prereqs else "Foundational coordinate geometry and algebra"
        segments.append(
            LessonSegment(
                segment_index=idx,
                title=f"Prerequisite Activation & Framing ({prereq_names})",
                segment_type="prerequisite_bridge",
                estimated_minutes=bridge_time,
                learning_objectives=[f"Verify readiness on prerequisite concepts: {prereq_names}"],
                teacher_script_or_guidance=(
                    f"Begin by connecting today's topic ({cid}) to earlier principles ({prereq_names}). "
                    "Ask students: 'How does our previous understanding change when we introduce this new constraint?'"
                ),
                key_equations_or_definitions=[],
                common_pitfalls_to_address=[],
                check_for_understanding_prompts=[
                    f"Quick 2-minute diagnostic: State the governing condition for {prereqs[0]} before we begin." if prereqs else "Quick check on coordinate conventions."
                ],
            )
        )
        idx += 1

        # Segment 2: Core Concept Exposition
        segments.append(
            LessonSegment(
                segment_index=idx,
                title=f"Core Concept Exposition & Formalization: {cid}",
                segment_type="concept_exposition",
                estimated_minutes=exposition_time,
                learning_objectives=[f"Master definition and governing laws of {cid}"],
                teacher_script_or_guidance=(
                    f"Present the formal physical definition:\n{definition}\n\n"
                    "Highlight the core principles systematically. Emphasize the boundary conditions under which formulas hold."
                ),
                key_equations_or_definitions=[definition] + equations,
                common_pitfalls_to_address=[],
                check_for_understanding_prompts=[
                    f"Which fundamental quantity is conserved in {cid}?",
                    "Under what physical constraints does this governing equation cease to apply?",
                ],
            )
        )
        idx += 1

        # Segment 3: Scaffolded Worked Example
        example_title = worked_ex.get("title", f"Representative {cid} Problem")
        example_prompt = worked_ex.get("prompt", "Analyze the physical system and determine unknown state variables.")
        example_steps = worked_ex.get("steps", [])
        step_texts = [f"Step {s.get('step_index', i)+1}: {s.get('content', '')}" for i, s in enumerate(example_steps)]
        segments.append(
            LessonSegment(
                segment_index=idx,
                title=f"Scaffolded Worked Example: {example_title}",
                segment_type="worked_example",
                estimated_minutes=worked_time,
                learning_objectives=["Demonstrate multi-step derivation and variable isolation"],
                teacher_script_or_guidance=(
                    f"Walk through the problem on the board:\n**Problem:** {example_prompt}\n\n"
                    "Demonstrate standard problem decomposition:\n"
                    + "\n".join(step_texts)
                ),
                key_equations_or_definitions=equations[:2],
                common_pitfalls_to_address=[],
                check_for_understanding_prompts=[
                    "Before computing, what is the expected order of magnitude and physical dimension of our answer?",
                    "Why did we choose this coordinate frame rather than another?",
                ],
            )
        )
        idx += 1

        # Segment 4: Proactive Misconception & Distractor Refutation
        refutation_pitfalls = []
        for m in misconceptions:
            refutation_pitfalls.append({
                "trap": m.get("misconception", ""),
                "clarification": m.get("explanation", ""),
                "counter_example": m.get("counter_example", ""),
            })

        segments.append(
            LessonSegment(
                segment_index=idx,
                title="Proactive Misconception Clinic & Distractor Analysis",
                segment_type="misconception_refutation",
                estimated_minutes=refutation_time,
                learning_objectives=["Identify and inoculate students against the classic distractor traps"],
                teacher_script_or_guidance=(
                    "Directly address the most frequent exam errors before students make them in practice. "
                    "Show common distractor choices and explain the minute conceptual difference."
                ),
                key_equations_or_definitions=[],
                common_pitfalls_to_address=refutation_pitfalls,
                check_for_understanding_prompts=[
                    "Why is option B attractive to a student who forgets Newton's 3rd law acts on distinct bodies?",
                    "What sign error in coordinate selection leads to distractor C?",
                ],
            )
        )
        idx += 1

        # Segment 5: Formative Check & Exit Ticket
        segments.append(
            LessonSegment(
                segment_index=idx,
                title="Formative Check & Exit Ticket (4-Question Check)",
                segment_type="formative_check",
                estimated_minutes=check_time,
                learning_objectives=["Gauge real-time classroom comprehension across all students"],
                teacher_script_or_guidance=(
                    "Administer a rapid 4-question interactive micro-quiz. "
                    "Review distribution of answers immediately to determine if homework should be reinforcement or remediation."
                ),
                key_equations_or_definitions=[],
                common_pitfalls_to_address=[],
                check_for_understanding_prompts=[
                    f"4-item check on {cid} (see MicroQuiz generator)",
                    "Exit ticket: Write one sentence explaining why governing equation holds only under constant conditions.",
                ],
            )
        )

        plan_id = f"PLAN_IND_{uuid.uuid4().hex[:10].upper()}"
        c_content = self.knowledge_base.get_concept_content(cid)
        c_name = c_content.concept_name if c_content else cid
        return DynamicTeachingPlan(
            plan_id=plan_id,
            persona="independent_teacher",
            concept_id=cid,
            concept_name=c_name,
            target_grade_or_course=target_grade,
            total_duration_minutes=total_minutes,
            prerequisite_concepts=prereqs,
            segments=segments,
            cohort_summary={"source_citation": citation},
            differentiation_strategies={
                "struggling_students": "Provide pre-drawn Free Body Diagrams and formula index sheets.",
                "advanced_students": "Assign non-uniform / calculus-dependent boundary variation problems.",
            },
        )


class CohortTeacherManager:
    """Manages B2B institutional classes, aggregated Knowledge Tracing (KT), and cohort-adapted lesson plans."""

    def __init__(
        self,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
    ) -> None:
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.independent_planner = IndependentTeacherPlanner(self.knowledge_base, self.knowledge_graph)

    def analyze_cohort(
        self,
        class_id: str,
        class_name: str,
        learner_ids: List[str],
        concept_ids: List[str],
        state_service: LearnerStateService,
        misconception_tracker: Optional[MisconceptionTracker] = None,
    ) -> CohortClassroomReport:
        """Aggregates individual student KT states and misconception registries into a cohesive cohort view."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        concept_analytics: Dict[str, CohortConceptAnalytics] = {}
        high_priority_interventions: List[Dict[str, Any]] = []
        misconception_tally: Dict[str, Dict[str, Any]] = {}

        for cid in concept_ids:
            masteries: List[float] = []
            m_count = 0
            d_count = 0
            r_count = 0
            active_misc_list: List[Dict[str, Any]] = []

            for lid in learner_ids:
                st = state_service.get_state(lid, cid)
                p_l = st.mastery_probability if st else 0.35
                masteries.append(p_l)

                if p_l >= 0.75:
                    m_count += 1
                elif p_l >= 0.40:
                    d_count += 1
                else:
                    r_count += 1
                    high_priority_interventions.append({
                        "learner_id": lid,
                        "concept_id": cid,
                        "mastery": round(p_l, 3),
                        "reason": "Critically low mastery state (< 0.40)",
                        "urgency": "high",
                    })

                # Check active misconceptions for this student & concept
                if misconception_tracker:
                    student_miscs = misconception_tracker.get_misconceptions(lid, cid)
                    for sm in student_miscs:
                        if sm.status in {MisconceptionStatus.SUSPECTED.value, MisconceptionStatus.RECURRING.value}:
                            key = f"{cid}:{sm.category}"
                            if key not in misconception_tally:
                                misconception_tally[key] = {
                                    "concept_id": cid,
                                    "category": sm.category,
                                    "description": sm.description,
                                    "remediation": sm.remediation,
                                    "affected_students": set(),
                                }
                            misconception_tally[key]["affected_students"].add(lid)

            mean_m = (sum(masteries) / len(masteries)) if masteries else 0.0
            concept_analytics[cid] = CohortConceptAnalytics(
                concept_id=cid,
                student_count=len(learner_ids),
                mean_mastery=round(mean_m, 4),
                mastered_count=m_count,
                developing_count=d_count,
                at_risk_count=r_count,
                active_misconceptions=active_misc_list,
            )

        # Build clean heatmap
        heatmap: List[Dict[str, Any]] = []
        for key, val in misconception_tally.items():
            affected = list(val["affected_students"])
            pct = round(len(affected) / len(learner_ids), 3) if learner_ids else 0.0
            heatmap.append({
                "concept_id": val["concept_id"],
                "category": val["category"],
                "description": val["description"],
                "remediation": val["remediation"],
                "affected_student_count": len(affected),
                "affected_student_percentage": pct,
                "student_ids": affected,
            })
        heatmap.sort(key=lambda x: x["affected_student_count"], reverse=True)

        return CohortClassroomReport(
            class_id=class_id,
            class_name=class_name,
            student_count=len(learner_ids),
            concept_analytics=concept_analytics,
            high_priority_interventions=high_priority_interventions,
            class_misconception_heatmap=heatmap,
            generated_at=now_iso,
        )

    def generate_cohort_teaching_plan(
        self,
        class_id: str,
        class_name: str,
        concept_id: str,
        learner_ids: List[str],
        state_service: LearnerStateService,
        misconception_tracker: Optional[MisconceptionTracker] = None,
        total_minutes: int = 60,
    ) -> DynamicTeachingPlan:
        """Generates a dynamic teaching plan tailored to the live knowledge profile of the cohort."""
        cid = concept_id.strip()
        prereqs = self.knowledge_graph.get_direct_prerequisites(cid) if self.knowledge_graph.contains(cid) else []
        report = self.analyze_cohort(
            class_id, class_name, learner_ids, [cid] + prereqs, state_service, misconception_tracker
        )

        target_analytics = report.concept_analytics.get(cid)
        mean_target_m = target_analytics.mean_mastery if target_analytics else 0.50

        # Check prerequisite health in the cohort
        prereq_risks: List[str] = []
        for p in prereqs:
            pa = report.concept_analytics.get(p)
            if pa and (pa.at_risk_count / len(learner_ids)) > 0.25:
                prereq_risks.append(f"{p} ({pa.at_risk_count}/{len(learner_ids)} students at risk)")

        base_plan = self.independent_planner.generate_plan(cid, total_minutes)

        # Dynamic adaptation:
        adapted_segments: List[LessonSegment] = []
        for seg in base_plan.segments:
            seg_copy = copy.deepcopy(seg)
            if seg_copy.segment_type == "prerequisite_bridge":
                if prereq_risks:
                    seg_copy.estimated_minutes += 5
                    seg_copy.title += " [ELEVATED CLASS PREREQUISITE DEFICIT]"
                    seg_copy.teacher_script_or_guidance += (
                        f"\n\n**Cohort Alert:** High failure risk detected in prerequisite(s): {', '.join(prereq_risks)}. "
                        "Allocate an extra 5 minutes to explicitly re-derive foundational vectors/units before proceeding."
                    )
            elif seg_copy.segment_type == "misconception_refutation":
                # Find active cohort misconceptions for this concept
                relevant_misc = [h for h in report.class_misconception_heatmap if h["concept_id"] == cid]
                if relevant_misc:
                    top_misc = relevant_misc[0]
                    seg_copy.title += f" [Targeting {top_misc['affected_student_count']} Affected Students]"
                    seg_copy.teacher_script_or_guidance += (
                        f"\n\n**Classroom Heatmap Focal Point:** {top_misc['affected_student_count']} students ({top_misc['affected_student_percentage']:.0%}) "
                        f"in this section demonstrate '{top_misc['category']}'. Specifically pause the lecture to work through: {top_misc['remediation']}"
                    )
            adapted_segments.append(seg_copy)

        # Differentiated breakouts
        remedial_count = target_analytics.at_risk_count if target_analytics else 0
        advanced_count = target_analytics.mastered_count if target_analytics else 0

        diff_strategies = {
            "cohort_breakdown": {
                "at_risk_students_count": remedial_count,
                "developing_students_count": target_analytics.developing_count if target_analytics else 0,
                "mastered_students_count": advanced_count,
            },
            "guided_remediation_group": {
                "recommended_focus": "Focus on sign conventions and simple single-variable isolation before attempting multi-body problems.",
                "suggested_materials": "Scaffolded worksheets with step-by-step vector breakdowns.",
            },
            "accelerated_extension_group": {
                "recommended_focus": "Provide JEE Advanced multi-concept synthesis problems (e.g., Kinematics coupled with non-inertial pseudo forces).",
                "suggested_materials": "Timed high-difficulty challenge set with numerical free-entry constraints.",
            },
        }

        c_content = self.knowledge_base.get_concept_content(cid)
        c_name = c_content.concept_name if c_content else cid
        return DynamicTeachingPlan(
            plan_id=f"PLAN_COHORT_{class_id}_{uuid.uuid4().hex[:8].upper()}",
            persona="b2b_cohort_teacher",
            concept_id=cid,
            concept_name=c_name,
            target_grade_or_course=f"Section {class_name}",
            total_duration_minutes=total_minutes,
            prerequisite_concepts=prereqs,
            segments=adapted_segments,
            cohort_summary={
                "class_id": class_id,
                "class_name": class_name,
                "student_count": len(learner_ids),
                "mean_mastery": mean_target_m,
                "prerequisite_alerts": prereq_risks,
            },
            differentiation_strategies=diff_strategies,
        )

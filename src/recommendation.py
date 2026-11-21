"""LearnSense Person 3 — Personalized Learning Activity Recommendation Engine.

Selects the next best pedagogical activity across learning, remediation, practice,
diagnostic assessment, worked examples, and spaced review.
Strictly conforms to contracts/recommendation_schema.json with explainable reason codes,
prerequisite gating, and evidence references.
"""

from __future__ import annotations

import copy
import datetime
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.adaptive_assessment import AdaptiveAssessmentSelector, AssessmentSelectionResult
from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.knowledge_graph import PrerequisiteGraph, load_knowledge_graph_from_csv
from src.spaced_review import ConceptReviewStatus, SpacedReviewScheduler
from src.state import LearnerConceptState, LearnerStateService


@dataclass
class RecommendationItem:
    """Actionable recommendation conforming to contracts/recommendation_schema.json."""
    recommendation_id: str
    learner_id: str
    kind: str  # 'practice_question' | 'review_concept' | 'learn_concept' | 'worked_example' | 'hint' | 'reassessment' | 'tutor_session'
    target: Dict[str, str]  # {'target_type': 'question'|'concept'|'lesson'|'learning_resource'|'tutor_session', 'target_id': str}
    reason_codes: List[str]  # e.g. ['low_mastery_estimate', 'prerequisite_gap', ...]
    rationale: str
    priority: int = 50  # 0 to 100
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    status: str = "proposed"
    evidence_refs: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_contract_payload(self) -> Dict[str, Any]:
        """Serializes recommendation strictly adhering to recommendation_schema.json."""
        now_iso = self.created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "recommendation_id": self.recommendation_id,
            "learner_id": self.learner_id,
            "kind": self.kind,
            "target": {
                "target_type": self.target["target_type"],
                "target_id": self.target["target_id"],
            },
            "reason_codes": list(self.reason_codes),
            "rationale": self.rationale,
            "priority": int(self.priority),
            "created_at": now_iso,
            "expires_at": self.expires_at,
            "status": self.status,
            "evidence_refs": copy.deepcopy(self.evidence_refs),
            "metadata": copy.deepcopy(self.metadata),
        }


class RecommendationEngine:
    """Personalized Pedagogical Recommendation Engine.
    
    Synthesizes learner knowledge state, prerequisite graphs, spaced review schedules,
    and adaptive assessment to guide the student's next learning step.
    """

    def __init__(
        self,
        knowledge_graph: Optional[PrerequisiteGraph] = None,
        assessment_selector: Optional[AdaptiveAssessmentSelector] = None,
        review_scheduler: Optional[SpacedReviewScheduler] = None,
        knowledge_base: Optional[GroundedKnowledgeBase] = None,
        misconception_tracker: Optional[Any] = None,
        retention_model: Optional[Any] = None,
        transfer_verifier: Optional[Any] = None,
    ) -> None:
        self.knowledge_graph = knowledge_graph or load_knowledge_graph_from_csv()
        self.assessment_selector = assessment_selector or AdaptiveAssessmentSelector(knowledge_graph=self.knowledge_graph)
        self.review_scheduler = review_scheduler or SpacedReviewScheduler()
        self.knowledge_base = knowledge_base or get_default_knowledge_base()
        self.misconception_tracker = misconception_tracker
        self.retention_model = retention_model
        self.transfer_verifier = transfer_verifier
        self._topological_order = self.knowledge_graph.topological_sort()

    def recommend_next_activity(
        self,
        learner_id: str,
        state_service: LearnerStateService,
        focus_concept_id: Optional[str] = None,
        recent_recommendations: Optional[Sequence[str]] = None,
        as_of_time: Optional[Union[str, datetime.datetime]] = None,
    ) -> RecommendationItem:
        """Determines the most pedagogically valuable next activity for the learner.
        
        Priority Cascade:
        1. Prerequisite Remediation (Priority 90): If target or active concept has unmet prerequisites.
        2. Error Streak Scaffold (Priority 85): If learner has consecutive errors, provide worked example or explanation.
        3. Spaced Review Due (Priority 80): If a previously learned concept is due/overdue for review.
        4. Misconception Remediation (Priority 75): If active recurring or high-confidence misconception is tracked.
        5. Foundational Learning (Priority 70): If target concept is unassessed, recommend conceptual teaching.
        6. Mastery Uncertainty Reassessment (Priority 65): If responses are conflicting or evidence is stale.
        7. Adaptive Assessment / Practice (Priority 60): If concept is developing, choose an information-gain question.
        8. Transfer Verification Practice (Priority 55): If concept is mastered, test on unseen transfer items.
        9. Curriculum Advancement / Challenge (Priority 50): Advance in topological curriculum order.
        """
        lid = str(learner_id).strip()
        learner_states = state_service.get_all_learner_states(lid)
        mastery_vector = state_service.get_learner_mastery_vector(lid)
        recent_ids = set(recent_recommendations or [])
        rec_id = f"REC_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Step A: Resolve target concept
        target_cid = focus_concept_id.strip() if focus_concept_id else None
        if not target_cid or not self.knowledge_graph.contains(target_cid):
            # Select the earliest unmastered concept in topological curriculum order
            for cid in self._topological_order:
                m_prob = mastery_vector.get(cid, 0.0)
                st = learner_states.get(cid)
                if st is None or st.evidence_count == 0 or m_prob < 0.75:
                    target_cid = cid
                    break
            if not target_cid:
                target_cid = self._topological_order[0]

        target_state = state_service.get_or_initialize_state(lid, target_cid)

        # Step B: Check Prerequisite Readiness (Priority 90)
        is_ready, prereq_map, broken_prereqs = self.knowledge_graph.evaluate_prerequisite_readiness(
            target_cid, mastery_vector, mastery_threshold=0.50
        )
        if not is_ready:
            # Foundational gap identified: prioritize earliest unmet prerequisite
            remediation_seq = self.knowledge_graph.get_remediation_sequence(target_cid, mastery_vector)
            remedy_cid = remediation_seq[0] if remediation_seq else broken_prereqs[0]
            remedy_state = state_service.get_or_initialize_state(lid, remedy_cid)

            # If completely unassessed, learn it; if weak from attempts, review it
            kind = "learn_concept" if remedy_state.evidence_count == 0 else "review_concept"
            rationale = (
                f"Before advancing to '{target_cid}', prerequisite '{remedy_cid}' requires foundational remediation. "
                f"Current estimated mastery: {remedy_state.mastery_probability:.2f} (evidence: {remedy_state.evidence_count})."
            )

            return RecommendationItem(
                recommendation_id=rec_id,
                learner_id=lid,
                kind=kind,
                target={"target_type": "concept", "target_id": remedy_cid},
                reason_codes=["prerequisite_gap", "low_mastery_estimate"],
                rationale=rationale,
                priority=90,
                created_at=now_iso,
                status="proposed",
                evidence_refs=[
                    {"ref_type": "concept", "ref_id": remedy_cid},
                    {"ref_type": "learner_state", "ref_id": remedy_cid},
                ],
                metadata={
                    "blocked_target_concept": target_cid,
                    "remediation_sequence": remediation_seq,
                    "prerequisite_status_map": prereq_map,
                },
            )

        # Step C: Check Recent Error Streaks (Priority 85)
        consecutive_errors = target_state.metadata.get("consecutive_errors", 0)
        if consecutive_errors >= 2:
            rationale = (
                f"Learner encountered {consecutive_errors} consecutive errors on '{target_cid}'. "
                f"Studying a worked example provides scaffolded reasoning before further assessment."
            )
            return RecommendationItem(
                recommendation_id=rec_id,
                learner_id=lid,
                kind="worked_example",
                target={"target_type": "concept", "target_id": target_cid},
                reason_codes=["recent_error_pattern", "low_mastery_estimate"],
                rationale=rationale,
                priority=85,
                created_at=now_iso,
                status="proposed",
                evidence_refs=[
                    {"ref_type": "learner_state", "ref_id": target_cid},
                    {"ref_type": "concept", "ref_id": target_cid},
                ],
                metadata={
                    "consecutive_errors": consecutive_errors,
                    "mastery_probability": target_state.mastery_probability,
                },
            )

        # Step D: Check Spaced Review Scheduling (Priority 80)
        # Overdue spaced review takes precedence over new concept learning (Priority 70) and
        # adaptive practice (Priority 60), remaining subordinate only to prerequisite gaps (P90)
        # and active error streak scaffolding (P85).
        due_reviews = self.review_scheduler.find_concepts_due_for_review(learner_states, as_of_time=as_of_time)
        if due_reviews:
            most_urgent = due_reviews[0]
            rationale = (
                f"Concept '{most_urgent.concept_id}' is {most_urgent.status} for spaced repetition review "
                f"(interval of {most_urgent.recommended_interval_days:.1f} days elapsed). Retention reinforcement recommended."
            )
            return RecommendationItem(
                recommendation_id=rec_id,
                learner_id=lid,
                kind="review_concept",
                target={"target_type": "concept", "target_id": most_urgent.concept_id},
                reason_codes=["spaced_review_due"],
                rationale=rationale,
                priority=80,
                created_at=now_iso,
                status="proposed",
                evidence_refs=[
                    {"ref_type": "learner_state", "ref_id": most_urgent.concept_id},
                    {"ref_type": "concept", "ref_id": most_urgent.concept_id},
                ],
                metadata=most_urgent.to_dict(),
            )

        # Step D.2: Check Active Misconceptions (Priority 75)
        if self.misconception_tracker:
            active_miscs = self.misconception_tracker.get_misconceptions(lid, target_cid, active_only=True)
            if active_miscs:
                top_misc = active_miscs[0]
                rationale = (
                    f"Active misconception detected on '{target_cid}': {top_misc.description}. "
                    f"Remediation action: {top_misc.remediation_action}"
                )
                return RecommendationItem(
                    recommendation_id=rec_id,
                    learner_id=lid,
                    kind="tutor_session",
                    target={"target_type": "concept", "target_id": target_cid},
                    reason_codes=["recent_error_pattern", "low_mastery_estimate"],
                    rationale=rationale,
                    priority=75,
                    created_at=now_iso,
                    status="proposed",
                    evidence_refs=[
                        {"ref_type": "learner_state", "ref_id": target_cid},
                        {"ref_type": "concept", "ref_id": target_cid},
                    ],
                    metadata={
                        "misconception_id": top_misc.misconception_id,
                        "category": top_misc.category,
                        "confidence": top_misc.confidence,
                        "recurrence_count": top_misc.recurrence_count,
                    },
                )

        # Step E: Unassessed Target Concept (Priority 70)
        if target_state.evidence_count == 0:
            rationale = (
                f"Concept '{target_cid}' is currently unassessed. Conceptual explanation and guided introductory study "
                f"recommended to establish foundational understanding."
            )
            return RecommendationItem(
                recommendation_id=rec_id,
                learner_id=lid,
                kind="learn_concept",
                target={"target_type": "concept", "target_id": target_cid},
                reason_codes=["curriculum_sequence"],
                rationale=rationale,
                priority=70,
                created_at=now_iso,
                status="proposed",
                evidence_refs=[{"ref_type": "concept", "ref_id": target_cid}],
                metadata={"status": "unassessed", "initial_prior": target_state.mastery_probability},
            )

        # Step E.2: Check High Uncertainty / Stale Reassessment (Priority 65)
        try:
            from src.uncertainty import MasteryClassification, MasteryUncertaintyEvaluator
            uncertainty_eval = MasteryUncertaintyEvaluator.evaluate_state(
                target_state,
                as_of_time=str(as_of_time) if as_of_time else None,
            )
            if uncertainty_eval.classification == MasteryClassification.UNCERTAIN and target_state.evidence_count >= 2:
                rationale = (
                    f"Mastery estimate for '{target_cid}' is uncertain ({uncertainty_eval.explanation}). "
                    "Targeted reassessment recommended to establish calibrated mastery belief."
                )
                return RecommendationItem(
                    recommendation_id=rec_id,
                    learner_id=lid,
                    kind="reassessment",
                    target={"target_type": "concept", "target_id": target_cid},
                    reason_codes=["low_mastery_estimate", "other"],
                    rationale=rationale,
                    priority=65,
                    created_at=now_iso,
                    status="proposed",
                    evidence_refs=[
                        {"ref_type": "learner_state", "ref_id": target_cid},
                        {"ref_type": "concept", "ref_id": target_cid},
                    ],
                    metadata=uncertainty_eval.to_dict(),
                )
        except Exception:
            pass

        # Step F: Developing Knowledge State — Adaptive Practice Question (Priority 60)
        if target_state.mastery_probability < 0.80:
            # Query adaptive assessment selector for maximum information gain question
            recent_attempts = [
                rec.question_id
                for rec in state_service._learner_history.get(lid, [])[-10:]
            ]
            assess_res = self.assessment_selector.select_next_question(
                target_concept_id=target_cid,
                learner_state=target_state,
                recent_question_ids=recent_attempts,
                objective="progress",
                learner_mastery_vector=mastery_vector,
            )

            if assess_res.selected_question is not None:
                q = assess_res.selected_question
                rationale = (
                    f"Adaptive practice question {q.question_id} selected to resolve knowledge uncertainty "
                    f"for concept '{target_cid}'. Expected Information Gain: {assess_res.information_gain:.4f} bits."
                )
                return RecommendationItem(
                    recommendation_id=rec_id,
                    learner_id=lid,
                    kind="practice_question",
                    target={"target_type": "question", "target_id": q.question_id},
                    reason_codes=["low_mastery_estimate"],
                    rationale=rationale,
                    priority=60,
                    created_at=now_iso,
                    status="proposed",
                    evidence_refs=[
                        {"ref_type": "learner_state", "ref_id": target_cid},
                        {"ref_type": "question", "ref_id": q.question_id},
                    ],
                    metadata={
                        "expected_information_gain": assess_res.information_gain,
                        "question_difficulty": q.difficulty,
                        "estimated_time_seconds": q.estimated_time_seconds,
                    },
                )

        # Step G: Mastered Target Concept — Check Transfer Verification then Advance
        if self.transfer_verifier:
            try:
                from src.transfer import TransferStatus
                transfer_res = self.transfer_verifier.evaluate_transfer(lid, target_cid)
                if transfer_res.status in {TransferStatus.UNTESTED, TransferStatus.EMERGING_TRANSFER}:
                    assess_res = self.assessment_selector.select_next_question(
                        target_concept_id=target_cid,
                        learner_state=target_state,
                        objective="progress",
                        learner_mastery_vector=mastery_vector,
                    )
                    if assess_res.selected_question is not None:
                        q = assess_res.selected_question
                        rationale = (
                            f"Mastery demonstrated on familiar items for '{target_cid}'. "
                            f"Unseen transfer question {q.question_id} recommended to verify generalized comprehension."
                        )
                        return RecommendationItem(
                            recommendation_id=rec_id,
                            learner_id=lid,
                            kind="practice_question",
                            target={"target_type": "question", "target_id": q.question_id},
                            reason_codes=["ready_for_challenge"],
                            rationale=rationale,
                            priority=55,
                            created_at=now_iso,
                            status="proposed",
                            evidence_refs=[
                                {"ref_type": "learner_state", "ref_id": target_cid},
                                {"ref_type": "question", "ref_id": q.question_id},
                            ],
                            metadata={
                                "transfer_verification": transfer_res.to_dict(),
                                "objective": "transfer_check",
                            },
                        )
            except Exception:
                pass

        # Advance to direct dependent first, or next in topological sequence
        next_cid = None
        direct_deps = self.knowledge_graph.get_direct_dependents(target_cid)
        for dep in direct_deps:
            if mastery_vector.get(dep, 0.0) < 0.75:
                next_cid = dep
                break

        if not next_cid:
            curr_idx = self._topological_order.index(target_cid) if target_cid in self._topological_order else -1
            for idx in range(curr_idx + 1, len(self._topological_order)):
                candidate = self._topological_order[idx]
                if mastery_vector.get(candidate, 0.0) < 0.75:
                    next_cid = candidate
                    break

        if next_cid:
            rationale = (
                f"Mastery demonstrated on '{target_cid}' (P(mastery) = {target_state.mastery_probability:.2f}). "
                f"Advancing to next curriculum objective: '{next_cid}'."
            )
            return RecommendationItem(
                recommendation_id=rec_id,
                learner_id=lid,
                kind="learn_concept",
                target={"target_type": "concept", "target_id": next_cid},
                reason_codes=["curriculum_sequence", "ready_for_challenge"],
                rationale=rationale,
                priority=50,
                created_at=now_iso,
                status="proposed",
                evidence_refs=[
                    {"ref_type": "learner_state", "ref_id": target_cid},
                    {"ref_type": "concept", "ref_id": next_cid},
                ],
                metadata={"previous_mastered_concept": target_cid},
            )

        # Fallback: challenge question on current concept
        assess_res = self.assessment_selector.select_next_question(
            target_concept_id=target_cid,
            learner_state=target_state,
            objective="mastery_check",
            learner_mastery_vector=mastery_vector,
        )
        target_qid = assess_res.selected_question.question_id if assess_res.selected_question else "Q_GENERAL"
        return RecommendationItem(
            recommendation_id=rec_id,
            learner_id=lid,
            kind="practice_question",
            target={"target_type": "question", "target_id": target_qid},
            reason_codes=["ready_for_challenge"],
            rationale=f"Challenge assessment item recommended to solidify comprehensive mastery of '{target_cid}'.",
            priority=50,
            created_at=now_iso,
            status="proposed",
            evidence_refs=[{"ref_type": "learner_state", "ref_id": target_cid}],
            metadata={"objective": "mastery_check"},
        )

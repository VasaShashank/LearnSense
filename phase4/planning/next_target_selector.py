"""
Next Learning Target Selector.
Determines WHAT the learner should work on next and creates appropriate activity wrapping.
"""

from typing import List, Optional
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.models import LearnerState
from phase4.models import ActivityType, LearningActivity, LearningPath, LearningTarget


class NextTargetSelector:
    """Selects the active learning target from path and creates associated activity."""

    def select_next_target(
        self,
        learning_path: LearningPath,
        learner_state: LearnerState,
        learning_context: LearningContext,
    ) -> Optional[LearningTarget]:
        """
        Selects first non-completed concept node from learning path as next LearningTarget.
        """
        if not learning_path.nodes:
            return None

        # Pick first node in PENDING or IN_PROGRESS
        active_node = None
        for node in learning_path.nodes:
            if node.status in ("PENDING", "IN_PROGRESS"):
                active_node = node
                break

        if not active_node:
            # All path nodes completed
            return None

        reason = (
            f"Foundational concept '{active_node.concept_name}'"
            if active_node.is_foundational
            else f"Remediation target '{active_node.concept_name}' (estimated mastery: {active_node.estimated_mastery:.2f})"
        )

        return LearningTarget(
            target_id=f"target_{active_node.concept_id}",
            concept_id=active_node.concept_id,
            concept_name=active_node.concept_name,
            target_type="FOUNDATIONAL_START" if active_node.is_foundational else "PREREQUISITE_REMEDIATION",
            reason=reason,
        )

    def create_activity_for_target(
        self,
        target: LearningTarget,
        activity_type: ActivityType = ActivityType.EXPLANATION,
    ) -> LearningActivity:
        """
        Wraps LearningTarget into a LearningActivity ready for Phase 3 content generation.
        """
        return LearningActivity(
            activity_id=f"act_{target.concept_id}_{activity_type.value.lower()}",
            target_id=target.target_id,
            concept_id=target.concept_id,
            activity_type=activity_type,
            title=f"Activity for {target.concept_name}",
            content={
                "concept_id": target.concept_id,
                "concept_name": target.concept_name,
                "activity_type": activity_type.value,
                "reason": target.reason,
            },
        )

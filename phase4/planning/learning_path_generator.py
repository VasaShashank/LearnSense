"""
Learning Path Generator.
Generates prerequisite-aware, cycle-safe, deduplicated personalized learning paths.
Excludes concepts that are already sufficiently mastered.
"""

from typing import Dict, List, Optional, Set
import uuid
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.models import LearnerState
from phase4.config import phase4_config
from phase4.gaps.gap_detector import GapDetector
from phase4.gaps.gap_prioritizer import GapPrioritizer
from phase4.models import KnowledgeGap, LearningPath, LearningPathNode
from phase4.planning.prerequisite_resolver import PrerequisiteResolver


class LearningPathGenerator:
    """Constructs personalized learning path from knowledge graph, learner state, and gaps."""

    def __init__(
        self,
        resolver: Optional[PrerequisiteResolver] = None,
        detector: Optional[GapDetector] = None,
        prioritizer: Optional[GapPrioritizer] = None,
        config=None,
    ):
        self.resolver = resolver or PrerequisiteResolver()
        self.detector = detector or GapDetector()
        self.prioritizer = prioritizer or GapPrioritizer()
        self.config = config or phase4_config

    def generate_path(
        self,
        learning_context: LearningContext,
        learner_state: LearnerState,
        subject_concept_ids: List[str],
        target_concept_id: Optional[str] = None,
    ) -> LearningPath:
        """
        Generates a cycle-safe, prerequisite-first personalized learning path.
        Filters out already-mastered concepts unless required as remediation context.
        Respects MAX_LEARNING_PATH_LENGTH.
        """
        # Step 1: Detect and prioritize gaps
        gaps = self.detector.detect_gaps(learning_context, learner_state, subject_concept_ids)
        prioritized_gaps = self.prioritizer.prioritize_gaps(gaps)
        gap_concept_ids = set(g.concept_id for g in prioritized_gaps)

        # Step 2: Determine candidate concepts to include in path
        if not subject_concept_ids:
            return LearningPath(path_id=f"path_{uuid.uuid4().hex[:10]}", learner_id=learner_state.learner_id, subject_id="")

        foundational_ids = set(self.resolver.find_foundational_concepts(learning_context, subject_concept_ids))

        # Include candidate concepts: Gaps + Foundational concepts that aren't mastered
        candidate_ids: List[str] = []

        # High priority gap concepts
        for gap in prioritized_gaps:
            c_id = gap.concept_id
            if c_id not in candidate_ids:
                candidate_ids.append(c_id)

        # Foundational concepts if zero gaps or to anchor starting point
        for f_id in foundational_ids:
            f_state = learner_state.get_concept_state(f_id)
            if f_state.mastery_probability < self.config.MASTERY_THRESHOLD and f_id not in candidate_ids:
                candidate_ids.append(f_id)

        # Fallback: If learner mastered everything, include remaining unmastered or foundational concept
        if not candidate_ids and subject_concept_ids:
            candidate_ids = [subject_concept_ids[0]]

        # Step 3: Topologically sort candidate concepts cycle-safely
        ordered_concept_ids = self.resolver.cycle_safe_topological_sort(learning_context, candidate_ids)

        # Step 4: Cap to MAX_LEARNING_PATH_LENGTH
        max_len = self.config.MAX_LEARNING_PATH_LENGTH
        final_concept_ids = ordered_concept_ids[:max_len]

        # Step 5: Construct path nodes
        nodes: List[LearningPathNode] = []
        for idx, c_id in enumerate(final_concept_ids):
            c_view = learning_context.concepts.get(c_id)
            c_name = c_view.canonical_name if c_view else c_id
            c_state = learner_state.get_concept_state(c_id)

            is_found = (c_id in foundational_ids)
            is_prereq = (c_id in gap_concept_ids and c_id != target_concept_id)

            nodes.append(
                LearningPathNode(
                    node_id=f"node_{idx+1}_{c_id}",
                    concept_id=c_id,
                    concept_name=c_name,
                    order=idx + 1,
                    is_foundational=is_found,
                    is_prerequisite=is_prereq,
                    estimated_mastery=c_state.mastery_probability,
                    status="IN_PROGRESS" if idx == 0 else "PENDING",
                )
            )

        return LearningPath(
            path_id=f"path_{uuid.uuid4().hex[:10]}",
            learner_id=learner_state.learner_id,
            subject_id=learning_context.document_id,
            nodes=nodes,
            target_concept_id=target_concept_id or (nodes[-1].concept_id if nodes else None),
        )

"""
Gap Detector.
Detects concept gaps across LOW_MASTERY, INSUFFICIENT_EVIDENCE, WEAK_PREREQUISITE,
and HIGH_DOWNSTREAM_IMPACT categories based on structured application state.
"""

from typing import Dict, List, Set
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.learner.models import LearnerState
from phase4.config import phase4_config
from phase4.models import GapReason, GapType, KnowledgeGap


class GapDetector:
    """Detects knowledge gaps across four structured categories."""

    def __init__(self, config=None):
        self.config = config or phase4_config

    def detect_gaps(
        self,
        learning_context: LearningContext,
        learner_state: LearnerState,
        subject_concept_ids: List[str],
    ) -> List[KnowledgeGap]:
        """
        Scans all concepts in subject_concept_ids and detects all applicable gaps.
        Excludes concepts that are sufficiently mastered without weak prerequisites.
        """
        gaps: List[KnowledgeGap] = []

        # Precompute downstream count for each concept
        # prereq link: source = prereq concept, target = dependent concept
        downstream_counts: Dict[str, int] = {}
        prereq_map: Dict[str, List[str]] = {}  # target -> list of source concept_ids

        for link in learning_context.prerequisites:
            src = link.source_concept_id
            tgt = link.target_concept_id

            downstream_counts[src] = downstream_counts.get(src, 0) + 1

            if tgt not in prereq_map:
                prereq_map[tgt] = []
            if src not in prereq_map[tgt]:
                prereq_map[tgt].append(src)

        for c_id in subject_concept_ids:
            c_view = learning_context.concepts.get(c_id)
            c_name = c_view.canonical_name if c_view else c_id
            c_state = learner_state.get_concept_state(c_id)

            mastery = c_state.mastery_probability
            uncertainty = c_state.uncertainty
            attempts = c_state.attempt_count
            downstream_cnt = downstream_counts.get(c_id, 0)

            detected_reasons: List[GapReason] = []
            primary_gap_type: GapType = GapType.LOW_MASTERY

            # Category 1: Insufficient Evidence
            is_insufficient = (
                attempts < self.config.MIN_EVIDENCE_COUNT
                or uncertainty > self.config.UNCERTAINTY_THRESHOLD
            )
            if is_insufficient:
                detected_reasons.append(
                    GapReason(
                        gap_type=GapType.INSUFFICIENT_EVIDENCE,
                        description=f"Insufficient evidence for '{c_name}' (attempts={attempts}, uncertainty={uncertainty:.2f}).",
                        details={"attempts": attempts, "uncertainty": uncertainty},
                    )
                )

            # Category 2: Low Mastery
            is_low_mastery = mastery < self.config.MASTERY_THRESHOLD
            if is_low_mastery:
                detected_reasons.append(
                    GapReason(
                        gap_type=GapType.LOW_MASTERY,
                        description=f"Mastery for '{c_name}' is {mastery:.2f}, below threshold {self.config.MASTERY_THRESHOLD:.2f}.",
                        details={"mastery_probability": mastery, "threshold": self.config.MASTERY_THRESHOLD},
                    )
                )

            # Category 3: Weak Prerequisite
            weak_prereq_ids = []
            prereqs = prereq_map.get(c_id, [])
            for p_id in prereqs:
                p_state = learner_state.get_concept_state(p_id)
                if p_state.mastery_probability < self.config.MASTERY_THRESHOLD:
                    weak_prereq_ids.append(p_id)

            if weak_prereq_ids:
                detected_reasons.append(
                    GapReason(
                        gap_type=GapType.WEAK_PREREQUISITE,
                        description=f"Target '{c_name}' depends on {len(weak_prereq_ids)} weak prerequisite concept(s).",
                        details={"weak_prerequisite_ids": weak_prereq_ids},
                    )
                )

            # Category 4: High Downstream Impact
            if (is_low_mastery or is_insufficient) and downstream_cnt >= 2:
                detected_reasons.append(
                    GapReason(
                        gap_type=GapType.HIGH_DOWNSTREAM_IMPACT,
                        description=f"Weak concept '{c_name}' impacts {downstream_cnt} downstream concepts.",
                        details={"downstream_impact_count": downstream_cnt},
                    )
                )

            # If any reasons detected, construct KnowledgeGap
            if detected_reasons:
                # Determine primary gap type
                if is_low_mastery:
                    primary_gap_type = GapType.LOW_MASTERY
                elif is_insufficient:
                    primary_gap_type = GapType.INSUFFICIENT_EVIDENCE
                elif weak_prereq_ids:
                    primary_gap_type = GapType.WEAK_PREREQUISITE
                else:
                    primary_gap_type = GapType.HIGH_DOWNSTREAM_IMPACT

                gaps.append(
                    KnowledgeGap(
                        gap_id=f"gap_{c_id}",
                        concept_id=c_id,
                        concept_name=c_name,
                        gap_type=primary_gap_type,
                        priority_score=0.0,  # Calculated by GapPrioritizer
                        reasons=detected_reasons,
                        mastery_probability=mastery,
                        uncertainty=uncertainty,
                        downstream_impact_count=downstream_cnt,
                        weak_prerequisite_ids=weak_prereq_ids,
                    )
                )

        return gaps

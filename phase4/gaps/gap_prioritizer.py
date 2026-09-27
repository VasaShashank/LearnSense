"""
Gap Prioritizer.
Ranks knowledge gaps using a deterministic weighted linear model based on application state.
Does NOT rely on LLMs or ML ranking models.
"""

from typing import List
from phase4.config import phase4_config
from phase4.models import KnowledgeGap


class GapPrioritizer:
    """Deterministically ranks knowledge gaps using centralized config weights."""

    def __init__(self, config=None):
        self.config = config or phase4_config

    def compute_priority_score(self, gap: KnowledgeGap) -> float:
        """
        Computes priority score in range [0.0, 1.0].
        Higher priority means the gap should be addressed earlier.
        Formula components:
        - Low mastery contribution: (1.0 - mastery_probability)
        - Uncertainty contribution: uncertainty
        - Prerequisite contribution: 1.0 if has weak prerequisites else 0.0
        - Downstream impact contribution: min(1.0, downstream_impact_count / 5.0)
        """
        w_mastery = self.config.MASTERY_WEIGHT
        w_uncert = self.config.UNCERTAINTY_WEIGHT
        w_prereq = self.config.PREREQUISITE_WEIGHT
        w_downstream = self.config.DOWNSTREAM_IMPACT_WEIGHT

        mastery_term = (1.0 - gap.mastery_probability)
        uncert_term = gap.uncertainty
        prereq_term = 1.0 if gap.weak_prerequisite_ids else 0.0
        downstream_term = min(1.0, gap.downstream_impact_count / 5.0)

        score = (
            (w_mastery * mastery_term)
            + (w_uncert * uncert_term)
            + (w_prereq * prereq_term)
            + (w_downstream * downstream_term)
        )

        return round(max(0.0, min(1.0, score)), 4)

    def prioritize_gaps(self, gaps: List[KnowledgeGap]) -> List[KnowledgeGap]:
        """
        Updates priority scores and sorts gaps in descending order of priority.
        Maintains deterministic tie-breaking by concept_id.
        """
        for gap in gaps:
            gap.priority_score = self.compute_priority_score(gap)

        # Sort primary by priority_score descending, secondary by concept_id ascending for determinism
        sorted_gaps = sorted(
            gaps,
            key=lambda g: (-g.priority_score, g.concept_id)
        )
        return sorted_gaps

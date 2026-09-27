"""
Gap Reasoner.
Formats structured gap reasons into human-readable explainable statements derived strictly
from structured data (without LLM fabrication).
"""

from typing import List
from phase4.models import GapReason, KnowledgeGap


class GapReasoner:
    """Produces explainable data-driven reasons for detected gaps."""

    def generate_explanation(self, gap: KnowledgeGap) -> List[str]:
        """Returns clean list of textual explanations derived directly from gap reasons."""
        explanations = []
        for reason in gap.reasons:
            explanations.append(reason.description)
        return explanations

"""
Topic-Local Remediation Engine for Phase 3.
Provides immediate local remediation materials and recommendations when learner encounters mistakes.
"""

from typing import List
from pydantic import BaseModel, Field
from phase3.knowledge.phase2_adapter import LearningContext


class RemediationItem(BaseModel):
    concept_id: str
    concept_name: str
    summary_explanation: str
    relevant_units: List[str] = Field(default_factory=list)


class RemediationRecommendation(BaseModel):
    topic_id: str
    remediation_items: List[RemediationItem] = Field(default_factory=list)
    actionable_advice: str


class LocalRemediationEngine:
    """Provides topic-local remediation materials based on incorrect concept attempts."""

    @staticmethod
    def generate_remediation(
        topic_id: str, incorrect_concept_ids: List[str], context: LearningContext
    ) -> RemediationRecommendation:
        items = []
        for c_id in incorrect_concept_ids:
            c_view = context.concepts.get(c_id)
            c_name = c_view.canonical_name if c_view else c_id

            # Locate educational units explaining or defining this concept
            matching_units = []
            for unit_id, unit in context.educational_units.items():
                for link in unit.concept_links:
                    if link.concept_id == c_id:
                        matching_units.append(unit_id)

            summary = f"Review foundational material for {c_name}."
            items.append(
                RemediationItem(
                    concept_id=c_id,
                    concept_name=c_name,
                    summary_explanation=summary,
                    relevant_units=matching_units,
                )
            )

        advice = (
            f"Focus your review on {len(items)} key concepts before retrying the topic assessment."
            if items
            else "Solid performance overall. Keep practicing!"
        )

        return RemediationRecommendation(
            topic_id=topic_id,
            remediation_items=items,
            actionable_advice=advice,
        )

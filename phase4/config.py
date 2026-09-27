"""
Phase 4 Centralized Configuration parameters.
Initial numeric values are tunable engineering/product parameters, not universal educational constants.
"""

from typing import Dict
from pydantic import BaseModel, Field


class Phase4Config(BaseModel):
    # Knowledge Tracing & Gap Detection Thresholds
    MASTERY_THRESHOLD: float = Field(
        default=0.5,
        description="Neutral Bayesian decision boundary (odds 1:1) or threshold below which concepts are considered weak."
    )
    UNCERTAINTY_THRESHOLD: float = Field(
        default=0.4,
        description="Uncertainty threshold above which evidence is considered insufficient."
    )
    MIN_EVIDENCE_COUNT: int = Field(
        default=3,
        description="Minimum number of observed attempts required before declaring knowledge evidence sufficient."
    )

    # Deterministic Gap Prioritization Scoring Weights
    MASTERY_WEIGHT: float = Field(
        default=0.35,
        description="Weight given to low mastery when calculating gap priority."
    )
    UNCERTAINTY_WEIGHT: float = Field(
        default=0.20,
        description="Weight given to knowledge estimation uncertainty."
    )
    PREREQUISITE_WEIGHT: float = Field(
        default=0.25,
        description="Weight given to prerequisite gap severity."
    )
    DOWNSTREAM_IMPACT_WEIGHT: float = Field(
        default=0.15,
        description="Weight given to downstream dependency count."
    )
    HISTORY_WEIGHT: float = Field(
        default=0.05,
        description="Weight given to recency or repeated failures."
    )

    # Diagnostic Assessment Limits
    DIAGNOSTIC_MIN_QUESTIONS: int = Field(
        default=3,
        description="Minimum number of questions per diagnostic session."
    )
    DIAGNOSTIC_MAX_QUESTIONS: int = Field(
        default=10,
        description="Maximum questions to present in initial diagnostic session."
    )
    DIAGNOSTIC_STOPPING_POLICY: str = Field(
        default="TARGET_REACHED_OR_INSUFFICIENT",
        description="Policy for stopping diagnostic assessment."
    )

    # Personalized Path Parameters
    MAX_LEARNING_PATH_LENGTH: int = Field(
        default=10,
        description="Maximum number of concepts/nodes included in a generated learning path."
    )


# Default global instance
phase4_config = Phase4Config()

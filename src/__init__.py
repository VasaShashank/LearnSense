"""LearnSense Person 3: Learner Modeling and Personalization module."""

from src.knowledge_graph import ConceptNode, PrerequisiteGraph, load_knowledge_graph_from_csv
from src.knowledge_base import GroundedKnowledgeBase, get_default_knowledge_base
from src.state import LearnerConceptState, LearnerStateService
from src.spaced_review import SpacedReviewScheduler, ConceptReviewStatus
from src.adaptive_assessment import (
    AdaptiveAssessmentSelector,
    AssessmentSelectionResult,
    QuestionItem,
    compute_expected_information_gain,
)
from src.recommendation import RecommendationEngine, RecommendationItem
from src.tutoring import TutoringEngine, TutoringRequest, TutoringResponse
from src.attempt_pipeline import PersonalizationPipeline, PipelineProcessingResult
from src.service import LearnSensePersonalizationService

from src.misconceptions import MisconceptionTracker, MisconceptionRecord, MisconceptionCategory, MisconceptionStatus
from src.retention import PersonalizedRetentionModel
from src.uncertainty import MasteryUncertaintyEvaluator, MasteryClassification, MasteryUncertaintyEvaluation
from src.transfer import MasteryTransferVerifier, TransferStatus, TransferType
from src.integration import (
    AssessmentAdapter,
    KnowledgeGraphAdapter,
    QuestionBankAdapter,
    AttemptEventDispatcher,
    IntegratedLearningLoopPipeline,
    EndToEndPipelineResult,
)

__version__ = "0.5.0"

__all__ = [
    "ConceptNode",
    "PrerequisiteGraph",
    "load_knowledge_graph_from_csv",
    "GroundedKnowledgeBase",
    "get_default_knowledge_base",
    "LearnerConceptState",
    "LearnerStateService",
    "SpacedReviewScheduler",
    "ConceptReviewStatus",
    "AdaptiveAssessmentSelector",
    "AssessmentSelectionResult",
    "QuestionItem",
    "compute_expected_information_gain",
    "RecommendationEngine",
    "RecommendationItem",
    "TutoringEngine",
    "TutoringRequest",
    "TutoringResponse",
    "PersonalizationPipeline",
    "PipelineProcessingResult",
    "LearnSensePersonalizationService",
    "MisconceptionTracker",
    "MisconceptionRecord",
    "MisconceptionCategory",
    "MisconceptionStatus",
    "PersonalizedRetentionModel",
    "MasteryUncertaintyEvaluator",
    "MasteryClassification",
    "MasteryUncertaintyEvaluation",
    "MasteryTransferVerifier",
    "TransferStatus",
    "TransferType",
    "AssessmentAdapter",
    "KnowledgeGraphAdapter",
    "QuestionBankAdapter",
    "AttemptEventDispatcher",
    "IntegratedLearningLoopPipeline",
    "EndToEndPipelineResult",
]

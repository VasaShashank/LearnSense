"""LearnSense Person 3 — Integration Package.

Exports contract validators, external service adapters, event handlers, and end-to-end pipeline orchestrator.
"""

from __future__ import annotations

from src.integration.assessment_adapter import AssessmentAdapter, IngestedAttemptEvent
from src.integration.contracts import (
    ContractValidatorRegistry,
    validate_attempt,
    validate_concept,
    validate_contract_payload,
    validate_learner_state,
    validate_question,
    validate_recommendation,
    validate_tutoring_request,
    validate_tutoring_response,
)
from src.integration.event_handlers import AttemptDispatchOutcome, AttemptEventDispatcher
from src.integration.knowledge_graph_adapter import KnowledgeGraphAdapter
from src.integration.pipeline import EndToEndPipelineResult, IntegratedLearningLoopPipeline
from src.integration.question_bank_adapter import QuestionBankAdapter

__all__ = [
    "AssessmentAdapter",
    "IngestedAttemptEvent",
    "KnowledgeGraphAdapter",
    "QuestionBankAdapter",
    "AttemptEventDispatcher",
    "AttemptDispatchOutcome",
    "IntegratedLearningLoopPipeline",
    "EndToEndPipelineResult",
    "ContractValidatorRegistry",
    "validate_attempt",
    "validate_concept",
    "validate_question",
    "validate_learner_state",
    "validate_recommendation",
    "validate_tutoring_request",
    "validate_tutoring_response",
    "validate_contract_payload",
]

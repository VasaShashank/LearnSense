"""
Standardized Error Types and Base Exceptions for Taproot Phase 5.
"""

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCategory(str, Enum):
    INPUT_ERROR = "INPUT_ERROR"
    EXTRACTION_ERROR = "EXTRACTION_ERROR"
    NLP_ERROR = "NLP_ERROR"
    KNOWLEDGE_GRAPH_ERROR = "KNOWLEDGE_GRAPH_ERROR"
    QUESTION_GENERATION_ERROR = "QUESTION_GENERATION_ERROR"
    QUESTION_VALIDATION_ERROR = "QUESTION_VALIDATION_ERROR"
    LEARNER_STATE_ERROR = "LEARNER_STATE_ERROR"
    KT_ERROR = "KT_ERROR"
    PLANNING_ERROR = "PLANNING_ERROR"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"


class TaprootException(Exception):
    """Base exception for all Taproot domain errors."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.INPUT_ERROR,
        recoverable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.recoverable = recoverable
        self.details = details or {}


class InputValidationError(TaprootException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.INPUT_ERROR, recoverable=False, details=details)


class ExtractionValidationError(TaprootException):
    def __init__(self, message: str, recoverable: bool = True, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.EXTRACTION_ERROR, recoverable=recoverable, details=details)


class NLPValidationError(TaprootException):
    def __init__(self, message: str, recoverable: bool = True, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.NLP_ERROR, recoverable=recoverable, details=details)


class KnowledgeGraphValidationError(TaprootException):
    def __init__(self, message: str, recoverable: bool = True, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.KNOWLEDGE_GRAPH_ERROR, recoverable=recoverable, details=details)


class QuestionValidationError(TaprootException):
    def __init__(self, message: str, recoverable: bool = True, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.QUESTION_VALIDATION_ERROR, recoverable=recoverable, details=details)


class LearnerStateValidationError(TaprootException):
    def __init__(self, message: str, recoverable: bool = False, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.LEARNER_STATE_ERROR, recoverable=recoverable, details=details)


class PlanningValidationError(TaprootException):
    def __init__(self, message: str, recoverable: bool = True, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, category=ErrorCategory.PLANNING_ERROR, recoverable=recoverable, details=details)

"""
Standardized Validation Result and Recovery Status Models for Phase 5.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    INSUFFICIENT = "INSUFFICIENT"


class RecoveryClassification(str, Enum):
    RECOVERABLE = "RECOVERABLE"
    PARTIALLY_RECOVERABLE = "PARTIALLY_RECOVERABLE"
    NON_RECOVERABLE = "NON_RECOVERABLE"


class ValidationResult(BaseModel):
    status: ValidationStatus = Field(default=ValidationStatus.VALID)
    is_valid: bool = Field(default=True)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recoverable: bool = Field(default=True)
    recovery_classification: RecoveryClassification = Field(default=RecoveryClassification.RECOVERABLE)
    suggested_action: Optional[str] = Field(default=None, description="Recommended recovery action to execute.")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_error(self, message: str, action: Optional[str] = None):
        self.errors.append(message)
        self.is_valid = False
        if self.status != ValidationStatus.INVALID:
            self.status = ValidationStatus.INVALID
        if action and not self.suggested_action:
            self.suggested_action = action

    def add_warning(self, message: str):
        self.warnings.append(message)
        if self.status == ValidationStatus.VALID:
            self.status = ValidationStatus.WARNING

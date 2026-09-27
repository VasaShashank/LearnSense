"""
Phase 5 Centralized Configuration parameters.
Contains operational thresholds, bounded retry counts, resource limits, and validation behavior flags.
"""

from pydantic import BaseModel, Field


class Phase5Config(BaseModel):
    # Retry Limits
    MAX_PDF_RETRIES: int = Field(default=2, description="Maximum retries for PDF processing/repair attempts.")
    MAX_NLP_RETRIES: int = Field(default=2, description="Maximum retries for low-confidence NLP extraction.")
    MAX_QUESTION_RETRIES: int = Field(default=3, description="Maximum retries for question generation/regeneration.")
    MAX_RECOVERY_ATTEMPTS: int = Field(default=3, description="Maximum total recovery attempts per process boundary.")

    # Validation Thresholds
    NLP_CONFIDENCE_THRESHOLD: float = Field(default=0.70, description="Minimum confidence score for NLP extracted entities.")
    MIN_USABLE_TEXT_LENGTH: int = Field(default=100, description="Minimum extracted text length (characters) for valid document content.")
    MAX_FILE_SIZE_BYTES: int = Field(default=104857600, description="Maximum allowed file size in bytes (100 MB).")
    MAX_PAGE_COUNT: int = Field(default=500, description="Maximum allowed PDF page count.")

    # Execution Mode
    VALIDATION_STRICT_MODE: bool = Field(
        default=False,
        description="If True, validation warnings/recoverable errors raise immediate exceptions (useful for testing/strict verification)."
    )


# Default global configuration instance
phase5_config = Phase5Config()

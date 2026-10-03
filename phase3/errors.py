"""
Explicit, Typed Error Model for the LearnSense learning runtime (Phase 3 / application layer).

Design rules enforced by this module:

* Every failure mode that a caller may want to *retry* carries ``recoverable=True``.
* Every error carries a machine-readable ``code`` plus structured ``details`` so the
  HTTP layer can surface an actionable retry state to the frontend.
* No error in this module ever implies that substitute educational content is acceptable.
  When an LLM-backed artifact cannot be produced, the error propagates. Inventing content
  is a bug, not a recovery strategy.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class LearnSenseError(Exception):
    """Base class for all LearnSense runtime errors."""

    code: str = "LEARNSENSE_ERROR"
    http_status: int = 500
    recoverable: bool = False

    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        recoverable: Optional[bool] = None,
        http_status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: Dict[str, Any] = details or {}
        if recoverable is not None:
            self.recoverable = recoverable
        if http_status is not None:
            self.http_status = http_status

    def to_payload(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "recoverable": self.recoverable,
                "details": self.details,
            }
        }


# ---------------------------------------------------------------------------
# Configuration / credential errors
# ---------------------------------------------------------------------------

class LLMConfigurationError(LearnSenseError):
    """No usable LLM provider is configured (missing key or missing model)."""

    code = "LLM_NOT_CONFIGURED"
    http_status = 503
    recoverable = False


class LLMInvalidAPIKeyError(LearnSenseError):
    """The configured provider rejected the API key (401/403)."""

    code = "LLM_INVALID_API_KEY"
    http_status = 502
    recoverable = False


# ---------------------------------------------------------------------------
# Transport / provider errors
# ---------------------------------------------------------------------------

class LLMTimeoutError(LearnSenseError):
    """The provider did not respond within the configured timeout."""

    code = "LLM_TIMEOUT"
    http_status = 504
    recoverable = True


class LLMRateLimitError(LearnSenseError):
    """The provider rate-limited the request (429)."""

    code = "LLM_RATE_LIMITED"
    http_status = 429
    recoverable = True


class LLMProviderError(LearnSenseError):
    """The provider returned a 5xx or otherwise unusable response."""

    code = "LLM_PROVIDER_ERROR"
    http_status = 502
    recoverable = True


class LLMUnavailableError(LearnSenseError):
    """The provider could not be reached at all (DNS, TLS, offline, ...)."""

    code = "LLM_UNAVAILABLE"
    http_status = 503
    recoverable = True


# ---------------------------------------------------------------------------
# Output-shape / semantic errors
# ---------------------------------------------------------------------------

class LLMOutputError(LearnSenseError):
    """The provider replied, but the content was not decodable / conformed to the schema."""

    code = "LLM_MALFORMED_OUTPUT"
    http_status = 502
    recoverable = True


class ContentValidationError(LearnSenseError):
    """A generated lesson failed structural or source-grounding validation."""

    code = "CONTENT_VALIDATION_FAILED"
    http_status = 422
    recoverable = True


class QuestionValidationError(LearnSenseError):
    """A generated question failed structural / semantic / grounding validation."""

    code = "QUESTION_VALIDATION_FAILED"
    http_status = 422
    recoverable = True


class RetrievalError(LearnSenseError):
    """The evidence retrieval layer could not produce grounding material."""

    code = "RETRIEVAL_FAILED"
    http_status = 503
    recoverable = True


# ---------------------------------------------------------------------------
# Ingestion errors
# ---------------------------------------------------------------------------

class IngestionError(LearnSenseError):
    """Phase 1 ingestion failed for the uploaded document."""

    code = "INGESTION_FAILED"
    http_status = 422
    recoverable = False


class UnsupportedDocumentError(LearnSenseError):
    """The uploaded file type is not supported by the ingestion pipeline."""

    code = "UNSUPPORTED_DOCUMENT"
    http_status = 415
    recoverable = False


class KnowledgeBuildError(LearnSenseError):
    """Phase 2 (EKR) failed, or produced too little knowledge to teach from."""

    code = "KNOWLEDGE_BUILD_FAILED"
    http_status = 422
    recoverable = True


class KnowledgeNotFoundError(LearnSenseError):
    """The requested document / concept has no persisted knowledge representation."""

    code = "KNOWLEDGE_NOT_FOUND"
    http_status = 404
    recoverable = False


class QuestionBankError(LearnSenseError):
    """
    A question bank could not be produced from the learner's material.

    Raised instead of substituting placeholder questions when the document has no
    passages to ground them in, or when generation produced nothing that validates.
    """

    code = "QUESTION_BANK_UNAVAILABLE"
    http_status = 422
    recoverable = True


# ---------------------------------------------------------------------------
# OCR errors (no-fallback policy: Tesseract failures must be loud)
# ---------------------------------------------------------------------------

class OCRUnavailableError(LearnSenseError):
    """Tesseract binary could not be found or executed."""

    code = "OCR_UNAVAILABLE"
    http_status = 503
    recoverable = False


class OCRLanguageMissingError(LearnSenseError):
    """A required Tesseract language data pack is not installed."""

    code = "OCR_LANGUAGE_MISSING"
    http_status = 503
    recoverable = False


class OCRImageError(LearnSenseError):
    """The image could not be decoded or processed by OCR."""

    code = "OCR_IMAGE_ERROR"
    http_status = 422
    recoverable = False


# ---------------------------------------------------------------------------
# VLM errors (no-fallback policy: VLM failures must be loud)
# ---------------------------------------------------------------------------

class VLMConfigurationError(LearnSenseError):
    """VLM provider, model, or API key is not configured when VLM_MODE requires it."""

    code = "VLM_NOT_CONFIGURED"
    http_status = 503
    recoverable = False


class VLMExtractionError(LearnSenseError):
    """VLM extraction failed for a page that was routed to VLM."""

    code = "VLM_EXTRACTION_FAILED"
    http_status = 502
    recoverable = True


# ---------------------------------------------------------------------------
# Table / Math extraction errors
# ---------------------------------------------------------------------------

class TableExtractionError(LearnSenseError):
    """Table extraction failed for a page."""

    code = "TABLE_EXTRACTION_FAILED"
    http_status = 422
    recoverable = False


class MathExtractionError(LearnSenseError):
    """Math/equation extraction failed for a page."""

    code = "MATH_EXTRACTION_FAILED"
    http_status = 422
    recoverable = False


# ---------------------------------------------------------------------------
# Tutor errors
# ---------------------------------------------------------------------------

class TutorGenerationError(LearnSenseError):
    """The LLM-backed tutor could not produce a response."""

    code = "TUTOR_GENERATION_FAILED"
    http_status = 502
    recoverable = True


class NoGroundedTutorEvidenceError(LearnSenseError):
    """
    The document contains no extractable evidence for this concept to ground tutoring.
    Enforces §2 / Issue 4: Never fabricate teaching prose when source grounding is missing.
    """

    code = "NO_GROUNDED_TUTOR_EVIDENCE"
    http_status = 422
    recoverable = False

    def __init__(
        self,
        message: str = "No extractable source evidence found for this concept.",
        *,
        subject_id: str,
        concept_id: str,
        reason: Optional[str] = None,
        evidence_status: str = "UNAVAILABLE",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        merged_details = {
            "subject_id": subject_id,
            "concept_id": concept_id,
            "reason": reason or message,
            "evidence_status": evidence_status,
        }
        if details:
            merged_details.update(details)
        super().__init__(message, details=merged_details, recoverable=False, http_status=422)
        self.subject_id = subject_id
        self.concept_id = concept_id
        self.reason = reason or message
        self.evidence_status = evidence_status


# ---------------------------------------------------------------------------
# Startup / preflight errors
# ---------------------------------------------------------------------------

class StartupPreflightError(LearnSenseError):
    """A required dependency failed startup validation."""

    code = "STARTUP_PREFLIGHT_FAILED"
    http_status = 503
    recoverable = False


# ---------------------------------------------------------------------------
# Section 39 Canonical Structured Errors
# ---------------------------------------------------------------------------

class ConfigurationError(LearnSenseError):
    """Authoritative configuration error (provider, model, or parameter missing/invalid)."""
    code = "CONFIGURATION_ERROR"
    http_status = 503
    recoverable = False


class ValidationError(LearnSenseError):
    """Generic or domain validation failure."""
    code = "VALIDATION_ERROR"
    http_status = 422
    recoverable = False


class OCRFailure(LearnSenseError):
    """OCR execution or engine failure."""
    code = "OCR_FAILURE"
    http_status = 503
    recoverable = False


class VLMFailure(LearnSenseError):
    """VLM execution or routing failure."""
    code = "VLM_FAILURE"
    http_status = 502
    recoverable = True


class ExtractionFailure(LearnSenseError):
    """Document block, text, table, or math extraction failure."""
    code = "EXTRACTION_FAILURE"
    http_status = 422
    recoverable = False


class SemanticResolutionFailure(LearnSenseError):
    """Entity resolution or canonicalization failure."""
    code = "SEMANTIC_RESOLUTION_FAILURE"
    http_status = 422
    recoverable = False


class RelationshipResolutionFailure(LearnSenseError):
    """CKG relationship extraction or verification failure."""
    code = "RELATIONSHIP_RESOLUTION_FAILURE"
    http_status = 422
    recoverable = False


class RetrievalFailure(RetrievalError):
    """Evidence retrieval failure matching Section 39."""
    code = "RETRIEVAL_FAILURE"
    http_status = 503
    recoverable = True


class LLMOutputValidationError(LLMOutputError):
    """LLM output failed schema or semantic validation."""
    code = "LLM_OUTPUT_VALIDATION_ERROR"
    http_status = 502
    recoverable = True


class GroundingValidationError(ValidationError):
    """Citation or claim failed evidence-grounding verification."""
    code = "GROUNDING_VALIDATION_ERROR"
    http_status = 422
    recoverable = False


class LearnerStateError(LearnSenseError):
    """Learner state corruption, missing concept state, or invalid transition."""
    code = "LEARNER_STATE_ERROR"
    http_status = 422
    recoverable = False


class PersistenceError(LearnSenseError):
    """Storage, database, or repository persistence failure."""
    code = "PERSISTENCE_ERROR"
    http_status = 500
    recoverable = True


class AuthorizationError(LearnSenseError):
    """Unauthorized learner or resource access attempt."""
    code = "AUTHORIZATION_ERROR"
    http_status = 403
    recoverable = False


class ConcurrencyError(LearnSenseError):
    """Concurrent submission or state mutation conflict."""
    code = "CONCURRENCY_ERROR"
    http_status = 409
    recoverable = True


class CancellationError(LearnSenseError):
    """Job, pipeline, or session cancelled upon user/system signal."""
    code = "CANCELLATION_ERROR"
    http_status = 499
    recoverable = False


__all__ = [
    "LearnSenseError",
    "LLMConfigurationError",
    "LLMInvalidAPIKeyError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMProviderError",
    "LLMUnavailableError",
    "LLMOutputError",
    "ContentValidationError",
    "QuestionValidationError",
    "RetrievalError",
    "IngestionError",
    "UnsupportedDocumentError",
    "KnowledgeBuildError",
    "KnowledgeNotFoundError",
    "QuestionBankError",
    "OCRUnavailableError",
    "OCRLanguageMissingError",
    "OCRImageError",
    "VLMConfigurationError",
    "VLMExtractionError",
    "TableExtractionError",
    "MathExtractionError",
    "TutorGenerationError",
    "NoGroundedTutorEvidenceError",
    "StartupPreflightError",
    "ConfigurationError",
    "ValidationError",
    "OCRFailure",
    "VLMFailure",
    "ExtractionFailure",
    "SemanticResolutionFailure",
    "RelationshipResolutionFailure",
    "RetrievalFailure",
    "LLMOutputValidationError",
    "GroundingValidationError",
    "LearnerStateError",
    "PersistenceError",
    "AuthorizationError",
    "ConcurrencyError",
    "CancellationError",
]


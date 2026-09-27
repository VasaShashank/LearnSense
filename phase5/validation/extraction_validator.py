"""
Structured Document Extraction Validator for Taproot Phase 5.
Validates extracted StructuredDocument objects for structural usability, total text yield, page completeness, and metadata integrity.
"""

from typing import Optional
from phase5.config.phase5_config import phase5_config
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger
from schemas.document import StructuredDocument, ProcessingStatusEnum, PageStatusEnum


class ExtractionValidator:
    """Validates StructuredDocument extraction outputs."""

    def __init__(self, min_text_length: int = phase5_config.MIN_USABLE_TEXT_LENGTH):
        self.min_text_length = min_text_length

    def validate_structured_document(self, doc: StructuredDocument) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        doc_id = doc.document_id

        # 1. Structural Checks
        if not doc.document_id or doc.document_id.strip() == "":
            result.add_error("StructuredDocument missing valid document_id.")

        if not doc.pages or len(doc.pages) == 0:
            result.add_error("StructuredDocument pages list is empty.")
            result.recoverable = True
            result.recovery_classification = RecoveryClassification.RECOVERABLE
            result.suggested_action = "Trigger OCR/alternative fallback extraction."
            ValidationEventLogger.log_event("extraction_validation_failed", "INVALID", result.errors[-1], document_id=doc_id)
            return result

        # 2. Text Yield Check
        total_text_chars = 0
        empty_page_count = 0
        failed_page_count = 0

        for page in doc.pages:
            page_text = ""
            for block in page.blocks:
                if block.content and block.content.text:
                    page_text += block.content.text.strip() + " "

            total_text_chars += len(page_text)
            if len(page_text.strip()) == 0:
                empty_page_count += 1
            if page.status == PageStatusEnum.FAILED:
                failed_page_count += 1

        result.metadata["total_text_length"] = total_text_chars
        result.metadata["page_count"] = len(doc.pages)
        result.metadata["empty_pages"] = empty_page_count
        result.metadata["failed_pages"] = failed_page_count

        # 3. Yield Evaluation
        if total_text_chars == 0:
            result.add_error("Extracted document contains zero usable text.", action="Trigger OCR fallback processing.")
            result.recoverable = True
            result.recovery_classification = RecoveryClassification.RECOVERABLE
        elif total_text_chars < self.min_text_length:
            result.add_warning(
                f"Abnormally low total text yield ({total_text_chars} chars < threshold {self.min_text_length})."
            )
            result.suggested_action = "Consider OCR or alternative extraction pass."
            result.status = ValidationStatus.WARNING

        if empty_page_count > 0 and empty_page_count < len(doc.pages):
            result.add_warning(f"Document contains {empty_page_count} empty or unparseable page(s).")

        if failed_page_count > 0:
            result.add_warning(f"{failed_page_count} page(s) failed during extraction pass.")

        if result.is_valid:
            ValidationEventLogger.log_event(
                "extraction_validation_passed",
                result.status.value,
                f"Document '{doc_id}' passed extraction validation (yield={total_text_chars} chars).",
                document_id=doc_id,
            )
        else:
            ValidationEventLogger.log_event(
                "extraction_validation_failed",
                "INVALID",
                f"Document '{doc_id}' failed extraction validation.",
                document_id=doc_id,
            )

        return result

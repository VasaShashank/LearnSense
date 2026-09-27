"""
Document Input Validator for Taproot Phase 5.
Validates file type, size, magic header, page limits, and corrupt/empty files prior to ingestion.
"""

from typing import Optional
import pymupdf as fitz
from phase5.config.phase5_config import phase5_config
from phase5.errors.error_types import InputValidationError
from phase5.models.validation_result import RecoveryClassification, ValidationResult, ValidationStatus
from phase5.observability.validation_events import ValidationEventLogger


class InputValidator:
    """Validates raw incoming file uploads prior to resource-intensive processing."""

    def __init__(
        self,
        max_file_size_bytes: int = phase5_config.MAX_FILE_SIZE_BYTES,
        max_page_count: int = phase5_config.MAX_PAGE_COUNT,
    ):
        self.max_file_size_bytes = max_file_size_bytes
        self.max_page_count = max_page_count

    def validate_file(self, content: bytes, filename: str) -> ValidationResult:
        result = ValidationResult(status=ValidationStatus.VALID, is_valid=True)
        size_bytes = len(content)

        # 1. File type extension check
        if not filename.lower().endswith(".pdf"):
            result.add_error(f"Unsupported file type for filename '{filename}'. Only PDF files are supported.")
            result.recoverable = False
            result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
            ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
            return result

        # 2. File size check
        if size_bytes > self.max_file_size_bytes:
            result.add_error(f"File size ({size_bytes} bytes) exceeds configured limit of {self.max_file_size_bytes} bytes.")
            result.recoverable = False
            result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
            ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
            return result

        if size_bytes < 10:
            result.add_error("Uploaded file is empty or corrupted (file size too small).")
            result.recoverable = False
            result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
            ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
            return result

        # 3. PDF Magic Header Check (%PDF-)
        if not content.startswith(b"%PDF-"):
            offset = content.find(b"%PDF-")
            if offset == -1:
                result.add_error("Missing PDF magic header '%PDF-'. File is not a valid PDF.")
                result.recoverable = False
                result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
                ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
                return result

        # 4. PyMuPDF Readability & Password Check
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            if doc.is_encrypted and doc.needs_pass:
                doc.close()
                result.add_error("PDF is password-protected and requires a password to decrypt.")
                result.recoverable = False
                result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
                ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
                return result

            page_count = len(doc)
            doc.close()

            if page_count == 0:
                result.add_error("PDF document contains zero pages.")
                result.recoverable = False
                result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
                ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
                return result

            if page_count > self.max_page_count:
                result.add_error(f"Document page count ({page_count}) exceeds limit of {self.max_page_count} pages.")
                result.recoverable = False
                result.recovery_classification = RecoveryClassification.NON_RECOVERABLE
                ValidationEventLogger.log_event("input_validation_failed", "INVALID", result.errors[-1])
                return result

            result.metadata["page_count"] = page_count
            result.metadata["size_bytes"] = size_bytes

        except Exception as e:
            result.add_error(f"Failed to parse PDF document structure: {str(e)}", action="Attempt PDF repair.")
            result.recoverable = True
            result.recovery_classification = RecoveryClassification.RECOVERABLE
            ValidationEventLogger.log_event("input_validation_failed", "RECOVERABLE", result.errors[-1])
            return result

        ValidationEventLogger.log_event("input_validation_passed", "VALID", f"PDF '{filename}' passed input validation.")
        return result

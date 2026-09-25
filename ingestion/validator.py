"""
PDF Validation and Automatic Repair Engine for Taproot Phase 1.
Handles file integrity, size/page limits, PyMuPDF load checks, automatic xref repair, and password protection policies.
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import fitz  # PyMuPDF


class ValidationResult:
    def __init__(
        self,
        is_valid: bool,
        status: str,  # "VALID", "REPAIRED", "ENCRYPTED", "CORRUPTED", "UNSUPPORTED"
        message: str,
        page_count: int = 0,
        repaired_pdf_bytes: Optional[bytes] = None,
        warnings: Optional[list] = None,
    ):
        self.is_valid = is_valid
        self.status = status
        self.message = message
        self.page_count = page_count
        self.repaired_pdf_bytes = repaired_pdf_bytes
        self.warnings = warnings or []


class PDFValidator:
    def __init__(
        self,
        max_file_size_bytes: int = 104857600,  # 100 MB
        max_page_count: int = 500,
    ):
        self.max_file_size_bytes = max_file_size_bytes
        self.max_page_count = max_page_count

    def validate_and_repair(self, pdf_bytes: bytes, filename: str = "source.pdf") -> ValidationResult:
        size_bytes = len(pdf_bytes)

        # 1. File Size Check
        if size_bytes > self.max_file_size_bytes:
            return ValidationResult(
                is_valid=False,
                status="UNSUPPORTED",
                message=f"File size ({size_bytes} bytes) exceeds limit of {self.max_file_size_bytes} bytes",
            )

        if size_bytes < 5:
            return ValidationResult(
                is_valid=False,
                status="CORRUPTED",
                message="File is empty or too small to be a valid PDF",
            )

        # 2. Magic Bytes Check (%PDF-)
        if not pdf_bytes.startswith(b"%PDF-"):
            # Check if header is slightly offset
            offset = pdf_bytes.find(b"%PDF-")
            if offset == -1:
                return ValidationResult(
                    is_valid=False,
                    status="CORRUPTED",
                    message="Missing PDF magic header '%PDF-'",
                )

        # 3. PyMuPDF Load & Inspection
        warnings = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            # Attempt automatic PyMuPDF / fitz repair
            repaired_result = self._attempt_repair(pdf_bytes)
            if repaired_result:
                return repaired_result
            return ValidationResult(
                is_valid=False,
                status="CORRUPTED",
                message=f"Failed to open PDF document: {str(e)}",
            )

        # 4. Password Protection Check
        if doc.is_encrypted:
            if doc.needs_pass:
                # User password required to open
                doc.close()
                return ValidationResult(
                    is_valid=False,
                    status="ENCRYPTED",
                    message="PDF is password-protected and requires a user password to decrypt",
                )
            else:
                # Owner password only; content freely readable
                warnings.append({
                    "code": "OWNER_PASSWORD_RESTRICTED",
                    "severity": "info",
                    "message": "PDF has owner password restriction flags set, but content is open and readable.",
                })

        # 5. Page Count Check
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return ValidationResult(
                is_valid=False,
                status="CORRUPTED",
                message="PDF document contains zero pages",
            )

        if page_count > self.max_page_count:
            doc.close()
            return ValidationResult(
                is_valid=False,
                status="UNSUPPORTED",
                message=f"Document page count ({page_count}) exceeds limit of {self.max_page_count} pages",
            )

        # Check if xref or trailer issues were detected internally by PyMuPDF
        is_repaired = False
        repaired_bytes = None
        if doc.is_repaired:
            is_repaired = True
            warnings.append({
                "code": "REPAIRED_PDF",
                "severity": "medium",
                "message": "PDF had damaged cross-reference table or trailer and was automatically repaired.",
            })
            repaired_bytes = doc.write(clean=True, deflate=True, garbage=3)

        doc.close()

        status = "REPAIRED" if is_repaired else "VALID"
        return ValidationResult(
            is_valid=True,
            status=status,
            message="PDF validation successful",
            page_count=page_count,
            repaired_pdf_bytes=repaired_bytes,
            warnings=warnings,
        )

    def _attempt_repair(self, pdf_bytes: bytes) -> Optional[ValidationResult]:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = len(doc)
            if page_count > 0:
                repaired_bytes = doc.write(clean=True, deflate=True, garbage=3)
                doc.close()
                return ValidationResult(
                    is_valid=True,
                    status="REPAIRED",
                    message="PDF automatically repaired after load error",
                    page_count=page_count,
                    repaired_pdf_bytes=repaired_bytes,
                    warnings=[{
                        "code": "REPAIRED_PDF",
                        "severity": "medium",
                        "message": "Damaged PDF structure successfully repaired.",
                    }],
                )
        except Exception:
            pass
        return None

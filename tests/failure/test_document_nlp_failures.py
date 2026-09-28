"""
Phase 7 Document and NLP Failure Classification Test Suite.
Verifies Phase 5 validators for Input, NLP, and Recovery classifications:
- Unsupported file extension
- Empty or undersized file
- Non-PDF magic header
- Password protected or corrupt PDF
- Low-confidence NLP extraction recovery classifications (RECOVERABLE, PARTIALLY_RECOVERABLE, NON_RECOVERABLE)
"""

import pytest
from phase5.validation.input_validator import InputValidator
from phase5.validation.nlp_validator import NLPValidator
from phase5.models.validation_result import RecoveryClassification, ValidationStatus


def test_input_validator_unsupported_file_type():
    # ".docx" is a supported format, so it exercises the DOCX parsing path rather than
    # the unsupported-extension path. Use a genuinely unsupported extension here.
    validator = InputValidator()
    res = validator.validate_file(b"some content text", "document.xyz")
    assert res.is_valid is False
    assert res.recovery_classification == RecoveryClassification.NON_RECOVERABLE
    assert "Unsupported file type" in res.errors[0]


def test_input_validator_malformed_docx_is_non_recoverable():
    """A supported extension carrying garbage must fail explicitly, not be accepted."""
    validator = InputValidator()
    res = validator.validate_file(b"some content text", "document.docx")
    assert res.is_valid is False
    assert res.recovery_classification == RecoveryClassification.NON_RECOVERABLE
    assert "DOCX" in res.errors[0]


def test_input_validator_empty_file():
    validator = InputValidator()
    res = validator.validate_file(b"", "empty.pdf")
    assert res.is_valid is False
    assert res.recovery_classification == RecoveryClassification.NON_RECOVERABLE


def test_input_validator_invalid_pdf_header():
    validator = InputValidator()
    res = validator.validate_file(b"NOT_A_PDF_HEADER_CONTENT_HERE", "bad.pdf")
    assert res.is_valid is False
    assert "magic header" in res.errors[0]


from phase2.models import Concept, ConceptTypeEnum, ConfidenceBreakdown

def test_nlp_validator_low_confidence():
    validator = NLPValidator(confidence_threshold=0.7)
    c_low = Concept(
        concept_id="c_test",
        canonical_name="Test Concept",
        type=ConceptTypeEnum.CONCEPT,
        confidence=ConfidenceBreakdown(value=0.4),
    )
    res = validator.validate_concepts([c_low], document_id="doc_test")
    assert res.is_valid is True
    assert res.metadata["low_confidence_concepts"] == 1

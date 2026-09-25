"""
Unit tests for Phase 1A Core Modules: Validator, Inspector, Coordinate Normalizer, and Native Text Extractor.
"""

import fitz  # PyMuPDF
import pytest
from extraction.text import NativeTextExtractor
from ingestion.coordinate import CoordinateNormalizer
from ingestion.inspector import PageInspector
from ingestion.validator import PDFValidator


@pytest.fixture
def sample_pdf_bytes():
    """Generates a simple 2-page native PDF in memory for testing."""
    doc = fitz.open()
    # Page 1: Native text
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 100), "Newton's First Law of Motion", fontsize=18)
    page1.insert_text(
        (50, 150),
        "An object at rest remains at rest unless acted upon by an external force.",
        fontsize=12,
    )
    page1.insert_text((50, 180), "ac-\nceleration is zero.", fontsize=12)

    # Page 2: Blank / near blank
    doc.new_page(width=595, height=842)

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def test_pdf_validator(sample_pdf_bytes):
    validator = PDFValidator(max_file_size_bytes=10 * 1024 * 1024, max_page_count=10)

    # Test valid PDF
    res = validator.validate_and_repair(sample_pdf_bytes)
    assert res.is_valid is True
    assert res.status in ("VALID", "REPAIRED")
    assert res.page_count == 2

    # Test invalid magic bytes
    bad_res = validator.validate_and_repair(b"NOT_A_PDF_STREAM")
    assert bad_res.is_valid is False
    assert bad_res.status == "CORRUPTED"


def test_coordinate_normalizer():
    # Top-Left points normalizer
    bbox = [10.0, 20.0, 100.0, 200.0]
    norm = CoordinateNormalizer.normalize_bbox(
        bbox, page_width=595.0, page_height=842.0, rotation=0, source_origin="top-left"
    )
    assert norm == [10.0, 20.0, 100.0, 200.0]

    # Bottom-Left PDF origin conversion
    bottom_left_bbox = [10.0, 100.0, 100.0, 200.0]
    norm_flips = CoordinateNormalizer.normalize_bbox(
        bottom_left_bbox, page_width=595.0, page_height=842.0, rotation=0, source_origin="bottom-left"
    )
    # y0 = 842 - 200 = 642, y1 = 842 - 100 = 742
    assert norm_flips == [10.0, 642.0, 100.0, 742.0]


def test_page_inspector(sample_pdf_bytes):
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    inspector = PageInspector()

    # Page 1 inspection
    metrics1 = inspector.inspect_page(doc[0], page_index=0)
    assert metrics1.page_type == "native"
    assert metrics1.char_count > 50
    assert metrics1.orientation == "portrait"
    assert metrics1.preview_png_bytes is not None

    # Page 2 inspection (blank page)
    metrics2 = inspector.inspect_page(doc[1], page_index=1)
    assert metrics2.page_type == "blank"
    assert metrics2.char_count == 0

    doc.close()


def test_native_text_extractor(sample_pdf_bytes):
    doc = fitz.open(stream=sample_pdf_bytes, filetype="pdf")
    extractor = NativeTextExtractor()

    blocks = extractor.extract_page_blocks(doc[0], page_width=595.0, page_height=842.0)
    assert len(blocks) >= 1

    extracted_text = " ".join([b.content.text for b in blocks])
    assert "Newton's First Law" in extracted_text
    # Check line hyphenation rejoining ('ac-\nceleration' -> 'acceleration')
    assert "acceleration" in extracted_text

    # Ligature test
    norm_lig = extractor.normalize_text("ﬁrst ﬂow")
    assert norm_lig == "first flow"

    doc.close()

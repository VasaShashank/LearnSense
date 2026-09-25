"""
Unit tests for StructuredDocument Pydantic V2 Schema.
"""

import pytest
from pydantic import ValidationError
from schemas.document import (
    BlockContent,
    BlockTypeEnum,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    DocumentWarning,
    ExtractionMethodEnum,
    PageTypeEnum,
    ProcessingStatusEnum,
    SourceMetadata,
    StructuredDocument,
    TitleMetadata,
    WarningCodeEnum,
    WarningSeverityEnum,
)


def test_valid_structured_document_creation():
    doc = StructuredDocument(
        document_id="doc_test_123",
        source=SourceMetadata(
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            filename="physics.pdf",
            size_bytes=1024,
        ),
        metadata=DocumentMetadata(
            page_count=1,
            title=TitleMetadata(value="Physics Notes"),
            processing_status=ProcessingStatusEnum.COMPLETED,
        ),
        pages=[
            DocumentPage(
                page_index=0,
                page_label="1",
                width=595.0,
                height=842.0,
                page_type=PageTypeEnum.NATIVE,
                blocks=[
                    DocumentBlock(
                        block_id="blk_0001",
                        type=BlockTypeEnum.HEADING,
                        role="body",
                        bbox=[50.0, 50.0, 500.0, 80.0],
                        content=BlockContent(text="Newton's First Law", text_raw="Newton's First Law"),
                        reading_order=1,
                        extraction_method=ExtractionMethodEnum.NATIVE,
                    )
                ],
            )
        ],
        warnings=[
            DocumentWarning(
                code=WarningCodeEnum.LOW_OCR_CONFIDENCE,
                severity=WarningSeverityEnum.LOW,
                message="Low confidence on page 1 header",
            )
        ],
    )

    assert doc.document_id == "doc_test_123"
    assert doc.schema_version == "1.0.0"
    assert len(doc.pages) == 1
    assert doc.pages[0].blocks[0].content.text == "Newton's First Law"
    assert doc.warnings[0].code == WarningCodeEnum.LOW_OCR_CONFIDENCE


def test_invalid_bbox_length():
    with pytest.raises(ValidationError):
        DocumentBlock(
            block_id="blk_bad",
            type=BlockTypeEnum.PARAGRAPH,
            role="body",
            bbox=[10.0, 20.0, 30.0],  # Invalid: only 3 elements
            content=BlockContent(text="test", text_raw="test"),
            reading_order=1,
            extraction_method=ExtractionMethodEnum.NATIVE,
        )

"""
Integration Test Suite verifying Phase 1A Definition of Done criteria.
Tests end-to-end ingestion pipeline execution on single-column, multi-column, multi-page, and blank digital PDFs.
"""

import os
import shutil
import tempfile
import fitz  # PyMuPDF
import pytest
from ingestion.pipeline import IngestionPipeline
from schemas.document import BlockTypeEnum, ProcessingStatusEnum, StructuredDocument
from storage.db import DatabaseManager
from storage.store import DocumentStorage


@pytest.fixture
def temp_pipeline_env():
    temp_dir = tempfile.mkdtemp()
    store_dir = os.path.join(temp_dir, "documents")
    db_path = os.path.join(temp_dir, "test.db")

    storage = DocumentStorage(root_dir=store_dir)
    db = DatabaseManager(db_path=db_path)
    pipeline = IngestionPipeline(storage=storage, db=db)

    yield pipeline, storage, db, temp_dir
    shutil.rmtree(temp_dir)


def create_sample_digital_pdf_bytes() -> bytes:
    """Creates a 3-page digital PDF with headings, multi-column text, running headers/footers, and page numbers."""
    doc = fitz.open()

    # Page 1: Chapter 1 & Heading
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 40), "RVCE Physics Course Notes", fontsize=9)  # Running Header
    page1.insert_text((50, 100), "Chapter 1: Kinematics", fontsize=22)  # H1 Heading
    page1.insert_text((50, 140), "1.1 Velocity and Acceleration", fontsize=16)  # H2 Heading
    page1.insert_text(
        (50, 180),
        "Kinematics is the subfield of physics that describes the motion of points, bodies, and systems.",
        fontsize=11,
    )
    page1.insert_text((50, 210), "1. First law of motion", fontsize=11)  # List item
    page1.insert_text((50, 800), "1", fontsize=10)  # Page Number

    # Page 2: Continuation & 2-column content
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 40), "RVCE Physics Course Notes", fontsize=9)  # Running Header
    page2.insert_text((50, 100), "1.2 Dynamics", fontsize=16)  # H2 Heading
    # Left Column
    page2.insert_text((50, 140), "Dynamics studies forces and their effect on motion.", fontsize=11)
    # Right Column
    page2.insert_text((320, 140), "Force is a vector quantity having magnitude and direction.", fontsize=11)
    page2.insert_text((50, 800), "2", fontsize=10)  # Page Number

    # Page 3: Blank page
    doc.new_page(width=595, height=842)

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def test_phase_1a_definition_of_done(temp_pipeline_env):
    pipeline, storage, db, temp_dir = temp_pipeline_env
    pdf_bytes = create_sample_digital_pdf_bytes()

    # Process PDF through end-to-end Phase 1A pipeline
    structured_doc = pipeline.process_pdf_bytes(
        pdf_bytes=pdf_bytes,
        filename="rvce_physics_notes.pdf",
    )

    # 1. Every valid test PDF receives a structured output matching schema
    assert isinstance(structured_doc, StructuredDocument)
    assert structured_doc.metadata.page_count == 3
    assert structured_doc.metadata.processing_status in (
        ProcessingStatusEnum.COMPLETED,
        ProcessingStatusEnum.COMPLETED_WITH_WARNINGS,
    )

    # 2. Reading order is verified correct & physical page_index vs printed page_label are preserved
    pages = structured_doc.pages
    assert len(pages) == 3

    p1 = pages[0]
    assert p1.page_index == 0
    assert p1.page_label == "1"
    assert len(p1.blocks) >= 2

    # Check reading_order indices are strictly 1-based sequential integers
    p1_orders = [b.reading_order for b in p1.blocks]
    assert p1_orders == list(range(1, len(p1.blocks) + 1))

    # 3. Headings, paragraphs, and lists are structurally distinguishable
    block_types = [b.type for b in p1.blocks]
    assert BlockTypeEnum.HEADING in block_types
    assert BlockTypeEnum.PARAGRAPH in block_types
    assert BlockTypeEnum.LIST_ITEM in block_types

    # 4. Repeated headers, footers, and page numbers do not pollute main text flow (tagged with role/type)
    p2 = pages[1]
    header_blocks = [b for b in p2.blocks if b.type == BlockTypeEnum.HEADER or b.role == "header"]
    assert len(header_blocks) >= 1
    assert "RVCE Physics Course Notes" in header_blocks[0].content.text

    # 5. Section tree outline is generated for the document
    outline = structured_doc.outline
    assert len(outline) >= 1
    assert outline[0].title == "Chapter 1: Kinematics"
    assert len(outline[0].children) >= 1
    assert outline[0].children[0].title == "1.1 Velocity and Acceleration"

    # 6. Blank page correctly classified
    p3 = pages[2]
    assert p3.page_type.value == "blank"
    assert p3.status.value == "empty"

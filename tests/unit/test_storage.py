"""
Unit tests for DocumentStorage and DatabaseManager.
"""

import os
import shutil
import tempfile
import pytest
from storage.db import DatabaseManager
from storage.store import DocumentStorage


@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    store_dir = os.path.join(temp_dir, "documents")
    db_path = os.path.join(temp_dir, "test.db")
    storage = DocumentStorage(root_dir=store_dir)
    db = DatabaseManager(db_path=db_path)
    yield storage, db, temp_dir
    shutil.rmtree(temp_dir)


def test_storage_operations(temp_env):
    storage, db, temp_dir = temp_env
    doc_id = "test_doc_001"

    # Save PDF
    pdf_bytes = b"%PDF-1.4 test pdf content"
    saved_pdf_path = storage.save_original_pdf(doc_id, pdf_bytes)
    assert saved_pdf_path.exists()
    assert saved_pdf_path.read_bytes() == pdf_bytes

    # Save intermediate page
    page_data = {"page_index": 0, "blocks": [{"id": "b1"}]}
    inter_path = storage.save_intermediate_page(doc_id, 0, page_data)
    assert inter_path.exists()

    loaded_page = storage.load_intermediate_page(doc_id, 0)
    assert loaded_page["page_index"] == 0
    assert loaded_page["blocks"][0]["id"] == "b1"


def test_db_operations(temp_env):
    storage, db, temp_dir = temp_env
    doc_id = "test_doc_002"
    sha = DocumentStorage.compute_sha256(b"content")

    # Create job
    job = db.create_document_job(
        document_id=doc_id,
        sha256=sha,
        filename="notes.pdf",
        size_bytes=100,
        cache_key="ckey_123",
        status="queued",
    )
    assert job["document_id"] == doc_id
    assert job["status"] == "queued"

    # Update status
    db.update_document_status(doc_id, "completed", page_count=5, processed_pages=5)
    updated_job = db.get_document_job(doc_id)
    assert updated_job["status"] == "completed"
    assert updated_job["page_count"] == 5

    # Find cached
    cached = db.find_cached_document("ckey_123")
    assert cached is not None
    assert cached["document_id"] == doc_id

    # Add warning and page state
    db.set_page_state(doc_id, 0, "1", "native", "ok")
    db.add_warning(doc_id, "LOW_OCR_CONFIDENCE", "low", "Low confidence on header")

    page_states = db.get_page_states(doc_id)
    assert len(page_states) == 1
    assert page_states[0]["page_label"] == "1"

    warnings = db.get_warnings(doc_id)
    assert len(warnings) == 1
    assert warnings[0]["code"] == "LOW_OCR_CONFIDENCE"

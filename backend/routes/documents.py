"""
Document Ingestion REST API Router Endpoints for Taproot Phase 1.
Implements POST /documents, GET /documents/{id}, GET /documents/{id}/status,
GET /documents/{id}/structured, GET /documents/{id}/pages/{page},
GET /documents/{id}/assets/{asset}, POST /documents/{id}/reprocess, POST /documents/{id}/cancel.
Matches Section 26 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from ingestion.pipeline import IngestionPipeline
from storage.db import DatabaseManager
from storage.store import DocumentStorage
from phase5.validation.input_validator import InputValidator

router = APIRouter()
pipeline = IngestionPipeline()
storage = DocumentStorage()
db = DatabaseManager()
input_validator = InputValidator()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(file: UploadFile = File(...)):
    """Upload PDF document for Phase 1 ingestion."""
    content = await file.read()

    val_res = input_validator.validate_file(content, file.filename)
    if not val_res.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=val_res.errors[0] if val_res.errors else "Document validation failed.",
        )

    sha256 = DocumentStorage.compute_sha256(content)
    doc_id = f"doc_{sha256[:12]}"

    # Exact-hash caching lookup
    cached_job = db.find_cached_document(cache_key=sha256)
    if cached_job:
        return {
            "document_id": cached_job["document_id"],
            "status": cached_job["status"],
            "cached": True,
            "message": "Document content matched exact cache key.",
        }

    # Execute processing job
    try:
        structured_doc = pipeline.process_pdf_bytes(pdf_bytes=content, filename=file.filename, document_id=doc_id)
        return {
            "document_id": doc_id,
            "status": structured_doc.metadata.processing_status.value,
            "created_at": db.get_document_job(doc_id).get("created_at"),
            "page_count": structured_doc.metadata.page_count,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{document_id}")
async def get_document_info(document_id: str):
    """Fetch high-level document metadata and processing status."""
    job = db.get_document_job(document_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document ID not found.")

    warnings = db.get_warnings(document_id)
    return {
        "document_id": job["document_id"],
        "filename": job["filename"],
        "status": job["status"],
        "page_count": job["page_count"],
        "processed_pages": job["processed_pages"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "warnings_count": len(warnings),
    }


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    """Lightweight endpoint for polling document extraction progress."""
    job = db.get_document_job(document_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document ID not found.")

    return {
        "document_id": job["document_id"],
        "status": job["status"],
        "processed_pages": job["processed_pages"],
        "total_pages": job["page_count"],
    }


@router.get("/{document_id}/structured")
async def get_structured_document(document_id: str):
    """Fetch complete canonical StructuredDocument JSON."""
    doc_json = storage.load_structured_document(document_id)
    if not doc_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Structured document not found or processing incomplete.",
        )
    return doc_json


@router.get("/{document_id}/pages/{page_index}")
async def get_document_page(document_id: str, page_index: int):
    """Fetch extracted structured page payload for a single page."""
    doc_json = storage.load_structured_document(document_id)
    if not doc_json:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Structured document not found.")

    pages = doc_json.get("pages", [])
    if page_index < 0 or page_index >= len(pages):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page index out of bounds.")

    return pages[page_index]


@router.get("/{document_id}/assets/{asset_filename}")
async def get_document_asset(document_id: str, asset_filename: str):
    """Download extracted binary image asset PNG."""
    asset_path = storage.get_document_dir(document_id) / "assets" / asset_filename
    if not asset_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found.")

    return FileResponse(asset_path, media_type="image/png")


@router.post("/{document_id}/cancel")
async def cancel_document_job(document_id: str):
    """Cancel an active processing job."""
    job = db.get_document_job(document_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document ID not found.")

    db.update_document_status(document_id, "cancelled")
    return {"document_id": document_id, "status": "cancelled"}

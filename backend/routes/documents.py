"""
Document Ingestion REST API Router Endpoints for Taproot Phase 1.
Implements POST /documents, GET /documents/{id}, GET /documents/{id}/status,
GET /documents/{id}/structured, GET /documents/{id}/pages/{page},
GET /documents/{id}/assets/{asset}, POST /documents/{id}/reprocess, POST /documents/{id}/cancel.
Matches Section 26 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from ingestion.pipeline import IngestionPipeline
from storage.db import DatabaseManager
from storage.document_ownership import DocumentOwnershipRepository
from storage.document_shares import DocumentShareRepository
from storage.store import DocumentStorage
from phase5.validation.input_validator import InputValidator
from backend.auth import AuthenticatedUser, get_current_user
from backend.services.document_access import DocumentAccessService
from backend.services.institution_service import InstitutionService

router = APIRouter()
pipeline = IngestionPipeline()
storage = DocumentStorage()
db = DatabaseManager()
input_validator = InputValidator()
ownership = DocumentOwnershipRepository()
shares = DocumentShareRepository()
document_access = DocumentAccessService(
    ownership=ownership,
    shares=shares,
    institutions=InstitutionService(),
)


def _require_document_access(document_id: str, user: AuthenticatedUser) -> None:
    """Require uploader ownership or active class enrollment with an explicit grant."""
    owner_id = ownership.get_owner(document_id)
    if owner_id is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    job = db.get_document_job(document_id)
    if job is not None and job.get("owner_id") != owner_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    if user.id != owner_id and not document_access.can_read(document_id, user.id):
        raise HTTPException(status_code=404, detail="Document not found.")


def _require_document_owner(document_id: str, user: AuthenticatedUser) -> None:
    """Mutating upload operations remain limited to the verified uploader."""
    owner_id = ownership.get_owner(document_id)
    if owner_id is None or owner_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    job = db.get_document_job(document_id)
    if job is not None and job.get("owner_id") != owner_id:
        raise HTTPException(status_code=404, detail="Document not found.")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Upload PDF document for Phase 1 ingestion."""
    content = await file.read()

    val_res = input_validator.validate_file(content, file.filename)
    if not val_res.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=val_res.errors[0] if val_res.errors else "Document validation failed.",
        )

    sha256 = DocumentStorage.compute_sha256(content)
    cache_key = pipeline.owner_scoped_cache_key(user.id, sha256)

    # Cache lookup is scoped by the verified owner. Confirm both persisted owner
    # records before returning even cache metadata to the caller.
    cached_job = db.find_cached_document(cache_key=cache_key, owner_id=user.id)
    if cached_job:
        _require_document_owner(cached_job["document_id"], user)
        if cached_job.get("owner_id") != user.id:
            raise HTTPException(status_code=404, detail="Document not found.")
        return {
            "document_id": cached_job["document_id"],
            "status": cached_job["status"],
            "cached": True,
            "message": "Document content matched exact cache key.",
        }

    # Execute processing job
    try:
        doc_id = f"doc_{uuid.uuid4().hex}"
        ownership.claim(doc_id, user.id)
        structured_doc = pipeline.process_pdf_bytes(
            pdf_bytes=content, filename=file.filename, document_id=doc_id,
            owner_id=user.id,
        )
        return {
            "document_id": doc_id,
            "status": structured_doc.metadata.processing_status.value,
            "created_at": db.get_document_job(doc_id).get("created_at"),
            "page_count": structured_doc.metadata.page_count,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{document_id}")
async def get_document_info(
    document_id: str, user: AuthenticatedUser = Depends(get_current_user)
):
    """Fetch high-level document metadata and processing status."""
    _require_document_access(document_id, user)
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
async def get_document_status(
    document_id: str, user: AuthenticatedUser = Depends(get_current_user)
):
    """Lightweight endpoint for polling document extraction progress."""
    _require_document_access(document_id, user)
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
async def get_structured_document(
    document_id: str, user: AuthenticatedUser = Depends(get_current_user)
):
    """Fetch complete canonical StructuredDocument JSON."""
    _require_document_access(document_id, user)
    doc_json = storage.load_structured_document(document_id)
    if not doc_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Structured document not found or processing incomplete.",
        )
    return doc_json


@router.get("/{document_id}/pages/{page_index}")
async def get_document_page(
    document_id: str, page_index: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Fetch extracted structured page payload for a single page."""
    _require_document_access(document_id, user)
    doc_json = storage.load_structured_document(document_id)
    if not doc_json:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Structured document not found.")

    pages = doc_json.get("pages", [])
    if page_index < 0 or page_index >= len(pages):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page index out of bounds.")

    return pages[page_index]


@router.get("/{document_id}/assets/{asset_filename}")
async def get_document_asset(
    document_id: str, asset_filename: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Download extracted binary image asset PNG."""
    _require_document_access(document_id, user)
    asset_root = (storage.get_document_dir(document_id) / "assets").resolve()
    asset_path = (asset_root / asset_filename).resolve()
    if Path(asset_filename).name != asset_filename or not asset_path.is_relative_to(asset_root):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found.")
    if not asset_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found.")

    return FileResponse(asset_path, media_type="image/png")


@router.post("/{document_id}/cancel")
async def cancel_document_job(
    document_id: str, user: AuthenticatedUser = Depends(get_current_user)
):
    """Cancel an active processing job."""
    _require_document_owner(document_id, user)
    job = db.get_document_job(document_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document ID not found.")

    db.update_document_status(document_id, "cancelled")
    return {"document_id": document_id, "status": "cancelled"}

"""
Source Service Facade for Taproot Application Layer.
Manages source document ingestion, extraction inspection, page assets, and Phase 5 error/recovery states.
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from storage.store import DocumentStorage
from phase5.config.phase5_config import Phase5Config


class SourceService:
    def __init__(self, doc_storage: Optional[DocumentStorage] = None):
        self.doc_storage = doc_storage or DocumentStorage()
        self.p5_config = Phase5Config()

    def list_sources(self) -> List[Dict[str, Any]]:
        """
        Lists stored documents with metadata, page counts, and Phase 5 ingestion status.
        """
        sources = []
        root_dir = self.doc_storage.root_dir
        if root_dir.exists():
            for doc_dir in root_dir.iterdir():
                if doc_dir.is_dir():
                    doc_id = doc_dir.name
                    struct_doc = self.doc_storage.load_structured_document(doc_id)
                    pdf_path = self.doc_storage.get_original_pdf_path(doc_id)

                    status = "READY"
                    recovery_state = "COMPLETED"
                    page_count = 0

                    if struct_doc and "pages" in struct_doc:
                        page_count = len(struct_doc["pages"])
                    elif pdf_path.exists():
                        status = "PROCESSING"
                        recovery_state = "RECOVERING"
                    else:
                        status = "PARTIAL"
                        recovery_state = "PARTIAL_RECOVERY"

                    title = doc_id.replace("_", " ").title()
                    if struct_doc and "metadata" in struct_doc and struct_doc["metadata"].get("title"):
                        title = struct_doc["metadata"]["title"]

                    sources.append({
                        "document_id": doc_id,
                        "title": title,
                        "status": status,
                        "recovery_state": recovery_state,
                        "page_count": page_count,
                        "file_size_bytes": pdf_path.stat().st_size if pdf_path.exists() else 0,
                    })

        # Provide standard demonstration sources if empty
        if not sources:
            sources = [
                {
                    "document_id": "calculus_101",
                    "title": "Calculus: Early Transcendentals (Textbook)",
                    "status": "READY",
                    "recovery_state": "COMPLETED",
                    "page_count": 42,
                    "file_size_bytes": 10485760,
                },
                {
                    "document_id": "machine_learning",
                    "title": "Introduction to Statistical Machine Learning",
                    "status": "READY",
                    "recovery_state": "COMPLETED",
                    "page_count": 58,
                    "file_size_bytes": 15728640,
                }
            ]
        return sources

    def save_uploaded_source(self, document_id: str, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """
        Saves PDF and checks Phase 5 size limits.
        """
        if len(file_bytes) > self.p5_config.MAX_PDF_FILE_SIZE_BYTES:
            raise ValueError(f"File size exceeds maximum allowed limit of {self.p5_config.MAX_PDF_FILE_SIZE_MB}MB.")

        saved_path = self.doc_storage.save_original_pdf(document_id, file_bytes)
        return {
            "document_id": document_id,
            "filename": filename,
            "status": "PROCESSING",
            "recovery_state": "INITIALIZING",
            "saved_path": str(saved_path),
        }

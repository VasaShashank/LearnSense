"""
Content-Addressed Filesystem Storage Manager for Taproot Phase 1.
Manages original PDFs, page previews, intermediate page outputs, assets, and structured documents.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Union
from schemas.document import StructuredDocument


class DocumentStorage:
    def __init__(self, root_dir: str = "storage/documents"):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def get_document_dir(self, document_id: str) -> Path:
        doc_dir = self.root_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def initialize_document_structure(self, document_id: str) -> Dict[str, Path]:
        doc_dir = self.get_document_dir(document_id)
        dirs = {
            "original": doc_dir / "original",
            "pages": doc_dir / "pages",
            "assets": doc_dir / "assets",
            "intermediate": doc_dir / "intermediate",
            "structured": doc_dir / "structured",
            "logs": doc_dir / "logs",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def save_original_pdf(self, document_id: str, content: bytes) -> Path:
        dirs = self.initialize_document_structure(document_id)
        dest = dirs["original"] / "source.pdf"
        with open(dest, "wb") as f:
            f.write(content)
        return dest

    def get_original_pdf_path(self, document_id: str) -> Path:
        return self.get_document_dir(document_id) / "original" / "source.pdf"

    def save_page_preview(self, document_id: str, page_index: int, image_bytes: bytes) -> Path:
        dirs = self.initialize_document_structure(document_id)
        filename = f"page_{page_index:04d}.png"
        dest = dirs["pages"] / filename
        with open(dest, "wb") as f:
            f.write(image_bytes)
        return dest

    def save_asset(self, document_id: str, filename: str, image_bytes: bytes) -> Path:
        dirs = self.initialize_document_structure(document_id)
        dest = dirs["assets"] / filename
        with open(dest, "wb") as f:
            f.write(image_bytes)
        return dest

    def save_intermediate_page(self, document_id: str, page_index: int, data: Dict[str, Any]) -> Path:
        dirs = self.initialize_document_structure(document_id)
        filename = f"page_{page_index:04d}_raw.json"
        dest = dirs["intermediate"] / filename
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return dest

    def load_intermediate_page(self, document_id: str, page_index: int) -> Optional[Dict[str, Any]]:
        file_path = self.get_document_dir(document_id) / "intermediate" / f"page_{page_index:04d}_raw.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_structured_document(self, document_id: str, doc: Union[StructuredDocument, Dict[str, Any]]) -> Path:
        dirs = self.initialize_document_structure(document_id)
        dest = dirs["structured"] / "document.json"
        if isinstance(doc, StructuredDocument):
            data = doc.model_dump(mode="json")
        else:
            data = doc
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return dest

    def load_structured_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        file_path = self.get_document_dir(document_id) / "structured" / "document.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete_document(self, document_id: str) -> bool:
        doc_dir = self.root_dir / document_id
        if doc_dir.exists():
            shutil.rmtree(doc_dir)
            return True
        return False

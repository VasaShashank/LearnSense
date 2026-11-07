"""Owner metadata for private uploaded documents.

Legacy documents have no record here and are intentionally treated as ownerless.
The document identifier is storage-safe validated before every filesystem access.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional, Set

from storage.id_validation import validate_storage_id


class DocumentOwnershipRepository:
    def __init__(self, base_dir: str = "storage/document_owners"):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, document_id: str) -> Path:
        safe_id = validate_storage_id(document_id, name="document_id")
        path = (self.base_dir / f"{safe_id}.json").resolve()
        if not path.is_relative_to(self.base_dir):
            raise ValueError("Invalid document_id")
        return path

    def claim(self, document_id: str, owner_id: str) -> None:
        """Create owner metadata once; never transfer or infer ownership."""
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id is required")
        path = self._path(document_id)
        with self._lock:
            if path.exists():
                if self.get_owner(document_id) == owner_id:
                    return
                raise ValueError("Document already has an owner")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self.get_owner(document_id) == owner_id:
                    return
                raise ValueError("Document already has an owner") from None
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"document_id": document_id, "owner_id": owner_id}, stream)
                stream.flush()
                os.fsync(stream.fileno())

    def get_owner(self, document_id: str) -> Optional[str]:
        path = self._path(document_id)
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
            if data.get("document_id") != document_id:
                return None
            owner_id = data.get("owner_id")
            return owner_id if isinstance(owner_id, str) and owner_id else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def is_owned_by(self, document_id: str, owner_id: str) -> bool:
        try:
            return self.get_owner(document_id) == owner_id
        except ValueError:
            return False

    def list_owned_document_ids(self, owner_id: str) -> Set[str]:
        document_ids = set()
        for path in self.base_dir.glob("*.json"):
            document_id = path.stem
            try:
                if self.get_owner(document_id) == owner_id:
                    document_ids.add(document_id)
            except ValueError:
                continue
        return document_ids

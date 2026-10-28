"""Persistent explicit class grants for privately uploaded documents."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from storage.id_validation import validate_storage_id


class DocumentShareRepository:
    """Stores additive document-to-class grants under the local storage root."""

    def __init__(self, base_dir: str = "storage/document_shares"):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, document_id: str) -> Path:
        safe_id = validate_storage_id(document_id, name="document_id")
        path = (self.base_dir / f"{safe_id}.json").resolve()
        if not path.is_relative_to(self.base_dir):
            raise ValueError("Invalid document_id")
        return path

    @staticmethod
    def _safe_class_id(class_id: str) -> str:
        return validate_storage_id(class_id, name="class_id")

    def _read(self, document_id: str) -> Dict[str, Any]:
        path = self._path(document_id)
        if not path.exists():
            return {"document_id": document_id, "shares": {}}
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
            if (
                not isinstance(data, dict)
                or data.get("document_id") != document_id
                or not isinstance(data.get("shares"), dict)
            ):
                raise ValueError("Invalid document share record")
            return data
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid document share record") from exc

    def _write(self, document_id: str, data: Dict[str, Any]) -> None:
        path = self._path(document_id)
        fd, temp_name = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def grant(
        self,
        document_id: str,
        class_id: str,
        owner_id: str,
        shared_by: str,
    ) -> Dict[str, str]:
        """Create or return the existing grant for this document and class."""
        class_id = self._safe_class_id(class_id)
        if not owner_id or not shared_by:
            raise ValueError("Verified owner and sharing user are required")
        with self._lock:
            data = self._read(document_id)
            existing = data["shares"].get(class_id)
            if existing:
                if existing.get("owner_id") != owner_id:
                    raise ValueError("Document share owner mismatch")
                return existing
            record = {
                "document_id": document_id,
                "class_id": class_id,
                "owner_id": owner_id,
                "shared_by": shared_by,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data["shares"][class_id] = record
            self._write(document_id, data)
            return record

    def revoke(self, document_id: str, class_id: str, owner_id: str) -> bool:
        """Remove one matching grant; repeated revocation is harmless."""
        class_id = self._safe_class_id(class_id)
        with self._lock:
            data = self._read(document_id)
            grant = data["shares"].get(class_id)
            if grant is None or grant.get("owner_id") != owner_id:
                return False
            del data["shares"][class_id]
            self._write(document_id, data)
            return True

    def list_for_document(self, document_id: str) -> List[Dict[str, str]]:
        try:
            data = self._read(document_id)
        except ValueError:
            return []
        return [
            item for item in data["shares"].values()
            if isinstance(item, dict)
            and item.get("document_id") == document_id
            and isinstance(item.get("class_id"), str)
            and isinstance(item.get("owner_id"), str)
        ]

    def list_all(self) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for path in self.base_dir.glob("*.json"):
            document_id = path.stem
            try:
                results.extend(self.list_for_document(document_id))
            except ValueError:
                continue
        return results

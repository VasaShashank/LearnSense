"""
Question Bank Storage Repository for Phase 3.
Persists Question Banks to disk under Phase 3 directory structure.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from phase3.question_bank.models import QuestionBank, QuestionValidationStatus


class QuestionBankRepository:
    def __init__(self, base_dir: str = "storage/question_banks"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_bank_path(self, document_id: str, chapter_id: str) -> Path:
        return self.base_dir / document_id / f"{chapter_id}.json"

    def save_bank(self, bank: QuestionBank) -> Path:
        """
        Persist the bank atomically.

        A crash mid-write would otherwise leave truncated JSON that fails to load on
        the next request, which would look like "the learner has no questions".
        """
        path = self.get_bank_path(bank.document_id, bank.chapter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bank.model_dump(mode="json")

        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception:
            # Never leave a stray temp file behind on failure.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return path

    def load_bank(self, document_id: str, chapter_id: str) -> Optional[QuestionBank]:
        """
        Load a persisted bank, or ``None`` if absent or unreadable.

        A corrupt file is treated as absent so the caller regenerates instead of
        failing the whole request.
        """
        path = self.get_bank_path(document_id, chapter_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return QuestionBank.model_validate(data)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Discarding unreadable question bank %s (%s); it will be rebuilt.", path, exc
            )
            return None

    def load_grounded_bank(self, document_id: str, chapter_id: str) -> Optional[QuestionBank]:
        """
        Load a bank and demote any question that is no longer grounded.

        This keeps a previously persisted bank honest: a question saved before the
        grounding requirement existed, or one whose citation no longer resolves, is
        never served again.
        """
        bank = self.load_bank(document_id, chapter_id)
        if bank is None:
            return None
        for item in bank.questions.values():
            if not item.source_citations:
                item.validation_status = QuestionValidationStatus.INVALID
        return bank

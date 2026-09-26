"""
Question Bank Storage Repository for Phase 3.
Persists Question Banks to disk under Phase 3 directory structure.
"""

import json
import os
from pathlib import Path
from typing import Optional
from phase3.question_bank.models import QuestionBank


class QuestionBankRepository:
    def __init__(self, base_dir: str = "storage/question_banks"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_bank_path(self, document_id: str, chapter_id: str) -> Path:
        return self.base_dir / document_id / f"{chapter_id}.json"

    def save_bank(self, bank: QuestionBank) -> Path:
        path = self.get_bank_path(bank.document_id, bank.chapter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bank.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def load_bank(self, document_id: str, chapter_id: str) -> Optional[QuestionBank]:
        path = self.get_bank_path(document_id, chapter_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return QuestionBank.model_validate(data)

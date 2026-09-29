"""
JSON-based Persistent Repositories for Sessions, Learning Contexts, and Question Banks in Storage.
Ensures Phase 4 data structures persist across application restarts.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional, Any
from phase4.models import KnowledgeInitializationSession
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import QuestionBank, QuestionValidationStatus


def _atomic_write_json(path: Path, data: Any, base_dir: Path) -> Path:
    """Write data as JSON atomically so process crashes cannot leave truncated files."""
    base_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(base_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


class SessionRepository:
    def __init__(self, base_dir: str = "storage/sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def save_session(self, session: KnowledgeInitializationSession) -> Path:
        path = self.get_path(session.session_id)
        data = session.model_dump(mode="json")
        return _atomic_write_json(path, data, self.base_dir)

    def load_session(self, session_id: str) -> Optional[KnowledgeInitializationSession]:
        path = self.get_path(session_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return KnowledgeInitializationSession.model_validate(data)


class QuestionBankRepository:
    def __init__(self, base_dir: str = "storage/question_banks"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, subject_id: str) -> Path:
        return self.base_dir / f"{subject_id}.json"

    def save_bank(self, bank: QuestionBank) -> Path:
        """Write atomically so a crash cannot leave truncated JSON behind."""
        path = self.get_path(bank.document_id)
        data = bank.model_dump(mode="json")
        fd, tmp_name = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return path

    def load_bank(self, subject_id: str) -> Optional[QuestionBank]:
        """
        Load a bank, or ``None`` when absent or unreadable.

        A corrupt file is treated as absent so the caller rebuilds it instead of
        failing the whole request with a JSON decode error.
        """
        path = self.get_path(subject_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return QuestionBank.model_validate(data)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logging.getLogger(__name__).warning(
                "Discarding unreadable question bank %s (%s); it will be rebuilt.", path, exc
            )
            return None

    def load_grounded_bank(self, subject_id: str) -> Optional[QuestionBank]:
        """
        Load a bank and demote any question that is not grounded in the material.

        Keeps a bank honest across the switch to provenance-checked questions: anything
        without a real citation is marked invalid and can never be served again.
        """
        bank = self.load_bank(subject_id)
        if bank is None:
            return None
        for item in bank.questions.values():
            if not item.source_citations:
                item.validation_status = QuestionValidationStatus.INVALID
        return bank


class LearningContextRepository:
    def __init__(self, base_dir: str = "storage/learning_contexts"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, subject_id: str) -> Path:
        return self.base_dir / f"{subject_id}.json"

    def save_context(self, context: LearningContext) -> Path:
        path = self.get_path(context.document_id)
        data = context.model_dump(mode="json")
        return _atomic_write_json(path, data, self.base_dir)

    def load_context(self, subject_id: str) -> Optional[LearningContext]:
        path = self.get_path(subject_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return LearningContext.model_validate(data)

"""
JSON-based Persistent Repositories for Sessions, Learning Contexts, and Question Banks in Storage.
Ensures Phase 4 data structures persist across application restarts.
"""

import json
from pathlib import Path
from typing import Dict, Optional, Any
from phase4.models import KnowledgeInitializationSession
from phase3.knowledge.phase2_adapter import LearningContext
from phase3.question_bank.models import QuestionBank


class SessionRepository:
    def __init__(self, base_dir: str = "storage/sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def save_session(self, session: KnowledgeInitializationSession) -> Path:
        path = self.get_path(session.session_id)
        data = session.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

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
        path = self.get_path(bank.document_id)
        data = bank.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def load_bank(self, subject_id: str) -> Optional[QuestionBank]:
        path = self.get_path(subject_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return QuestionBank.model_validate(data)


class LearningContextRepository:
    def __init__(self, base_dir: str = "storage/learning_contexts"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, subject_id: str) -> Path:
        return self.base_dir / f"{subject_id}.json"

    def save_context(self, context: LearningContext) -> Path:
        path = self.get_path(context.document_id)
        data = context.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def load_context(self, subject_id: str) -> Optional[LearningContext]:
        path = self.get_path(subject_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return LearningContext.model_validate(data)

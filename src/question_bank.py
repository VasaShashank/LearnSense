"""LearnSense Person 3 — Unified Question Bank Adapter & Person 2 Provider Interface.

Provides canonical question access, filtering, and indexing across:
1. 1,750-question synthetic JEE bank from data/synthetic jee/v5_1_production/questions.csv.
2. Canonical concept validation (active concepts in 2026.jee.v1, fingerprint 6d44446f63d5f173).
3. JEE Main 2027 syllabus eligibility filtering (excluding cc_e4951a49b665b28b, cc_105b9a15f20f98b3, cc_ebafa02826c9b205).
4. Multi-concept indexing, difficulty indexing, and question-type indexing.
5. Person2QuestionProvider interface for external Person 2 question bank hand-off.
"""

from __future__ import annotations

import copy
import csv
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.migration_adapter import (
    DEPRECATED_IDS,
    EXCLUDED_FROM_JEE_MAIN_2027,
    CanonicalConceptMigrationAdapter,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_QUESTIONS_CSV = REPO_ROOT / "curriculum" / "questions.csv"
DEFAULT_PRODUCTION_QUESTIONS_CSV = (
    RELEASE_QUESTIONS_CSV
    if RELEASE_QUESTIONS_CSV.is_file()
    else REPO_ROOT / "data" / "synthetic jee" / "v5_1_production" / "questions.csv"
)


@dataclass
class QuestionOption:
    """A multiple-choice option for a question."""
    option_id: str  # 'A', 'B', 'C', 'D'
    text: str
    is_correct: bool = False
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "option_id": self.option_id,
            "text": self.text,
            "is_correct": self.is_correct,
            "explanation": self.explanation,
        }


@dataclass
class QuestionBankItem:
    """A validated question item in the LearnSense curriculum."""
    question_id: str
    primary_concept_id: str
    concept_ids: List[str]
    concept_count: int
    subject: str
    chapter: str
    difficulty: str
    option_count: int
    question_type: str
    estimated_time_seconds: int
    item_family_id: str
    item_role: str
    item_format: str
    is_jee_main_2027_eligible: bool
    question_text_status: str
    synthetic_item: bool
    prompt: Optional[str] = None
    options: List[QuestionOption] = field(default_factory=list)
    hints: List[str] = field(default_factory=list)
    solution_steps: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_contract_dict(self) -> Dict[str, Any]:
        """Converts item to contracts/question_schema.json format."""
        return {
            "question_id": self.question_id,
            "primary_concept_id": self.primary_concept_id,
            "concept_ids": list(self.concept_ids),
            "subject": self.subject,
            "difficulty": self.difficulty,
            "question_type": self.question_type,
            "estimated_time_seconds": self.estimated_time_seconds,
            "is_jee_main_2027_eligible": self.is_jee_main_2027_eligible,
            "prompt": self.prompt or f"Conceptual item for {self.primary_concept_id}",
            "options": [opt.to_dict() for opt in self.options],
            "hints": list(self.hints),
            "metadata": copy.deepcopy(self.metadata),
        }


class Person2QuestionProvider(ABC):
    """Abstract interface defining the formal question bank contract with Person 2."""

    @abstractmethod
    def get_question(self, question_id: str) -> Optional[QuestionBankItem]:
        """Retrieves a single question by its unique ID."""
        pass

    @abstractmethod
    def get_questions_for_concept(
        self,
        concept_id: str,
        difficulty: Optional[str] = None,
        jee_main_2027_only: bool = True,
    ) -> List[QuestionBankItem]:
        """Retrieves all available questions for a target concept."""
        pass

    @abstractmethod
    def list_available_concepts(self) -> List[str]:
        """Returns list of canonical concept IDs having questions."""
        pass

    @abstractmethod
    def count(self) -> int:
        """Returns total question count in the provider."""
        pass


class QuestionBankAdapter(Person2QuestionProvider):
    """Production Question Bank Adapter indexing synthetic and external question items."""

    def __init__(
        self,
        questions_csv_path: Optional[Union[str, Path]] = None,
        migration_adapter: Optional[CanonicalConceptMigrationAdapter] = None,
        external_provider: Optional[Person2QuestionProvider] = None,
        auto_load: bool = True,
    ) -> None:
        self.questions_csv_path = Path(questions_csv_path or DEFAULT_PRODUCTION_QUESTIONS_CSV)
        self.migration_adapter = migration_adapter or CanonicalConceptMigrationAdapter()
        self.external_provider = external_provider

        # Indexes
        self._questions_by_id: Dict[str, QuestionBankItem] = {}
        self._questions_by_primary_concept: Dict[str, List[QuestionBankItem]] = {}
        self._questions_by_concept: Dict[str, List[QuestionBankItem]] = {}
        self._questions_by_difficulty: Dict[str, List[QuestionBankItem]] = {
            "easy": [],
            "medium": [],
            "hard": [],
        }

        if auto_load and self.questions_csv_path.is_file():
            self.load_from_csv(self.questions_csv_path)

    def load_from_csv(self, file_path: Path) -> int:
        """Loads and indexes questions from questions.csv."""
        if not file_path.is_file():
            logger.warning(f"Questions CSV not found at: {file_path}")
            return 0

        loaded_count = 0
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                qid = row["question_id"].strip()
                raw_primary = row["primary_concept_id"].strip()

                # Migrate/validate primary concept ID
                try:
                    primary_cid = self.migration_adapter.to_canonical_id(
                        raw_primary,
                        default_split_to_ray=True,
                    )
                except Exception:
                    primary_cid = raw_primary

                # Reject deprecated concepts
                if primary_cid in DEPRECATED_IDS:
                    continue

                raw_concept_ids = [c.strip() for c in row.get("concept_ids", "").split(";") if c.strip()]
                canonical_cids: List[str] = []
                for c in raw_concept_ids:
                    try:
                        c_can = self.migration_adapter.to_canonical_id(c, default_split_to_ray=True)
                        if c_can not in DEPRECATED_IDS:
                            canonical_cids.append(c_can)
                    except Exception:
                        if c not in DEPRECATED_IDS:
                            canonical_cids.append(c)

                if primary_cid not in canonical_cids:
                    canonical_cids.insert(0, primary_cid)

                is_eligible = (
                    str(row.get("is_jee_main_2027_eligible", "True")).lower() == "true"
                    and primary_cid not in EXCLUDED_FROM_JEE_MAIN_2027
                )

                difficulty = row.get("difficulty", "medium").lower().strip()
                if difficulty not in ("easy", "medium", "hard"):
                    difficulty = "medium"

                item = QuestionBankItem(
                    question_id=qid,
                    primary_concept_id=primary_cid,
                    concept_ids=canonical_cids,
                    concept_count=int(row.get("concept_count", len(canonical_cids))),
                    subject=row.get("subject", "").strip(),
                    chapter=row.get("chapter", "").strip(),
                    difficulty=difficulty,
                    option_count=int(row.get("option_count", 4)),
                    question_type=row.get("question_type", "single_correct_mcq").strip(),
                    estimated_time_seconds=int(row.get("estimated_time_seconds", 120)),
                    item_family_id=row.get("item_family_id", "").strip(),
                    item_role=row.get("item_role", "practice").strip(),
                    item_format=row.get("item_format", "direct").strip(),
                    is_jee_main_2027_eligible=is_eligible,
                    question_text_status=row.get("question_text_status", "metadata_only").strip(),
                    synthetic_item=str(row.get("synthetic_item", "True")).lower() == "true",
                    prompt=row.get("prompt"),
                    metadata={
                        "item_family_id": row.get("item_family_id"),
                        "item_role": row.get("item_role"),
                        "item_format": row.get("item_format"),
                    },
                )

                self._questions_by_id[qid] = item

                # Index by primary concept
                if primary_cid not in self._questions_by_primary_concept:
                    self._questions_by_primary_concept[primary_cid] = []
                self._questions_by_primary_concept[primary_cid].append(item)

                # Index by all associated concepts
                for cid in canonical_cids:
                    if cid not in self._questions_by_concept:
                        self._questions_by_concept[cid] = []
                    self._questions_by_concept[cid].append(item)

                # Index by difficulty
                self._questions_by_difficulty[difficulty].append(item)
                loaded_count += 1

        logger.info(
            f"QuestionBankAdapter successfully loaded {loaded_count} questions from {file_path} "
            f"covering {len(self._questions_by_primary_concept)} primary concepts."
        )
        return loaded_count

    def resolve_concept_id(self, concept_id: str) -> str:
        """Resolves legacy or canonical concept ID to canonical concept ID."""
        try:
            return self.migration_adapter.to_canonical_id(str(concept_id).strip(), default_split_to_ray=True)
        except Exception:
            return str(concept_id).strip()

    def get_question(self, question_id: str) -> Optional[QuestionBankItem]:
        """Retrieves a question by its ID from local bank or external provider."""
        qid = str(question_id).strip()
        if qid in self._questions_by_id:
            return self._questions_by_id[qid]
        if self.external_provider:
            return self.external_provider.get_question(qid)
        return None

    def has_questions_for_concept(self, concept_id: str, jee_main_2027_only: bool = False) -> bool:
        """Checks if questions exist for a given concept."""
        cid = self.resolve_concept_id(concept_id)
        if jee_main_2027_only and cid in EXCLUDED_FROM_JEE_MAIN_2027:
            return False

        if cid in self._questions_by_primary_concept and len(self._questions_by_primary_concept[cid]) > 0:
            return True

        if cid in self._questions_by_concept and len(self._questions_by_concept[cid]) > 0:
            return True

        if self.external_provider:
            ext_qs = self.external_provider.get_questions_for_concept(cid, jee_main_2027_only=jee_main_2027_only)
            return len(ext_qs) > 0

        return False

    def get_questions_for_concept(
        self,
        concept_id: str,
        difficulty: Optional[str] = None,
        jee_main_2027_only: bool = True,
        question_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[QuestionBankItem]:
        """Retrieves questions matching criteria for a concept."""
        cid = self.resolve_concept_id(concept_id)

        if jee_main_2027_only and cid in EXCLUDED_FROM_JEE_MAIN_2027:
            logger.warning(f"Concept '{cid}' is excluded from JEE Main 2027 syllabus.")
            return []

        # Retrieve questions where cid is primary, or secondary
        candidates = list(self._questions_by_primary_concept.get(cid, []))
        if not candidates:
            candidates = list(self._questions_by_concept.get(cid, []))

        # Check external provider if local has none
        if not candidates and self.external_provider:
            candidates = self.external_provider.get_questions_for_concept(
                cid,
                difficulty=difficulty,
                jee_main_2027_only=jee_main_2027_only,
            )

        # Filters
        filtered: List[QuestionBankItem] = []
        for q in candidates:
            if jee_main_2027_only and not q.is_jee_main_2027_eligible:
                continue
            if difficulty and q.difficulty != difficulty.lower().strip():
                continue
            if question_type and q.question_type != question_type.strip():
                continue
            filtered.append(q)

        if limit and limit > 0:
            return filtered[:limit]
        return filtered

    def list_available_concepts(self, jee_main_2027_only: bool = False) -> List[str]:
        """Returns sorted list of all canonical concept IDs with available questions."""
        concepts = set(self._questions_by_primary_concept.keys())
        if jee_main_2027_only:
            concepts = concepts - EXCLUDED_FROM_JEE_MAIN_2027
        return sorted(concepts)

    def count(self) -> int:
        """Returns total questions loaded."""
        return len(self._questions_by_id)

    @property
    def question_count(self) -> int:
        """Property returning total questions loaded."""
        return self.count()


_DEFAULT_QUESTION_BANK_ADAPTER: Optional[QuestionBankAdapter] = None


def get_default_question_bank() -> QuestionBankAdapter:
    """Returns singleton default QuestionBankAdapter."""
    global _DEFAULT_QUESTION_BANK_ADAPTER
    if _DEFAULT_QUESTION_BANK_ADAPTER is None:
        _DEFAULT_QUESTION_BANK_ADAPTER = QuestionBankAdapter()
    return _DEFAULT_QUESTION_BANK_ADAPTER


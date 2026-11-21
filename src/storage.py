"""LearnSense Person 3 — Durable Transactional Storage and Concurrency-Safe Idempotency.

Provides SQLite-backed transactional persistence and multi-process coordination for:
- Per-learner, per-concept knowledge states conforming to contracts/learner_state_schema.json.
- Persistent attempt idempotency records preventing duplicate updates across restarts.
- Concurrency-safe atomic attempt processing with conflict detection.
"""

from __future__ import annotations

import copy
import datetime
import json
import sqlite3
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.bkt import (
    BKTConfig,
    LearnerConceptState,
    clamp_probability,
    evaluate_and_update_bkt_step,
)


def _binary_entropy(prob: float) -> float:
    p = max(1e-12, min(1.0 - 1e-12, float(prob)))
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def _bernoulli_variance(prob: float) -> float:
    p = max(0.0, min(1.0, float(prob)))
    return p * (1.0 - p)


@dataclass
class AttemptRecord:
    """Immutable audit record of a processed attempt."""
    attempt_id: str
    learner_id: str
    question_id: str
    concept_id: str
    outcome: int
    submitted_at: str
    p_pred: float
    prior_mastery: float
    posterior_mastery: float
    updated_at: str
    payload_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AttemptRecord:
        return cls(
            attempt_id=str(data["attempt_id"]),
            learner_id=str(data["learner_id"]),
            question_id=str(data.get("question_id", "Q_UNKNOWN")),
            concept_id=str(data["concept_id"]),
            outcome=int(data["outcome"]),
            submitted_at=str(data["submitted_at"]),
            p_pred=float(data["p_pred"]),
            prior_mastery=float(data["prior_mastery"]),
            posterior_mastery=float(data["posterior_mastery"]),
            updated_at=str(data["updated_at"]),
            payload_hash=data.get("payload_hash"),
        )


@dataclass
class MisconceptionRecord:
    """Persistent audit record of an observed or hypothesized learner misconception."""
    misconception_id: str
    learner_id: str
    concept_id: str
    category: str
    description: str
    confidence: float
    first_observed_at: str
    last_observed_at: str
    recurrence_count: int
    status: str  # suspected, recurring, improving, resolved, needs_reassessment
    remediation_action: Optional[str] = None
    supporting_attempt_ids: List[str] = field(default_factory=list)
    evidence_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MisconceptionRecord:
        return cls(
            misconception_id=str(data["misconception_id"]),
            learner_id=str(data["learner_id"]),
            concept_id=str(data["concept_id"]),
            category=str(data["category"]),
            description=str(data["description"]),
            confidence=float(data["confidence"]),
            first_observed_at=str(data["first_observed_at"]),
            last_observed_at=str(data["last_observed_at"]),
            recurrence_count=int(data["recurrence_count"]),
            status=str(data["status"]),
            remediation_action=data.get("remediation_action"),
            supporting_attempt_ids=list(data.get("supporting_attempt_ids", [])),
            evidence_history=list(data.get("evidence_history", [])),
        )


@dataclass
class RetentionRecord:
    """Persistent per-learner per-concept memory retention estimate."""
    learner_id: str
    concept_id: str
    half_life_days: float
    last_review_at: str
    review_count: int
    consecutive_successes: int
    last_recall_probability: float
    updated_at: str
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RetentionRecord:
        return cls(
            learner_id=str(data["learner_id"]),
            concept_id=str(data["concept_id"]),
            half_life_days=float(data["half_life_days"]),
            last_review_at=str(data["last_review_at"]),
            review_count=int(data["review_count"]),
            consecutive_successes=int(data["consecutive_successes"]),
            last_recall_probability=float(data["last_recall_probability"]),
            updated_at=str(data["updated_at"]),
            history=list(data.get("history", [])),
        )


@dataclass
class TransferRecord:
    """Persistent record of mastery transfer and delayed recall evidence."""
    learner_id: str
    attempt_id: str
    concept_id: str
    question_id: str
    transfer_type: str  # "unseen_near", "unseen_distant", "familiar_repeat"
    is_delayed_recall: bool
    is_correct: bool
    submitted_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TransferRecord:
        return cls(
            learner_id=str(data["learner_id"]),
            attempt_id=str(data["attempt_id"]),
            concept_id=str(data["concept_id"]),
            question_id=str(data["question_id"]),
            transfer_type=str(data["transfer_type"]),
            is_delayed_recall=bool(data["is_delayed_recall"]),
            is_correct=bool(data["is_correct"]),
            submitted_at=str(data["submitted_at"]),
        )


@dataclass
class ConfidenceRecord:
    """Persistent audit record of a student-reported confidence rating."""
    learner_id: str
    attempt_id: str
    concept_id: str
    question_id: str
    is_correct: bool
    confidence_score: float  # [0.0, 1.0]
    calibration_quadrant: str  # well_calibrated_mastery, high_confidence_error, low_confidence_correct, well_calibrated_uncertainty, intermediate_calibration
    submitted_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConfidenceRecord:
        return cls(
            learner_id=str(data["learner_id"]),
            attempt_id=str(data["attempt_id"]),
            concept_id=str(data["concept_id"]),
            question_id=str(data["question_id"]),
            is_correct=bool(data["is_correct"]),
            confidence_score=float(data["confidence_score"]),
            calibration_quadrant=str(data["calibration_quadrant"]),
            submitted_at=str(data["submitted_at"]),
        )


class LearnerStateStore(ABC):
    """Abstract interface for durable learner state and idempotency storage."""

    @abstractmethod
    def get_state(self, learner_id: str, concept_id: str) -> Optional[LearnerConceptState]:
        pass

    @abstractmethod
    def get_all_states(self, learner_id: Optional[str] = None) -> List[LearnerConceptState]:
        pass

    @abstractmethod
    def save_state(self, state: LearnerConceptState) -> None:
        pass

    @abstractmethod
    def get_attempt_record(self, learner_id: str, attempt_id: str) -> Optional[AttemptRecord]:
        pass

    @abstractmethod
    def get_all_attempt_records(self, learner_id: Optional[str] = None) -> List[AttemptRecord]:
        pass

    @abstractmethod
    def record_attempt_atomically(
        self,
        record: AttemptRecord,
        updated_state: LearnerConceptState,
        bkt_config: Optional[BKTConfig] = None,
    ) -> Tuple[bool, AttemptRecord]:
        """Atomically checks idempotency and persists both attempt and updated state."""
        pass

    @abstractmethod
    def save_misconception(self, record: MisconceptionRecord) -> None:
        pass

    @abstractmethod
    def get_misconception(self, learner_id: str, misconception_id: str) -> Optional[MisconceptionRecord]:
        pass

    @abstractmethod
    def get_learner_misconceptions(self, learner_id: str, concept_id: Optional[str] = None) -> List[MisconceptionRecord]:
        pass

    @abstractmethod
    def save_retention(self, record: RetentionRecord) -> None:
        pass

    @abstractmethod
    def get_retention(self, learner_id: str, concept_id: str) -> Optional[RetentionRecord]:
        pass

    @abstractmethod
    def get_all_retention(self, learner_id: str) -> List[RetentionRecord]:
        pass

    @abstractmethod
    def save_transfer_evidence(self, record: TransferRecord) -> None:
        pass

    @abstractmethod
    def get_transfer_evidence(self, learner_id: str, concept_id: Optional[str] = None) -> List[TransferRecord]:
        pass

    @abstractmethod
    def save_confidence_record(self, record: ConfidenceRecord) -> None:
        pass

    @abstractmethod
    def get_confidence_records(self, learner_id: str, concept_id: Optional[str] = None) -> List[ConfidenceRecord]:
        pass


class SQLiteStateStore(LearnerStateStore):
    """Production-grade SQLite transactional store with WAL mode and thread locks."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self.db_path,
                timeout=60.0,
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode; we manage explicit transactions
            )
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=60000;")
            self._conn = conn
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learner_states (
                    learner_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    mastery_probability REAL NOT NULL,
                    evidence_count INTEGER NOT NULL,
                    last_attempt_id TEXT,
                    last_evidence_at TEXT,
                    updated_at TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (learner_id, concept_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attempt_idempotency (
                    learner_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    outcome INTEGER NOT NULL,
                    submitted_at TEXT NOT NULL,
                    p_pred REAL NOT NULL,
                    prior_mastery REAL NOT NULL,
                    posterior_mastery REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_hash TEXT,
                    PRIMARY KEY (learner_id, attempt_id)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attempt_learner_concept 
                ON attempt_idempotency (learner_id, concept_id);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learner_misconceptions (
                    misconception_id TEXT NOT NULL,
                    learner_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    recurrence_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    remediation_action TEXT,
                    supporting_attempt_ids_json TEXT NOT NULL,
                    evidence_history_json TEXT NOT NULL,
                    PRIMARY KEY (learner_id, misconception_id)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_misconception_learner_concept
                ON learner_misconceptions (learner_id, concept_id);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learner_retention (
                    learner_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    half_life_days REAL NOT NULL,
                    last_review_at TEXT NOT NULL,
                    review_count INTEGER NOT NULL,
                    consecutive_successes INTEGER NOT NULL,
                    last_recall_probability REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    PRIMARY KEY (learner_id, concept_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learner_transfer_evidence (
                    learner_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    transfer_type TEXT NOT NULL,
                    is_delayed_recall INTEGER NOT NULL,
                    is_correct INTEGER NOT NULL,
                    submitted_at TEXT NOT NULL,
                    PRIMARY KEY (learner_id, attempt_id)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_transfer_learner_concept
                ON learner_transfer_evidence (learner_id, concept_id);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learner_confidence_records (
                    learner_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    is_correct INTEGER NOT NULL,
                    confidence_score REAL NOT NULL,
                    calibration_quadrant TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    PRIMARY KEY (learner_id, attempt_id)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_confidence_learner_concept
                ON learner_confidence_records (learner_id, concept_id);
                """
            )

    def get_state(self, learner_id: str, concept_id: str) -> Optional[LearnerConceptState]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT learner_id, concept_id, mastery_probability, evidence_count,
                       last_attempt_id, last_evidence_at, updated_at, status, metadata_json
                FROM learner_states
                WHERE learner_id = ? AND concept_id = ?
                """,
                (str(learner_id), str(concept_id)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return LearnerConceptState(
                learner_id=row[0],
                concept_id=row[1],
                mastery_probability=float(row[2]),
                evidence_count=int(row[3]),
                last_attempt_id=row[4],
                last_evidence_at=row[5],
                updated_at=row[6],
                status=row[7],
                metadata=json.loads(row[8]),
            )

    def get_all_states(self, learner_id: Optional[str] = None) -> List[LearnerConceptState]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            if learner_id:
                cur.execute(
                    """
                    SELECT learner_id, concept_id, mastery_probability, evidence_count,
                           last_attempt_id, last_evidence_at, updated_at, status, metadata_json
                    FROM learner_states WHERE learner_id = ?
                    ORDER BY concept_id
                    """,
                    (str(learner_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT learner_id, concept_id, mastery_probability, evidence_count,
                           last_attempt_id, last_evidence_at, updated_at, status, metadata_json
                    FROM learner_states ORDER BY learner_id, concept_id
                    """
                )
            rows = cur.fetchall()
            return [
                LearnerConceptState(
                    learner_id=r[0],
                    concept_id=r[1],
                    mastery_probability=float(r[2]),
                    evidence_count=int(r[3]),
                    last_attempt_id=r[4],
                    last_evidence_at=r[5],
                    updated_at=r[6],
                    status=r[7],
                    metadata=json.loads(r[8]),
                )
                for r in rows
            ]

    def save_state(self, state: LearnerConceptState) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO learner_states (
                    learner_id, concept_id, mastery_probability, evidence_count,
                    last_attempt_id, last_evidence_at, updated_at, status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learner_id, concept_id) DO UPDATE SET
                    mastery_probability = excluded.mastery_probability,
                    evidence_count = excluded.evidence_count,
                    last_attempt_id = excluded.last_attempt_id,
                    last_evidence_at = excluded.last_evidence_at,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json
                """,
                (
                    state.learner_id,
                    state.concept_id,
                    state.mastery_probability,
                    state.evidence_count,
                    state.last_attempt_id,
                    state.last_evidence_at,
                    state.updated_at,
                    state.status,
                    json.dumps(state.metadata),
                ),
            )

    def get_attempt_record(self, learner_id: str, attempt_id: str) -> Optional[AttemptRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT attempt_id, learner_id, question_id, concept_id, outcome,
                       submitted_at, p_pred, prior_mastery, posterior_mastery, updated_at, payload_hash
                FROM attempt_idempotency
                WHERE learner_id = ? AND attempt_id = ?
                """,
                (str(learner_id), str(attempt_id)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return AttemptRecord(
                attempt_id=row[0],
                learner_id=row[1],
                question_id=row[2],
                concept_id=row[3],
                outcome=int(row[4]),
                submitted_at=row[5],
                p_pred=float(row[6]),
                prior_mastery=float(row[7]),
                posterior_mastery=float(row[8]),
                updated_at=row[9],
                payload_hash=row[10],
            )

    def get_all_attempt_records(self, learner_id: Optional[str] = None) -> List[AttemptRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            if learner_id:
                cur.execute(
                    """
                    SELECT attempt_id, learner_id, question_id, concept_id, outcome,
                           submitted_at, p_pred, prior_mastery, posterior_mastery, updated_at, payload_hash
                    FROM attempt_idempotency WHERE learner_id = ? ORDER BY submitted_at
                    """,
                    (str(learner_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT attempt_id, learner_id, question_id, concept_id, outcome,
                           submitted_at, p_pred, prior_mastery, posterior_mastery, updated_at, payload_hash
                    FROM attempt_idempotency ORDER BY submitted_at
                    """
                )
            rows = cur.fetchall()
            return [
                AttemptRecord(
                    attempt_id=r[0],
                    learner_id=r[1],
                    question_id=r[2],
                    concept_id=r[3],
                    outcome=int(r[4]),
                    submitted_at=r[5],
                    p_pred=float(r[6]),
                    prior_mastery=float(r[7]),
                    posterior_mastery=float(r[8]),
                    updated_at=r[9],
                    payload_hash=r[10],
                )
                for r in rows
            ]

    def record_attempt_atomically(
        self,
        record: AttemptRecord,
        updated_state: LearnerConceptState,
        bkt_config: Optional[BKTConfig] = None,
    ) -> Tuple[bool, AttemptRecord]:
        """Atomically records attempt with strict payload conflict checking inside a transaction."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT attempt_id, learner_id, question_id, concept_id, outcome,
                           submitted_at, p_pred, prior_mastery, posterior_mastery, updated_at, payload_hash
                    FROM attempt_idempotency
                    WHERE learner_id = ? AND attempt_id = ?
                    """,
                    (record.learner_id, record.attempt_id),
                )
                row = cur.fetchone()
                if row:
                    existing = AttemptRecord(
                        attempt_id=row[0],
                        learner_id=row[1],
                        question_id=row[2],
                        concept_id=row[3],
                        outcome=int(row[4]),
                        submitted_at=row[5],
                        p_pred=float(row[6]),
                        prior_mastery=float(row[7]),
                        posterior_mastery=float(row[8]),
                        updated_at=row[9],
                        payload_hash=row[10],
                    )
                    # Check for conflicting payload
                    if (
                        existing.concept_id != record.concept_id
                        or existing.question_id != record.question_id
                        or existing.outcome != record.outcome
                    ):
                        raise ValueError(
                            f"Idempotency conflict for attempt '{record.attempt_id}': Attempt already registered with conflicting payload "
                            f"(registered: concept={existing.concept_id}, question={existing.question_id}, outcome={existing.outcome}; "
                            f"received: concept={record.concept_id}, question={record.question_id}, outcome={record.outcome})"
                        )
                    conn.execute("COMMIT;")
                    return False, existing

                # Check current state in DB inside transaction to catch concurrent updates
                cur.execute(
                    """
                    SELECT mastery_probability, evidence_count, last_attempt_id, last_evidence_at, updated_at, status, metadata_json
                    FROM learner_states
                    WHERE learner_id = ? AND concept_id = ?
                    """,
                    (record.learner_id, record.concept_id),
                )
                state_row = cur.fetchone()
                if state_row is not None:
                    db_mastery = float(state_row[0])
                    db_evidence = int(state_row[1])
                    db_last_evidence = state_row[3]

                    # Verify chronological ordering against durable DB state
                    if db_last_evidence and record.submitted_at:
                        try:
                            curr_dt = datetime.datetime.fromisoformat(record.submitted_at.replace("Z", "+00:00"))
                            last_dt = datetime.datetime.fromisoformat(db_last_evidence.replace("Z", "+00:00"))
                            if curr_dt < last_dt:
                                # In concurrent multi-process environments, if another worker committed during lock wait,
                                # and the difference is sub-second (lock contention), advance timestamp to preserve monotonicity
                                if db_evidence >= updated_state.evidence_count and (last_dt - curr_dt).total_seconds() < 5.0:
                                    curr_dt = last_dt + datetime.timedelta(microseconds=1000)
                                    record.submitted_at = curr_dt.isoformat()
                                    record.updated_at = record.submitted_at
                                else:
                                    raise ValueError(
                                        f"Chronological regression detected for learner '{record.learner_id}' on concept '{record.concept_id}': "
                                        f"attempt timestamp ({record.submitted_at}) precedes last evidence ({db_last_evidence})."
                                    )
                        except (ValueError, TypeError) as e:
                            if "Chronological regression" in str(e):
                                raise

                    # If another worker committed an update while this worker was processing
                    if db_evidence >= updated_state.evidence_count:
                        cfg = bkt_config or BKTConfig(config_id="store_sync_v1")
                        params = cfg.get_parameters_for_concept(record.concept_id)
                        step_result = evaluate_and_update_bkt_step(
                            p_mastery_prior=db_mastery,
                            response=record.outcome,
                            parameters=params,
                            concept_id=record.concept_id,
                        )
                        record.prior_mastery = db_mastery
                        record.p_pred = step_result.p_correct_pred
                        record.posterior_mastery = step_result.p_mastery_next

                        updated_state.mastery_probability = step_result.p_mastery_next
                        updated_state.evidence_count = db_evidence + 1
                        updated_state.last_attempt_id = record.attempt_id
                        updated_state.last_evidence_at = record.submitted_at
                        updated_state.updated_at = record.updated_at

                        ent = _binary_entropy(updated_state.mastery_probability)
                        var = _bernoulli_variance(updated_state.mastery_probability)
                        conf = round(min(1.0, (1.0 - ent) * (updated_state.evidence_count / (updated_state.evidence_count + 3.0))), 4)

                        try:
                            db_meta = json.loads(state_row[6])
                        except Exception:
                            db_meta = {}

                        recent = list(db_meta.get("recent_correctness", []))
                        recent.append(record.outcome)
                        if len(recent) > 10:
                            recent = recent[-10:]
                        consec_err = 0 if record.outcome == 1 else (db_meta.get("consecutive_errors", 0) + 1)

                        st_status = "unassessed" if updated_state.evidence_count == 0 else ("provisional" if updated_state.evidence_count < 5 else "estimated")
                        if consec_err >= 2 and st_status == "estimated":
                            st_status = "needs_review"

                        updated_state.status = st_status
                        updated_state.metadata["entropy_bits"] = round(ent, 5)
                        updated_state.metadata["variance"] = round(var, 5)
                        updated_state.metadata["confidence"] = conf
                        updated_state.metadata["recent_correctness"] = recent
                        updated_state.metadata["consecutive_errors"] = consec_err

                # Insert attempt
                conn.execute(
                    """
                    INSERT INTO attempt_idempotency (
                        attempt_id, learner_id, question_id, concept_id, outcome,
                        submitted_at, p_pred, prior_mastery, posterior_mastery, updated_at, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.attempt_id,
                        record.learner_id,
                        record.question_id,
                        record.concept_id,
                        record.outcome,
                        record.submitted_at,
                        record.p_pred,
                        record.prior_mastery,
                        record.posterior_mastery,
                        record.updated_at,
                        record.payload_hash,
                    ),
                )

                # Upsert state
                conn.execute(
                    """
                    INSERT INTO learner_states (
                        learner_id, concept_id, mastery_probability, evidence_count,
                        last_attempt_id, last_evidence_at, updated_at, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(learner_id, concept_id) DO UPDATE SET
                        mastery_probability = excluded.mastery_probability,
                        evidence_count = excluded.evidence_count,
                        last_attempt_id = excluded.last_attempt_id,
                        last_evidence_at = excluded.last_evidence_at,
                        updated_at = excluded.updated_at,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        updated_state.learner_id,
                        updated_state.concept_id,
                        updated_state.mastery_probability,
                        updated_state.evidence_count,
                        updated_state.last_attempt_id,
                        updated_state.last_evidence_at,
                        updated_state.updated_at,
                        updated_state.status,
                        json.dumps(updated_state.metadata),
                    ),
                )
                conn.execute("COMMIT;")
                return True, record
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def save_misconception(self, record: MisconceptionRecord) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO learner_misconceptions (
                    misconception_id, learner_id, concept_id, category, description,
                    confidence, first_observed_at, last_observed_at, recurrence_count,
                    status, remediation_action, supporting_attempt_ids_json, evidence_history_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learner_id, misconception_id) DO UPDATE SET
                    concept_id = excluded.concept_id,
                    category = excluded.category,
                    description = excluded.description,
                    confidence = excluded.confidence,
                    last_observed_at = excluded.last_observed_at,
                    recurrence_count = excluded.recurrence_count,
                    status = excluded.status,
                    remediation_action = excluded.remediation_action,
                    supporting_attempt_ids_json = excluded.supporting_attempt_ids_json,
                    evidence_history_json = excluded.evidence_history_json
                """,
                (
                    record.misconception_id,
                    record.learner_id,
                    record.concept_id,
                    record.category,
                    record.description,
                    float(record.confidence),
                    record.first_observed_at,
                    record.last_observed_at,
                    int(record.recurrence_count),
                    record.status,
                    record.remediation_action,
                    json.dumps(record.supporting_attempt_ids),
                    json.dumps(record.evidence_history),
                ),
            )

    def get_misconception(self, learner_id: str, misconception_id: str) -> Optional[MisconceptionRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT misconception_id, learner_id, concept_id, category, description,
                       confidence, first_observed_at, last_observed_at, recurrence_count,
                       status, remediation_action, supporting_attempt_ids_json, evidence_history_json
                FROM learner_misconceptions
                WHERE learner_id = ? AND misconception_id = ?
                """,
                (str(learner_id), str(misconception_id)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return MisconceptionRecord(
                misconception_id=row[0],
                learner_id=row[1],
                concept_id=row[2],
                category=row[3],
                description=row[4],
                confidence=float(row[5]),
                first_observed_at=row[6],
                last_observed_at=row[7],
                recurrence_count=int(row[8]),
                status=row[9],
                remediation_action=row[10],
                supporting_attempt_ids=json.loads(row[11]),
                evidence_history=json.loads(row[12]),
            )

    def get_learner_misconceptions(self, learner_id: str, concept_id: Optional[str] = None) -> List[MisconceptionRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            if concept_id:
                cur.execute(
                    """
                    SELECT misconception_id, learner_id, concept_id, category, description,
                           confidence, first_observed_at, last_observed_at, recurrence_count,
                           status, remediation_action, supporting_attempt_ids_json, evidence_history_json
                    FROM learner_misconceptions
                    WHERE learner_id = ? AND concept_id = ?
                    ORDER BY last_observed_at DESC
                    """,
                    (str(learner_id), str(concept_id)),
                )
            else:
                cur.execute(
                    """
                    SELECT misconception_id, learner_id, concept_id, category, description,
                           confidence, first_observed_at, last_observed_at, recurrence_count,
                           status, remediation_action, supporting_attempt_ids_json, evidence_history_json
                    FROM learner_misconceptions
                    WHERE learner_id = ?
                    ORDER BY last_observed_at DESC
                    """,
                    (str(learner_id),),
                )
            rows = cur.fetchall()
            return [
                MisconceptionRecord(
                    misconception_id=r[0],
                    learner_id=r[1],
                    concept_id=r[2],
                    category=r[3],
                    description=r[4],
                    confidence=float(r[5]),
                    first_observed_at=r[6],
                    last_observed_at=r[7],
                    recurrence_count=int(r[8]),
                    status=r[9],
                    remediation_action=r[10],
                    supporting_attempt_ids=json.loads(r[11]),
                    evidence_history=json.loads(r[12]),
                )
                for r in rows
            ]

    def save_retention(self, record: RetentionRecord) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO learner_retention (
                    learner_id, concept_id, half_life_days, last_review_at,
                    review_count, consecutive_successes, last_recall_probability,
                    updated_at, history_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learner_id, concept_id) DO UPDATE SET
                    half_life_days = excluded.half_life_days,
                    last_review_at = excluded.last_review_at,
                    review_count = excluded.review_count,
                    consecutive_successes = excluded.consecutive_successes,
                    last_recall_probability = excluded.last_recall_probability,
                    updated_at = excluded.updated_at,
                    history_json = excluded.history_json
                """,
                (
                    record.learner_id,
                    record.concept_id,
                    float(record.half_life_days),
                    record.last_review_at,
                    int(record.review_count),
                    int(record.consecutive_successes),
                    float(record.last_recall_probability),
                    record.updated_at,
                    json.dumps(record.history),
                ),
            )

    def get_retention(self, learner_id: str, concept_id: str) -> Optional[RetentionRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT learner_id, concept_id, half_life_days, last_review_at,
                       review_count, consecutive_successes, last_recall_probability,
                       updated_at, history_json
                FROM learner_retention
                WHERE learner_id = ? AND concept_id = ?
                """,
                (str(learner_id), str(concept_id)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return RetentionRecord(
                learner_id=row[0],
                concept_id=row[1],
                half_life_days=float(row[2]),
                last_review_at=row[3],
                review_count=int(row[4]),
                consecutive_successes=int(row[5]),
                last_recall_probability=float(row[6]),
                updated_at=row[7],
                history=json.loads(row[8]),
            )

    def get_all_retention(self, learner_id: str) -> List[RetentionRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT learner_id, concept_id, half_life_days, last_review_at,
                       review_count, consecutive_successes, last_recall_probability,
                       updated_at, history_json
                FROM learner_retention
                WHERE learner_id = ?
                """,
                (str(learner_id),),
            )
            rows = cur.fetchall()
            return [
                RetentionRecord(
                    learner_id=r[0],
                    concept_id=r[1],
                    half_life_days=float(r[2]),
                    last_review_at=r[3],
                    review_count=int(r[4]),
                    consecutive_successes=int(r[5]),
                    last_recall_probability=float(r[6]),
                    updated_at=r[7],
                    history=json.loads(r[8]),
                )
                for r in rows
            ]

    def save_transfer_evidence(self, record: TransferRecord) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO learner_transfer_evidence (
                    learner_id, attempt_id, concept_id, question_id,
                    transfer_type, is_delayed_recall, is_correct, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learner_id, attempt_id) DO UPDATE SET
                    concept_id = excluded.concept_id,
                    question_id = excluded.question_id,
                    transfer_type = excluded.transfer_type,
                    is_delayed_recall = excluded.is_delayed_recall,
                    is_correct = excluded.is_correct,
                    submitted_at = excluded.submitted_at
                """,
                (
                    record.learner_id,
                    record.attempt_id,
                    record.concept_id,
                    record.question_id,
                    record.transfer_type,
                    1 if record.is_delayed_recall else 0,
                    1 if record.is_correct else 0,
                    record.submitted_at,
                ),
            )

    def get_transfer_evidence(self, learner_id: str, concept_id: Optional[str] = None) -> List[TransferRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            if concept_id:
                cur.execute(
                    """
                    SELECT learner_id, attempt_id, concept_id, question_id,
                           transfer_type, is_delayed_recall, is_correct, submitted_at
                    FROM learner_transfer_evidence
                    WHERE learner_id = ? AND concept_id = ?
                    ORDER BY submitted_at ASC
                    """,
                    (str(learner_id), str(concept_id)),
                )
            else:
                cur.execute(
                    """
                    SELECT learner_id, attempt_id, concept_id, question_id,
                           transfer_type, is_delayed_recall, is_correct, submitted_at
                    FROM learner_transfer_evidence
                    WHERE learner_id = ?
                    ORDER BY submitted_at ASC
                    """,
                    (str(learner_id),),
                )
            rows = cur.fetchall()
            return [
                TransferRecord(
                    learner_id=r[0],
                    attempt_id=r[1],
                    concept_id=r[2],
                    question_id=r[3],
                    transfer_type=r[4],
                    is_delayed_recall=bool(r[5]),
                    is_correct=bool(r[6]),
                    submitted_at=r[7],
                )
                for r in rows
            ]

    def save_confidence_record(self, record: ConfidenceRecord) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO learner_confidence_records (
                    learner_id, attempt_id, concept_id, question_id,
                    is_correct, confidence_score, calibration_quadrant, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learner_id, attempt_id) DO UPDATE SET
                    concept_id = excluded.concept_id,
                    question_id = excluded.question_id,
                    is_correct = excluded.is_correct,
                    confidence_score = excluded.confidence_score,
                    calibration_quadrant = excluded.calibration_quadrant,
                    submitted_at = excluded.submitted_at
                """,
                (
                    record.learner_id,
                    record.attempt_id,
                    record.concept_id,
                    record.question_id,
                    1 if record.is_correct else 0,
                    float(record.confidence_score),
                    record.calibration_quadrant,
                    record.submitted_at,
                ),
            )

    def get_confidence_records(self, learner_id: str, concept_id: Optional[str] = None) -> List[ConfidenceRecord]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            if concept_id:
                cur.execute(
                    """
                    SELECT learner_id, attempt_id, concept_id, question_id,
                           is_correct, confidence_score, calibration_quadrant, submitted_at
                    FROM learner_confidence_records
                    WHERE learner_id = ? AND concept_id = ?
                    ORDER BY submitted_at ASC
                    """,
                    (str(learner_id), str(concept_id)),
                )
            else:
                cur.execute(
                    """
                    SELECT learner_id, attempt_id, concept_id, question_id,
                           is_correct, confidence_score, calibration_quadrant, submitted_at
                    FROM learner_confidence_records
                    WHERE learner_id = ?
                    ORDER BY submitted_at ASC
                    """,
                    (str(learner_id),),
                )
            rows = cur.fetchall()
            return [
                ConfidenceRecord(
                    learner_id=r[0],
                    attempt_id=r[1],
                    concept_id=r[2],
                    question_id=r[3],
                    is_correct=bool(r[4]),
                    confidence_score=float(r[5]),
                    calibration_quadrant=str(r[6]),
                    submitted_at=str(r[7]),
                )
                for r in rows
            ]

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

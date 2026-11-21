"""LearnSense Person 3 — Data Ingestion, Validation, and Leakage Guardrails.

Provides robust loading, validation, and leakage prevention for:
1. Longitudinal synthetic interaction CSV records.
2. Production JSON assessment attempt payloads conforming to contracts/attempt_schema.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import jsonschema
from jsonschema import Draft202012Validator
import numpy as np
import pandas as pd

# Default paths in current workspace
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = WORKSPACE_ROOT / "data" / "synthetic jee" / "v4"
DEFAULT_CONTRACTS_DIR = WORKSPACE_ROOT / "contracts"

# -----------------------------------------------------------------------------
# 1. Leakage Guardrail Definitions
# -----------------------------------------------------------------------------

# Exact 10 named simulator ground-truth columns identified in Phase 0 audit
PROHIBITED_LEAKAGE_COLUMNS: Set[str] = {
    "predicted_response_probability_simulator",
    "time_pressure_index",
    "latent_mastery_min_before",
    "latent_mastery_mean_before",
    "latent_mastery_primary_before",
    "latent_mastery_primary_after",
    "ground_truth_learning_rate_primary",
    "ground_truth_forgetting_rate_primary",
    "ground_truth_slip_base_primary",
    "ground_truth_guess_base_primary",
}

# Prohibited column name prefixes (fail-closed against simulator latent variables)
PROHIBITED_PREFIXES: Tuple[str, ...] = (
    "latent_mastery_",
    "ground_truth_",
    "predicted_response_probability_simulator",
    "generating_response_probability",
    "effective_mastery_",
    "profile_",
    "baseline_subject_strength_",
    "item_difficulty_b",
    "item_discrimination_a",
    "item_guessing",
    "item_slip",
    "prerequisite_penalty",
    "learning_update_factor",
    "feedback_carryover_used",
    "hint_uplift",
    "p_learned_component",
    "concept_mastery_offset",
    "concept_learning_rate",
    "concept_forgetting_rate",
    "concept_difficulty_offset",
)

# Explicit allowlist of approved features for prediction models (available prior to response).
# v4 columns are additive; v2/v3 datasets simply do not contain most of them.
APPROVED_FEATURE_COLUMNS: Set[str] = {
    "question_id",
    "primary_concept_id",
    "concept_ids",
    "subject",
    "difficulty",
    "question_type",
    "option_count",
    "days_since_previous_interaction",
    "sequence_index",
    "session_index",
    "attempt_number_primary_concept",
    "prior_attempts_concept",
    "prior_attempts_item",
    "prior_attempts_item_family",
    "days_since_concept_practice",
    "is_assessment",
    "assessment_type",
    "item_family_id",
    "item_role",
    "item_format",
    "assistance_type",
}

# Approved metadata columns for identity, partitioning, and trajectory management
APPROVED_METADATA_COLUMNS: Set[str] = {
    "interaction_id",
    "student_id",
    "student_split",
    "history_cohort",
    "timestamp_utc",
    "session_id",
    "question_id",
    "chapter",
    "synthetic_data",
    "dataset_version",
}

# Post-outcome observables (collected during or after response; valid for logging/updates, NOT features).
# hint_used is pre-response in v4 but is kept quarantined here for legacy compatibility and to
# prevent hints entering standard BKT without an explicit extension.
POST_OUTCOME_COLUMNS: Set[str] = {
    "correct",
    "response_time_seconds",
    "hint_used",
    "feedback_provided",
    "feedback_type",
}

# Required columns for a valid raw interactions DataFrame
REQUIRED_INTERACTION_COLUMNS: Set[str] = {
    "interaction_id",
    "student_id",
    "student_split",
    "sequence_index",
    "timestamp_utc",
    "question_id",
    "primary_concept_id",
    "concept_ids",
    "correct",
}

VALID_SPLITS: Set[str] = {"train", "validation", "test"}


# -----------------------------------------------------------------------------
# 2. Validation Data Structures
# -----------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Detailed summary of dataset or payload validation results."""
    is_valid: bool
    row_count: int = 0
    student_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    split_counts: Dict[str, int] = field(default_factory=dict)
    leakage_columns_found: List[str] = field(default_factory=list)
    unapproved_columns_found: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASSED" if self.is_valid else "FAILED"
        lines = [
            f"ValidationReport [{status}]: {self.row_count} rows, {self.student_count} learners",
            f"  Split counts: {self.split_counts}",
        ]
        if self.errors:
            lines.append(f"  Errors ({len(self.errors)}):")
            for err in self.errors[:10]:
                lines.append(f"    - {err}")
            if len(self.errors) > 10:
                lines.append(f"    ... and {len(self.errors) - 10} more errors")
        if self.warnings:
            lines.append(f"  Warnings ({len(self.warnings)}):")
            for warn in self.warnings[:10]:
                lines.append(f"    - {warn}")
        if self.leakage_columns_found:
            lines.append(f"  Prohibited leakage columns identified: {self.leakage_columns_found}")
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# 3. CSV Ingestion and Strict Validation
# -----------------------------------------------------------------------------

def load_raw_interactions_csv(file_path: Union[str, Path]) -> pd.DataFrame:
    """Reads interaction CSV into a DataFrame without modifying source files.
    
    Args:
        file_path: Path to interactions CSV file.
    Returns:
        pd.DataFrame: Raw interaction records.
    Raises:
        FileNotFoundError: If the specified file does not exist.
        ValueError: If file is empty or unparseable.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Interactions file not found: {path.resolve()}")
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"Interactions file is empty: {path.resolve()}")
    return df


def validate_interactions_dataframe(
    df: pd.DataFrame,
    student_profiles: Optional[pd.DataFrame] = None,
    questions: Optional[pd.DataFrame] = None,
    concepts: Optional[pd.DataFrame] = None,
) -> ValidationReport:
    """Performs rigorous structural, chronological, relational, and split validation.
    
    Checks:
    - Required columns present with valid datatypes.
    - Non-null constraints on primary keys and labels.
    - Correctness labels in {0, 1}.
    - Valid split assignments in {'train', 'validation', 'test'}.
    - 0 split leakage (each student exists in exactly one split).
    - Chronological monotonicity: within each student, sequence_index and timestamp_utc
      must be strictly monotonically increasing. Records are NOT sorted before checking.
    - Duplicate interaction IDs or duplicate (student_id, sequence_index) pairs.
    - Referential integrity against student_profiles, questions, and concepts if provided.
    - Prohibited leakage fields detected and flagged.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Required column presence
    missing_cols = REQUIRED_INTERACTION_COLUMNS - set(df.columns)
    if missing_cols:
        errors.append(f"Missing required interaction columns: {sorted(list(missing_cols))}")

    # 2. Check nulls in critical fields
    for col in ["interaction_id", "student_id", "student_split", "sequence_index", "timestamp_utc", "correct"]:
        if col in df.columns:
            null_count = int(df[col].isnull().sum())
            if null_count > 0:
                errors.append(f"Column '{col}' has {null_count} null/missing values.")

    # 3. Correctness label domain
    if "correct" in df.columns:
        invalid_correct = df[~df["correct"].isin([0, 1, True, False])]
        if not invalid_correct.empty:
            errors.append(
                f"Column 'correct' contains {len(invalid_correct)} non-binary values. "
                f"Sample invalid values: {invalid_correct['correct'].head(3).tolist()}"
            )

    # 4. Duplicate checks
    if "interaction_id" in df.columns:
        dup_ids = int(df["interaction_id"].duplicated().sum())
        if dup_ids > 0:
            errors.append(f"Found {dup_ids} duplicate 'interaction_id' values.")

    if "student_id" in df.columns and "sequence_index" in df.columns:
        dup_seq = int(df.duplicated(subset=["student_id", "sequence_index"]).sum())
        if dup_seq > 0:
            errors.append(f"Found {dup_seq} duplicate (student_id, sequence_index) pairs.")

    # 5. Split assignment and split isolation
    split_counts: Dict[str, int] = {}
    if "student_split" in df.columns:
        invalid_splits = set(df["student_split"].dropna().unique()) - VALID_SPLITS
        if invalid_splits:
            errors.append(f"Invalid split values found: {invalid_splits}. Permitted: {VALID_SPLITS}")
        split_counts = df["student_split"].value_counts().to_dict()

        if "student_id" in df.columns:
            # Check student split leakage: does any student appear in >1 split?
            splits_per_student = df.groupby("student_id")["student_split"].nunique()
            leaked_students = splits_per_student[splits_per_student > 1]
            if not leaked_students.empty:
                errors.append(
                    f"Student split leakage detected! {len(leaked_students)} students appear in multiple splits. "
                    f"Sample leaked student IDs: {leaked_students.head(5).index.tolist()}"
                )

    # 6. Chronological monotonicity check (DO NOT SORT before checking)
    if "student_id" in df.columns and "sequence_index" in df.columns and "timestamp_utc" in df.columns:
        student_arr = df["student_id"].values
        same_student = student_arr[1:] == student_arr[:-1]

        # Check for non-contiguous / interleaved student blocks
        n_blocks = int(np.sum(~same_student)) + 1 if len(student_arr) > 0 else 0
        n_unique_students = df["student_id"].nunique()
        if n_blocks > n_unique_students:
            errors.append(
                f"Student interactions are interleaved or non-contiguous: found {n_blocks} "
                f"contiguous blocks for {n_unique_students} unique students."
            )

        # Check sequence_index strictly increasing within student
        seq_arr = df["sequence_index"].values
        seq_diff = seq_arr[1:] - seq_arr[:-1]
        bad_seq = same_student & (seq_diff <= 0)
        if np.any(bad_seq):
            idx = int(np.where(bad_seq)[0][0]) + 1
            bad_student = student_arr[idx]
            errors.append(
                f"Student '{bad_student}' has non-monotonic sequence_index values: "
                f"{seq_arr[max(0, idx - 2):idx + 3].tolist()}..."
            )

        # Check timestamp_utc strictly increasing within student
        ts_series = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
        if ts_series.isnull().any():
            bad_ts_idx = int(np.where(ts_series.isnull())[0][0])
            bad_student = student_arr[bad_ts_idx]
            errors.append(f"Student '{bad_student}' contains unparseable ISO-8601 timestamps.")
        else:
            ts_vals = ts_series.values
            ts_diff = ts_vals[1:] - ts_vals[:-1]
            bad_ts = same_student & (ts_diff.astype("int64") <= 0)
            if np.any(bad_ts):
                idx = int(np.where(bad_ts)[0][0]) + 1
                bad_student = student_arr[idx]
                errors.append(
                    f"Student '{bad_student}' has out-of-order or non-monotonic timestamps."
                )

    # 7. Referential integrity checks against optional reference tables
    if student_profiles is not None and "student_id" in df.columns:
        if "student_id" in student_profiles.columns:
            missing_students = set(df["student_id"]) - set(student_profiles["student_id"])
            if missing_students:
                errors.append(
                    f"{len(missing_students)} students in interactions do not exist in student_profiles."
                )
            # Verify split consistency between interactions and profiles
            if "student_split" in df.columns and "student_split" in student_profiles.columns:
                prof_map = student_profiles.set_index("student_id")["student_split"].to_dict()
                int_mismatch = df[df["student_split"] != df["student_id"].map(prof_map)]
                if not int_mismatch.empty:
                    errors.append(
                        f"Split mismatch between interactions and student_profiles for {len(int_mismatch)} rows."
                    )

    if questions is not None and "question_id" in df.columns:
        if "question_id" in questions.columns:
            missing_questions = set(df["question_id"]) - set(questions["question_id"])
            if missing_questions:
                errors.append(
                    f"{len(missing_questions)} questions in interactions do not exist in questions catalog."
                )

    if concepts is not None:
        valid_concept_ids = set(concepts["concept_id"])
        if "primary_concept_id" in df.columns:
            missing_primary = set(df["primary_concept_id"]) - valid_concept_ids
            if missing_primary:
                errors.append(
                    f"{len(missing_primary)} primary concepts in interactions do not exist in concepts catalog."
                )
        if "concept_ids" in df.columns:
            all_int_concepts = set()
            for c_str in df["concept_ids"].dropna():
                for cid in str(c_str).split(";"):
                    if cid.strip():
                        all_int_concepts.add(cid.strip())
            missing_multi = all_int_concepts - valid_concept_ids
            if missing_multi:
                errors.append(
                    f"{len(missing_multi)} multi-concept IDs in interactions do not exist in concepts catalog: {missing_multi}"
                )

    # 7b. Check concept list parsing, primary_concept_id containment, and duplicates
    if "concept_ids" in df.columns:
        null_cids = int(df["concept_ids"].isnull().sum())
        if null_cids > 0:
            errors.append(f"Column 'concept_ids' has {null_cids} null/missing values.")

        empty_cids = int((df["concept_ids"].dropna().astype(str).str.strip() == "").sum())
        if empty_cids > 0:
            errors.append(f"Column 'concept_ids' contains {empty_cids} empty string values.")

    if "primary_concept_id" in df.columns and "concept_ids" in df.columns:
        valid_both = df["primary_concept_id"].notna() & df["concept_ids"].notna()
        if valid_both.any():
            pri_series = df.loc[valid_both, "primary_concept_id"].astype(str).str.strip()
            cid_split = df.loc[valid_both, "concept_ids"].astype(str).apply(
                lambda s: [c.strip() for c in s.split(";") if c.strip()]
            )
            in_list = [p in cl for p, cl in zip(pri_series, cid_split)]
            missing_pri_in_list = int(sum(not x for x in in_list))
            if missing_pri_in_list > 0:
                warnings.append(
                    f"Found {missing_pri_in_list} rows where 'primary_concept_id' is not present in 'concept_ids'."
                )

            has_dups = [len(cl) != len(set(cl)) for cl in cid_split]
            dup_count = int(sum(has_dups))
            if dup_count > 0:
                warnings.append(
                    f"Found {dup_count} rows with duplicate concept IDs in 'concept_ids'."
                )

    # 8. Check for presence of prohibited leakage fields
    leakage_cols_found = [c for c in df.columns if is_prohibited_column(c)]
    if leakage_cols_found:
        warnings.append(
            f"Interactions DataFrame contains {len(leakage_cols_found)} prohibited leakage columns. "
            f"These MUST be quarantined before feature construction: {leakage_cols_found}"
        )

    # 9. Check for unapproved columns
    all_known_cols = APPROVED_FEATURE_COLUMNS | APPROVED_METADATA_COLUMNS | POST_OUTCOME_COLUMNS | PROHIBITED_LEAKAGE_COLUMNS
    unapproved_cols = [c for c in df.columns if c not in all_known_cols and not is_prohibited_column(c)]
    if unapproved_cols:
        warnings.append(f"Interactions DataFrame contains unapproved columns: {unapproved_cols}")

    is_valid = len(errors) == 0
    row_count = len(df)
    student_count = df["student_id"].nunique() if "student_id" in df.columns else 0

    return ValidationReport(
        is_valid=is_valid,
        row_count=row_count,
        student_count=student_count,
        errors=errors,
        warnings=warnings,
        split_counts=split_counts,
        leakage_columns_found=leakage_cols_found,
        unapproved_columns_found=unapproved_cols,
    )


def is_prohibited_column(column_name: str) -> bool:
    """Returns True if the column is explicitly prohibited due to data leakage."""
    if column_name in PROHIBITED_LEAKAGE_COLUMNS:
        return True
    return any(column_name.startswith(pfx) for pfx in PROHIBITED_PREFIXES)


def sort_chronologically(df: pd.DataFrame) -> pd.DataFrame:
    """Explicitly sorts interaction records by student_id and sequence_index.
    
    This is a subsequent operation for deterministic replay, never used to mask
    chronological validation failures.
    """
    if "student_id" in df.columns and "sequence_index" in df.columns:
        return df.sort_values(by=["student_id", "sequence_index"]).reset_index(drop=True)
    return df.copy()


def parse_concept_ids(
    concept_entry: Any,
    delimiter: str = ";",
    deduplicate: bool = True,
) -> List[str]:
    """Parses a delimited concept string or iterable into an ordered list of concept IDs.

    Args:
        concept_entry: Semicolon-delimited string, iterable, or missing/NaN value.
        delimiter: Separator token (default ';').
        deduplicate: If True, preserves first appearance order while dropping duplicate IDs.

    Returns:
        List[str]: Clean list of non-empty concept ID strings. Returns [] for missing/null/empty.
    """
    if concept_entry is None:
        return []
    if isinstance(concept_entry, (list, tuple, set)):
        tokens = [str(t).strip() for t in concept_entry if str(t).strip()]
    else:
        if pd.isna(concept_entry):
            return []
        s = str(concept_entry).strip()
        if not s:
            return []
        raw_tokens = [tok.strip() for tok in s.split(delimiter)]
        tokens = [tok for tok in raw_tokens if tok]

    if deduplicate:
        seen = set()
        deduped: List[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        return deduped
    return tokens



# -----------------------------------------------------------------------------
# 4. Leakage-Proof Feature and Target Extraction (Fail-Closed)
# -----------------------------------------------------------------------------

def extract_features_and_target(
    df: pd.DataFrame,
    feature_allowlist: Optional[Set[str]] = None,
    target_column: str = "correct",
    require_target: bool = True,
) -> Tuple[pd.DataFrame, Optional[pd.Series], pd.DataFrame]:
    """Extracts downstream model features, target labels, and metadata fail-closed.
    
    Invariants enforced:
    1. ZERO prohibited leakage columns may enter feature matrix X.
    2. Any column not in the explicit feature_allowlist is rejected from X.
    3. Target column is separated cleanly from features and not passed into X.
    4. Metadata needed for evaluation (student_id, sequence_index, split) is separated.

    Args:
        df: Input interaction DataFrame.
        feature_allowlist: Explicit set of approved feature columns. Defaults to APPROVED_FEATURE_COLUMNS.
        target_column: Name of binary correctness column. Default 'correct'.
        require_target: If True, raises ValueError if target_column is missing or has nulls.

    Returns:
        X (pd.DataFrame): Approved prediction features.
        y (pd.Series or None): Target correctness vector (0 or 1).
        metadata (pd.DataFrame): Tracking columns (student_id, split, timestamps, interaction_id).

    Raises:
        ValueError: If prohibited leakage columns are detected in X, or unknown unapproved columns
                    attempt to enter X.
    """
    allowlist = set(feature_allowlist) if feature_allowlist is not None else APPROVED_FEATURE_COLUMNS

    # 1. Verify target
    y: Optional[pd.Series] = None
    if target_column in df.columns:
        y_raw = df[target_column]
        if require_target and y_raw.isnull().any():
            raise ValueError(f"Target column '{target_column}' contains missing values.")
        y = y_raw.astype(int)
    elif require_target:
        raise ValueError(f"Required target column '{target_column}' not found in DataFrame.")

    # 2. Extract approved features
    present_approved_features = [c for c in allowlist if c in df.columns]
    X = df[present_approved_features].copy()

    # 3. Fail-closed verification on X
    for col in X.columns:
        if is_prohibited_column(col):
            raise ValueError(
                f"CRITICAL LEAKAGE DETECTED: Column '{col}' is prohibited but appeared in features!"
            )
        if col not in allowlist:
            raise ValueError(
                f"UNAPPROVED COLUMN DETECTED: Column '{col}' is not in feature allowlist {allowlist}!"
            )
        if col == target_column:
            raise ValueError(
                f"TARGET LEAKAGE DETECTED: Target '{target_column}' cannot appear in feature matrix X!"
            )

    # 4. Extract metadata
    metadata_cols = [c for c in APPROVED_METADATA_COLUMNS if c in df.columns]
    metadata = df[metadata_cols].copy()

    return X, y, metadata


# -----------------------------------------------------------------------------
# 5. JSON Attempt Ingestion and Schema Validation
# -----------------------------------------------------------------------------

_ATTEMPT_VALIDATOR: Optional[Draft202012Validator] = None


def get_attempt_schema_validator(schema_path: Optional[Path] = None) -> Draft202012Validator:
    """Loads and caches the JSON Schema Draft 2020-12 validator for attempt_schema.json."""
    global _ATTEMPT_VALIDATOR
    if _ATTEMPT_VALIDATOR is None or schema_path is not None:
        target_path = schema_path or (DEFAULT_CONTRACTS_DIR / "attempt_schema.json")
        if not target_path.is_file():
            raise FileNotFoundError(f"Attempt schema not found at: {target_path.resolve()}")
        with open(target_path, "r", encoding="utf-8") as f:
            schema_json = json.load(f)
        Draft202012Validator.check_schema(schema_json)
        validator = Draft202012Validator(schema_json)
        if schema_path is None:
            _ATTEMPT_VALIDATOR = validator
        return validator
    return _ATTEMPT_VALIDATOR


def validate_json_attempt(
    attempt_obj: Dict[str, Any],
    schema_path: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """Validates an attempt dictionary against attempt_schema.json (Draft 2020-12).
    
    Args:
        attempt_obj: Deserialized attempt JSON dictionary.
        schema_path: Optional override path for attempt schema.
    Returns:
        (is_valid: bool, errors: List[str])
    """
    validator = get_attempt_schema_validator(schema_path)
    errors = [e.message for e in validator.iter_errors(attempt_obj)]
    return len(errors) == 0, errors


def is_attempt_trusted_and_scored(attempt_obj: Dict[str, Any]) -> Tuple[bool, Optional[bool], str]:
    """Evaluates whether an attempt is trusted, scored, and eligible for knowledge tracing updates.
    
    Rules:
    - Attempt must be valid against attempt_schema.json.
    - outcome.scoring_status MUST be 'scored'.
    - outcome.is_correct MUST be boolean (not null).
    - outcome.scoring_source MUST be trusted ('server_key', 'rubric', 'human_review').
      Attempts scored by 'unknown' or unverified sources are rejected from model updates.
    
    Returns:
        (is_eligible: bool, is_correct: Optional[bool], reason: str)
    """
    is_valid, schema_errors = validate_json_attempt(attempt_obj)
    if not is_valid:
        return False, None, f"Schema validation failed: {schema_errors[:2]}"

    outcome = attempt_obj.get("outcome", {})
    status = outcome.get("scoring_status")
    if status != "scored":
        return False, None, f"Attempt is unscored (scoring_status: '{status}')"

    is_correct = outcome.get("is_correct")
    if is_correct is None or not isinstance(is_correct, bool):
        return False, None, "outcome.is_correct is null or not a boolean"

    scoring_source = outcome.get("scoring_source", "unknown")
    trusted_sources = {"server_key", "rubric", "human_review", "external_service"}
    if scoring_source not in trusted_sources:
        return False, None, f"Untrusted scoring source: '{scoring_source}'"

    return True, is_correct, "Scored and trusted"


def load_json_attempts(source: Union[str, Path, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Loads a JSON attempt file or parses a list of attempt dictionaries."""
    if isinstance(source, list):
        return source
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"Attempt JSON file not found: {path.resolve()}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    elif isinstance(data, list):
        return data
    raise ValueError(f"Attempt JSON file must contain an object or array: {path.resolve()}")


# -----------------------------------------------------------------------------
# 6. Synthetic Interaction to Attempt Adapter (Documented Fixture Bridge)
# -----------------------------------------------------------------------------

def interaction_row_to_attempt(
    row: Union[pd.Series, Dict[str, Any]],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Converts a synthetic interaction record into a contract-compliant attempt payload.
    
    Documented mapping semantics:
    - student_id -> learner_id
    - timestamp_utc -> submitted_at
    - interaction_id -> attempt_id and idempotency_key
    - question_type: 'single_correct_mcq' -> 'single_choice', 'numerical' -> 'numeric'
    - correct: 1/0 -> outcome.is_correct (True/False) and outcome.score (1.0/0.0)
    - outcome.scoring_status: set to 'scored'
    - outcome.scoring_source: set to 'server_key'
    """
    r = row if isinstance(row, dict) else row.to_dict()

    raw_qtype = str(r.get("question_type", "single_correct_mcq"))
    qtype_map = {
        "single_correct_mcq": "single_choice",
        "numerical": "numeric",
        "single_choice": "single_choice",
        "numeric": "numeric",
        "multiple_select": "multiple_select",
    }
    response_type = qtype_map.get(raw_qtype, "other")

    is_correct = bool(r.get("correct", 0) == 1)
    sub_at = str(r.get("timestamp_utc", "2025-01-01T00:00:00Z"))

    attempt_payload: Dict[str, Any] = {
        "attempt_id": str(r.get("interaction_id", "ATTEMPT_UNKNOWN")),
        "learner_id": str(r.get("student_id", "LEARNER_UNKNOWN")),
        "question_id": str(r.get("question_id", "QUESTION_UNKNOWN")),
        "submitted_at": sub_at,
        "response": {
            "response_type": response_type,
            "value": "SIMULATED_RESPONSE",
            "work_steps": [],
        },
        "outcome": {
            "scoring_status": "scored",
            "is_correct": is_correct,
            "score": 1.0 if is_correct else 0.0,
            "max_score": 1.0,
            "scored_at": sub_at,
            "scoring_source": "server_key",
        },
        "context": {
            "session_id": session_id or f"SESSION_{r.get('student_id', '0')}",
            "item_index": int(r.get("sequence_index", 1)) - 1,
            "response_time_ms": int(float(r.get("response_time_seconds", 60)) * 1000),
            "hint_count": int(r.get("hint_used", 0)),
        },
        "idempotency_key": str(r.get("interaction_id", "ATTEMPT_UNKNOWN")),
        "schema_version": "0.1",
    }
    return attempt_payload

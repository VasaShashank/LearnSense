"""LearnSense Person 3 — Bayesian Knowledge Tracing (BKT) Engine.

Provides mathematically pure, side-effect-free implementations of:
1. Standard BKT prediction, Bayesian posterior update, and transition.
2. Robust boundary handling and clamping in [0.001, 0.999].
3. Versioned parameter configuration manager (JSON & CSV).
4. Multi-concept attribution policies:
   - 'primary_only': Production baseline updating only primary_concept_id without evidence inflation.
   - 'conjunctive': Noisy-AND joint prediction and Bayesian attribution.
5. Deterministic trajectory replay engine producing state representations
   compatible with contracts/learner_state_schema.json.
"""

from __future__ import annotations

import copy
import csv
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd

from src.ingestion import parse_concept_ids

# -----------------------------------------------------------------------------
# 1. Parameter Bounds and Numerical Constants
# -----------------------------------------------------------------------------

PARAM_MIN: float = 0.001
PARAM_MAX: float = 0.999
PROB_EPSILON: float = 1e-12

DEFAULT_CONFIG_ID: str = "generic_sanity_baseline"


# -----------------------------------------------------------------------------
# 2. Data Structures for Mathematical Steps and Configurations
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class BKTParameters:
    """Standard 4-parameter BKT bundle constrained to [0.001, 0.999].
    
    Attributes:
        p_l0: Initial probability of mastery prior to any observations.
        p_t: Probability of transitioning from unmastered to mastered.
        p_g: Probability of a correct response while unmastered (guess).
        p_s: Probability of an incorrect response while mastered (slip).
    """
    p_l0: float
    p_t: float
    p_g: float
    p_s: float

    def __post_init__(self) -> None:
        for name, val in [("p_l0", self.p_l0), ("p_t", self.p_t), ("p_g", self.p_g), ("p_s", self.p_s)]:
            if val is None or not isinstance(val, (int, float)):
                raise TypeError(f"Parameter '{name}' must be numeric. Found: {type(val)}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"Parameter '{name}' cannot be NaN or infinite. Found: {val}")
            if not (PARAM_MIN <= val <= PARAM_MAX):
                raise ValueError(
                    f"Parameter '{name}'={val} violates required bounds [{PARAM_MIN}, {PARAM_MAX}]."
                )

    @property
    def p_init(self) -> float:
        return self.p_l0

    @property
    def p_transition(self) -> float:
        return self.p_t

    @property
    def p_guess(self) -> float:
        return self.p_g

    @property
    def p_slip(self) -> float:
        return self.p_s

    def to_dict(self) -> Dict[str, float]:
        return {
            "p_l0": float(self.p_l0),
            "p_t": float(self.p_t),
            "p_g": float(self.p_g),
            "p_s": float(self.p_s),
        }


@dataclass
class BKTStepResult:
    """Result of a single-step BKT evaluation and belief transition."""
    concept_id: str
    p_mastery_prior: float
    p_correct_pred: float
    response: int
    p_mastery_posterior: float
    p_mastery_next: float
    parameters: BKTParameters


@dataclass
class BKTConfig:
    """Versioned BKT parameter configuration bundle.
    
    Attributes:
        config_id: Unique string identifier for the parameter set.
        version: Semantic or bundle version string.
        model_type: Name of knowledge tracing model (default 'standard_bkt').
        parameters: Global fallback BKTParameters.
        concept_overrides: Concept-specific parameter overrides.
        provenance: Explicit source/lineage explanation.
        status: Status flag (e.g. 'provisional', 'candidate', 'selected', 'deprecated').
        creation_method: Description of fitting or assignment method.
        source_dataset: Name/version of dataset split used for fitting (e.g. 'v3_train').
        notes: Contextual documentation.
    """
    config_id: str
    version: str = "1.0"
    model_type: str = "standard_bkt"
    parameters: BKTParameters = field(
        default_factory=lambda: BKTParameters(p_l0=0.30, p_t=0.10, p_g=0.20, p_s=0.10)
    )
    concept_overrides: Dict[str, BKTParameters] = field(default_factory=dict)
    provenance: str = "illustrative_unsourced_values"
    status: str = "provisional"
    creation_method: str = "heuristic_baseline"
    source_dataset: str = "none"
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.config_id or not isinstance(self.config_id, str):
            raise ValueError("BKTConfig 'config_id' must be a non-empty string.")
        if not self.version or not isinstance(self.version, str):
            raise ValueError("BKTConfig 'version' must be a non-empty string.")

    def get_parameters_for_concept(self, concept_id: str) -> BKTParameters:
        """Resolves parameters with concept override taking precedence over global."""
        cid = str(concept_id).strip()
        if cid in self.concept_overrides:
            return self.concept_overrides[cid]
        return self.parameters

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_id": self.config_id,
            "version": self.version,
            "model_type": self.model_type,
            "parameters": self.parameters.to_dict(),
            "concept_overrides": {k: v.to_dict() for k, v in self.concept_overrides.items()},
            "provenance": self.provenance,
            "status": self.status,
            "creation_method": self.creation_method,
            "source_dataset": self.source_dataset,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BKTConfig:
        raw_p = data.get("parameters", {})
        params = BKTParameters(
            p_l0=float(raw_p.get("p_l0", raw_p.get("p_init", 0.30))),
            p_t=float(raw_p.get("p_t", raw_p.get("p_transition", 0.10))),
            p_g=float(raw_p.get("p_g", raw_p.get("p_guess", 0.20))),
            p_s=float(raw_p.get("p_s", raw_p.get("p_slip", 0.10))),
        )
        raw_overrides = data.get("concept_overrides", {})
        overrides: Dict[str, BKTParameters] = {}
        for cid, cp in raw_overrides.items():
            overrides[str(cid)] = BKTParameters(
                p_l0=float(cp.get("p_l0", cp.get("p_init", params.p_l0))),
                p_t=float(cp.get("p_t", cp.get("p_transition", params.p_t))),
                p_g=float(cp.get("p_g", cp.get("p_guess", params.p_g))),
                p_s=float(cp.get("p_s", cp.get("p_slip", params.p_s))),
            )
        return cls(
            config_id=str(data["config_id"]),
            version=str(data.get("version", "1.0")),
            model_type=str(data.get("model_type", "standard_bkt")),
            parameters=params,
            concept_overrides=overrides,
            provenance=str(data.get("provenance", "unknown")),
            status=str(data.get("status", "provisional")),
            creation_method=str(data.get("creation_method", "heuristic")),
            source_dataset=str(data.get("source_dataset", "none")),
            notes=str(data.get("notes", "")),
        )


# -----------------------------------------------------------------------------
# 3. Core Mathematical Functions (Pure & Side-Effect Free)
# -----------------------------------------------------------------------------

def clamp_probability(val: float, min_val: float = PARAM_MIN, max_val: float = PARAM_MAX) -> float:
    """Clamps probability value strictly within specified numerical bounds."""
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Cannot clamp NaN or infinite value: {val}")
    return max(min_val, min(max_val, float(val)))


def predict_correctness(p_mastery: float, p_guess: float, p_slip: float) -> float:
    """Computes pre-response probability of a correct response.
    
    Formula:
        P(correct) = P(L) * (1 - P(S)) + (1 - P(L)) * P(G)
        
    Args:
        p_mastery: Pre-response mastery belief P(L).
        p_guess: Probability of guess P(G).
        p_slip: Probability of slip P(S).
        
    Returns:
        float: Predicted probability of correctness in [PARAM_MIN, PARAM_MAX].
    """
    if not (0.0 <= p_mastery <= 1.0):
        raise ValueError(f"Mastery probability must be in [0, 1]. Found: {p_mastery}")
    if math.isnan(p_mastery) or math.isnan(p_guess) or math.isnan(p_slip):
        raise ValueError("Inputs to predict_correctness cannot be NaN.")

    p_corr = p_mastery * (1.0 - p_slip) + (1.0 - p_mastery) * p_guess
    return clamp_probability(p_corr)


def update_mastery_posterior(
    p_mastery: float,
    response: int,
    p_guess: float,
    p_slip: float,
) -> float:
    """Calculates Bayesian posterior mastery belief given binary response outcome.
    
    Formulas:
        For y = 1:
            P(L | y=1) = [P(L) * (1 - P(S))] / P(correct)
        For y = 0:
            P(L | y=0) = [P(L) * P(S)] / [1 - P(correct)]
                       = [P(L) * P(S)] / [P(L)*P(S) + (1-P(L))*(1-P(G))]
                       
    Args:
        p_mastery: Prior mastery belief P(L) in [0, 1].
        response: Binary outcome (1 for correct, 0 for incorrect).
        p_guess: Slip probability P(G).
        p_slip: Guess probability P(S).
        
    Returns:
        float: Post-observation Bayesian posterior clamped to [PARAM_MIN, PARAM_MAX].
    """
    if response not in (0, 1):
        raise ValueError(f"Response label must be binary 0 or 1. Found: {response}")
    if not (0.0 <= p_mastery <= 1.0):
        raise ValueError(f"p_mastery must be in [0, 1]. Found: {p_mastery}")

    p_correct = p_mastery * (1.0 - p_slip) + (1.0 - p_mastery) * p_guess

    if response == 1:
        denom = p_correct
        if denom < PROB_EPSILON:
            post = PARAM_MAX if p_mastery > 0.5 else PARAM_MIN
        else:
            post = (p_mastery * (1.0 - p_slip)) / denom
    else:
        denom = 1.0 - p_correct
        if denom < PROB_EPSILON:
            post = PARAM_MIN
        else:
            post = (p_mastery * p_slip) / denom

    return clamp_probability(post)


def apply_learning_transition(p_posterior: float, p_transition: float) -> float:
    """Applies monotonic learning transition from unmastered to mastered state.
    
    Formula:
        P(L_next) = P(L_post) + (1 - P(L_post)) * P(T)
        
    Args:
        p_posterior: Bayesian posterior mastery after observation.
        p_transition: Learning transition rate P(T).
        
    Returns:
        float: Updated mastery for next opportunity clamped to [PARAM_MIN, PARAM_MAX].
    """
    if not (0.0 <= p_posterior <= 1.0):
        raise ValueError(f"Posterior probability must be in [0, 1]. Found: {p_posterior}")
    if not (0.0 <= p_transition <= 1.0):
        raise ValueError(f"Transition probability must be in [0, 1]. Found: {p_transition}")

    p_next = p_posterior + (1.0 - p_posterior) * p_transition
    return clamp_probability(p_next)


def evaluate_and_update_bkt_step(
    p_mastery_prior: float,
    response: int,
    parameters: BKTParameters,
    concept_id: str = "default_concept",
) -> BKTStepResult:
    """Executes a complete single-step BKT sequence with clean intermediate tracking.
    
    Sequence:
    1. Pre-response prediction P(correct).
    2. Observation of response y.
    3. Bayesian posterior update P(L | y).
    4. Learning transition to P(L_next).
    """
    p_pred = predict_correctness(p_mastery_prior, parameters.p_guess, parameters.p_slip)
    p_post = update_mastery_posterior(p_mastery_prior, response, parameters.p_guess, parameters.p_slip)
    p_next = apply_learning_transition(p_post, parameters.p_transition)

    return BKTStepResult(
        concept_id=str(concept_id),
        p_mastery_prior=float(p_mastery_prior),
        p_correct_pred=float(p_pred),
        response=int(response),
        p_mastery_posterior=float(p_post),
        p_mastery_next=float(p_next),
        parameters=parameters,
    )


# -----------------------------------------------------------------------------
# 4. Multi-Concept Item Prediction & Attribution Strategies
# -----------------------------------------------------------------------------

def predict_conjunctive_correctness(
    concept_masteries: Sequence[float],
    p_guess: float,
    p_slip: float,
) -> float:
    """Computes joint probability of correctness for multi-concept item under Noisy-AND.
    
    Formula:
        L_joint = prod_{k=1..K} L_k
        P(correct) = L_joint * (1 - P(S)) + (1 - L_joint) * P(G)
        
    Args:
        concept_masteries: List/array of concept mastery probabilities L_k.
        p_guess: Slip rate P(G).
        p_slip: Guess rate P(S).
    """
    if not concept_masteries:
        raise ValueError("concept_masteries cannot be empty.")
    for val in concept_masteries:
        if not (0.0 <= val <= 1.0):
            raise ValueError(f"All mastery probabilities must be in [0, 1]. Found: {val}")

    l_joint = float(np.prod(concept_masteries))
    p_correct = l_joint * (1.0 - p_slip) + (1.0 - l_joint) * p_guess
    return clamp_probability(p_correct)


def update_conjunctive_posteriors(
    concept_ids: Sequence[str],
    concept_masteries: Sequence[float],
    response: int,
    p_guess: float,
    p_slip: float,
) -> Dict[str, float]:
    """Computes exact Bayesian marginal posteriors P(L_k = 1 | Y) under conjunctive Noisy-AND.
    
    Formulas:
        Let L_joint_k = prod_{j != k} L_j.
        P(Y = 1 | L_k = 1) = L_joint_k * (1 - S) + (1 - L_joint_k) * G
        P(Y = 0 | L_k = 1) = 1 - P(Y = 1 | L_k = 1)
        
        P(L_k = 1 | Y) = [ P(L_k) * P(Y | L_k = 1) ] / P(Y)
    """
    if response not in (0, 1):
        raise ValueError(f"Response must be binary 0 or 1. Found: {response}")
    if len(concept_ids) != len(concept_masteries):
        raise ValueError("Length mismatch between concept_ids and concept_masteries.")
    if not concept_ids:
        raise ValueError("concept_ids cannot be empty.")

    p_corr_joint = predict_conjunctive_correctness(concept_masteries, p_guess, p_slip)
    py = p_corr_joint if response == 1 else (1.0 - p_corr_joint)

    posteriors: Dict[str, float] = {}
    for idx, (cid, l_k) in enumerate(zip(concept_ids, concept_masteries)):
        other_masteries = [m for j, m in enumerate(concept_masteries) if j != idx]
        l_other = float(np.prod(other_masteries)) if other_masteries else 1.0

        p_correct_given_lk1 = l_other * (1.0 - p_slip) + (1.0 - l_other) * p_guess
        p_y_given_lk1 = p_correct_given_lk1 if response == 1 else (1.0 - p_correct_given_lk1)

        if py < PROB_EPSILON:
            post = PARAM_MIN
        else:
            post = (l_k * p_y_given_lk1) / py

        posteriors[cid] = clamp_probability(post)

    return posteriors


# -----------------------------------------------------------------------------
# 5. Parameter Configuration Manager (JSON & CSV)
# -----------------------------------------------------------------------------

def load_bkt_candidate_configs_csv(file_path: Union[str, Path]) -> Dict[str, BKTConfig]:
    """Loads candidate BKT configurations from a CSV file.
    
    Required columns: config_id, p_l0, p_t, p_g, p_s
    Optional columns: provenance, status, notes, creation_method, source_dataset
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")

    configs: Dict[str, BKTConfig] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        
        # Check required columns (supporting standard aliases)
        col_l0 = "p_l0" if "p_l0" in fieldnames else ("p_init" if "p_init" in fieldnames else None)
        col_t = "p_t" if "p_t" in fieldnames else ("p_transition" if "p_transition" in fieldnames else None)
        col_g = "p_g" if "p_g" in fieldnames else ("p_guess" if "p_guess" in fieldnames else None)
        col_s = "p_s" if "p_s" in fieldnames else ("p_slip" if "p_slip" in fieldnames else None)

        if not ("config_id" in fieldnames and col_l0 and col_t and col_g and col_s):
            missing = []
            if "config_id" not in fieldnames: missing.append("config_id")
            if not col_l0: missing.append("p_l0/p_init")
            if not col_t: missing.append("p_t/p_transition")
            if not col_g: missing.append("p_g/p_guess")
            if not col_s: missing.append("p_s/p_slip")
            raise ValueError(f"CSV configuration file missing required columns: {missing}")

        for row_idx, row in enumerate(reader, start=2):
            cfg_id = row["config_id"].strip()
            if not cfg_id:
                raise ValueError(f"Empty config_id on row {row_idx}")
            if cfg_id in configs:
                raise ValueError(f"Duplicate config_id '{cfg_id}' detected on row {row_idx}")

            try:
                p_l0 = float(row[col_l0])
                p_t = float(row[col_t])
                p_g = float(row[col_g])
                p_s = float(row[col_s])
            except ValueError as e:
                raise ValueError(f"Non-numeric parameter on row {row_idx}: {e}")

            params = BKTParameters(p_l0=p_l0, p_t=p_t, p_g=p_g, p_s=p_s)
            configs[cfg_id] = BKTConfig(
                config_id=cfg_id,
                version=row.get("version", "1.0").strip() or "1.0",
                model_type=row.get("model_type", "standard_bkt").strip() or "standard_bkt",
                parameters=params,
                provenance=row.get("provenance", "csv_candidate").strip(),
                status=row.get("status", "provisional").strip(),
                creation_method=row.get("creation_method", "csv_import").strip(),
                source_dataset=row.get("source_dataset", "none").strip(),
                notes=row.get("notes", "").strip(),
            )

    return configs


def load_bkt_config_json(file_path: Union[str, Path]) -> Union[BKTConfig, Dict[str, BKTConfig]]:
    """Loads a single BKTConfig or dictionary of BKTConfigs from a JSON manifest."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"JSON configuration file not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "candidates" in data and isinstance(data["candidates"], list):
            # Format used in data/research/configs/bkt_candidates.json
            configs: Dict[str, BKTConfig] = {}
            for item in data["candidates"]:
                cfg_id = item["config_id"]
                params = BKTParameters(
                    p_l0=float(item.get("p_l0", item.get("p_init", 0.30))),
                    p_t=float(item.get("p_t", item.get("p_transition", 0.10))),
                    p_g=float(item.get("p_g", item.get("p_guess", 0.20))),
                    p_s=float(item.get("p_s", item.get("p_slip", 0.10))),
                )
                configs[cfg_id] = BKTConfig(
                    config_id=cfg_id,
                    version=str(data.get("schema_version", "1.0")),
                    parameters=params,
                    provenance=item.get("provenance", "research_candidate"),
                    status=item.get("status", "provisional"),
                    notes=data.get("note", ""),
                )
            return configs
        elif "config_id" in data:
            return BKTConfig.from_dict(data)

    raise ValueError(f"Unrecognized BKT JSON format in {path.resolve()}")


def save_bkt_config_json(config: BKTConfig, file_path: Union[str, Path]) -> None:
    """Serializes a BKTConfig instance to a versioned JSON document."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)


# -----------------------------------------------------------------------------
# 6. Learner State Container & Contract Serialization
# -----------------------------------------------------------------------------

@dataclass
class LearnerConceptState:
    """Represents a learner's evolving knowledge state for a single concept."""
    learner_id: str
    concept_id: str
    mastery_probability: float
    evidence_count: int = 0
    last_attempt_id: Optional[str] = None
    last_evidence_at: Optional[str] = None
    updated_at: Optional[str] = None
    status: str = "unassessed"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_contract_payload(self, model_info: Dict[str, Any]) -> Dict[str, Any]:
        """Formats the state into a payload strictly conforming to learner_state_schema.json."""
        # Derive status from evidence_count if unassigned
        status = self.status
        if status == "unassessed" and self.evidence_count > 0:
            status = "provisional" if self.evidence_count < 5 else "estimated"

        return {
            "learner_id": str(self.learner_id),
            "concept_id": str(self.concept_id),
            "mastery_probability": float(round(self.mastery_probability, 6)),
            "evidence_count": int(self.evidence_count),
            "last_attempt_id": self.last_attempt_id,
            "last_evidence_at": self.last_evidence_at,
            "updated_at": self.updated_at or self.last_evidence_at or "2026-10-20T00:00:00Z",
            "model": {
                "name": str(model_info.get("name", "bkt")),
                "version": str(model_info.get("version", "1.0")),
                "parameters_id": model_info.get("parameters_id"),
                "extensions": list(model_info.get("extensions", [])),
            },
            "status": status,
            "metadata": copy.deepcopy(self.metadata),
        }


# -----------------------------------------------------------------------------
# 7. Deterministic Trajectory Replay Engine
# -----------------------------------------------------------------------------

@dataclass
class ReplayStep:
    """Detailed log record of an interaction processed during trajectory replay."""
    interaction_id: str
    student_id: str
    sequence_index: int
    question_id: str
    target_concept_id: str
    p_prior: float
    p_pred: float
    outcome: int
    p_posterior: float
    p_next: float
    policy: str
    co_occurring_concepts: List[str] = field(default_factory=list)
    fractional_evidence: Optional[Dict[str, float]] = None


@dataclass
class TrajectoryReplayResult:
    """Aggregated output from a deterministic trajectory replay run."""
    steps: List[ReplayStep]
    final_states: Dict[Tuple[str, str], LearnerConceptState]  # (student_id, concept_id) -> state
    config: BKTConfig
    policy: str

    def get_student_states(self, student_id: str) -> Dict[str, LearnerConceptState]:
        """Returns concept_id -> state mapping for a specific student."""
        return {
            cid: state
            for (sid, cid), state in self.final_states.items()
            if sid == student_id
        }

    def to_contract_states(self) -> List[Dict[str, Any]]:
        """Serializes all final concept states into schema-compliant dictionaries."""
        model_info = {
            "name": "bkt",
            "version": self.config.version,
            "parameters_id": self.config.config_id,
            "extensions": [self.policy],
        }
        return [
            state.to_contract_payload(model_info)
            for state in self.final_states.values()
        ]


def replay_interactions(
    interactions: Union[pd.DataFrame, Sequence[Dict[str, Any]]],
    config: BKTConfig,
    policy: str = "primary_only",
    initial_states: Optional[Dict[Tuple[str, str], LearnerConceptState]] = None,
) -> TrajectoryReplayResult:
    """Executes pure, deterministic trajectory replay across an interaction sequence.
    
    Guarantees:
    1. Pre-response prediction generated strictly prior to outcome observation.
    2. Interactions ordered deterministically by student_id and sequence_index.
    3. State isolation: observation for student A never mutates student B.
    4. Exact multi-concept policy enforcement ('primary_only' vs 'conjunctive').
    5. Pure execution: does not mutate source data or input records.
    
    Args:
        interactions: DataFrame or sequence of interaction dicts.
        config: Versioned BKT parameter bundle.
        policy: 'primary_only' (default production baseline) or 'conjunctive'.
        initial_states: Optional pre-existing concept states to resume from.
        
    Returns:
        TrajectoryReplayResult: Sequence of steps and final learner-concept states.
    """
    if policy not in {"primary_only", "conjunctive"}:
        raise ValueError(f"Unsupported multi-concept policy '{policy}'. Permitted: 'primary_only', 'conjunctive'")

    # 1. Normalize and validate input structure
    if isinstance(interactions, pd.DataFrame):
        if interactions.empty:
            return TrajectoryReplayResult(steps=[], final_states={}, config=config, policy=policy)
        # Check required columns
        req = {"student_id", "sequence_index", "primary_concept_id", "correct"}
        missing = req - set(interactions.columns)
        if missing:
            raise ValueError(f"Interactions DataFrame missing required columns: {missing}")
        # Deterministic sorting
        sort_cols = ["student_id", "sequence_index"]
        if "timestamp_utc" in interactions.columns:
            sort_cols.append("timestamp_utc")
        sorted_df = interactions.sort_values(by=sort_cols).reset_index(drop=True)
        records = sorted_df.to_dict("records")
    else:
        if not interactions:
            return TrajectoryReplayResult(steps=[], final_states={}, config=config, policy=policy)
        # Convert to list and sort deterministically
        records = sorted(
            interactions,
            key=lambda r: (
                str(r.get("student_id", "")),
                int(r.get("sequence_index", 0)),
                str(r.get("timestamp_utc", "")),
            ),
        )

    # 2. Initialize state dictionary (keyed by (student_id, concept_id))
    states: Dict[Tuple[str, str], LearnerConceptState] = (
        copy.deepcopy(initial_states) if initial_states is not None else {}
    )

    steps: List[ReplayStep] = []

    def get_or_create_state(sid: str, cid: str) -> LearnerConceptState:
        key = (sid, cid)
        if key not in states:
            params = config.get_parameters_for_concept(cid)
            states[key] = LearnerConceptState(
                learner_id=sid,
                concept_id=cid,
                mastery_probability=params.p_l0,
                evidence_count=0,
                status="unassessed",
            )
        return states[key]

    # 3. Step through chronological interactions
    for rec in records:
        sid = str(rec["student_id"])
        seq_idx = int(rec["sequence_index"])
        int_id = str(rec.get("interaction_id", f"INT_{sid}_{seq_idx}"))
        qid = str(rec.get("question_id", "Q_UNKNOWN"))
        primary_cid = str(rec["primary_concept_id"]).strip()
        try:
            outcome = int(rec["correct"])
            if outcome not in (0, 1):
                raise ValueError(f"Correctness outcome must be binary 0 or 1. Found: {rec['correct']}")
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid correctness outcome on interaction '{int_id}': {e}")

        ts = str(rec.get("timestamp_utc", "2026-10-20T00:00:00Z"))

        # Parse associated concepts and guarantee primary concept is at index 0
        raw_concept_ids = rec.get("concept_ids", primary_cid)
        parsed_cids = parse_concept_ids(raw_concept_ids)
        if primary_cid in parsed_cids:
            parsed_cids.remove(primary_cid)
        parsed_cids.insert(0, primary_cid)

        co_occurring = parsed_cids[1:]

        if policy == "primary_only":
            # --- Primary-Only Strategy (Production Baseline) ---
            primary_params = config.get_parameters_for_concept(primary_cid)
            pri_state = get_or_create_state(sid, primary_cid)

            prior_mastery = pri_state.mastery_probability
            step_res = evaluate_and_update_bkt_step(
                p_mastery_prior=prior_mastery,
                response=outcome,
                parameters=primary_params,
                concept_id=primary_cid,
            )

            # Mutate state strictly for primary concept
            pri_state.mastery_probability = step_res.p_mastery_next
            pri_state.evidence_count += 1
            pri_state.last_attempt_id = int_id
            pri_state.last_evidence_at = ts
            pri_state.updated_at = ts
            pri_state.status = "provisional" if pri_state.evidence_count < 5 else "estimated"
            pri_state.metadata["last_co_occurring_concepts"] = co_occurring

            # Secondary concepts are NOT mutated; no evidence inflation
            steps.append(
                ReplayStep(
                    interaction_id=int_id,
                    student_id=sid,
                    sequence_index=seq_idx,
                    question_id=qid,
                    target_concept_id=primary_cid,
                    p_prior=prior_mastery,
                    p_pred=step_res.p_correct_pred,
                    outcome=outcome,
                    p_posterior=step_res.p_mastery_posterior,
                    p_next=step_res.p_mastery_next,
                    policy="primary_only",
                    co_occurring_concepts=co_occurring,
                    fractional_evidence=None,
                )
            )

        elif policy == "conjunctive":
            # --- Conjunctive Strategy (Opt-in Research Policy) ---
            c_states = [get_or_create_state(sid, cid) for cid in parsed_cids]
            priors = [cs.mastery_probability for cs in c_states]

            # Use primary concept parameters for item slip/guess reference
            ref_params = config.get_parameters_for_concept(primary_cid)
            p_pred_joint = predict_conjunctive_correctness(priors, ref_params.p_guess, ref_params.p_slip)

            # Compute exact Bayesian marginal posteriors
            posteriors = update_conjunctive_posteriors(
                concept_ids=parsed_cids,
                concept_masteries=priors,
                response=outcome,
                p_guess=ref_params.p_guess,
                p_slip=ref_params.p_slip,
            )

            # Update each concept with its transition rate
            fractional_weight = 1.0 / len(parsed_cids)
            frac_dict: Dict[str, float] = {}

            for cs in c_states:
                cid = cs.concept_id
                c_params = config.get_parameters_for_concept(cid)
                post_k = posteriors[cid]
                next_k = apply_learning_transition(post_k, c_params.p_transition)

                cs.mastery_probability = next_k
                # Evidence bookkeeping vs Bayesian inference:
                # 1. Bayesian posterior inference: post_k = P(L_k = 1 | response)
                # 2. Learning transition: next_k = post_k + (1 - post_k) * p_transition
                # 3. Evidence count: Integer evidence count is only incremented for the primary concept (no integer inflation).
                # 4. Bookkeeping metadata: fractional opportunity share (1/K) records the accounting weight across
                #    co-occurring concepts, explicitly distinguished from the Bayesian marginal posterior.
                if cid == primary_cid:
                    cs.evidence_count += 1
                cs.last_attempt_id = int_id
                cs.last_evidence_at = ts
                cs.updated_at = ts
                cs.status = "provisional" if cs.evidence_count < 5 else "estimated"
                cs.metadata["last_marginal_posterior"] = post_k
                cs.metadata["fractional_opportunity_share"] = fractional_weight
                cs.metadata["fractional_evidence_credit"] = cs.metadata.get("fractional_evidence_credit", 0.0) + fractional_weight
                frac_dict[cid] = fractional_weight

            steps.append(
                ReplayStep(
                    interaction_id=int_id,
                    student_id=sid,
                    sequence_index=seq_idx,
                    question_id=qid,
                    target_concept_id=primary_cid,
                    p_prior=priors[0],
                    p_pred=p_pred_joint,
                    outcome=outcome,
                    p_posterior=posteriors[primary_cid],
                    p_next=c_states[0].mastery_probability,
                    policy="conjunctive",
                    co_occurring_concepts=co_occurring,
                    fractional_evidence=frac_dict,
                )
            )

    return TrajectoryReplayResult(steps=steps, final_states=states, config=config, policy=policy)

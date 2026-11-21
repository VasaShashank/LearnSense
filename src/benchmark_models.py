"""Traditional and BKT-based models for the comprehensive benchmark.

All models consume only pre-response fields. Effect tables, history counts, and
hyperparameters are fitted on training data; validation is used for model
selection. The functions here deliberately keep the statistical models separate
from the neural sequence models.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from src.baselines import PROBABILITY_EPSILON, evaluate_predictions
from src.bkt import (
    BKTConfig,
    apply_learning_transition,
    evaluate_and_update_bkt_step,
    predict_correctness,
    replay_interactions,
    update_mastery_posterior,
)
from src.v4_benchmark import EffectTable, fit_effect_table

DIFFICULTY_ORDER: Tuple[str, ...] = ("easy", "medium", "hard")
DEFAULT_C_GRID: Tuple[float, ...] = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
PFA_C_GRID: Tuple[float, ...] = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0)


def clip_probabilities(values: Sequence[float]) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)


def logit(values: Sequence[float]) -> np.ndarray:
    p = clip_probabilities(values)
    return np.log(p / (1.0 - p))


def sigmoid(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return 1.0 / (1.0 + np.exp(-np.clip(arr, -35.0, 35.0)))


def add_history_features(
    targets: pd.DataFrame,
    *,
    population_probability: float,
    smoothing_m: float = 10.0,
) -> pd.DataFrame:
    """Adds strictly prior learner, concept, and item response counts."""

    df = targets.sort_values(
        by=["student_id", "sequence_index", "timestamp_utc"],
        kind="mergesort",
    ).reset_index(drop=True).copy()
    if "correct" not in df.columns:
        raise ValueError("Targets must contain 'correct'.")
    pop = float(np.clip(population_probability, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON))
    m = float(smoothing_m)

    student = df.groupby("student_id", sort=False)
    df["prior_overall_n"] = student.cumcount().astype(int)
    df["prior_overall_correct"] = (
        student["correct"].cumsum() - df["correct"]
    ).astype(int)
    df["prior_overall_incorrect"] = df["prior_overall_n"] - df["prior_overall_correct"]
    df["prior_overall_last_correct"] = (
        student["correct"].shift(1).fillna(pop).astype(float)
    )

    concept = df.groupby(["student_id", "primary_concept_id"], sort=False)
    df["prior_concept_n"] = concept.cumcount().astype(int)
    df["prior_concept_correct"] = (
        concept["correct"].cumsum() - df["correct"]
    ).astype(int)
    df["prior_concept_incorrect"] = df["prior_concept_n"] - df["prior_concept_correct"]
    df["prior_concept_last_correct"] = (
        concept["correct"].shift(1).fillna(pop).astype(float)
    )

    item = df.groupby(["student_id", "question_id"], sort=False)
    df["prior_item_n"] = item.cumcount().astype(int)
    df["prior_item_correct"] = (
        item["correct"].cumsum() - df["correct"]
    ).astype(int)
    df["prior_item_incorrect"] = df["prior_item_n"] - df["prior_item_correct"]

    df["prior_overall_rate_smoothed"] = (
        df["prior_overall_correct"] + m * pop
    ) / (df["prior_overall_n"] + m)
    df["prior_concept_rate_smoothed"] = (
        df["prior_concept_correct"] + m * pop
    ) / (df["prior_concept_n"] + m)
    df["log1p_prior_overall_n"] = np.log1p(df["prior_overall_n"].astype(float))
    df["log1p_prior_concept_n"] = np.log1p(df["prior_concept_n"].astype(float))

    if "days_since_concept_practice" not in df.columns:
        df["days_since_concept_practice"] = 0.0
    if "days_since_previous_interaction" not in df.columns:
        df["days_since_previous_interaction"] = 0.0
    for column in ("days_since_concept_practice", "days_since_previous_interaction"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0).clip(lower=0.0)
    df["log1p_days_since_concept_practice"] = np.log1p(
        df["days_since_concept_practice"].astype(float)
    )
    df["log1p_days_since_previous_interaction"] = np.log1p(
        df["days_since_previous_interaction"].astype(float)
    )
    return df


def add_concept_features(
    targets: pd.DataFrame,
    concept_effects: EffectTable,
) -> pd.DataFrame:
    df = targets.copy()
    df["concept_logit"] = concept_effects.map_logit(df["primary_concept_id"])
    concept_values = df["concept_ids"].fillna(df["primary_concept_id"]).astype(str)
    exploded = concept_values.str.split(";").explode().str.strip()
    mapped = exploded.map(concept_effects.logits)
    mean_logit = mapped.groupby(level=0).mean()
    max_logit = mapped.groupby(level=0).max()
    df["concept_mean_logit"] = mean_logit.reindex(df.index).fillna(
        concept_effects.population_logit
    ).to_numpy(dtype=float)
    df["concept_max_logit"] = max_logit.reindex(df.index).fillna(
        concept_effects.population_logit
    ).to_numpy(dtype=float)
    df["is_multi_concept"] = df["is_multi_concept"].astype(bool)
    df["concept_count"] = df["concept_count"].astype(float)
    return df


@dataclass
class StaticTables:
    item: EffectTable
    concept: EffectTable
    difficulty: EffectTable
    difficulty_categories: Tuple[str, ...]
    difficulty_reference: str


def fit_static_tables(
    train_targets: pd.DataFrame,
    *,
    item_prior_strength_m: float = 10.0,
) -> StaticTables:
    categories = tuple(
        category for category in DIFFICULTY_ORDER if category in set(train_targets["difficulty"])
    )
    if not categories:
        categories = tuple(sorted(train_targets["difficulty"].astype(str).unique()))
    return StaticTables(
        item=fit_effect_table(
            train_targets,
            "question_id",
            prior_strength_m=item_prior_strength_m,
        ),
        concept=fit_effect_table(
            train_targets,
            "primary_concept_id",
            prior_strength_m=10.0,
        ),
        difficulty=fit_effect_table(
            train_targets,
            "difficulty",
            prior_strength_m=10.0,
        ),
        difficulty_categories=categories,
        difficulty_reference=categories[0],
    )


def add_static_features(
    targets: pd.DataFrame,
    tables: StaticTables,
) -> pd.DataFrame:
    df = add_concept_features(targets, tables.concept)
    df["item_logit"] = tables.item.map_logit(df["question_id"])
    df["difficulty_logit"] = tables.difficulty.map_logit(df["difficulty"])
    for category in tables.difficulty_categories:
        df[f"difficulty_{category}"] = (
            df["difficulty"].astype(str).eq(category).astype(float)
        )
    return df


def difficulty_feature_names(tables: StaticTables) -> List[str]:
    return [
        f"difficulty_{category}"
        for category in tables.difficulty_categories
        if category != tables.difficulty_reference
    ]


def concept_feature_names() -> List[str]:
    return ["concept_logit", "concept_mean_logit", "concept_count", "is_multi_concept"]


def item_concept_difficulty_features(tables: StaticTables) -> List[str]:
    return ["item_logit"] + concept_feature_names() + difficulty_feature_names(tables)


class FeatureLogisticModel:
    """L2 logistic regression over explicit interpretable features."""

    def __init__(
        self,
        feature_names: Sequence[str],
        *,
        C: float = 1.0,
        max_iter: int = 2000,
        random_state: int = 20261020,
    ) -> None:
        if C <= 0:
            raise ValueError("C must be positive.")
        self.feature_names = list(feature_names)
        self.C = float(C)
        self.max_iter = int(max_iter)
        self.random_state = int(random_state)
        self.model_: Optional[LogisticRegression] = None
        self.fit_seconds_: float = 0.0

    def _matrix(self, df: pd.DataFrame) -> np.ndarray:
        missing = [name for name in self.feature_names if name not in df.columns]
        if missing:
            raise ValueError(f"Missing model features: {missing}")
        matrix = df[self.feature_names].to_numpy(dtype=float)
        if not np.isfinite(matrix).all():
            raise ValueError("Feature matrix contains non-finite values.")
        return matrix

    def fit(self, train_targets: pd.DataFrame) -> "FeatureLogisticModel":
        started = time.perf_counter()
        self.model_ = LogisticRegression(
            C=self.C,
            solver="lbfgs",
            max_iter=self.max_iter,
            random_state=self.random_state,
        )
        self.model_.fit(self._matrix(train_targets), train_targets["correct"].to_numpy(dtype=int))
        self.fit_seconds_ = time.perf_counter() - started
        return self

    def predict_proba(self, targets: pd.DataFrame) -> np.ndarray:
        if self.model_ is None:
            raise RuntimeError("Model must be fitted before prediction.")
        return clip_probabilities(self.model_.predict_proba(self._matrix(targets))[:, 1])

    def coefficients(self) -> Dict[str, float]:
        if self.model_ is None:
            raise RuntimeError("Model must be fitted before reading coefficients.")
        return {
            name: float(value)
            for name, value in zip(self.feature_names, self.model_.coef_[0])
        }


def select_feature_model(
    train_targets: pd.DataFrame,
    validation_targets: pd.DataFrame,
    *,
    feature_names: Sequence[str],
    c_grid: Sequence[float] = DEFAULT_C_GRID,
) -> Tuple[FeatureLogisticModel, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_model: Optional[FeatureLogisticModel] = None
    best_c: Optional[float] = None
    best_key: Optional[Tuple[float, float]] = None
    for c_value in c_grid:
        model = FeatureLogisticModel(feature_names, C=float(c_value)).fit(train_targets)
        probabilities = model.predict_proba(validation_targets)
        metrics = evaluate_predictions(validation_targets["correct"], probabilities)
        rows.append(
            {
                "C": float(c_value),
                "log_loss": metrics["log_loss"],
                "brier_score": metrics["brier_score"],
                "roc_auc": metrics["roc_auc"],
                "expected_calibration_error": metrics["expected_calibration_error"],
            }
        )
        key = (float(metrics["log_loss"]), float(c_value))
        if best_key is None or key < best_key:
            best_key = key
            best_model = model
            best_c = float(c_value)
    if best_model is None or best_c is None:
        raise RuntimeError("Feature model selection failed.")
    return best_model, best_c, rows


class PFAModel:
    """Concept-specific performance factors with optional item/static features.

    PFA practice counts are attached to the primary concept. Multi-concept items
    are handled by the separate item/concept metadata features; their secondary
    concepts do not receive practice-count features in this baseline.
    """

    def __init__(
        self,
        concept_ids: Sequence[str],
        *,
        include_static: bool = False,
        static_feature_names: Optional[Sequence[str]] = None,
        C: float = 0.01,
        max_iter: int = 1000,
        random_state: int = 20261020,
    ) -> None:
        self.concept_ids = [str(value) for value in concept_ids]
        self.concept_index = {value: index for index, value in enumerate(self.concept_ids)}
        self.include_static = bool(include_static)
        self.static_feature_names = list(static_feature_names or [])
        self.C = float(C)
        self.max_iter = int(max_iter)
        self.random_state = int(random_state)
        self.model_: Optional[LogisticRegression] = None
        self.fit_seconds_: float = 0.0

    def _matrix(self, df: pd.DataFrame) -> Any:
        n_rows = len(df)
        n_concepts = len(self.concept_ids)
        concept_index = df["primary_concept_id"].astype(str).map(self.concept_index)
        valid = concept_index.notna().to_numpy()
        idx = concept_index.fillna(-1).to_numpy(dtype=int)
        correct = df["prior_concept_correct"].to_numpy(dtype=float)
        incorrect = df["prior_concept_incorrect"].to_numpy(dtype=float)
        rows: List[np.ndarray] = []
        cols: List[np.ndarray] = []
        values: List[np.ndarray] = []
        valid_positions = np.flatnonzero(valid)
        if len(valid_positions):
            rows.append(valid_positions)
            cols.append(idx[valid_positions])
            values.append(correct[valid_positions])
            rows.append(valid_positions)
            cols.append(n_concepts + idx[valid_positions])
            values.append(incorrect[valid_positions])
        positions = np.arange(n_rows)
        rows.append(positions)
        cols.append(np.full(n_rows, 2 * n_concepts, dtype=int))
        values.append(df["prior_overall_correct"].to_numpy(dtype=float))
        rows.append(positions)
        cols.append(np.full(n_rows, 2 * n_concepts + 1, dtype=int))
        values.append(df["prior_overall_incorrect"].to_numpy(dtype=float))
        pfa = sparse.csr_matrix(
            (
                np.concatenate(values),
                (np.concatenate(rows), np.concatenate(cols)),
            ),
            shape=(n_rows, 2 * n_concepts + 2),
        )
        if not self.include_static:
            return pfa
        missing = [name for name in self.static_feature_names if name not in df.columns]
        if missing:
            raise ValueError(f"Missing static PFA features: {missing}")
        static = sparse.csr_matrix(df[self.static_feature_names].to_numpy(dtype=float))
        return sparse.hstack([pfa, static], format="csr")

    def fit(self, train_targets: pd.DataFrame) -> "PFAModel":
        started = time.perf_counter()
        self.model_ = LogisticRegression(
            C=self.C,
            solver="liblinear",
            max_iter=self.max_iter,
            random_state=self.random_state,
        )
        self.model_.fit(self._matrix(train_targets), train_targets["correct"].to_numpy(dtype=int))
        self.fit_seconds_ = time.perf_counter() - started
        return self

    def predict_proba(self, targets: pd.DataFrame) -> np.ndarray:
        if self.model_ is None:
            raise RuntimeError("Model must be fitted before prediction.")
        return clip_probabilities(self.model_.predict_proba(self._matrix(targets))[:, 1])


def select_pfa_model(
    train_targets: pd.DataFrame,
    validation_targets: pd.DataFrame,
    *,
    concept_ids: Sequence[str],
    include_static: bool,
    static_feature_names: Optional[Sequence[str]] = None,
    c_grid: Sequence[float] = PFA_C_GRID,
) -> Tuple[PFAModel, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_model: Optional[PFAModel] = None
    best_c: Optional[float] = None
    best_key: Optional[Tuple[float, float]] = None
    for c_value in c_grid:
        model = PFAModel(
            concept_ids,
            include_static=include_static,
            static_feature_names=static_feature_names,
            C=float(c_value),
        ).fit(train_targets)
        probabilities = model.predict_proba(validation_targets)
        metrics = evaluate_predictions(validation_targets["correct"], probabilities)
        rows.append(
            {
                "C": float(c_value),
                "log_loss": metrics["log_loss"],
                "brier_score": metrics["brier_score"],
                "roc_auc": metrics["roc_auc"],
                "expected_calibration_error": metrics["expected_calibration_error"],
            }
        )
        key = (float(metrics["log_loss"]), float(c_value))
        if best_key is None or key < best_key:
            best_key = key
            best_model = model
            best_c = float(c_value)
    if best_model is None or best_c is None:
        raise RuntimeError("PFA model selection failed.")
    return best_model, best_c, rows


class LearnerConceptSmoothedModel:
    def __init__(self, m: float = 10.0) -> None:
        self.m = float(m)

    def predict_proba(self, targets: pd.DataFrame) -> np.ndarray:
        pop = targets.attrs.get("population_probability")
        if pop is None:
            raise ValueError("Targets must carry attrs['population_probability'].")
        pop = float(pop)
        concept = (
            targets["prior_concept_correct"].to_numpy(dtype=float) + self.m * pop
        ) / (targets["prior_concept_n"].to_numpy(dtype=float) + self.m)
        overall = (
            targets["prior_overall_correct"].to_numpy(dtype=float) + self.m * pop
        ) / (targets["prior_overall_n"].to_numpy(dtype=float) + self.m)
        has_concept = targets["prior_concept_n"].to_numpy(dtype=int) > 0
        result = np.where(has_concept, concept, overall)
        return clip_probabilities(result)


def select_learner_concept_smoothed(
    validation_targets: pd.DataFrame,
    *,
    m_grid: Sequence[float] = (1.0, 5.0, 10.0, 20.0, 50.0, 100.0),
) -> Tuple[LearnerConceptSmoothedModel, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_model: Optional[LearnerConceptSmoothedModel] = None
    best_m: Optional[float] = None
    best_key: Optional[Tuple[float, float]] = None
    for m_value in m_grid:
        model = LearnerConceptSmoothedModel(m_value)
        probabilities = model.predict_proba(validation_targets)
        metrics = evaluate_predictions(validation_targets["correct"], probabilities)
        rows.append(
            {
                "m": float(m_value),
                "log_loss": metrics["log_loss"],
                "brier_score": metrics["brier_score"],
                "roc_auc": metrics["roc_auc"],
            }
        )
        key = (float(metrics["log_loss"]), float(m_value))
        if best_key is None or key < best_key:
            best_key = key
            best_model = model
            best_m = float(m_value)
    if best_model is None or best_m is None:
        raise RuntimeError("Learner-concept smoothing selection failed.")
    return best_model, best_m, rows


class IRT1PLOnlineModel:
    """Train-calibrated item difficulty with causal online learner ability."""

    def __init__(self, item_effects: EffectTable, *, learning_rate: float = 0.1, l2: float = 0.001) -> None:
        self.item_effects = item_effects
        self.learning_rate = float(learning_rate)
        self.l2 = float(l2)

    def _item_difficulty(self, question_ids: Iterable[Any]) -> np.ndarray:
        logits = self.item_effects.map_logit(question_ids)
        return -logits

    def predict_online(self, targets: pd.DataFrame) -> np.ndarray:
        df = targets.sort_values(
            by=["student_id", "sequence_index", "timestamp_utc"],
            kind="mergesort",
        ).reset_index(drop=True)
        ability: Dict[str, float] = {}
        output = np.full(len(df), np.nan, dtype=float)
        difficulties = self._item_difficulty(df["question_id"])
        y = df["correct"].to_numpy(dtype=int)
        student_ids = df["student_id"].astype(str).to_numpy()
        for position in range(len(df)):
            student = student_ids[position]
            theta = ability.get(student, 0.0)
            probability = float(sigmoid([theta - difficulties[position]])[0])
            output[position] = probability
            gradient = y[position] - probability
            theta = theta + self.learning_rate * gradient - self.l2 * theta
            ability[student] = float(np.clip(theta, -8.0, 8.0))
        result = pd.Series(output, index=df["interaction_id"].to_numpy())
        return clip_probabilities(result.reindex(targets["interaction_id"]).to_numpy(dtype=float))


def select_irt_model(
    item_effects: EffectTable,
    validation_targets: pd.DataFrame,
) -> Tuple[IRT1PLOnlineModel, Dict[str, float], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_model: Optional[IRT1PLOnlineModel] = None
    best_params: Dict[str, float] = {}
    best_key: Optional[Tuple[float, float, float]] = None
    for learning_rate in (0.01, 0.03, 0.1, 0.3, 1.0):
        for l2 in (0.0, 0.001, 0.01, 0.1):
            model = IRT1PLOnlineModel(item_effects, learning_rate=learning_rate, l2=l2)
            probabilities = model.predict_online(validation_targets)
            metrics = evaluate_predictions(validation_targets["correct"], probabilities)
            rows.append(
                {
                    "learning_rate": learning_rate,
                    "l2": l2,
                    "log_loss": metrics["log_loss"],
                    "brier_score": metrics["brier_score"],
                    "roc_auc": metrics["roc_auc"],
                }
            )
            key = (float(metrics["log_loss"]), float(learning_rate), float(l2))
            if best_key is None or key < best_key:
                best_key = key
                best_model = model
                best_params = {"learning_rate": float(learning_rate), "l2": float(l2)}
    if best_model is None:
        raise RuntimeError("IRT model selection failed.")
    return best_model, best_params, rows


class EloOnlineModel:
    def __init__(self, *, k_factor: float = 0.1) -> None:
        self.k_factor = float(k_factor)

    def predict_online(self, targets: pd.DataFrame) -> np.ndarray:
        df = targets.sort_values(
            by=["student_id", "sequence_index", "timestamp_utc"],
            kind="mergesort",
        ).reset_index(drop=True)
        ability: Dict[str, float] = {}
        difficulty: Dict[str, float] = {}
        output = np.full(len(df), np.nan, dtype=float)
        y = df["correct"].to_numpy(dtype=int)
        student_ids = df["student_id"].astype(str).to_numpy()
        question_ids = df["question_id"].astype(str).to_numpy()
        for position in range(len(df)):
            student = student_ids[position]
            item = question_ids[position]
            theta = ability.get(student, 0.0)
            b = difficulty.get(item, 0.0)
            probability = float(sigmoid([theta - b])[0])
            output[position] = probability
            update = self.k_factor * (y[position] - probability)
            ability[student] = float(np.clip(theta + update, -8.0, 8.0))
            difficulty[item] = float(np.clip(b - update, -8.0, 8.0))
        result = pd.Series(output, index=df["interaction_id"].to_numpy())
        return clip_probabilities(result.reindex(targets["interaction_id"]).to_numpy(dtype=float))


def select_elo_model(
    validation_targets: pd.DataFrame,
    *,
    k_grid: Sequence[float] = (0.01, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5),
) -> Tuple[EloOnlineModel, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_model: Optional[EloOnlineModel] = None
    best_k: Optional[float] = None
    best_key: Optional[Tuple[float, float]] = None
    for k_value in k_grid:
        model = EloOnlineModel(k_factor=float(k_value))
        probabilities = model.predict_online(validation_targets)
        metrics = evaluate_predictions(validation_targets["correct"], probabilities)
        rows.append(
            {
                "k_factor": float(k_value),
                "log_loss": metrics["log_loss"],
                "brier_score": metrics["brier_score"],
                "roc_auc": metrics["roc_auc"],
            }
        )
        key = (float(metrics["log_loss"]), float(k_value))
        if best_key is None or key < best_key:
            best_key = key
            best_model = model
            best_k = float(k_value)
    if best_model is None or best_k is None:
        raise RuntimeError("Elo model selection failed.")
    return best_model, best_k, rows


def load_prerequisite_map(concepts_path: str | Any) -> Dict[str, List[str]]:
    concepts = pd.read_csv(concepts_path)
    known = set(concepts["concept_id"].astype(str))
    result: Dict[str, List[str]] = {}
    for row in concepts.itertuples(index=False):
        concept = str(row.concept_id)
        raw = getattr(row, "prerequisite_ids")
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            result[concept] = []
            continue
        values = [str(value).strip() for value in str(raw).split(";") if str(value).strip()]
        result[concept] = [value for value in values if value in known and value != concept]
    return result


@dataclass
class BKTStepFrame:
    frame: pd.DataFrame
    variant: str
    parameters: Dict[str, Any]


def bkt_variant_features(
    targets: pd.DataFrame,
    config: BKTConfig,
    *,
    variant: str = "standard",
    forgetting_lambda: float = 0.0,
    prerequisite_alpha: float = 0.0,
    prerequisites: Optional[Mapping[str, Sequence[str]]] = None,
) -> BKTStepFrame:
    if variant == "multiconcept":
        replay = replay_interactions(targets, config=config, policy="conjunctive")
        rows = [
            {
                "interaction_id": step.interaction_id,
                "bkt_p_prior": float(step.p_prior),
                "bkt_p_pred": float(step.p_pred),
                "bkt_p_posterior": float(step.p_posterior),
                "bkt_p_next": float(step.p_next),
            }
            for step in replay.steps
        ]
        frame = targets.merge(pd.DataFrame(rows), on="interaction_id", how="left", validate="one_to_one")
        return BKTStepFrame(_add_bkt_logits(frame), variant, {"policy": "conjunctive"})

    if variant not in {"standard", "forgetting", "prerequisite"}:
        raise ValueError(f"Unsupported BKT variant '{variant}'.")
    if variant == "prerequisite" and prerequisites is None:
        raise ValueError("Prerequisite variant requires a prerequisite map.")

    df = targets.sort_values(
        by=["student_id", "sequence_index", "timestamp_utc"],
        kind="mergesort",
    ).reset_index(drop=True)
    states: Dict[Tuple[str, str], float] = {}
    output: List[Dict[str, Any]] = []
    for row in df.itertuples(index=False):
        student = str(row.student_id)
        concept = str(row.primary_concept_id)
        params = config.get_parameters_for_concept(concept)
        key = (student, concept)
        p_state = float(states.get(key, params.p_l0))
        p_prior = p_state
        if variant == "forgetting":
            days = float(getattr(row, "days_since_concept_practice", 0.0))
            retention = math.exp(-float(forgetting_lambda) * max(days, 0.0))
            p_prior = params.p_l0 + (p_prior - params.p_l0) * retention
        if variant == "prerequisite":
            prereq_ids = list(prerequisites.get(concept, []))
            if prereq_ids:
                values = [
                    float(states.get((student, prereq), config.get_parameters_for_concept(prereq).p_l0))
                    for prereq in prereq_ids
                ]
                prereq_mastery = float(np.mean(values))
                alpha = float(prerequisite_alpha)
                p_prior = (1.0 - alpha) * p_prior + alpha * prereq_mastery
        p_prior = float(np.clip(p_prior, 0.001, 0.999))
        p_pred = predict_correctness(p_prior, params.p_guess, params.p_slip)
        p_posterior = update_mastery_posterior(
            p_prior,
            int(row.correct),
            params.p_guess,
            params.p_slip,
        )
        p_next = apply_learning_transition(p_posterior, params.p_transition)
        states[key] = float(p_next)
        output.append(
            {
                "interaction_id": row.interaction_id,
                "bkt_p_prior": p_prior,
                "bkt_p_pred": p_pred,
                "bkt_p_posterior": p_posterior,
                "bkt_p_next": p_next,
            }
        )
    frame = targets.merge(pd.DataFrame(output), on="interaction_id", how="left", validate="one_to_one")
    parameters: Dict[str, Any] = {"variant": variant}
    if variant == "forgetting":
        parameters["forgetting_lambda"] = float(forgetting_lambda)
    if variant == "prerequisite":
        parameters["prerequisite_alpha"] = float(prerequisite_alpha)
    return BKTStepFrame(_add_bkt_logits(frame), variant, parameters)


def _add_bkt_logits(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["bkt_p_prior", "bkt_p_pred", "bkt_p_posterior", "bkt_p_next"]
    if frame[required].isna().any().any():
        raise ValueError("BKT replay failed to produce every target row.")
    result = frame.copy()
    result["bkt_logit_prior"] = logit(result["bkt_p_prior"])
    result["bkt_logit_pred"] = logit(result["bkt_p_pred"])
    result["bkt_logit_posterior"] = logit(result["bkt_p_posterior"])
    result["bkt_logit_next"] = logit(result["bkt_p_next"])
    return result


def select_forgetting_bkt(
    validation_targets: pd.DataFrame,
    config: BKTConfig,
    *,
    lambda_grid: Sequence[float] = (0.0, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0),
) -> Tuple[float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_lambda: Optional[float] = None
    best_key: Optional[Tuple[float, float]] = None
    for lambda_value in lambda_grid:
        features = bkt_variant_features(
            validation_targets,
            config,
            variant="forgetting",
            forgetting_lambda=float(lambda_value),
        ).frame
        metrics = evaluate_predictions(features["correct"], features["bkt_p_pred"])
        rows.append(
            {
                "forgetting_lambda": float(lambda_value),
                "log_loss": metrics["log_loss"],
                "brier_score": metrics["brier_score"],
                "roc_auc": metrics["roc_auc"],
            }
        )
        key = (float(metrics["log_loss"]), float(lambda_value))
        if best_key is None or key < best_key:
            best_key = key
            best_lambda = float(lambda_value)
    if best_lambda is None:
        raise RuntimeError("Forgetting BKT selection failed.")
    return best_lambda, rows


def select_prerequisite_bkt(
    validation_targets: pd.DataFrame,
    config: BKTConfig,
    prerequisites: Mapping[str, Sequence[str]],
    *,
    alpha_grid: Sequence[float] = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0),
) -> Tuple[float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_alpha: Optional[float] = None
    best_key: Optional[Tuple[float, float]] = None
    for alpha_value in alpha_grid:
        features = bkt_variant_features(
            validation_targets,
            config,
            variant="prerequisite",
            prerequisite_alpha=float(alpha_value),
            prerequisites=prerequisites,
        ).frame
        metrics = evaluate_predictions(features["correct"], features["bkt_p_pred"])
        rows.append(
            {
                "prerequisite_alpha": float(alpha_value),
                "log_loss": metrics["log_loss"],
                "brier_score": metrics["brier_score"],
                "roc_auc": metrics["roc_auc"],
            }
        )
        key = (float(metrics["log_loss"]), float(alpha_value))
        if best_key is None or key < best_key:
            best_key = key
            best_alpha = float(alpha_value)
    if best_alpha is None:
        raise RuntimeError("Prerequisite BKT selection failed.")
    return best_alpha, rows


def hierarchical_item_tables(
    train_targets: pd.DataFrame,
    *,
    item_prior_strength_m: float,
) -> StaticTables:
    return fit_static_tables(
        train_targets,
        item_prior_strength_m=item_prior_strength_m,
    )


def select_hierarchical_item_bkt(
    train_targets: pd.DataFrame,
    validation_targets: pd.DataFrame,
    *,
    bkt_features_train: pd.DataFrame,
    bkt_features_validation: pd.DataFrame,
    m_grid: Sequence[float] = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0),
    c_grid: Sequence[float] = DEFAULT_C_GRID,
) -> Tuple[FeatureLogisticModel, Dict[str, float], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_model: Optional[FeatureLogisticModel] = None
    best_params: Dict[str, float] = {}
    best_key: Optional[Tuple[float, float, float]] = None
    train_base = bkt_features_train.drop(columns=[c for c in ("item_logit", "concept_logit", "concept_mean_logit", "concept_max_logit", "difficulty_logit") if c in bkt_features_train.columns])
    validation_base = bkt_features_validation.drop(columns=[c for c in ("item_logit", "concept_logit", "concept_mean_logit", "concept_max_logit", "difficulty_logit") if c in bkt_features_validation.columns])
    for m_value in m_grid:
        tables = hierarchical_item_tables(train_targets, item_prior_strength_m=float(m_value))
        train_features = add_static_features(train_base, tables)
        validation_features = add_static_features(validation_base, tables)
        feature_names = ["bkt_logit_prior", "bkt_logit_pred"] + item_concept_difficulty_features(tables)
        for c_value in c_grid:
            model = FeatureLogisticModel(feature_names, C=float(c_value)).fit(train_features)
            probabilities = model.predict_proba(validation_features)
            metrics = evaluate_predictions(validation_features["correct"], probabilities)
            rows.append(
                {
                    "item_prior_strength_m": float(m_value),
                    "C": float(c_value),
                    "log_loss": metrics["log_loss"],
                    "brier_score": metrics["brier_score"],
                    "roc_auc": metrics["roc_auc"],
                }
            )
            key = (float(metrics["log_loss"]), float(m_value), float(c_value))
            if best_key is None or key < best_key:
                best_key = key
                best_model = model
                best_params = {"item_prior_strength_m": float(m_value), "C": float(c_value)}
    if best_model is None:
        raise RuntimeError("Hierarchical item-aware BKT selection failed.")
    return best_model, best_params, rows

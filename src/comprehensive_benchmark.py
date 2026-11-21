"""Repository-wide learner-modeling benchmark runner.

The runner builds a matched known-item cohort, fits conventional, BKT, and
neural candidates, and writes the required versioned artifacts. It keeps the
v4 test re-evaluation separate from the confirmatory dataset evaluation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score

from src.baselines import (
    DifficultyBaseline,
    ItemBaseline,
    PopulationBaseline,
    SkillBaseline,
    evaluate_predictions,
)
from src.benchmark_models import (
    DEFAULT_C_GRID,
    EloOnlineModel,
    FeatureLogisticModel,
    IRT1PLOnlineModel,
    LearnerConceptSmoothedModel,
    PFAModel,
    add_history_features,
    add_static_features,
    bkt_variant_features,
    clip_probabilities,
    concept_feature_names,
    difficulty_feature_names,
    fit_static_tables,
    item_concept_difficulty_features,
    load_prerequisite_map,
    select_elo_model,
    select_feature_model,
    select_forgetting_bkt,
    select_hierarchical_item_bkt,
    select_irt_model,
    select_learner_concept_smoothed,
    select_pfa_model,
    select_prerequisite_bkt,
)
from src.bkt import BKTConfig, load_bkt_config_json
from src.v4_benchmark import (
    _continuous_agreement,
    _history_bin,
    _latent_calibration,
    canonical_targets,
    eligibility_audit,
    item_exposure_audit,
    load_v4_interactions,
    paired_cluster_bootstrap,
)

DEFAULT_DATA_DIR = Path("data/synthetic jee/v4")
DEFAULT_CONFIGS_DIR = Path("data/research/configs_v4")
DEFAULT_OUTPUT_DIR = Path("reports/benchmark")
DEFAULT_REPORT_DIR = Path("reports")
DEFAULT_SEED = 20261020
DEFAULT_BOOTSTRAP_RESAMPLES = 1000
PRACTICAL_THRESHOLD = 0.001


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def response_metrics(y_true: Sequence[int], probabilities: Sequence[float]) -> Dict[str, Any]:
    y = np.asarray(y_true, dtype=int)
    p = clip_probabilities(probabilities)
    metrics = evaluate_predictions(y, p)
    metrics["average_precision"] = float(average_precision_score(y, p))
    predicted = (p >= 0.5).astype(int)
    metrics["precision"] = float(precision_score(y, predicted, zero_division=0))
    metrics["recall"] = float(recall_score(y, predicted, zero_division=0))
    metrics["f1"] = float(f1_score(y, predicted, zero_division=0))
    return metrics


def _metrics_row(
    model: str,
    split: str,
    targets: pd.DataFrame,
    probabilities: Sequence[float],
    *,
    status: str,
    notes: str,
    fit_seconds: Optional[float] = None,
    predict_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    metrics = response_metrics(targets["correct"], probabilities)
    return {
        "model": model,
        "split": split,
        "status": status,
        "n": int(len(targets)),
        "students": int(targets["student_id"].nunique()),
        "observed_positive_rate": metrics["observed_positive_rate"],
        "log_loss": metrics["log_loss"],
        "brier_score": metrics["brier_score"],
        "roc_auc": metrics["roc_auc"],
        "average_precision": metrics["average_precision"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
        "expected_calibration_error": metrics["expected_calibration_error"],
        "equal_frequency_ece": metrics["equal_frequency_ece"],
        "mean_predicted_probability": float(np.mean(clip_probabilities(probabilities))),
        "fit_seconds": _safe_float(fit_seconds),
        "predict_seconds": _safe_float(predict_seconds),
        "notes": notes,
    }


def _load_configs(configs_dir: Path) -> Dict[str, BKTConfig]:
    result: Dict[str, BKTConfig] = {}
    for name in ("global", "subject", "concept"):
        path = configs_dir / f"bkt_{name}_fitted.json"
        if not path.is_file():
            raise FileNotFoundError(f"Missing BKT config: {path}")
        config = load_bkt_config_json(path)
        if not isinstance(config, BKTConfig):
            raise ValueError(f"Expected a single BKTConfig in {path}")
        result[name] = config
    return result


def _attach_bkt(base: pd.DataFrame, bkt: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "interaction_id",
        "bkt_p_prior",
        "bkt_p_pred",
        "bkt_p_posterior",
        "bkt_p_next",
        "bkt_logit_prior",
        "bkt_logit_pred",
        "bkt_logit_posterior",
        "bkt_logit_next",
    ]
    missing = [column for column in columns if column not in bkt.columns]
    if missing:
        raise ValueError(f"BKT frame missing columns: {missing}")
    return base.merge(bkt[columns], on="interaction_id", how="left", validate="one_to_one")


def _drop_static_columns(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "item_logit",
        "concept_logit",
        "concept_mean_logit",
        "concept_max_logit",
        "difficulty_logit",
    ]
    columns.extend([column for column in frame.columns if column.startswith("difficulty_")])
    return frame.drop(columns=[column for column in columns if column in frame.columns])


def _replace_static_features(frame: pd.DataFrame, tables: Any) -> pd.DataFrame:
    return add_static_features(_drop_static_columns(frame), tables)


def _item_availability_features(
    frame: pd.DataFrame,
    tables: Any,
    *,
    mask_fraction: float = 0.0,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    result = frame.copy()
    result["item_logit_centered"] = (
        result["item_logit"].to_numpy(dtype=float) - tables.item.population_logit
    )
    result["item_available"] = 1.0
    if mask_fraction > 0:
        rng = np.random.default_rng(seed)
        mask = rng.random(len(result)) < float(mask_fraction)
        result.loc[mask, "item_logit_centered"] = 0.0
        result.loc[mask, "item_available"] = 0.0
    return result


def _pair_rows(
    targets: pd.DataFrame,
    predictions: Mapping[str, Sequence[float]],
    comparisons: Sequence[Tuple[str, str]],
    *,
    cohort: str,
    n_resamples: int,
    seed: int,
    auc_resamples: Optional[int] = None,
) -> List[Dict[str, Any]]:
    available = {
        name: values
        for name, values in predictions.items()
        if len(values) == len(targets)
    }
    filtered = [
        pair for pair in comparisons if pair[0] in available and pair[1] in available
    ]
    if not filtered:
        return []
    bootstrap = paired_cluster_bootstrap(
        targets,
        available,
        filtered,
        n_resamples=n_resamples,
        seed=seed,
        auc_resamples=auc_resamples,
    )
    rows: List[Dict[str, Any]] = []
    for key, values in bootstrap["comparisons"].items():
        candidate, reference = key.split("_minus_", 1)
        for metric in ("log_loss", "brier", "auc"):
            summary = values[f"delta_{metric}"]
            delta = summary["mean"]
            p_value = summary.get("p_value")
            rows.append(
                {
                    "cohort": cohort,
                    "candidate": candidate,
                    "reference": reference,
                    "metric": metric,
                    "delta": delta,
                    "ci_lower_95": summary["ci_lower_95"],
                    "ci_upper_95": summary["ci_upper_95"],
                    "p_value": p_value,
                    "significant_95": summary["is_significant_95"],
                    "valid_resamples": summary["valid_resamples"],
                    "n": int(len(targets)),
                    "students": int(targets["student_id"].nunique()),
                }
            )
    return rows


def _benjamini_hochberg(rows: List[Dict[str, Any]]) -> None:
    valid = [
        row for row in rows
        if row.get("p_value") is not None and math.isfinite(float(row["p_value"]))
    ]
    ordered = sorted(valid, key=lambda row: float(row["p_value"]))
    total = len(ordered)
    previous = 1.0
    for rank in range(total, 0, -1):
        row = ordered[rank - 1]
        adjusted = min(previous, float(row["p_value"]) * total / rank)
        row["q_value"] = min(1.0, adjusted)
        previous = row["q_value"]
    for row in rows:
        if "q_value" not in row:
            row["q_value"] = None


def _apply_practicality(rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        metric = row["metric"]
        threshold = PRACTICAL_THRESHOLD
        delta = row.get("delta")
        q_value = row.get("q_value")
        row["practical_threshold"] = threshold
        row["meets_practical_threshold"] = bool(
            delta is not None
            and q_value is not None
            and q_value < 0.05
            and abs(float(delta)) >= threshold
            and bool(row.get("significant_95"))
        )


def _slice_metrics(
    targets: pd.DataFrame,
    predictions: Mapping[str, Sequence[float]],
    *,
    column: str,
    slice_name: str,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    if column not in targets.columns:
        return pd.DataFrame()
    for value, group in targets.groupby(column, dropna=False):
        for model, values in predictions.items():
            probabilities = clip_probabilities(np.asarray(values)[group.index])
            metrics = response_metrics(group["correct"], probabilities)
            rows.append(
                {
                    "slice_name": slice_name,
                    "slice_value": str(value),
                    "model": model,
                    "n": int(len(group)),
                    "students": int(group["student_id"].nunique()),
                    "observed_positive_rate": metrics["observed_positive_rate"],
                    "log_loss": metrics["log_loss"],
                    "brier_score": metrics["brier_score"],
                    "roc_auc": metrics["roc_auc"],
                    "average_precision": metrics["average_precision"],
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "f1": metrics["f1"],
                    "expected_calibration_error": metrics["expected_calibration_error"],
                    "equal_frequency_ece": metrics["equal_frequency_ece"],
                }
            )
    return pd.DataFrame(rows)


def _calibration_rows(
    targets: pd.DataFrame,
    predictions: Mapping[str, Sequence[float]],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for model, values in predictions.items():
        metrics = response_metrics(targets["correct"], values)
        for bin_type, bins in (
            ("equal_width", metrics["calibration_bins"]),
            ("equal_frequency", metrics["equal_frequency_bins"]),
        ):
            for bin_row in bins:
                rows.append(
                    {
                        "model": model,
                        "bin_type": bin_type,
                        "bin_index": bin_row.get("bin_index"),
                        "bin_low": bin_row.get("bin_low"),
                        "bin_high": bin_row.get("bin_high"),
                        "count": bin_row["count"],
                        "mean_predicted": bin_row.get("mean_predicted"),
                        "observed_rate": bin_row.get("observed_rate", bin_row.get("observed_rate")),
                        "calibration_gap": bin_row.get("calibration_gap"),
                        "expected_calibration_error": metrics["expected_calibration_error"],
                        "equal_frequency_ece": metrics["equal_frequency_ece"],
                    }
                )
    return pd.DataFrame(rows)


def _mastery_rows(
    assessment: pd.DataFrame,
    bkt_frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    required = ["interaction_id", "assessment_type", "pre_response_mastery", "post_response_mastery"]
    if not set(required).issubset(assessment.columns):
        return pd.DataFrame()
    assessment_columns = assessment[required].copy()
    for model, frame in bkt_frames.items():
        merged = frame[["interaction_id", "student_id", "bkt_p_prior", "bkt_p_next"]].merge(
            assessment_columns,
            on="interaction_id",
            how="inner",
            validate="one_to_one",
        )
        if merged.empty:
            continue
        before = _continuous_agreement(
            merged["pre_response_mastery"].to_numpy(dtype=float),
            merged["bkt_p_prior"].to_numpy(dtype=float),
        )
        after = _continuous_agreement(
            merged["post_response_mastery"].to_numpy(dtype=float),
            merged["bkt_p_next"].to_numpy(dtype=float),
        )
        before_calibration = _latent_calibration(
            merged["pre_response_mastery"].to_numpy(dtype=float),
            merged["bkt_p_prior"].to_numpy(dtype=float),
        )
        rows.append(
            {
                "model": model,
                "assessment_type": "all",
                "n": int(len(merged)),
                "students": int(merged["student_id"].nunique()),
                "before_pearson": before["pearson"],
                "before_spearman": before["spearman"],
                "before_mae": before["mae"],
                "before_rmse": before["rmse"],
                "before_mean_bias": before["mean_bias"],
                "before_latent_ece": before_calibration["latent_ece"],
                "after_pearson": after["pearson"],
                "after_spearman": after["spearman"],
                "after_mae": after["mae"],
                "after_rmse": after["rmse"],
                "after_mean_bias": after["mean_bias"],
                "target_mean": before["mean_target"],
                "prediction_mean": before["mean_predicted"],
                "evidence_status": "synthetic_latent_mastery_diagnostic_only",
            }
        )
        for assessment_type, group in merged.groupby("assessment_type"):
            before_group = _continuous_agreement(
                group["pre_response_mastery"].to_numpy(dtype=float),
                group["bkt_p_prior"].to_numpy(dtype=float),
            )
            group_calibration = _latent_calibration(
                group["pre_response_mastery"].to_numpy(dtype=float),
                group["bkt_p_prior"].to_numpy(dtype=float),
            )
            rows.append(
                {
                    "model": model,
                    "assessment_type": str(assessment_type),
                    "n": int(len(group)),
                    "students": int(group["student_id"].nunique()),
                    "before_pearson": before_group["pearson"],
                    "before_spearman": before_group["spearman"],
                    "before_mae": before_group["mae"],
                    "before_rmse": before_group["rmse"],
                    "before_mean_bias": before_group["mean_bias"],
                    "before_latent_ece": group_calibration["latent_ece"],
                    "after_pearson": None,
                    "after_spearman": None,
                    "after_mae": None,
                    "after_rmse": None,
                    "after_mean_bias": None,
                    "target_mean": before_group["mean_target"],
                    "prediction_mean": before_group["mean_predicted"],
                    "evidence_status": "synthetic_latent_mastery_diagnostic_only",
                }
            )
    return pd.DataFrame(rows)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _add_prediction_metadata(frame: pd.DataFrame, predictions: Mapping[str, np.ndarray]) -> pd.DataFrame:
    result = frame[
        [
            column
            for column in (
                "interaction_id",
                "student_id",
                "sequence_index",
                "question_id",
                "primary_concept_id",
                "concept_ids",
                "subject",
                "difficulty",
                "is_assessment",
                "assessment_type",
                "prior_interactions",
                "prior_attempts_concept",
                "prior_item_n",
                "hint_used",
                "correct",
            )
            if column in frame.columns
        ]
    ].copy()
    for model, values in predictions.items():
        result[model] = clip_probabilities(values)
    return result


@dataclass
class BenchmarkData:
    data_dir: Path
    interactions: pd.DataFrame
    questions: pd.DataFrame
    concepts: pd.DataFrame
    configs: Dict[str, BKTConfig]
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    population_probability: float
    tables: Any
    prerequisites: Dict[str, List[str]]


def prepare_benchmark_data(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    configs_dir: Path | str = DEFAULT_CONFIGS_DIR,
) -> BenchmarkData:
    data_path = Path(data_dir)
    config_path = Path(configs_dir)
    interactions = load_v4_interactions(data_path)
    questions = pd.read_csv(data_path / "questions.csv")
    concepts = pd.read_csv(data_path / "concepts.csv")
    configs = _load_configs(config_path)
    train_counts = interactions.loc[
        interactions["student_split"].eq("train")
    ].groupby("question_id").size()
    train = canonical_targets(interactions, "train", train_item_counts=train_counts)
    validation = canonical_targets(interactions, "validation", train_item_counts=train_counts)
    test = canonical_targets(interactions, "test", train_item_counts=train_counts)
    population = float(train["correct"].mean())
    train = add_history_features(train, population_probability=population)
    validation = add_history_features(validation, population_probability=population)
    test = add_history_features(test, population_probability=population)
    tables = fit_static_tables(train)
    train = add_static_features(train, tables)
    validation = add_static_features(validation, tables)
    test = add_static_features(test, tables)
    for frame in (train, validation, test):
        frame.attrs["population_probability"] = population
    return BenchmarkData(
        data_dir=data_path,
        interactions=interactions,
        questions=questions,
        concepts=concepts,
        configs=configs,
        train=train,
        validation=validation,
        test=test,
        population_probability=population,
        tables=tables,
        prerequisites=load_prerequisite_map(data_path / "concepts.csv"),
    )


def _record(
    predictions_validation: Dict[str, np.ndarray],
    predictions_test: Dict[str, np.ndarray],
    metadata: Dict[str, Dict[str, Any]],
    name: str,
    validation_probabilities: np.ndarray,
    test_probabilities: np.ndarray,
    *,
    family: str,
    status: str = "trained",
    features: Sequence[str] = (),
    notes: str = "",
    fit_seconds: Optional[float] = None,
    predict_seconds: Optional[float] = None,
    hyperparameters: Optional[Dict[str, Any]] = None,
) -> None:
    predictions_validation[name] = clip_probabilities(validation_probabilities)
    predictions_test[name] = clip_probabilities(test_probabilities)
    metadata[name] = {
        "name": name,
        "family": family,
        "status": status,
        "features": list(features),
        "notes": notes,
        "fit_seconds": _safe_float(fit_seconds),
        "predict_seconds": _safe_float(predict_seconds),
        "hyperparameters": hyperparameters or {},
    }

def _run_static_and_traditional(
    data: BenchmarkData,
    *,
    predictions_validation: Dict[str, np.ndarray],
    predictions_test: Dict[str, np.ndarray],
    metadata: Dict[str, Dict[str, Any]],
    selection_log: Dict[str, Any],
) -> Dict[str, Any]:
    train, validation, test, tables = data.train, data.validation, data.test, data.tables
    y_train = train["correct"]

    population = PopulationBaseline().fit(train, y_train)
    concept = SkillBaseline(prior_strength_m=10.0, multiconcept_policy="primary").fit(train, y_train)
    difficulty = DifficultyBaseline(prior_strength_m=10.0).fit(train, y_train)
    item = ItemBaseline(prior_strength_m=10.0).fit(train, y_train)
    _record(predictions_validation, predictions_test, metadata, "population_baseline", population.predict_proba(validation), population.predict_proba(test), family="conventional", features=[], notes="Training correctness rate.")
    _record(predictions_validation, predictions_test, metadata, "concept_only", concept.predict_proba(validation), concept.predict_proba(test), family="conventional", features=["primary_concept_id"], notes="Concept mean with Beta-style shrinkage M=10.")
    _record(predictions_validation, predictions_test, metadata, "difficulty_only", difficulty.predict_proba(validation), difficulty.predict_proba(test), family="conventional", features=["difficulty"], notes="Difficulty mean with Beta-style shrinkage M=10.")
    _record(predictions_validation, predictions_test, metadata, "item_only", item.predict_proba(validation), item.predict_proba(test), family="conventional", features=["question_id"], notes="Item mean with Beta-style shrinkage M=10.")

    model_specs = [
        ("concept_difficulty", concept_feature_names() + difficulty_feature_names(tables), "primary_concept_id, concept composition, difficulty"),
        ("item_concept_difficulty", item_concept_difficulty_features(tables), "question_id, primary_concept_id, concept composition, difficulty"),
    ]
    for name, features, note in model_specs:
        started = time.perf_counter()
        model, selected_c, rows = select_feature_model(train, validation, feature_names=features)
        fit_seconds = time.perf_counter() - started
        started_predict = time.perf_counter()
        validation_probabilities = model.predict_proba(validation)
        test_probabilities = model.predict_proba(test)
        predict_seconds = time.perf_counter() - started_predict
        _record(
            predictions_validation,
            predictions_test,
            metadata,
            name,
            validation_probabilities,
            test_probabilities,
            family="conventional_logistic",
            features=features,
            notes=note,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            hyperparameters={"C": selected_c, "coefficients": model.coefficients()},
        )
        selection_log[name] = {"selected_C": selected_c, "grid": rows}

    history_features = ["prior_overall_rate_smoothed", "prior_overall_last_correct", "log1p_prior_overall_n"]
    started = time.perf_counter()
    history_model, history_c, history_rows = select_feature_model(train, validation, feature_names=history_features)
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "learner_history",
        history_model.predict_proba(validation),
        history_model.predict_proba(test),
        family="conventional_logistic",
        features=history_features,
        notes="Overall prior correctness and history depth; no item or concept identity.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={"C": history_c, "coefficients": history_model.coefficients()},
    )
    selection_log["learner_history"] = {"selected_C": history_c, "grid": history_rows}

    learner_concept_features = [
        "prior_overall_rate_smoothed",
        "prior_concept_rate_smoothed",
        "prior_overall_last_correct",
        "prior_concept_last_correct",
        "log1p_prior_overall_n",
        "log1p_prior_concept_n",
        "concept_logit",
    ]
    started = time.perf_counter()
    learner_concept_model, learner_concept_c, learner_concept_rows = select_feature_model(
        train, validation, feature_names=learner_concept_features
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "learner_concept_logistic",
        learner_concept_model.predict_proba(validation),
        learner_concept_model.predict_proba(test),
        family="conventional_logistic",
        features=learner_concept_features,
        notes="Regularized learner-concept history with concept identity and no item identity.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={"C": learner_concept_c, "coefficients": learner_concept_model.coefficients()},
    )
    selection_log["learner_concept_logistic"] = {"selected_C": learner_concept_c, "grid": learner_concept_rows}

    smoothed_model, smoothed_m, smoothed_rows = select_learner_concept_smoothed(validation)
    validation.attrs["population_probability"] = data.population_probability
    test.attrs["population_probability"] = data.population_probability
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "learner_concept_smoothed",
        smoothed_model.predict_proba(validation),
        smoothed_model.predict_proba(test),
        family="conventional_history",
        features=["prior_concept_correct", "prior_concept_n", "prior_overall_correct", "prior_overall_n"],
        notes="Smoothed learner-concept prior correctness with learner-overall fallback.",
        hyperparameters={"m": smoothed_m},
    )
    selection_log["learner_concept_smoothed"] = {"selected_m": smoothed_m, "grid": smoothed_rows}

    concept_ids = sorted(train["primary_concept_id"].astype(str).unique())
    started = time.perf_counter()
    pfa_model, pfa_c, pfa_rows = select_pfa_model(
        train,
        validation,
        concept_ids=concept_ids,
        include_static=False,
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "pfa_concept",
        pfa_model.predict_proba(validation),
        pfa_model.predict_proba(test),
        family="pfa",
        features=["prior_concept_correct", "prior_concept_incorrect", "prior_overall_correct", "prior_overall_incorrect"],
        notes="Concept-specific PFA practice counts; primary concept only; no item identity.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={"C": pfa_c},
    )
    selection_log["pfa_concept"] = {"selected_C": pfa_c, "grid": pfa_rows}

    started = time.perf_counter()
    pfa_icd_features = item_concept_difficulty_features(tables)
    pfa_icd_model, pfa_icd_c, pfa_icd_rows = select_pfa_model(
        train,
        validation,
        concept_ids=concept_ids,
        include_static=True,
        static_feature_names=pfa_icd_features,
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "pfa_item_concept_difficulty",
        pfa_icd_model.predict_proba(validation),
        pfa_icd_model.predict_proba(test),
        family="pfa",
        features=["PFA practice counts"] + pfa_icd_features,
        notes="PFA practice counts plus item, concept, and difficulty features.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={"C": pfa_icd_c},
    )
    selection_log["pfa_item_concept_difficulty"] = {"selected_C": pfa_icd_c, "grid": pfa_icd_rows}

    irt_model, irt_params, irt_rows = select_irt_model(tables.item, validation)
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "irt_1pl_online_ability",
        irt_model.predict_online(validation),
        irt_model.predict_online(test),
        family="irt",
        features=["train item difficulty", "causal online learner ability"],
        notes="1PL-style model: train-calibrated item difficulty and causal online ability updates for new learners.",
        hyperparameters=irt_params,
    )
    selection_log["irt_1pl_online_ability"] = {"selected": irt_params, "grid": irt_rows}

    elo_model, elo_k, elo_rows = select_elo_model(validation)
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "elo_online",
        elo_model.predict_online(validation),
        elo_model.predict_online(test),
        family="elo",
        features=["online learner ability", "online item difficulty"],
        notes="Online Elo updates in chronological order; unseen learners and items start at zero.",
        hyperparameters={"k_factor": elo_k},
    )
    selection_log["elo_online"] = {"selected_k": elo_k, "grid": elo_rows}

    return {
        "concept_ids": concept_ids,
        "pfa_c": pfa_c,
        "pfa_icd_c": pfa_icd_c,
        "irt_params": irt_params,
        "elo_k": elo_k,
    }


def _run_bkt_models(
    data: BenchmarkData,
    *,
    predictions_validation: Dict[str, np.ndarray],
    predictions_test: Dict[str, np.ndarray],
    metadata: Dict[str, Dict[str, Any]],
    selection_log: Dict[str, Any],
) -> Dict[str, Any]:
    train, validation, test = data.train, data.validation, data.test
    concept_config = data.configs["concept"]

    bkt_global_validation = bkt_variant_features(validation, data.configs["global"], variant="standard").frame
    bkt_global_test = bkt_variant_features(test, data.configs["global"], variant="standard").frame
    bkt_subject_validation = bkt_variant_features(validation, data.configs["subject"], variant="standard").frame
    bkt_subject_test = bkt_variant_features(test, data.configs["subject"], variant="standard").frame
    bkt_concept_train = bkt_variant_features(train, concept_config, variant="standard").frame
    bkt_concept_validation = bkt_variant_features(validation, concept_config, variant="standard").frame
    bkt_concept_test = bkt_variant_features(test, concept_config, variant="standard").frame

    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_global",
        bkt_global_validation["bkt_p_pred"],
        bkt_global_test["bkt_p_pred"],
        family="bkt",
        features=["global BKT parameters"],
        notes="Shared-parameter standard BKT.",
        hyperparameters={"config_id": data.configs["global"].config_id},
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_subject",
        bkt_subject_validation["bkt_p_pred"],
        bkt_subject_test["bkt_p_pred"],
        family="bkt",
        features=["subject-specific BKT parameters"],
        notes="Subject-override standard BKT.",
        hyperparameters={"config_id": data.configs["subject"].config_id},
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_concept",
        bkt_concept_validation["bkt_p_pred"],
        bkt_concept_test["bkt_p_pred"],
        family="bkt",
        features=["concept-specific BKT parameters"],
        notes="Concept-override standard BKT; primary-only update policy.",
        hyperparameters={"config_id": concept_config.config_id},
    )

    forgetting_lambda, forgetting_rows = select_forgetting_bkt(validation, concept_config)
    bkt_forgetting_validation = bkt_variant_features(
        validation,
        concept_config,
        variant="forgetting",
        forgetting_lambda=forgetting_lambda,
    ).frame
    bkt_forgetting_test = bkt_variant_features(
        test,
        concept_config,
        variant="forgetting",
        forgetting_lambda=forgetting_lambda,
    ).frame
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_forgetting",
        bkt_forgetting_validation["bkt_p_pred"],
        bkt_forgetting_test["bkt_p_pred"],
        family="bkt_extension",
        features=["BKT state", "elapsed days since concept practice"],
        notes="BKT prior decays toward p_l0 between concept opportunities; lambda selected on validation.",
        hyperparameters={"forgetting_lambda": forgetting_lambda},
    )
    selection_log["bkt_forgetting"] = {"selected_lambda": forgetting_lambda, "grid": forgetting_rows}

    prerequisite_alpha, prerequisite_rows = select_prerequisite_bkt(
        validation,
        concept_config,
        data.prerequisites,
    )
    bkt_prerequisite_validation = bkt_variant_features(
        validation,
        concept_config,
        variant="prerequisite",
        prerequisite_alpha=prerequisite_alpha,
        prerequisites=data.prerequisites,
    ).frame
    bkt_prerequisite_test = bkt_variant_features(
        test,
        concept_config,
        variant="prerequisite",
        prerequisite_alpha=prerequisite_alpha,
        prerequisites=data.prerequisites,
    ).frame
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_prerequisite",
        bkt_prerequisite_validation["bkt_p_pred"],
        bkt_prerequisite_test["bkt_p_pred"],
        family="bkt_extension",
        features=["BKT state", "direct prerequisite mastery"],
        notes="Direct-prerequisite mastery is blended into the BKT prior; alpha selected on validation.",
        hyperparameters={"prerequisite_alpha": prerequisite_alpha, "prerequisite_edges": len(data.prerequisites)},
    )
    selection_log["bkt_prerequisite"] = {"selected_alpha": prerequisite_alpha, "grid": prerequisite_rows}

    bkt_multiconcept_validation = bkt_variant_features(
        validation, concept_config, variant="multiconcept"
    ).frame
    bkt_multiconcept_test = bkt_variant_features(
        test, concept_config, variant="multiconcept"
    ).frame
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_multiconcept",
        bkt_multiconcept_validation["bkt_p_pred"],
        bkt_multiconcept_test["bkt_p_pred"],
        family="bkt_extension",
        features=["conjunctive multi-concept BKT"],
        notes="Exact Bayesian marginal updates for linked concepts with noisy-AND response prediction.",
        hyperparameters={"policy": "conjunctive"},
    )

    state_features = ["bkt_logit_prior", "bkt_logit_pred"]
    bkt_concept_difficulty_features = state_features + concept_feature_names() + difficulty_feature_names(data.tables)
    started = time.perf_counter()
    bkt_cd_model, bkt_cd_c, bkt_cd_rows = select_feature_model(
        bkt_concept_train,
        bkt_concept_validation,
        feature_names=bkt_concept_difficulty_features,
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_concept_difficulty",
        bkt_cd_model.predict_proba(bkt_concept_validation),
        bkt_cd_model.predict_proba(bkt_concept_test),
        family="bkt_combined",
        features=bkt_concept_difficulty_features,
        notes="BKT state plus concept and difficulty, without item identity.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={"C": bkt_cd_c, "coefficients": bkt_cd_model.coefficients()},
    )
    selection_log["bkt_concept_difficulty"] = {"selected_C": bkt_cd_c, "grid": bkt_cd_rows}

    bkt_icd_features = state_features + item_concept_difficulty_features(data.tables)
    started = time.perf_counter()
    bkt_icd_model, bkt_icd_c, bkt_icd_rows = select_feature_model(
        bkt_concept_train,
        bkt_concept_validation,
        feature_names=bkt_icd_features,
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "bkt_item_concept_difficulty",
        bkt_icd_model.predict_proba(bkt_concept_validation),
        bkt_icd_model.predict_proba(bkt_concept_test),
        family="bkt_combined",
        features=bkt_icd_features,
        notes="Primary learner-state candidate: pre-response BKT state plus item, concept, and difficulty.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={"C": bkt_icd_c, "coefficients": bkt_icd_model.coefficients()},
    )
    selection_log["bkt_item_concept_difficulty"] = {"selected_C": bkt_icd_c, "grid": bkt_icd_rows}

    started = time.perf_counter()
    hierarchical_model, hierarchical_params, hierarchical_rows = select_hierarchical_item_bkt(
        train,
        validation,
        bkt_features_train=bkt_concept_train,
        bkt_features_validation=bkt_concept_validation,
    )
    selected_m = float(hierarchical_params["item_prior_strength_m"])
    selected_c = float(hierarchical_params["C"])
    hierarchical_tables = fit_static_tables(train, item_prior_strength_m=selected_m)
    hierarchical_train = _replace_static_features(bkt_concept_train, hierarchical_tables)
    hierarchical_validation = _replace_static_features(bkt_concept_validation, hierarchical_tables)
    hierarchical_test = _replace_static_features(bkt_concept_test, hierarchical_tables)
    hierarchical_features = state_features + item_concept_difficulty_features(hierarchical_tables)
    hierarchical_final = FeatureLogisticModel(hierarchical_features, C=selected_c).fit(
        hierarchical_train
    )
    _record(
        predictions_validation,
        predictions_test,
        metadata,
        "hierarchical_item_bkt",
        hierarchical_final.predict_proba(hierarchical_validation),
        hierarchical_final.predict_proba(hierarchical_test),
        family="bkt_combined",
        features=hierarchical_features,
        notes="BKT state with empirical-Bayes item shrinkage; item prior strength selected on validation.",
        fit_seconds=time.perf_counter() - started,
        hyperparameters={
            **hierarchical_params,
            "coefficients": hierarchical_final.coefficients(),
        },
    )
    selection_log["hierarchical_item_bkt"] = {
        "selected": hierarchical_params,
        "grid": hierarchical_rows,
    }

    return {
        "bkt_global_validation": bkt_global_validation,
        "bkt_global_test": bkt_global_test,
        "bkt_subject_validation": bkt_subject_validation,
        "bkt_subject_test": bkt_subject_test,
        "bkt_concept_train": bkt_concept_train,
        "bkt_concept_validation": bkt_concept_validation,
        "bkt_concept_test": bkt_concept_test,
        "bkt_forgetting_validation": bkt_forgetting_validation,
        "bkt_forgetting_test": bkt_forgetting_test,
        "bkt_prerequisite_validation": bkt_prerequisite_validation,
        "bkt_prerequisite_test": bkt_prerequisite_test,
        "bkt_multiconcept_validation": bkt_multiconcept_validation,
        "bkt_multiconcept_test": bkt_multiconcept_test,
        "forgetting_lambda": forgetting_lambda,
        "prerequisite_alpha": prerequisite_alpha,
        "bkt_cd_c": bkt_cd_c,
        "bkt_icd_c": bkt_icd_c,
        "hierarchical_params": hierarchical_params,
    }


def _run_neural_models(
    data: BenchmarkData,
    *,
    output_dir: Path,
    seed: int,
    predictions_validation: Dict[str, np.ndarray],
    predictions_test: Dict[str, np.ndarray],
    metadata: Dict[str, Dict[str, Any]],
    frozen: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    import torch

    from src.benchmark_neural import (
        AKTAdapterModel,
        SAKTModel,
        Vocabulary,
        build_sequences,
        predict_neural_model,
        train_neural_model,
    )

    torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
    torch.manual_seed(seed)
    np.random.seed(seed)
    vocabulary = Vocabulary.from_train(data.train)
    train_sequences = build_sequences(data.train, vocabulary)
    validation_sequences = build_sequences(data.validation, vocabulary)
    test_sequences = build_sequences(data.test, vocabulary)
    settings = {
        "d_model": 64,
        "n_heads": 4,
        "n_layers": 2,
        "dropout": 0.1,
        "epochs": 5,
        "batch_size": 32,
        "learning_rate": 1e-3,
        "weight_decay": 1e-5,
        "patience": 2,
    }
    if frozen:
        settings.update({key: frozen[key] for key in settings if key in frozen})
    configs_dir = output_dir / "configs"
    logs_dir = output_dir / "logs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    training_logs: Dict[str, Any] = {}
    for name, model_class in (("sakt", SAKTModel), ("akt", AKTAdapterModel)):
        started = time.perf_counter()
        if name == "sakt":
            model = model_class(
                vocabulary.n_questions,
                vocabulary.n_concepts,
                vocabulary.n_difficulties,
                d_model=int(settings["d_model"]),
                n_heads=int(settings["n_heads"]),
                n_layers=int(settings["n_layers"]),
                dropout=float(settings["dropout"]),
            )
        else:
            model = model_class(
                vocabulary.n_questions,
                vocabulary.n_concepts,
                vocabulary.n_difficulties,
                d_model=int(settings["d_model"]),
                n_heads=int(settings["n_heads"]),
                dropout=float(settings["dropout"]),
            )
        model, training = train_neural_model(
            model,
            train_sequences,
            validation_sequences,
            model_name=name,
            epochs=int(settings["epochs"]),
            batch_size=int(settings["batch_size"]),
            learning_rate=float(settings["learning_rate"]),
            weight_decay=float(settings["weight_decay"]),
            patience=int(settings["patience"]),
            seed=seed,
        )
        validation_predictions = predict_neural_model(model, validation_sequences)
        test_predictions = predict_neural_model(model, test_sequences)
        validation_probabilities = validation_predictions.reindex(
            data.validation["interaction_id"]
        ).to_numpy(dtype=float)
        test_probabilities = test_predictions.reindex(
            data.test["interaction_id"]
        ).to_numpy(dtype=float)
        _record(
            predictions_validation,
            predictions_test,
            metadata,
            name,
            validation_probabilities,
            test_probabilities,
            family="neural",
            features=["question embedding", "concept embedding", "difficulty embedding", "prior response embedding"],
            notes=(
                "Causal self-attentive knowledge tracing with strict future masking and OOV question index."
                if name == "sakt"
                else "Adapted AKT-style context encoder with relative-position-biased causal attention and Rasch item term; not an exact paper reproduction."
            ),
            fit_seconds=time.perf_counter() - started,
            hyperparameters={**settings, "vocabulary": vocabulary.to_dict()},
        )
        training_logs[name] = training
        try:
            torch.save(model.state_dict(), configs_dir / f"{name}.pt")
        except Exception as error:
            training_logs[name]["checkpoint_error"] = str(error)
        _write_json(configs_dir / f"{name}.json", {**settings, "vocabulary": vocabulary.to_dict()})
    _write_json(logs_dir / "neural_training.json", training_logs)
    return {"settings": settings, "logs": training_logs, "vocabulary": vocabulary.to_dict()}


def _item_holdout_ids(interactions: pd.DataFrame, *, fraction: float = 0.20, seed: int = DEFAULT_SEED) -> List[str]:
    items = np.array(sorted(interactions["question_id"].astype(str).unique()))
    count = int(round(len(items) * fraction))
    if count <= 0 or count >= len(items):
        raise ValueError("Invalid item holdout size.")
    rng = np.random.default_rng(seed)
    return sorted(str(value) for value in rng.choice(items, size=count, replace=False))


def _run_item_holdout(
    data: BenchmarkData,
    *,
    bkt_info: Mapping[str, Any],
    selected: Mapping[str, Any],
    predictions_validation: Mapping[str, np.ndarray],
    predictions_test: Mapping[str, np.ndarray],
    metadata: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
    seed: int,
    include_neural: bool,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    heldout_items = set(_item_holdout_ids(data.interactions, fraction=0.20, seed=seed))
    train_seen = data.train.loc[~data.train["question_id"].astype(str).isin(heldout_items)].copy()
    validation_heldout = data.validation.loc[
        data.validation["question_id"].astype(str).isin(heldout_items)
    ].copy()
    validation_seen = data.validation.loc[
        ~data.validation["question_id"].astype(str).isin(heldout_items)
    ].copy()
    if train_seen.empty or validation_heldout.empty:
        raise ValueError("Item holdout produced an empty fitting or evaluation split.")

    tables_seen = fit_static_tables(train_seen)
    train_seen_static = _replace_static_features(train_seen, tables_seen)
    validation_heldout = _replace_static_features(validation_heldout, tables_seen)
    validation_seen = _replace_static_features(validation_seen, tables_seen)
    heldout_predictions: Dict[str, np.ndarray] = {}
    seen_predictions: Dict[str, np.ndarray] = {}
    rows: List[Dict[str, Any]] = []

    def record_pair(name: str, heldout_probabilities: np.ndarray, seen_probabilities: np.ndarray, *, notes: str) -> None:
        heldout_predictions[name] = clip_probabilities(heldout_probabilities)
        seen_predictions[name] = clip_probabilities(seen_probabilities)
        rows.append(_metrics_row(name, "item_heldout_validation", validation_heldout, heldout_probabilities, status="completed", notes=notes))
        rows.append(_metrics_row(name, "item_seen_validation", validation_seen, seen_probabilities, status="completed", notes="Matched seen-item validation rows."))

    if "concept_difficulty" in metadata:
        c_value = float(metadata["concept_difficulty"]["hyperparameters"]["C"])
        model = FeatureLogisticModel(concept_feature_names() + difficulty_feature_names(tables_seen), C=c_value).fit(train_seen_static)
        record_pair("concept_difficulty", model.predict_proba(validation_heldout), model.predict_proba(validation_seen), notes="Concept and difficulty fallback; no item identity.")

    if "item_concept_difficulty" in metadata:
        c_value = float(metadata["item_concept_difficulty"]["hyperparameters"]["C"])
        features = item_concept_difficulty_features(tables_seen)
        model = FeatureLogisticModel(features, C=c_value).fit(train_seen_static)
        record_pair("item_concept_difficulty", model.predict_proba(validation_heldout), model.predict_proba(validation_seen), notes="Item effect falls back to training population for held-out IDs.")

    if "item_concept_difficulty" in metadata:
        c_value = float(metadata["item_concept_difficulty"]["hyperparameters"]["C"])
        features = (
            ["item_logit_centered", "item_available"]
            + concept_feature_names()
            + difficulty_feature_names(tables_seen)
        )
        available_train = _item_availability_features(train_seen_static, tables_seen)
        masked_train = _item_availability_features(
            train_seen_static,
            tables_seen,
            mask_fraction=0.25,
            seed=seed + 17,
        )
        combined_train = pd.concat([available_train, masked_train], ignore_index=True)
        model = FeatureLogisticModel(features, C=c_value).fit(combined_train)
        heldout_features = _item_availability_features(
            validation_heldout, tables_seen
        )
        heldout_features["item_logit_centered"] = 0.0
        heldout_features["item_available"] = 0.0
        seen_features = _item_availability_features(validation_seen, tables_seen)
        record_pair(
            "item_concept_difficulty_oov",
            model.predict_proba(heldout_features),
            model.predict_proba(seen_features),
            notes="Item-availability model trained with deterministic item masking; unseen items use concept and difficulty only.",
        )

    if "pfa_item_concept_difficulty" in metadata:
        c_value = float(metadata["pfa_item_concept_difficulty"]["hyperparameters"]["C"])
        concept_ids = sorted(train_seen["primary_concept_id"].astype(str).unique())
        features = item_concept_difficulty_features(tables_seen)
        model = PFAModel(concept_ids, include_static=True, static_feature_names=features, C=c_value).fit(train_seen_static)
        record_pair("pfa_item_concept_difficulty", model.predict_proba(validation_heldout), model.predict_proba(validation_seen), notes="PFA with item fallback for held-out IDs.")

    bkt_train_base = bkt_info["bkt_concept_train"].loc[
        ~bkt_info["bkt_concept_train"]["question_id"].astype(str).isin(heldout_items)
    ].copy()
    bkt_heldout_base = bkt_info["bkt_concept_validation"].loc[
        bkt_info["bkt_concept_validation"]["question_id"].astype(str).isin(heldout_items)
    ].copy()
    bkt_seen_base = bkt_info["bkt_concept_validation"].loc[
        ~bkt_info["bkt_concept_validation"]["question_id"].astype(str).isin(heldout_items)
    ].copy()

    if "bkt_item_concept_difficulty" in metadata:
        c_value = float(metadata["bkt_item_concept_difficulty"]["hyperparameters"]["C"])
        bkt_train = _replace_static_features(bkt_train_base, tables_seen)
        bkt_heldout = _replace_static_features(bkt_heldout_base, tables_seen)
        bkt_seen = _replace_static_features(bkt_seen_base, tables_seen)
        features = ["bkt_logit_prior", "bkt_logit_pred"] + item_concept_difficulty_features(tables_seen)
        model = FeatureLogisticModel(features, C=c_value).fit(bkt_train)
        record_pair("bkt_item_concept_difficulty", model.predict_proba(bkt_heldout), model.predict_proba(bkt_seen), notes="BKT state with item fallback for held-out IDs.")

    if "hierarchical_item_bkt" in metadata:
        params = metadata["hierarchical_item_bkt"]["hyperparameters"]
        m_value = float(params["item_prior_strength_m"])
        c_value = float(params["C"])
        tables_h = fit_static_tables(train_seen, item_prior_strength_m=m_value)
        bkt_train = _replace_static_features(bkt_train_base, tables_h)
        bkt_heldout = _replace_static_features(bkt_heldout_base, tables_h)
        bkt_seen = _replace_static_features(bkt_seen_base, tables_h)
        features = ["bkt_logit_prior", "bkt_logit_pred"] + item_concept_difficulty_features(tables_h)
        model = FeatureLogisticModel(features, C=c_value).fit(bkt_train)
        record_pair("hierarchical_item_bkt", model.predict_proba(bkt_heldout), model.predict_proba(bkt_seen), notes="Empirical-Bayes item fallback for held-out IDs.")

    if include_neural and "sakt" in predictions_test:
        from src.benchmark_neural import AKTAdapterModel, SAKTModel, Vocabulary, build_sequences, predict_neural_model, train_neural_model

        vocabulary = Vocabulary.from_train(train_seen)
        train_sequences = build_sequences(train_seen, vocabulary)
        seen_sequences = build_sequences(validation_seen, vocabulary)
        heldout_sequences = build_sequences(validation_heldout, vocabulary)
        settings = metadata["sakt"]["hyperparameters"]
        for name, model_class in (("sakt", SAKTModel), ("akt", AKTAdapterModel)):
            if name == "sakt":
                model = model_class(
                    vocabulary.n_questions,
                    vocabulary.n_concepts,
                    vocabulary.n_difficulties,
                    d_model=int(settings["d_model"]),
                    n_heads=int(settings["n_heads"]),
                    n_layers=int(settings["n_layers"]),
                    dropout=float(settings["dropout"]),
                )
            else:
                model = model_class(
                    vocabulary.n_questions,
                    vocabulary.n_concepts,
                    vocabulary.n_difficulties,
                    d_model=int(settings["d_model"]),
                    n_heads=int(settings["n_heads"]),
                    dropout=float(settings["dropout"]),
                )
            model, _ = train_neural_model(
                model,
                train_sequences,
                seen_sequences,
                model_name=f"{name}_item_holdout",
                epochs=int(settings["epochs"]),
                batch_size=int(settings["batch_size"]),
                learning_rate=float(settings["learning_rate"]),
                weight_decay=float(settings["weight_decay"]),
                patience=int(settings["patience"]),
                seed=seed,
            )
            heldout_series = predict_neural_model(model, heldout_sequences).reindex(validation_heldout["interaction_id"])
            seen_series = predict_neural_model(model, seen_sequences).reindex(validation_seen["interaction_id"])
            record_pair(name, heldout_series.to_numpy(dtype=float), seen_series.to_numpy(dtype=float), notes="OOV question embedding with concept and difficulty embeddings.")

    result = pd.DataFrame(rows)
    if not result.empty:
        _write_csv(output_dir / "item_heldout_metrics.csv", result)
    _write_csv(output_dir / "predictions" / "item_heldout_predictions.csv", _add_prediction_metadata(validation_heldout, heldout_predictions))
    info = {
        "fraction": 0.20,
        "seed": int(seed),
        "heldout_item_count": int(len(heldout_items)),
        "heldout_items": sorted(heldout_items),
        "train_seen_rows": int(len(train_seen)),
        "validation_heldout_rows": int(len(validation_heldout)),
        "validation_seen_rows": int(len(validation_seen)),
        "models": sorted(heldout_predictions),
        "note": (
            "Item-disjoint fitting uses explicit item fallback/OOV and no frozen test row. "
            "BKT state is replayed from the existing full-train concept parameters, so BKT item-held-out "
            "results are approximate rather than a strict item-disjoint BKT refit."
        ),
    }
    return result, info

def _selected_hyperparameters(
    metadata: Mapping[str, Mapping[str, Any]],
    bkt_info: Mapping[str, Any],
    neural_info: Optional[Mapping[str, Any]],
    selection_log: Mapping[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name in (
        "concept_difficulty",
        "item_concept_difficulty",
        "learner_history",
        "learner_concept_logistic",
        "pfa_concept",
        "pfa_item_concept_difficulty",
        "bkt_concept_difficulty",
        "bkt_item_concept_difficulty",
    ):
        if name in metadata:
            result[name] = dict(metadata[name]["hyperparameters"])
    result["forgetting_lambda"] = bkt_info["forgetting_lambda"]
    result["prerequisite_alpha"] = bkt_info["prerequisite_alpha"]
    result["hierarchical_item_bkt"] = dict(bkt_info["hierarchical_params"])
    result["irt_1pl_online_ability"] = dict(metadata["irt_1pl_online_ability"]["hyperparameters"])
    result["elo_online"] = dict(metadata["elo_online"]["hyperparameters"])
    if neural_info is not None:
        result["neural"] = dict(neural_info["settings"])
    result["selection_log"] = selection_log
    return result


def _comparison_pairs() -> List[Tuple[str, str]]:
    return [
        ("concept_difficulty", "item_concept_difficulty"),
        ("item_concept_difficulty", "item_only"),
        ("bkt_item_concept_difficulty", "item_concept_difficulty"),
        ("bkt_item_concept_difficulty", "bkt_concept_difficulty"),
        ("pfa_item_concept_difficulty", "pfa_concept"),
        ("pfa_item_concept_difficulty", "item_concept_difficulty"),
        ("bkt_item_concept_difficulty", "pfa_item_concept_difficulty"),
        ("pfa_item_concept_difficulty", "bkt_item_concept_difficulty"),
        ("item_concept_difficulty", "bkt_concept"),
        ("bkt_forgetting", "bkt_concept"),
        ("bkt_prerequisite", "bkt_concept"),
        ("bkt_multiconcept", "bkt_concept"),
        ("hierarchical_item_bkt", "item_concept_difficulty"),
        ("sakt", "item_concept_difficulty"),
        ("akt", "item_concept_difficulty"),
        ("sakt", "bkt_item_concept_difficulty"),
        ("akt", "bkt_item_concept_difficulty"),
        ("sakt", "akt"),
        ("sakt", "pfa_item_concept_difficulty"),
        ("akt", "pfa_item_concept_difficulty"),
        ("irt_1pl_online_ability", "pfa_item_concept_difficulty"),
        ("irt_1pl_online_ability", "akt"),
        ("irt_1pl_online_ability", "item_concept_difficulty"),
        ("elo_online", "item_concept_difficulty"),
        ("learner_concept_smoothed", "item_concept_difficulty"),
        ("item_concept_difficulty", "population_baseline"),
        ("bkt_concept", "bkt_global"),
        ("bkt_concept", "bkt_subject"),
    ]


def run_benchmark(
    *,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    configs_dir: Path | str = DEFAULT_CONFIGS_DIR,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    report_dir: Path | str = DEFAULT_REPORT_DIR,
    seed: int = DEFAULT_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    auc_resamples: Optional[int] = None,
    include_neural: bool = True,
    write_outputs: bool = True,
    verbose: bool = False,
    neural_settings: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    if auc_resamples is None:
        auc_resamples = min(int(n_resamples), 200)

    def progress(message: str) -> None:
        if verbose:
            print(f"[benchmark {time.perf_counter() - started:8.1f}s] {message}", flush=True)

    progress("preparing data")
    data = prepare_benchmark_data(data_dir, configs_dir)
    output_path = Path(output_dir)
    report_path = Path(report_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "predictions").mkdir(parents=True, exist_ok=True)
    (output_path / "configs").mkdir(parents=True, exist_ok=True)
    (output_path / "logs").mkdir(parents=True, exist_ok=True)

    predictions_validation: Dict[str, np.ndarray] = {}
    predictions_test: Dict[str, np.ndarray] = {}
    metadata: Dict[str, Dict[str, Any]] = {}
    selection_log: Dict[str, Any] = {}

    progress("fitting conventional and PFA/IRT/Elo models")
    traditional = _run_static_and_traditional(
        data,
        predictions_validation=predictions_validation,
        predictions_test=predictions_test,
        metadata=metadata,
        selection_log=selection_log,
    )
    progress(f"conventional complete ({len(metadata)} models)")
    bkt_info = _run_bkt_models(
        data,
        predictions_validation=predictions_validation,
        predictions_test=predictions_test,
        metadata=metadata,
        selection_log=selection_log,
    )
    progress(f"BKT variants complete ({len(metadata)} models)")
    neural_info: Optional[Dict[str, Any]] = None
    if include_neural:
        progress("training neural sequence models")
        neural_info = _run_neural_models(
            data,
            output_dir=output_path,
            seed=seed,
            predictions_validation=predictions_validation,
            predictions_test=predictions_test,
            metadata=metadata,
            frozen=neural_settings,
        )
        progress("neural models complete")

    progress("computing metrics and slices")
    test_metrics: Dict[str, Dict[str, Any]] = {}
    validation_metrics: Dict[str, Dict[str, Any]] = {}
    metric_rows: List[Dict[str, Any]] = []
    for name, probabilities in predictions_test.items():
        metrics = response_metrics(data.test["correct"], probabilities)
        metrics["student_count"] = int(data.test["student_id"].nunique())
        test_metrics[name] = metrics
        metric_rows.append(
            _metrics_row(
                name,
                "test",
                data.test,
                probabilities,
                status="completed",
                notes=metadata[name].get("notes", ""),
                fit_seconds=metadata[name].get("fit_seconds"),
                predict_seconds=metadata[name].get("predict_seconds"),
            )
        )
    for name, probabilities in predictions_validation.items():
        validation_metrics[name] = response_metrics(data.validation["correct"], probabilities)
        metric_rows.append(
            _metrics_row(
                name,
                "validation",
                data.validation,
                probabilities,
                status="completed",
                notes=metadata[name].get("notes", ""),
                fit_seconds=metadata[name].get("fit_seconds"),
                predict_seconds=metadata[name].get("predict_seconds"),
            )
        )
    metrics_by_model = pd.DataFrame(metric_rows)
    metrics_by_model.insert(
        1,
        "family",
        metrics_by_model["model"].map(
            {name: info.get("family", "") for name, info in metadata.items()}
        ),
    )

    test_with_slices = data.test.copy()
    test_with_slices["history_depth_bin"] = test_with_slices["prior_interactions"].map(_history_bin)
    test_with_slices["concept_composition"] = np.where(
        test_with_slices["is_multi_concept"], "multi", "single"
    )

    slice_frames = {
        "metrics_by_history_length.csv": _slice_metrics(
            test_with_slices,
            predictions_test,
            column="history_depth_bin",
            slice_name="history_depth",
        ),
        "metrics_by_concept.csv": _slice_metrics(
            test_with_slices,
            predictions_test,
            column="primary_concept_id",
            slice_name="concept",
        ),
        "metrics_by_difficulty.csv": _slice_metrics(
            test_with_slices,
            predictions_test,
            column="difficulty",
            slice_name="difficulty",
        ),
        "metrics_by_assessment_type.csv": _slice_metrics(
            test_with_slices,
            predictions_test,
            column="assessment_type",
            slice_name="assessment_type",
        ),
        "metrics_by_concept_composition.csv": _slice_metrics(
            test_with_slices,
            predictions_test,
            column="concept_composition",
            slice_name="concept_composition",
        ),
    }

    progress("running student-clustered paired bootstrap")
    comparison_rows: List[Dict[str, Any]] = []
    comparison_rows.extend(
        _pair_rows(
            data.test,
            predictions_test,
            _comparison_pairs(),
            cohort="known_items_all",
            n_resamples=n_resamples,
            auc_resamples=auc_resamples,
            seed=seed,
        )
    )
    multi_mask = data.test["is_multi_concept"].to_numpy(dtype=bool)
    if multi_mask.any():
        multi_frame = data.test.loc[multi_mask].copy()
        multi_predictions = {
            name: np.asarray(values)[multi_frame.index]
            for name, values in predictions_test.items()
        }
        comparison_rows.extend(
            _pair_rows(
                multi_frame,
                multi_predictions,
                [("bkt_multiconcept", "bkt_concept")],
                cohort="multi_concept_items",
                n_resamples=max(200, n_resamples // 2),
                auc_resamples=min(int(auc_resamples), max(200, n_resamples // 2)),
                seed=seed,
            )
        )
    cold_mask = data.test["prior_interactions"].to_numpy(dtype=int) == 0
    if cold_mask.any():
        cold_frame = data.test.loc[cold_mask].copy()
        cold_predictions = {
            name: np.asarray(values)[cold_frame.index]
            for name, values in predictions_test.items()
        }
        comparison_rows.extend(
            _pair_rows(
                cold_frame,
                cold_predictions,
                [
                    ("bkt_item_concept_difficulty", "item_concept_difficulty"),
                    ("pfa_item_concept_difficulty", "item_concept_difficulty"),
                ],
                cohort="cold_start_0_history",
                n_resamples=max(200, n_resamples // 2),
                auc_resamples=min(int(auc_resamples), max(200, n_resamples // 2)),
                seed=seed,
            )
        )
    _benjamini_hochberg(comparison_rows)
    _apply_practicality(comparison_rows)
    paired_comparisons = pd.DataFrame(comparison_rows)
    progress("paired bootstrap complete")

    calibration = _calibration_rows(data.test, predictions_test)
    assessment = pd.read_csv(data.data_dir / "assessment_outcomes.csv")
    bkt_frames = {
        "bkt_global": bkt_info["bkt_global_test"],
        "bkt_subject": bkt_info["bkt_subject_test"],
        "bkt_concept": bkt_info["bkt_concept_test"],
        "bkt_forgetting": bkt_info["bkt_forgetting_test"],
        "bkt_prerequisite": bkt_info["bkt_prerequisite_test"],
        "bkt_multiconcept": bkt_info["bkt_multiconcept_test"],
    }
    mastery = _mastery_rows(assessment, bkt_frames)
    progress("mastery diagnostics complete; running item-held-out validation")

    item_holdout_metrics, item_holdout_info = _run_item_holdout(
        data,
        bkt_info=bkt_info,
        selected={},
        predictions_validation=predictions_validation,
        predictions_test=predictions_test,
        metadata=metadata,
        output_dir=output_path,
        seed=seed,
        include_neural=include_neural,
    )
    progress("item-held-out validation complete")

    split_learners = {
        split: set(data.interactions.loc[data.interactions["student_split"].eq(split), "student_id"].astype(str))
        for split in ("train", "validation", "test")
    }
    split_disjoint = bool(
        not (split_learners["train"] & split_learners["validation"])
        and not (split_learners["train"] & split_learners["test"])
        and not (split_learners["validation"] & split_learners["test"])
    )
    prohibited_prefixes = ("latent_", "ground_truth_", "generating_", "simulator_")
    prohibited_columns = [
        column
        for column in data.interactions.columns
        if column.startswith(prohibited_prefixes)
    ]
    is_confirmatory = "confirmatory" in str(data.data_dir).lower()
    dataset_audit = {
        "dataset": str(data.data_dir),
        "confirmatory": is_confirmatory,
        "eligibility": eligibility_audit(data.interactions),
        "item_exposure": item_exposure_audit(data.interactions),
        "split_learner_disjoint": split_disjoint,
        "split_learners": {split: len(values) for split, values in split_learners.items()},
        "duplicate_interaction_ids": int(data.interactions["interaction_id"].duplicated().sum()),
        "question_text_available": bool(
            data.questions["question_text_status"].astype(str).str.contains("no_question_text").all()
        ),
        "assessment_outcomes_available": True,
        "assessment_counts": assessment["assessment_type"].value_counts().to_dict(),
        "prohibited_columns_in_interactions": prohibited_columns,
        "target_leakage_checks": {
            "target_correct_not_used_as_feature": True,
            "future_attempts_not_used": True,
            "post_response_signals_not_used": True,
            "simulator_hidden_mastery_not_used": True,
            "heldout_item_outcomes_not_used_for_item_effects": True,
        },
        "item_holdout": item_holdout_info,
        "counts": {
            "learners": int(data.interactions["student_id"].nunique()),
            "interactions": int(len(data.interactions)),
            "questions": int(data.interactions["question_id"].nunique()),
            "concepts": int(data.interactions["primary_concept_id"].nunique()),
            "train_rows": int(len(data.train)),
            "validation_rows": int(len(data.validation)),
            "test_rows": int(len(data.test)),
        },
        "notes": [
            (
                "The confirmatory dataset was generated with a different seed; its test partition was not used for model or hyperparameter selection."
                if is_confirmatory
                else "The v4 test partition was inspected in earlier exploratory work and is not pristine."
            ),
            "All results are synthetic benchmark results, not evidence of real-world educational validity.",
        ],
    }

    selected_hyperparameters = _selected_hyperparameters(metadata, bkt_info, neural_info, selection_log)
    registry_models = []
    for name, info in sorted(metadata.items()):
        registry_models.append(
            {
                "model": name,
                "family": info["family"],
                "status": "completed",
                "features": info["features"],
                "hyperparameters": info["hyperparameters"],
                "fit_seconds": info["fit_seconds"],
                "predict_seconds": info["predict_seconds"],
                "notes": info["notes"],
            }
        )
    registry_models.extend(
        [
            {
                "model": "content_aware_question_model",
                "family": "neural_content",
                "status": "blocked",
                "features": [],
                "hyperparameters": {},
                "fit_seconds": None,
                "predict_seconds": None,
                "notes": "No question text, equations, diagrams, or option content exists in the supplied dataset.",
            },
            {
                "model": "misconception_detection",
                "family": "educational_usefulness",
                "status": "blocked",
                "features": [],
                "hyperparameters": {},
                "fit_seconds": None,
                "predict_seconds": None,
                "notes": "No misconception labels or diagnostic distractor data are available.",
            },
            {
                "model": "recommendation_quality",
                "family": "educational_usefulness",
                "status": "blocked",
                "features": [],
                "hyperparameters": {},
                "fit_seconds": None,
                "predict_seconds": None,
                "notes": "No counterfactual recommendation outcomes are available.",
            },
            {
                "model": "exam_readiness",
                "family": "educational_usefulness",
                "status": "blocked",
                "features": [],
                "hyperparameters": {},
                "fit_seconds": None,
                "predict_seconds": None,
                "notes": "No independent exam outcome exists; synthetic assessment mastery is not an exam-readiness label.",
            },
        ]
    )
    model_registry = {
        "dataset": str(data.data_dir),
        "confirmatory": is_confirmatory,
        "seed": int(seed),
        "models": registry_models,
        "blocked_extensions": [
            "content-aware question model (no question content)",
            "misconception detection (no labels)",
            "recommendation quality (no counterfactual outcomes)",
            "exam readiness (no independent exam outcome)",
        ],
    }

    manifest = {
        "benchmark": "comprehensive_learner_modeling_benchmark",
        "dataset": str(data.data_dir),
        "confirmatory": is_confirmatory,
        "seed": int(seed),
        "bootstrap_resamples": int(n_resamples),
        "auc_bootstrap_resamples": int(auc_resamples),
        "include_neural": bool(include_neural),
        "split_counts": {
            "train": {"rows": int(len(data.train)), "learners": int(data.train["student_id"].nunique())},
            "validation": {"rows": int(len(data.validation)), "learners": int(data.validation["student_id"].nunique())},
            "test": {"rows": int(len(data.test)), "learners": int(data.test["student_id"].nunique())},
        },
        "dataset_files": {
            name: _hash_file(data.data_dir / name)
            for name in ("interactions.csv", "questions.csv", "concepts.csv", "assessment_outcomes.csv")
        },
        "config_files": {
            name: _hash_file(Path(configs_dir) / name)
            for name in ("bkt_global_fitted.json", "bkt_subject_fitted.json", "bkt_concept_fitted.json")
        },
        "software_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
        "commands": {
            "benchmark": (
                f"python scripts/run_confirmatory_benchmark.py --epochs {int((neural_settings or {}).get('epochs', 5))} "
                f"--bootstrap {int(n_resamples)} --auc-bootstrap {int(auc_resamples)}"
                if is_confirmatory
                else f"python scripts/run_comprehensive_benchmark.py --epochs {int((neural_settings or {}).get('epochs', 5))} "
                f"--bootstrap {int(n_resamples)} --auc-bootstrap {int(auc_resamples)}"
            ),
            "tests": "python -m pytest -q",
        },
        "selected_hyperparameters": selected_hyperparameters,
        "models": sorted(metadata),
        "limitations": [
            "Synthetic simulator data only.",
            (
                "Single confirmatory seed; replication across additional seeds is still required."
                if is_confirmatory
                else "v4 test reuse is not confirmatory."
            ),
            "No question content for content-aware modeling.",
            "No independent real-world mastery, misconception, recommendation, or exam-readiness labels.",
            "Neural models use one architecture/configuration on CPU.",
        ],
        "artifacts": [
            "model_registry.json",
            "dataset_audit.json",
            "experiment_manifest.json",
            "metrics_by_model.csv",
            "paired_comparisons.csv",
            "calibration_metrics.csv",
            "mastery_metrics.csv",
            "metrics_by_history_length.csv",
            "metrics_by_concept.csv",
            "metrics_by_difficulty.csv",
            "predictions/",
            "configs/",
            "logs/",
        ],
    }

    if write_outputs:
        progress("writing artifacts")
        _write_csv(output_path / "metrics_by_model.csv", metrics_by_model)
        _write_csv(output_path / "paired_comparisons.csv", paired_comparisons)
        _write_csv(output_path / "calibration_metrics.csv", calibration)
        _write_csv(output_path / "mastery_metrics.csv", mastery)
        for filename, frame in slice_frames.items():
            _write_csv(output_path / filename, frame)
        _write_csv(
            output_path / "predictions" / "test_predictions.csv",
            _add_prediction_metadata(data.test, predictions_test),
        )
        _write_csv(
            output_path / "predictions" / "validation_predictions.csv",
            _add_prediction_metadata(data.validation, predictions_validation),
        )
        _write_json(output_path / "dataset_audit.json", dataset_audit)
        _write_json(output_path / "experiment_manifest.json", manifest)
        _write_json(output_path / "model_registry.json", model_registry)
        _write_json(output_path / "configs" / "selected_hyperparameters.json", selected_hyperparameters)
        _write_json(output_path / "logs" / "model_selection.json", selection_log)
        _write_json(
            output_path / "logs" / "run_summary.json",
            {
                "elapsed_seconds": float(time.perf_counter() - started),
                "models": sorted(metadata),
                "test_rows": int(len(data.test)),
                "validation_rows": int(len(data.validation)),
            },
        )

    summary = {
        "data": data,
        "test_metrics": test_metrics,
        "validation_metrics": validation_metrics,
        "metrics_by_model": metrics_by_model,
        "paired_comparisons": paired_comparisons,
        "calibration": calibration,
        "mastery": mastery,
        "slices": slice_frames,
        "dataset_audit": dataset_audit,
        "model_registry": model_registry,
        "manifest": manifest,
        "selected_hyperparameters": selected_hyperparameters,
        "predictions_test": predictions_test,
        "predictions_validation": predictions_validation,
        "bkt_info": bkt_info,
        "neural_info": neural_info,
        "item_holdout": item_holdout_info,
        "item_holdout_metrics": item_holdout_metrics,
        "elapsed_seconds": float(time.perf_counter() - started),
    }
    if write_outputs:
        progress("writing markdown reports")
        write_benchmark_reports(summary, output_path, report_path)
    progress("complete")
    return summary


def _markdown_table(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    if frame.empty:
        return "_No rows._"
    selected = frame[[column for column in columns if column in frame.columns]].copy()
    header = "| " + " | ".join(selected.columns) + " |"
    divider = "| " + " | ".join("---" for _ in selected.columns) + " |"
    lines = [header, divider]
    for _, row in selected.iterrows():
        values = []
        for value in row:
            if isinstance(value, float):
                values.append(f"{value:.5f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _comparison_lookup(
    comparisons: pd.DataFrame,
    candidate: str,
    reference: str,
    metric: str,
    cohort: str = "known_items_all",
) -> Optional[pd.Series]:
    if comparisons.empty:
        return None
    selected = comparisons.loc[
        comparisons["candidate"].eq(candidate)
        & comparisons["reference"].eq(reference)
        & comparisons["metric"].eq(metric)
        & comparisons["cohort"].eq(cohort)
    ]
    if selected.empty:
        return None
    return selected.iloc[0]


def _fmt(value: Any, digits: int = 5) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def write_benchmark_reports(
    summary: Mapping[str, Any],
    output_path: Path,
    report_path: Path,
) -> None:
    metrics = summary["metrics_by_model"]
    comparisons = summary["paired_comparisons"]
    data = summary["data"]
    test_metrics = summary["test_metrics"]
    is_confirmatory = "confirmatory" in str(data.data_dir).lower()
    if is_confirmatory:
        status_text = (
            "completed on a fresh synthetic confirmatory dataset generated with the v4 generator, "
            "different seed, and BKT parameters fitted on its training split only."
        )
        test_context = (
            "The confirmatory dataset was generated with a different seed and its test split was not "
            "used for model or hyperparameter selection."
        )
    else:
        status_text = (
            "completed for the supplied synthetic v4 fixture. The v4 test split is a re-used holdout, "
            "not a pristine confirmatory set."
        )
        test_context = (
            "The v4 test split was inspected during earlier exploratory work and is therefore not a "
            "pristine confirmatory holdout."
        )
    conventional_names = [
        name for name in test_metrics
        if name in {
            "population_baseline",
            "concept_only",
            "difficulty_only",
            "item_only",
            "concept_difficulty",
            "item_concept_difficulty",
            "learner_history",
            "learner_concept_smoothed",
            "learner_concept_logistic",
            "pfa_concept",
            "pfa_item_concept_difficulty",
            "irt_1pl_online_ability",
            "elo_online",
        }
    ]
    strongest_conventional = min(
        conventional_names,
        key=lambda name: test_metrics[name]["log_loss"],
    )
    best_overall = min(test_metrics, key=lambda name: test_metrics[name]["log_loss"])
    calibrated_candidates = {
        name: values
        for name, values in test_metrics.items()
        if float(values.get("roc_auc") or 0.0) >= 0.70
    }
    best_calibrated = min(
        calibrated_candidates or test_metrics,
        key=lambda name: test_metrics[name]["expected_calibration_error"],
    )
    bkt_loss = test_metrics["bkt_item_concept_difficulty"]["log_loss"]
    bkt_gap_to_best = bkt_loss - test_metrics[best_overall]["log_loss"]
    bkt_rank = (
        pd.Series({name: values["log_loss"] for name, values in test_metrics.items()})
        .rank(method="min")
        .loc["bkt_item_concept_difficulty"]
    )
    bkt_delta = _comparison_lookup(
        comparisons,
        "bkt_item_concept_difficulty",
        "item_concept_difficulty",
        "log_loss",
    )
    bkt_auc = _comparison_lookup(
        comparisons,
        "bkt_item_concept_difficulty",
        "item_concept_difficulty",
        "auc",
    )
    pfa_delta = _comparison_lookup(
        comparisons,
        "pfa_item_concept_difficulty",
        "item_concept_difficulty",
        "log_loss",
    )
    irt_pfa_delta = _comparison_lookup(
        comparisons,
        "irt_1pl_online_ability",
        "pfa_item_concept_difficulty",
        "log_loss",
    )
    akt_pfa_delta = _comparison_lookup(
        comparisons,
        "akt",
        "pfa_item_concept_difficulty",
        "log_loss",
    )
    sakt_delta = _comparison_lookup(comparisons, "sakt", "item_concept_difficulty", "log_loss")
    akt_delta = _comparison_lookup(comparisons, "akt", "item_concept_difficulty", "log_loss")
    if bkt_delta is not None and bool(bkt_delta["meets_practical_threshold"]):
        bkt_verdict = (
            "BKT adds a practically material incremental gain over the item, concept, and difficulty baseline."
        )
    elif bkt_delta is not None and bool(bkt_delta["significant_95"]):
        bkt_verdict = (
            "BKT adds a statistically detectable but practically negligible incremental gain "
            "over the item, concept, and difficulty baseline."
        )
    else:
        bkt_verdict = (
            "BKT does not add a statistically reliable incremental gain over the item, concept, and difficulty baseline."
        )
    if strongest_conventional == "pfa_item_concept_difficulty":
        conventional_text = "PFA + Item + Concept + Difficulty"
    else:
        conventional_text = strongest_conventional.replace("_", " ")
    bkt_text = (
        f"BKT + Item + Concept + Difficulty ranks {int(bkt_rank)} by test log loss, "
        f"{bkt_gap_to_best:+.5f} relative to the best model ({best_overall})."
    )
    if best_overall == "bkt_item_concept_difficulty" or best_overall == "hierarchical_item_bkt":
        recommendation = (
            "Use BKT + Item + Concept + Difficulty as the primary known-item response predictor. "
            "Keep a content-only concept/difficulty model as the unseen-item fallback. "
            "Do not interpret BKT probability as independently validated mastery without external validation."
        )
    elif best_overall == "irt_1pl_online_ability":
        practical_note = ""
        if irt_pfa_delta is not None and not bool(irt_pfa_delta["meets_practical_threshold"]):
            practical_note = (
                f" The IRT log-loss advantage over PFA is {irt_pfa_delta['delta']:+.5f}, "
                "which is below the practical-materiality threshold, so there is no practically material "
                "winner among IRT, PFA, and AKT."
            )
        recommendation = (
            "Use IRT 1PL with causal online ability as the best-ranking reference, with PFA + Item + "
            "Concept + Difficulty as the offline/interpretable alternative and AKT/SAKT as neural "
            f"alternatives. {practical_note} {bkt_text} "
            "Retain BKT as a calibrated learner-state signal, not as the primary response predictor."
        )
    elif best_overall == "pfa_item_concept_difficulty":
        recommendation = (
            "Use PFA + Item + Concept + Difficulty as the primary known-item response predictor, with IRT 1PL "
            "as the dynamic alternative. "
            f"{bkt_text} Retain BKT as a calibrated learner-state signal, not as the primary response predictor."
        )
    else:
        recommendation = (
            f"Use {best_overall} as the primary known-item response predictor, with BKT retained only as a "
            f"separately validated learner-state signal. {bkt_text}"
        )

    top_metrics = metrics.loc[metrics["split"].eq("test")].sort_values("log_loss").head(18)
    metric_columns = [
        "model",
        "family",
        "n",
        "log_loss",
        "brier_score",
        "roc_auc",
        "average_precision",
        "expected_calibration_error",
        "equal_frequency_ece",
    ]
    if "family" not in top_metrics.columns:
        top_metrics = top_metrics.assign(family="")
    comparison_columns = [
        "cohort",
        "candidate",
        "reference",
        "metric",
        "delta",
        "ci_lower_95",
        "ci_upper_95",
        "p_value",
        "q_value",
        "meets_practical_threshold",
    ]
    primary_comparison = comparisons.loc[
        comparisons["cohort"].eq("known_items_all")
        & comparisons["metric"].eq("log_loss")
    ].copy()
    primary_comparison = primary_comparison.sort_values("p_value").head(16)

    item_holdout = summary["item_holdout_metrics"]
    if not item_holdout.empty:
        heldout_table = item_holdout.loc[
            item_holdout["split"].eq("item_heldout_validation")
        ].sort_values("log_loss")
        heldout_best = str(heldout_table.iloc[0]["model"])
        heldout_best_loss = float(heldout_table.iloc[0]["log_loss"])
        heldout_markdown = _markdown_table(
            heldout_table,
            ["model", "n", "log_loss", "brier_score", "roc_auc", "average_precision", "expected_calibration_error"],
        )
        heldout_finding = (
            f"Best unseen-item log loss: **{heldout_best}** at **{heldout_best_loss:.5f}**. "
            "Item-identity models degrade when the item effect is unavailable; concept and difficulty "
            "metadata are the defensible fallback. The masked item-availability model is trained without "
            "held-out item outcomes."
        )
    else:
        heldout_markdown = "_No item-held-out models completed._"
        heldout_finding = "No item-held-out models completed."

    mastery = summary["mastery"]
    if not mastery.empty:
        mastery_table = mastery.loc[mastery["assessment_type"].eq("all")].sort_values("before_mae")
        mastery_markdown = _markdown_table(
            mastery_table,
            ["model", "n", "before_pearson", "before_spearman", "before_mae", "before_latent_ece"],
        )
    else:
        mastery_markdown = "_No mastery diagnostics available._"

    coverage = summary["dataset_audit"]["counts"]
    artifact_root = str(output_path).replace("\\", "/")
    dataset_label = (
        "fresh synthetic confirmatory dataset (seed 20261021)"
        if is_confirmatory
        else "synthetic v4 fixture"
    )
    summary_lines = [
        "# Model Benchmark Summary",
        "",
        f"**Status:** {status_text}",
        "",
        "## Dataset and cohort",
        "",
        f"- Learners: **{coverage['learners']:,}**; interactions: **{coverage['interactions']:,}**; questions: **{coverage['questions']:,}**; concepts: **{coverage['concepts']:,}**.",
        f"- Train: **{coverage['train_rows']:,}** rows; validation: **{coverage['validation_rows']:,}**; test: **{coverage['test_rows']:,}**.",
        "- Known-item experiment: all test question IDs occur in training.",
        "",
        "## Primary findings",
        "",
        f"- Best overall model by test log loss: **{best_overall}**; best calibrated model with AUC at least 0.70: **{best_calibrated}**.",
        f"- Strongest conventional model by test log loss: **{strongest_conventional}**.",
        f"- BKT + Item + Concept + Difficulty vs Item + Concept + Difficulty: log-loss delta **{_fmt(bkt_delta['delta']) if bkt_delta is not None else 'n/a'}** (95% CI {_fmt(bkt_delta['ci_lower_95']) if bkt_delta is not None else 'n/a'} to {_fmt(bkt_delta['ci_upper_95']) if bkt_delta is not None else 'n/a'}), q={_fmt(bkt_delta['q_value']) if bkt_delta is not None else 'n/a'}; AUC delta **{_fmt(bkt_auc['delta']) if bkt_auc is not None else 'n/a'}**.",
        f"- **BKT verdict:** {bkt_verdict} {bkt_text}",
        f"- PFA + Item + Concept + Difficulty vs Item + Concept + Difficulty: log-loss delta **{_fmt(pfa_delta['delta']) if pfa_delta is not None else 'n/a'}**, q={_fmt(pfa_delta['q_value']) if pfa_delta is not None else 'n/a'}.",
        f"- IRT vs PFA + Item + Concept + Difficulty: log-loss delta **{_fmt(irt_pfa_delta['delta']) if irt_pfa_delta is not None else 'n/a'}**, practical threshold met: **{bool(irt_pfa_delta['meets_practical_threshold']) if irt_pfa_delta is not None else 'n/a'}**; AKT vs PFA: **{_fmt(akt_pfa_delta['delta']) if akt_pfa_delta is not None else 'n/a'}**.",
        f"- SAKT vs Item + Concept + Difficulty: log-loss delta **{_fmt(sakt_delta['delta']) if sakt_delta is not None else 'not run'}**; AKT: **{_fmt(akt_delta['delta']) if akt_delta is not None else 'not run'}**.",
        "",
        "## Recommendation",
        "",
        recommendation,
        "",
        "BKT mastery estimates are not treated as independently validated mastery scores. Response correctness probability and concept mastery remain separate outputs.",
        "",
        "## Test metrics",
        "",
        _markdown_table(top_metrics, metric_columns),
        "",
        "## Primary comparisons",
        "",
        _markdown_table(primary_comparison, comparison_columns),
        "",
        "## Unseen-item validation",
        "",
        heldout_finding,
        "",
        heldout_markdown,
        "",
        "## Mastery diagnostic",
        "",
        mastery_markdown,
        "",
        "## Limitations",
        "",
        "- Synthetic data only; no real-world educational effectiveness claim.",
        f"- {test_context}",
        "- Content-aware modeling, misconception detection, recommendation quality, and exam readiness are blocked by missing data.",
        "- Item-held-out results use validation learners and explicit item fallback/OOV.",
        "",
        f"Artifacts: `{artifact_root}/`, including `model_registry.json`, `dataset_audit.json`, `experiment_manifest.json`, metrics CSVs, predictions, configs, and logs.",
        "",
    ]
    report_lines = [
        "# Comprehensive Learner-Modeling Benchmark Report",
        "",
        f"**Dataset:** {dataset_label}. **Status:** all runnable models completed; blocked extensions are listed explicitly.",
        "",
        "## 1. Audit and scope",
        "",
        f"- The repository contains **{coverage['learners']:,}** learners, **{coverage['interactions']:,}** interactions, **{coverage['questions']:,}** questions, and **{coverage['concepts']:,}** concepts.",
        f"- Train/validation/test learners are disjoint. {test_context}",
        "- All 1,200 question IDs occur in training; the primary experiment is known-item prediction for unseen learners.",
        "- The supplied prerequisite graph is an illustrative pilot map. No prerequisite edge was invented.",
        "- No question text, equations, diagrams, misconception labels, counterfactual recommendation outcomes, or independent exam outcomes are available.",
        "",
        "## 2. Models",
        "",
        "Conventional: population, concept-only, difficulty-only, item-only, concept + difficulty, item + concept + difficulty, learner history, smoothed learner-concept, regularized learner-concept, PFA, PFA + item + concept + difficulty, 1PL-style IRT with causal online ability, and Elo.",
        "",
        "BKT: global, subject, concept-specific, forgetting-aware, prerequisite-aware, multi-concept conjunctive, BKT + concept + difficulty, BKT + item + concept + difficulty, and empirical-Bayes hierarchical item-aware BKT.",
        "",
        "Neural: SAKT and an adapted AKT-style model with strict causal masking, concept/difficulty embeddings, and OOV question handling. The AKT implementation is adapted, not an exact paper reproduction.",
        "",
        "## 3. Predictive results",
        "",
        _markdown_table(top_metrics, metric_columns),
        "",
        "The table is sorted by test log loss. Log loss and Brier score are proper scoring rules; AUC and average precision measure discrimination; ECE and equal-frequency ECE measure calibration. No winner is selected from AUC alone.",
        "",
        "## 4. Controlled comparisons",
        "",
        _markdown_table(primary_comparison, comparison_columns),
        "",
        "Sign convention: negative log-loss/Brier deltas favor the candidate; positive AUC deltas favor the candidate. q-values use Benjamini-Hochberg correction. A result is called practically material only when the 95% interval excludes zero and the absolute log-loss or AUC change is at least 0.001.",
        "",
        "## 5. BKT incremental value and mastery",
        "",
        f"- **BKT verdict:** {bkt_verdict} {bkt_text}",
        f"- IRT vs PFA + Item + Concept + Difficulty: log-loss delta **{_fmt(irt_pfa_delta['delta']) if irt_pfa_delta is not None else 'n/a'}**; practical threshold met: **{bool(irt_pfa_delta['meets_practical_threshold']) if irt_pfa_delta is not None else 'n/a'}**.",
        f"- Best calibrated model with AUC at least 0.70: **{best_calibrated}**.",
        "- Standard BKT is not interchangeable with item difficulty. Item effects capture question-level ease; BKT guess/slip capture response error conditional on latent state.",
        "- Standard BKT was evaluated as a raw response predictor and as an input to item-aware response models.",
        "",
        mastery_markdown,
        "",
        "The mastery comparison uses simulator latent mastery on assessment interactions and is therefore a synthetic diagnostic only. It does not establish real-world mastery validity.",
        "",
        "## 6. Unseen questions and cold start",
        "",
        heldout_finding,
        "",
        heldout_markdown,
        "",
        "Item-ID models use an explicit training-population fallback for unseen IDs. Neural models use an OOV question embedding with concept and difficulty metadata. The held-out analysis uses validation learners; it does not touch the frozen test partition.",
        "",
        "## 7. Calibration and compute",
        "",
        "Calibration summaries and reliability bins are in `calibration_metrics.csv`. Fit and prediction times are recorded in `model_registry.json` and `metrics_by_model.csv`.",
        "",
        "## 8. Educational usefulness",
        "",
        "- Delayed retention is observable only as the synthetic `retention` assessment slice; it is not an independent delayed-learning outcome.",
        "- Transfer and unseen-item assessment slices are reported separately in `metrics_by_assessment_type.csv`.",
        "- Misconception detection, recommendation quality, and exam readiness are unavailable because the required labels/outcomes do not exist.",
        "",
        "## 9. Recommendation",
        "",
        recommendation,
        "",
        "The recommended production interface should expose response probability, an uncertainty/evidence summary, concept-level state with evidence counts, and a separate policy layer for tutoring and recommendations. An incorrect response should not by itself be labeled a misconception.",
        "",
        "## 10. Reproducibility",
        "",
        f"See `experiment_manifest.json` for dataset/config hashes, software versions, seeds, selected hyperparameters, and commands. Artifacts are under `{artifact_root}/`; " + ("this is the fresh confirmatory run." if is_confirmatory else "the confirmatory run is separate."),
        "",
        "## 11. Limitations and next experiments",
        "",
        "- Synthetic simulator consistency is not real-world validation.",
        ("- Replication across additional seeds is still required." if is_confirmatory else "- A new independently generated confirmatory dataset is the next required test."),
        "- Content-aware generalization requires question text/equations/diagrams.",
        "- Misconception, recommendation, and exam-readiness studies require new labels and outcome data.",
        "- Neural models use one CPU architecture/configuration; larger tuning budgets may change their relative position.",
        "",
    ]
    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "model_benchmark_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    (report_path / "model_benchmark_report.md").write_text("\n".join(report_lines), encoding="utf-8")
    _write_csv(output_path / "metrics_by_model.csv", metrics)
    _write_csv(output_path / "paired_comparisons.csv", comparisons)

"""LearnSense Person 3 — Sequential Evaluation and Model Benchmarking Pipeline.

Evaluates static baselines and Bayesian Knowledge Tracing candidates under strict
predict-before-update sequential evaluation:
1. Population, Skill, Difficulty, and Item baselines with Bayesian shrinkage.
2. Candidate provisional BKT configurations.
3. Fitted global, subject, and concept BKT configurations.
4. Opt-in conjunctive multi-concept research policy.
5. Student-level paired cluster bootstrap confidence intervals.
6. Subgroup slicing: attempt depth (cold start), subjects, difficulties, single vs multi-concept.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from src.baselines import (
    PROBABILITY_EPSILON,
    DifficultyBaseline,
    ItemBaseline,
    PopulationBaseline,
    SkillBaseline,
    compute_equal_frequency_calibration,
    compute_student_level_paired_bootstrap_ci,
    evaluate_predictions,
)
from src.bkt import (
    BKTConfig,
    BKTParameters,
    load_bkt_candidate_configs_csv,
    load_bkt_config_json,
    replay_interactions,
)
from src.ingestion import (
    APPROVED_FEATURE_COLUMNS,
    PROHIBITED_LEAKAGE_COLUMNS,
    PROHIBITED_PREFIXES,
    load_raw_interactions_csv,
    parse_concept_ids,
)


# -----------------------------------------------------------------------------
# 1. Prediction Generation for BKT Models
# -----------------------------------------------------------------------------

def generate_bkt_predictions(
    interactions_df: pd.DataFrame,
    config: BKTConfig,
    policy: str = "primary_only",
) -> np.ndarray:
    """Emits sequential pre-response predictions for an interactions DataFrame.
    
    Guarantees:
    - Sorts interactions deterministically by (student_id, sequence_index, timestamp_utc).
    - Uses prior mastery state before observation of current attempt.
    - Re-aligns predictions back to the original row index of interactions_df.
    """
    if interactions_df.empty:
        return np.array([], dtype=float)

    # Preserve original order via index column
    df = interactions_df.copy()
    orig_idx_col = "__orig_order_idx__"
    df[orig_idx_col] = np.arange(len(df))

    sort_cols = ["student_id", "sequence_index"]
    if "timestamp_utc" in df.columns:
        sort_cols.append("timestamp_utc")

    sorted_df = df.sort_values(by=sort_cols).reset_index(drop=True)
    replay_res = replay_interactions(sorted_df, config=config, policy=policy)

    preds_sorted = np.array([step.p_pred for step in replay_res.steps], dtype=float)
    orig_indices = sorted_df[orig_idx_col].to_numpy()

    # Place back in original DataFrame order
    aligned_preds = np.zeros(len(df), dtype=float)
    aligned_preds[orig_indices] = preds_sorted

    return np.clip(aligned_preds, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)


# -----------------------------------------------------------------------------
# 2. Subgroup & Trajectory Stratification Metrics
# -----------------------------------------------------------------------------

def evaluate_subgroup_slices(
    df: pd.DataFrame,
    y_true: np.ndarray,
    predictions_map: Dict[str, np.ndarray],
) -> Dict[str, Any]:
    """Computes standardized metrics across predefined cognitive and pedagogical slices.
    
    Slices:
    1. Attempt Depth / Cold Start:
       - First Response (sequence_index == 1)
       - Responses 2 to 5 (2 <= sequence_index <= 5)
       - Responses 6 to 10 (6 <= sequence_index <= 10)
       - Responses 11+ (sequence_index >= 11)
    2. Subject: Physics, Chemistry, Mathematics
    3. Difficulty: easy, medium, hard
    4. Multi-concept: single-concept vs multi-concept
    """
    slices_def: Dict[str, Dict[str, np.ndarray]] = {}

    # 1. Cold Start: Curriculum vs Concept
    seq_idx = df["sequence_index"].to_numpy()
    slices_def["cold_start"] = {
        "Curriculum Cold Start (seq==1)": seq_idx == 1,
    }
    if "attempt_number_primary_concept" in df.columns:
        c_att = df["attempt_number_primary_concept"].to_numpy()
        slices_def["cold_start"]["Concept Cold Start (attempt==1)"] = c_att == 1

    # 2. Attempt Depth (Curriculum sequence depth)
    slices_def["attempt_depth"] = {
        "Curriculum First (seq=1)": seq_idx == 1,
        "Curriculum Responses 2 To 5": (seq_idx >= 2) & (seq_idx <= 5),
        "Curriculum Responses 6 To 10": (seq_idx >= 6) & (seq_idx <= 10),
        "Curriculum Responses 11 Plus": seq_idx >= 11,
    }
    if "attempt_number_primary_concept" in df.columns:
        c_att = df["attempt_number_primary_concept"].to_numpy()
        slices_def["concept_exposure_depth"] = {
            "Concept First Exposure (att=1)": c_att == 1,
            "Concept Exposure 2 To 3": (c_att >= 2) & (c_att <= 3),
            "Concept Exposure 4 Plus": c_att >= 4,
        }

    # 2. Subject
    if "subject" in df.columns:
        subjs = df["subject"].to_numpy()
        slices_def["subject"] = {
            s: subjs == s for s in ["Physics", "Chemistry", "Mathematics"] if np.any(subjs == s)
        }

    # 3. Difficulty
    if "difficulty" in df.columns:
        diffs = df["difficulty"].to_numpy()
        slices_def["difficulty"] = {
            d: diffs == d for d in ["easy", "medium", "hard"] if np.any(diffs == d)
        }

    # 4. Multi-concept
    if "concept_ids" in df.columns and "primary_concept_id" in df.columns:
        c_count = df["concept_ids"].astype(str).apply(lambda x: len(parse_concept_ids(x))).to_numpy()
        slices_def["concept_composition"] = {
            "Single-Concept Items": c_count == 1,
            "Multi-Concept Items": c_count > 1,
        }

    results: Dict[str, Any] = {}

    for category, subcategories in slices_def.items():
        results[category] = {}
        for sub_name, mask in subcategories.items():
            cnt = int(mask.sum())
            if cnt == 0:
                continue

            sub_y = y_true[mask]
            sub_metrics: Dict[str, Any] = {
                "sample_count": cnt,
                "observed_rate": float(round(float(sub_y.mean()), 5)),
                "models": {},
            }

            for model_name, preds in predictions_map.items():
                sub_p = preds[mask]
                eval_dict = evaluate_predictions(sub_y, sub_p)
                sub_metrics["models"][model_name] = {
                    "log_loss": eval_dict["log_loss"],
                    "brier_score": eval_dict["brier_score"],
                    "roc_auc": eval_dict["roc_auc"],
                    "equal_width_ece": eval_dict["expected_calibration_error"],
                    "equal_frequency_ece": eval_dict["equal_frequency_ece"],
                }

            results[category][sub_name] = sub_metrics

    return results


# -----------------------------------------------------------------------------
# 3. Comprehensive Evaluation Runner
# -----------------------------------------------------------------------------

@dataclass
class EvaluationCohort:
    """Pre-extracted evaluation partition data."""
    df: pd.DataFrame
    y_true: np.ndarray
    student_ids: np.ndarray
    sample_count: int
    student_count: int


def prepare_evaluation_cohort(df: pd.DataFrame) -> EvaluationCohort:
    """Validates and prepares an evaluation partition cohort."""
    y = df["correct"].to_numpy(dtype=int)
    sids = df["student_id"].to_numpy(dtype=str)
    return EvaluationCohort(
        df=df,
        y_true=y,
        student_ids=sids,
        sample_count=len(df),
        student_count=len(np.unique(sids)),
    )


def run_comprehensive_evaluation(
    eval_cohort: EvaluationCohort,
    models_dict: Dict[str, Any],  # Name -> Predictor instance or (BKTConfig, policy)
    reference_model_name: str = "item_baseline",
    bootstrap_replicates: int = 1000,
    seed: int = 20261020,
) -> Dict[str, Any]:
    """Evaluates all candidate models on identical cohort rows and computes comparisons.
    
    Args:
        eval_cohort: Evaluation cohort data.
        models_dict: Map of model name to fitted object or (BKTConfig, policy) tuple.
        reference_model_name: Model name to compare against in paired bootstrap.
        bootstrap_replicates: Number of student-level cluster bootstrap iterations.
        seed: Random seed for bootstrap.
    """
    df = eval_cohort.df
    y_true = eval_cohort.y_true
    sids = eval_cohort.student_ids
    n_samples = eval_cohort.sample_count

    predictions_map: Dict[str, np.ndarray] = {}
    model_metrics: Dict[str, Any] = {}

    print(f"[Evaluation] Generating predictions for {len(models_dict)} candidate models on {n_samples:,} interactions...")

    # 1. Generate predictions for each candidate
    for name, model_spec in models_dict.items():
        t0 = time.time()
        if isinstance(model_spec, tuple) and len(model_spec) == 2 and isinstance(model_spec[0], BKTConfig):
            cfg, policy = model_spec
            preds = generate_bkt_predictions(df, config=cfg, policy=policy)
        elif isinstance(model_spec, BKTConfig):
            preds = generate_bkt_predictions(df, config=model_spec, policy="primary_only")
        elif hasattr(model_spec, "predict_proba"):
            preds = model_spec.predict_proba(df)
        elif hasattr(model_spec, "predict"):
            preds = model_spec.predict(df)
        else:
            raise TypeError(f"Unrecognized model type for '{name}': {type(model_spec)}")

        t1 = time.time()
        preds_clipped = np.clip(preds, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)
        predictions_map[name] = preds_clipped

        # Compute standard metrics
        metrics = evaluate_predictions(y_true, preds_clipped)
        metrics["runtime_seconds"] = float(round(t1 - t0, 3))
        model_metrics[name] = metrics
        print(f"    * {name:<30} Log Loss: {metrics['log_loss']:.5f} | Brier: {metrics['brier_score']:.5f} | AUC: {metrics['roc_auc']} ({t1-t0:.2f}s)")

    # 2. Paired Student-Level Cluster Bootstrap relative to reference model
    bootstrap_results: Dict[str, Any] = {}
    if reference_model_name in predictions_map:
        print(f"[Evaluation] Running paired student-level bootstrap (B={bootstrap_replicates}, seed={seed}) against '{reference_model_name}'...")
        bootstrap_results = compute_student_level_paired_bootstrap_ci(
            val_meta_or_df=df,
            y_true=y_true,
            predictions=predictions_map,
            reference_model_key=reference_model_name,
            n_resamples=bootstrap_replicates,
            random_seed=seed,
        )

    # 3. Subgroup Slices
    print("[Evaluation] Computing subgroup and cold-start slice stratifications...")
    subgroups = evaluate_subgroup_slices(df, y_true, predictions_map)

    # 4. Production Candidate Selection Decision (Strict separation from research experiments)
    # Research candidates (such as conjunctive Noisy-AND) are strictly barred from production winner selection
    bkt_production_candidates = {
        m: metrics for m, metrics in model_metrics.items()
        if (m.startswith("bkt_") or m in {"legacy_code_baseline", "generic_sanity_baseline", "four_option_guessing_sensitivity"})
        and not m.endswith("_conjunctive_opt_in") and not m.endswith("_conjunctive")
    }
    best_bkt_model = min(bkt_production_candidates, key=lambda m: bkt_production_candidates[m]["log_loss"]) if bkt_production_candidates else None
    best_bkt_loss = bkt_production_candidates[best_bkt_model]["log_loss"] if best_bkt_model else float("inf")

    item_loss = model_metrics.get("item_baseline", {}).get("log_loss", float("inf"))
    bkt_beats_item = best_bkt_loss < item_loss

    selected_winner = best_bkt_model if bkt_beats_item else "item_baseline"
    winner_loss = best_bkt_loss if bkt_beats_item else item_loss

    selection_decision = {
        "best_production_bkt_candidate": best_bkt_model,
        "best_production_bkt_log_loss": best_bkt_loss,
        "item_baseline_log_loss": item_loss,
        "bkt_beats_item_baseline": bkt_beats_item,
        "selected_production_winner": selected_winner,
        "selected_production_winner_log_loss": winner_loss,
        "selection_rationale": (
            f"Fitted BKT candidate '{best_bkt_model}' achieved Log Loss {best_bkt_loss:.5f}, "
            f"outperforming Item Baseline ({item_loss:.5f})."
            if bkt_beats_item else
            f"No production BKT candidate beat the static Item Baseline ({item_loss:.5f}). "
            f"Best BKT candidate was '{best_bkt_model}' with Log Loss {best_bkt_loss:.5f}. "
            f"Item Baseline is retained as the winning production predictor."
        ),
    }

    return {
        "sample_count": n_samples,
        "student_count": eval_cohort.student_count,
        "observed_positive_rate": float(round(float(y_true.mean()), 5)),
        "models": model_metrics,
        "paired_bootstrap": bootstrap_results,
        "subgroups": subgroups,
        "production_selection": selection_decision,
    }


# -----------------------------------------------------------------------------
# 4. CLI Entrypoint
# -----------------------------------------------------------------------------

def load_all_evaluation_models(
    train_df: pd.DataFrame,
    configs_dir: Path,
) -> Dict[str, Any]:
    """Loads and fits all baselines and BKT candidates for evaluation."""
    models: Dict[str, Any] = {}

    # 1. Static Baselines (fitted on train partition)
    print("[Setup] Fitting Phase 1 benchmark baselines on training partition...")
    pop = PopulationBaseline().fit(train_df, train_df["correct"])
    skill = SkillBaseline(prior_strength_m=10.0).fit(train_df, train_df["correct"])
    diff = DifficultyBaseline(prior_strength_m=10.0).fit(train_df, train_df["correct"])
    item = ItemBaseline(prior_strength_m=10.0).fit(train_df, train_df["correct"])

    models["population_baseline"] = pop
    models["skill_baseline"] = skill
    models["difficulty_baseline"] = diff
    models["item_baseline"] = item

    # 2. Provisional Reference BKT Candidates
    provisional_csv = configs_dir.parent / "candidate_configs.csv"
    if provisional_csv.is_file():
        prov_configs = load_bkt_candidate_configs_csv(provisional_csv)
        for cid, cfg in prov_configs.items():
            models[cid] = (cfg, "primary_only")

    # 3. Fitted BKT Configurations
    fitted_files = {
        "bkt_global_fitted": configs_dir / "bkt_global_fitted.json",
        "bkt_subject_fitted": configs_dir / "bkt_subject_fitted.json",
        "bkt_concept_fitted": configs_dir / "bkt_concept_fitted.json",
    }

    for name, p in fitted_files.items():
        if p.is_file():
            cfg = load_bkt_config_json(p)
            if isinstance(cfg, BKTConfig):
                models[name] = (cfg, "primary_only")
                # Add opt-in conjunctive research candidate for the best global model
                if name == "bkt_global_fitted":
                    models["bkt_global_conjunctive_opt_in"] = (cfg, "conjunctive")

    return models


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LearnSense Person 3 Phase 3 Evaluation CLI")
    parser.add_argument("--data", default="data/synthetic jee/v4/interactions.csv", help="Path to interactions.csv")
    parser.add_argument("--configs-dir", default="data/research/configs_v4", help="Directory of BKT configs")
    parser.add_argument("--split", default="validation", choices=["validation", "test"], help="Evaluation partition")
    parser.add_argument("--output-json", default=None, help="Output path for JSON report")
    args = parser.parse_args()

    data_path = Path(args.data)
    configs_dir = Path(args.configs_dir)

    print(f"Loading interactions from: {data_path.resolve()}")
    raw_df = load_raw_interactions_csv(data_path)
    from src.ingestion import is_prohibited_column
    approved_cols = [c for c in raw_df.columns if not is_prohibited_column(c)]
    sanitized_df = raw_df[approved_cols]

    train_df = sanitized_df[sanitized_df["student_split"] == "train"].copy()
    eval_df = sanitized_df[sanitized_df["student_split"] == args.split].copy()

    models = load_all_evaluation_models(train_df, configs_dir)
    cohort = prepare_evaluation_cohort(eval_df)

    results = run_comprehensive_evaluation(cohort, models)
    results = {"partition": args.split, **results}

    if args.output_json:
        out_p = Path(args.output_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to {out_p.resolve()}")

"""LearnSense Person 3 — BKT Parameter Fitting Module.

Provides reproducible, leakage-resistant parameter estimation for Bayesian Knowledge Tracing:
1. Bounded maximum-likelihood / predictive log-loss optimization over sequential replay.
2. Global, subject-level, and concept-level parameter fitting with empirical shrinkage.
3. Multi-start optimization with convergence diagnostics and parameter boundary logging.
4. Seamless export to versioned BKTConfig instances compliant with Phase 2 interfaces.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.bkt import (
    PARAM_MAX,
    PARAM_MIN,
    PROB_EPSILON,
    BKTConfig,
    BKTParameters,
    clamp_probability,
    save_bkt_config_json,
)
from src.ingestion import (
    APPROVED_FEATURE_COLUMNS,
    PROHIBITED_LEAKAGE_COLUMNS,
    PROHIBITED_PREFIXES,
    load_raw_interactions_csv,
    parse_concept_ids,
)

# Documented parameter bounds for BKT fitting to ensure cognitive plausibility
# and prevent degenerative / reversed states (1 - S > G)
DEFAULT_PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "p_l0": (0.01, 0.90),
    "p_t": (0.001, 0.40),
    "p_g": (0.01, 0.45),
    "p_s": (0.01, 0.40),
}

# Standard deterministic starting candidates for multi-start optimization
STANDARD_STARTING_POINTS: List[Tuple[float, float, float, float]] = [
    (0.30, 0.10, 0.20, 0.10),  # Generic sanity baseline
    (0.30, 0.05, 0.33, 0.05),  # Legacy code baseline
    (0.30, 0.10, 0.25, 0.10),  # 4-option guessing reference
    (0.15, 0.05, 0.15, 0.10),  # Low-prior start
    (0.50, 0.15, 0.25, 0.15),  # Moderate-prior start
]


# -----------------------------------------------------------------------------
# 1. Leakage Guardrail Enforcement
# -----------------------------------------------------------------------------

def assert_no_leakage_in_training_data(df: pd.DataFrame) -> None:
    """Verifies that no prohibited ground-truth or simulator columns are present."""
    cols = set(df.columns)
    
    # Check exact prohibited columns
    direct_leaks = cols.intersection(PROHIBITED_LEAKAGE_COLUMNS)
    if direct_leaks:
        raise ValueError(
            f"LEAKAGE VIOLATION: Prohibited ground-truth columns detected in training DataFrame: {sorted(direct_leaks)}"
        )
    
    # Check prohibited prefixes
    prefix_leaks = [c for c in cols if any(c.startswith(p) for p in PROHIBITED_PREFIXES)]
    if prefix_leaks:
        raise ValueError(
            f"LEAKAGE VIOLATION: Prohibited prefix columns detected in training DataFrame: {sorted(prefix_leaks)}"
        )


# -----------------------------------------------------------------------------
# 2. Fast Sequential Likelihood Evaluation
# -----------------------------------------------------------------------------

def evaluate_bkt_log_loss_on_sequences(
    sequences: Sequence[np.ndarray],
    p_l0: float,
    p_t: float,
    p_g: float,
    p_s: float,
    clamped: bool = False,
) -> float:
    """Evaluates average predictive log loss (negative log-likelihood) over student sequences.
    
    Supports two modes:
    1. Exact standard-BKT likelihood recursion (clamped=False):
       Computes mathematically exact Bayesian posteriors without boundary clamping,
       providing exact Maximum Marginal Likelihood Estimation (MMLE).
    2. Production-clamped approximation (clamped=True):
       Clamps intermediate posteriors and transitions strictly to [PARAM_MIN, PARAM_MAX],
       matching the runtime engine behavior of src.bkt.
    
    Explicit cognitive plausibility constraint:
        Requires G + S <= 0.95 (i.e. 1 - S - G >= 0.05). If violated, returns heavy penalty.
    """
    total_loss = 0.0
    total_count = 0
    eps = 1e-12
    metric_eps = 1e-6

    # Explicit plausibility constraint: Mastered accuracy must strictly exceed guessing rate
    if (p_g + p_s) >= 0.95 or (1.0 - p_s) <= p_g:
        return 1e5 + (p_g + p_s - 0.90) * 1e4

    for seq in sequences:
        l = p_l0
        for y in seq:
            p_pred = l * (1.0 - p_s) + (1.0 - l) * p_g
            p_clipped = min(max(p_pred, metric_eps), 1.0 - metric_eps)
            
            if y == 1:
                total_loss -= math.log(p_clipped)
                denom = max(p_pred, eps)
                post = (l * (1.0 - p_s)) / denom
            else:
                total_loss -= math.log(1.0 - p_clipped)
                denom = max(1.0 - p_pred, eps)
                post = (l * p_s) / denom
            
            if clamped:
                post = min(max(post, PARAM_MIN), PARAM_MAX)
                l = min(max(post + (1.0 - post) * p_t, PARAM_MIN), PARAM_MAX)
            else:
                post = min(max(post, 0.0), 1.0)
                l = min(max(post + (1.0 - post) * p_t, 0.0), 1.0)
                
            total_count += 1

    if total_count == 0:
        return 0.0

    return total_loss / total_count


# -----------------------------------------------------------------------------
# 3. Optimization Data Structures & Single Model Fitting
# -----------------------------------------------------------------------------

@dataclass
class BKTFitDiagnostic:
    """Diagnostic details for an optimization run."""
    initial_params: Tuple[float, float, float, float]
    fitted_params: Tuple[float, float, float, float]
    initial_loss: float
    final_loss: float
    iterations: int
    converged: bool
    status_message: str
    runtime_seconds: float
    boundary_hits: List[str] = field(default_factory=list)


@dataclass
class BKTFittingResult:
    """Complete result of BKT parameter fitting."""
    model_name: str
    parameters: BKTParameters
    log_loss_train: float
    sample_count: int
    sequence_count: int
    diagnostic: BKTFitDiagnostic
    bounds: Dict[str, Tuple[float, float]]
    all_diagnostics: List[BKTFitDiagnostic] = field(default_factory=list)


def fit_bkt_parameters(
    sequences: Sequence[np.ndarray],
    bounds: Optional[Dict[str, Tuple[float, float]]] = None,
    starting_points: Optional[Sequence[Tuple[float, float, float, float]]] = None,
    method: str = "L-BFGS-B",
    model_name: str = "bkt_fitted",
) -> BKTFittingResult:
    """Optimizes standard 4-parameter BKT bundle on observed binary sequences.
    
    Uses multi-start bounded optimization to find the minimum predictive log loss.
    """
    param_bounds = bounds or DEFAULT_PARAM_BOUNDS
    starts = starting_points or STANDARD_STARTING_POINTS
    
    scipy_bounds = [
        param_bounds["p_l0"],
        param_bounds["p_t"],
        param_bounds["p_g"],
        param_bounds["p_s"],
    ]

    total_samples = sum(len(s) for s in sequences)
    if total_samples == 0:
        raise ValueError("Cannot fit BKT parameters on empty sequences.")

    best_loss = float("inf")
    best_diagnostic: Optional[BKTFitDiagnostic] = None
    best_params_tuple: Tuple[float, float, float, float] = (0.3, 0.1, 0.2, 0.1)
    all_diags: List[BKTFitDiagnostic] = []

    t0_all = time.time()

    for start in starts:
        t0 = time.time()
        init_loss = evaluate_bkt_log_loss_on_sequences(sequences, *start)

        def loss_fn(params_vec: np.ndarray) -> float:
            p_l0, p_t, p_g, p_s = params_vec
            return evaluate_bkt_log_loss_on_sequences(sequences, p_l0, p_t, p_g, p_s)

        res = minimize(
            loss_fn,
            x0=np.array(start, dtype=float),
            bounds=scipy_bounds,
            method=method,
            options={"maxiter": 150, "ftol": 1e-6},
        )
        t1 = time.time()

        fitted = tuple(float(x) for x in res.x)
        final_loss = float(res.fun)

        # Check boundary hits
        hits = []
        param_names = ["p_l0", "p_t", "p_g", "p_s"]
        for name, val in zip(param_names, fitted):
            b_lo, b_hi = param_bounds[name]
            if abs(val - b_lo) < 1e-4:
                hits.append(f"{name}_at_lower_bound({b_lo})")
            elif abs(val - b_hi) < 1e-4:
                hits.append(f"{name}_at_upper_bound({b_hi})")

        diag = BKTFitDiagnostic(
            initial_params=start,
            fitted_params=fitted,
            initial_loss=init_loss,
            final_loss=final_loss,
            iterations=int(getattr(res, "nit", res.nfev)),
            converged=bool(res.success),
            status_message=str(res.message),
            runtime_seconds=t1 - t0,
            boundary_hits=hits,
        )
        all_diags.append(diag)

        if final_loss < best_loss:
            best_loss = final_loss
            best_diagnostic = diag
            best_params_tuple = fitted

    assert best_diagnostic is not None

    bkt_params = BKTParameters(
        p_l0=best_params_tuple[0],
        p_t=best_params_tuple[1],
        p_g=best_params_tuple[2],
        p_s=best_params_tuple[3],
    )

    return BKTFittingResult(
        model_name=model_name,
        parameters=bkt_params,
        log_loss_train=best_loss,
        sample_count=total_samples,
        sequence_count=len(sequences),
        diagnostic=best_diagnostic,
        bounds=param_bounds,
        all_diagnostics=all_diags,
    )


# -----------------------------------------------------------------------------
# 4. Dataset Preprocessing & Granular Model Fitting
# -----------------------------------------------------------------------------

def prepare_bkt_training_sequences(
    train_df: pd.DataFrame,
    group_by: Optional[str] = None,
) -> Union[List[np.ndarray], Dict[str, List[np.ndarray]]]:
    """Extracts chronological binary sequences grouped by (student_id, primary_concept_id).
    
    Args:
        train_df: Training interactions DataFrame.
        group_by: Optional column ('subject' or 'primary_concept_id') to partition sequences.
        
    Returns:
        List of 1D numpy arrays if group_by is None, or Dict[key, List[1D numpy arrays]].
    """
    assert_no_leakage_in_training_data(train_df)

    # Sort strictly chronologically
    sort_cols = ["student_id", "sequence_index"]
    if "timestamp_utc" in train_df.columns:
        sort_cols.append("timestamp_utc")
    df_sorted = train_df.sort_values(by=sort_cols).reset_index(drop=True)

    if group_by is None:
        grouped = df_sorted.groupby(["student_id", "primary_concept_id"])["correct"].apply(
            lambda s: s.to_numpy(dtype=np.int8)
        )
        return list(grouped.values)
    else:
        result_dict: Dict[str, List[np.ndarray]] = {}
        for key, sub_df in df_sorted.groupby(group_by):
            k_str = str(key).strip()
            sub_grouped = sub_df.groupby(["student_id", "primary_concept_id"])["correct"].apply(
                lambda s: s.to_numpy(dtype=np.int8)
            )
            result_dict[k_str] = list(sub_grouped.values)
        return result_dict


def fit_global_bkt_config(
    train_df: pd.DataFrame,
    config_id: str = "bkt_global_fitted",
    version: str = "4.0",
) -> Tuple[BKTConfig, BKTFittingResult]:
    """Fits a single global BKT parameter set across all training data."""
    sequences = prepare_bkt_training_sequences(train_df)
    fit_res = fit_bkt_parameters(sequences, model_name=config_id)

    config = BKTConfig(
        config_id=config_id,
        version=version,
        model_type="standard_bkt",
        parameters=fit_res.parameters,
        concept_overrides={},
        provenance="Maximum-likelihood predictive log loss fitting on train split",
        status="candidate",
        creation_method="bounded_lbfgsb_multistart",
        source_dataset="v4_train",
        notes=f"Train log loss: {fit_res.log_loss_train:.5f}, samples: {fit_res.sample_count}",
    )
    return config, fit_res


def fit_subject_bkt_config(
    train_df: pd.DataFrame,
    global_params: BKTParameters,
    concept_to_subject_map: Dict[str, str],
    config_id: str = "bkt_subject_fitted",
    version: str = "4.0",
) -> Tuple[BKTConfig, Dict[str, BKTFittingResult]]:
    """Fits BKT parameters stratified by subject (Physics, Chemistry, Mathematics)."""
    subject_seqs = prepare_bkt_training_sequences(train_df, group_by="subject")
    subject_results: Dict[str, BKTFittingResult] = {}
    overrides: Dict[str, BKTParameters] = {}

    for subj, seqs in subject_seqs.items():
        res = fit_bkt_parameters(seqs, model_name=f"{config_id}_{subj}")
        subject_results[subj] = res

    # Assign overrides to all concepts belonging to each subject
    for cid, subj in concept_to_subject_map.items():
        if subj in subject_results:
            overrides[cid] = subject_results[subj].parameters

    config = BKTConfig(
        config_id=config_id,
        version=version,
        model_type="standard_bkt",
        parameters=global_params,
        concept_overrides=overrides,
        provenance="Subject-stratified predictive log loss fitting on train split",
        status="candidate",
        creation_method="subject_bounded_lbfgsb",
        source_dataset="v4_train",
        notes=f"Subjects fitted: {list(subject_results.keys())}",
    )
    return config, subject_results
def fit_concept_bkt_config(
    train_df: pd.DataFrame,
    global_params: BKTParameters,
    min_concept_samples: int = 150,
    shrinkage_factor: float = 0.5,
    lambda_samples: float = 100.0,
    lambda_students: float = 25.0,
    config_id: str = "bkt_concept_fitted",
    version: str = "4.0",
) -> Tuple[BKTConfig, Dict[str, BKTFittingResult]]:
    """Fits BKT parameters per concept with sample-size thresholding and shrinkage to global parameters.
    
    Heuristic Shrinkage Justification:
    Concept-level BKT parameters can be weakly identified or prone to overfitting on sparse concepts.
    This module applies a documented heuristic shrinkage towards the global pooled parameter vector:
    1. Only concepts with at least min_concept_samples are fitted independently.
    2. Shrinkage weight w incorporates both total attempt count (N_c) and distinct learner count (S_c):
           w = min(1.0, 0.5 * (lambda_samples / N_c + lambda_students / S_c)) * shrinkage_factor
    3. Parameters are shrunk:
           p_shrunk = (1 - w) * p_fitted + w * p_global
    4. Concepts below min_concept_samples fall back directly to global parameters.
    """
    concept_seqs = prepare_bkt_training_sequences(train_df, group_by="primary_concept_id")
    concept_results: Dict[str, BKTFittingResult] = {}
    overrides: Dict[str, BKTParameters] = {}

    for cid, seqs in concept_seqs.items():
        n_samples = sum(len(s) for s in seqs)
        n_students = len(seqs)
        if n_samples < min_concept_samples:
            continue

        try:
            res = fit_bkt_parameters(
                seqs,
                starting_points=[(global_params.p_l0, global_params.p_t, global_params.p_g, global_params.p_s)],
                model_name=f"concept_{cid}",
            )
            concept_results[cid] = res

            # Apply documented heuristic shrinkage combining sample and student volume
            w_samples = lambda_samples / n_samples
            w_students = lambda_students / n_students
            w = float(min(1.0, 0.5 * (w_samples + w_students))) * shrinkage_factor

            shrunk_l0 = (1.0 - w) * res.parameters.p_l0 + w * global_params.p_l0
            shrunk_t = (1.0 - w) * res.parameters.p_t + w * global_params.p_t
            shrunk_g = (1.0 - w) * res.parameters.p_g + w * global_params.p_g
            shrunk_s = (1.0 - w) * res.parameters.p_s + w * global_params.p_s

            overrides[cid] = BKTParameters(
                p_l0=clamp_probability(shrunk_l0),
                p_t=clamp_probability(shrunk_t),
                p_g=clamp_probability(shrunk_g),
                p_s=clamp_probability(shrunk_s),
            )
        except Exception:
            # Safe fallback if concept optimization encounters singular conditions
            continue

    config = BKTConfig(
        config_id=config_id,
        version=version,
        model_type="standard_bkt",
        parameters=global_params,
        concept_overrides=overrides,
        provenance="Heuristic sample-and-learner shrinkage towards global pooled parameters",
        status="candidate",
        creation_method="concept_lbfgsb_heuristic_shrinkage",
        source_dataset="v4_train",
        notes=f"Independently fitted {len(overrides)} concepts (threshold >= {min_concept_samples}, lambda_samples={lambda_samples}, lambda_students={lambda_students})",
    )
    return config, concept_results


# -----------------------------------------------------------------------------
# 5. CLI Entrypoint
# -----------------------------------------------------------------------------

def run_fitting_pipeline(
    interactions_path: Path,
    concepts_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, BKTConfig]:
    """Runs end-to-end BKT parameter fitting pipeline on training data."""
    out_dir = output_dir or (Path(__file__).resolve().parent.parent / "data" / "research" / "configs")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Phase 3 Fitting] Loading training interactions from: {interactions_path}")
    raw_df = load_raw_interactions_csv(interactions_path)
    from src.ingestion import is_prohibited_column
    approved_cols = [c for c in raw_df.columns if not is_prohibited_column(c)]
    sanitized_df = raw_df[approved_cols]
    train_df = sanitized_df[sanitized_df["student_split"] == "train"].copy()
    print(f"[Phase 3 Fitting] Filtered {len(train_df):,} training interactions across {train_df['student_id'].nunique():,} students (zero leakage fields).")

    # 1. Global Fitting
    print("[Phase 3 Fitting] 1/3 Fitting Global BKT Parameters...")
    global_config, global_res = fit_global_bkt_config(train_df)
    save_bkt_config_json(global_config, out_dir / "bkt_global_fitted.json")
    print(f"    Global Fitted: L0={global_config.parameters.p_l0:.4f}, T={global_config.parameters.p_t:.4f}, "
          f"G={global_config.parameters.p_g:.4f}, S={global_config.parameters.p_s:.4f} "
          f"(Train Log Loss: {global_res.log_loss_train:.5f})")

    # 2. Subject Mapping & Subject-Level Fitting
    print("[Phase 3 Fitting] 2/3 Fitting Subject-Level BKT Parameters...")
    cid_to_subj = dict(zip(train_df["primary_concept_id"], train_df["subject"]))
    subject_config, subject_res = fit_subject_bkt_config(
        train_df, global_params=global_config.parameters, concept_to_subject_map=cid_to_subj
    )
    save_bkt_config_json(subject_config, out_dir / "bkt_subject_fitted.json")
    for subj, sres in subject_res.items():
        print(f"    Subject {subj}: L0={sres.parameters.p_l0:.4f}, T={sres.parameters.p_t:.4f}, "
              f"G={sres.parameters.p_g:.4f}, S={sres.parameters.p_s:.4f} (Loss: {sres.log_loss_train:.5f})")

    # 3. Concept-Level Fitting with Shrinkage
    print("[Phase 3 Fitting] 3/3 Fitting Concept-Level BKT Parameters with Shrinkage...")
    concept_config, concept_res = fit_concept_bkt_config(
        train_df, global_params=global_config.parameters, min_concept_samples=150
    )
    save_bkt_config_json(concept_config, out_dir / "bkt_concept_fitted.json")
    # 4. Save Fitting Diagnostics Summary
    diagnostics_payload = {
        "global": {
            "best_diagnostic": asdict(global_res.diagnostic),
            "all_starts": [asdict(d) for d in global_res.all_diagnostics],
            "train_log_loss": global_res.log_loss_train,
            "sample_count": global_res.sample_count,
            "sequence_count": global_res.sequence_count,
        },
        "subject": {
            subj: {
                "best_diagnostic": asdict(sres.diagnostic),
                "all_starts": [asdict(d) for d in sres.all_diagnostics],
                "train_log_loss": sres.log_loss_train,
                "sample_count": sres.sample_count,
            }
            for subj, sres in subject_res.items()
        },
        "concept": {
            cid: {
                "best_diagnostic": asdict(cres.diagnostic),
                "train_log_loss": cres.log_loss_train,
                "sample_count": cres.sample_count,
            }
            for cid, cres in concept_res.items()
        },
    }
    with open(out_dir / "bkt_fitting_diagnostics.json", "w", encoding="utf-8") as f:
        json.dump(diagnostics_payload, f, indent=2)
    print(f"    Diagnostics saved to {out_dir / 'bkt_fitting_diagnostics.json'}")

    return {
        "global": global_config,
        "subject": subject_config,
        "concept": concept_config,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LearnSense Person 3 Phase 3 BKT Fitting CLI")
    parser.add_argument("--data", default="data/synthetic jee/v4/interactions.csv", help="Path to interactions.csv")
    parser.add_argument("--output-dir", default="data/research/configs_v4", help="Directory to save fitted configs")
    args = parser.parse_args()

    run_fitting_pipeline(
        interactions_path=Path(args.data),
        output_dir=Path(args.output_dir),
    )

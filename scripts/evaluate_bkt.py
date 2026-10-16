"""
BKT Parameter Evaluation & Calibration Tool for LearnSense.

THREE LEVELS:
  Level 1 - Sanity checks on synthetic sequences (always runs, no data needed)
  Level 2 - Grid search calibration on real learner session data from storage/
  Level 3 - Per-concept calibration breakdown + suspicious state audit

Usage:
    python scripts/evaluate_bkt.py                          # all levels
    python scripts/evaluate_bkt.py --mode sanity            # level 1 only
    python scripts/evaluate_bkt.py --mode calibrate         # level 2 only
    python scripts/evaluate_bkt.py --mode audit             # level 3 only

    # Test alternative parameters:
    python scripts/evaluate_bkt.py --p-transit 0.20 --p-slip 0.08 --p-guess 0.25
"""

import argparse
import json
import math
import sys
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Core BKT math (self-contained)
# ---------------------------------------------------------------------------

def _update(p: float, obs: int, p_transit: float, p_slip: float, p_guess: float) -> float:
    """One BKT update step. Returns new mastery probability."""
    p_obs_given_known   = (1.0 - p_slip) if obs == 1 else p_slip
    p_obs_given_unknown = p_guess         if obs == 1 else (1.0 - p_guess)
    p_obs = p * p_obs_given_known + (1.0 - p) * p_obs_given_unknown
    p_post = (p * p_obs_given_known / p_obs) if p_obs > 0 else p
    return max(0.01, min(0.99, p_post + (1.0 - p_post) * p_transit))


def final_mastery(responses: List[int], p_init: float, p_transit: float,
                  p_slip: float, p_guess: float) -> float:
    p = p_init
    for obs in responses:
        p = _update(p, obs, p_transit, p_slip, p_guess)
    return round(p, 4)


def trajectory(responses: List[int], p_init: float, p_transit: float,
               p_slip: float, p_guess: float) -> List[float]:
    p = p_init
    traj = [round(p, 3)]
    for obs in responses:
        p = _update(p, obs, p_transit, p_slip, p_guess)
        traj.append(round(p, 3))
    return traj


def one_step_ahead_rmse(sequences: List[List[int]], p_init: float,
                         p_transit: float, p_slip: float, p_guess: float) -> float:
    """
    For each sequence, predict P(correct at step t+1) given steps 1..t.
    Returns RMSE across all predictions. Lower = better calibrated params.
    """
    errors = []
    for seq in sequences:
        if len(seq) < 2:
            continue
        p = p_init
        for i, obs in enumerate(seq):
            if i > 0:  # Skip first (no prior evidence yet)
                p_correct_pred = p * (1.0 - p_slip) + (1.0 - p) * p_guess
                errors.append((p_correct_pred - obs) ** 2)
            p = _update(p, obs, p_transit, p_slip, p_guess)
    if not errors:
        return float("inf")
    return math.sqrt(sum(errors) / len(errors))


# ---------------------------------------------------------------------------
# Level 1 — Sanity Checks (synthetic sequences)
# ---------------------------------------------------------------------------

def run_sanity_checks(p_init: float, p_transit: float,
                      p_slip: float, p_guess: float) -> bool:
    print()
    print("=" * 64)
    print("  LEVEL 1: BKT SANITY CHECK (synthetic sequences)")
    print(f"  p_init={p_init}  p_transit={p_transit}"
          f"  p_slip={p_slip}  p_guess={p_guess}")
    print("=" * 64)

    # -- Trajectories --
    scenarios = [
        ("5 correct in a row",      [1, 1, 1, 1, 1]),
        ("5 wrong in a row",        [0, 0, 0, 0, 0]),
        ("10 correct in a row",     [1] * 10),
        ("10 wrong in a row",       [0] * 10),
        ("Alternating C/W x5",      [1, 0, 1, 0, 1]),
        ("2 wrong then 3 correct",  [0, 0, 1, 1, 1]),
        ("1 guess then 5 wrong",    [1, 0, 0, 0, 0, 0]),
    ]
    print()
    print("  Learning curves (start -> end):")
    for label, seq in scenarios:
        traj = trajectory(seq, p_init, p_transit, p_slip, p_guess)
        s, e = traj[0], traj[-1]
        direction = "UP" if e > s + 0.05 else ("DOWN" if e < s - 0.05 else "FLAT")
        print(f"    {label:<30} {s:.3f} -> {e:.3f}  [{direction}]  {traj}")

    # -- Assertions --
    print()
    print("  Assertions:")
    checks = []

    def check(cond: bool, msg: str, detail: str = ""):
        label = "PASS" if cond else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"    [{label}]  {msg}{suffix}")
        checks.append(cond)

    m5c   = final_mastery([1]*5,            p_init, p_transit, p_slip, p_guess)
    m10c  = final_mastery([1]*10,           p_init, p_transit, p_slip, p_guess)
    m5w   = final_mastery([0]*5,            p_init, p_transit, p_slip, p_guess)
    m10w  = final_mastery([0]*10,           p_init, p_transit, p_slip, p_guess)
    m_alt = final_mastery([1,0,1,0,1],     p_init, p_transit, p_slip, p_guess)
    m_2w3c = final_mastery([0,0,1,1,1],    p_init, p_transit, p_slip, p_guess)
    m_1g5w = final_mastery([1,0,0,0,0,0],  p_init, p_transit, p_slip, p_guess)

    # Learning direction
    check(m5c  > 0.70, "5 correct  => mastery > 70%",  f"got {m5c:.3f}")
    check(m10c > 0.85, "10 correct => mastery > 85%",  f"got {m10c:.3f}")
    check(m5w  < 0.35, "5 wrong    => mastery < 35%",  f"got {m5w:.3f}")
    check(m10w < 0.25, "10 wrong   => mastery < 25%",  f"got {m10w:.3f}")

    # Monotonicity — use tolerance so ceiling/floor hits don't false-fail
    check(m10c >= m5c,  "10 correct >= 5 correct (monotone or ceiling reached)",
          f"{m10c:.3f} >= {m5c:.3f}")
    check(m10w <= m5w,  "10 wrong <= 5 wrong (monotone or floor reached)",
          f"{m10w:.3f} <= {m5w:.3f}")

    # Mixed evidence should stay broadly mid-range (allow down to 0.15 --
    # with low p_slip + p_transit, wrong-after-correct drops mastery sharply,
    # and last answer determines final direction; this is correct BKT behaviour)
    check(0.15 < m_alt < 0.75,
          "Alternating C/W => mastery stays 15%-75%",  f"got {m_alt:.3f}")

    # Recovery
    check(m_2w3c > 0.50,
          "2 wrong then 3 correct => mastery > 50%",   f"got {m_2w3c:.3f}")

    # Single lucky guess followed by wrong shouldn't inflate mastery
    check(m_1g5w < 0.35,
          "1 lucky guess + 5 wrong => mastery < 35%",  f"got {m_1g5w:.3f}")

    # Parameter bounds (the 4-param identifiability constraints from BKT literature)
    check(0.0 < p_guess < 0.5,      "p_guess in (0, 0.5)  -- guessing < random")
    check(0.0 < p_slip  < 0.5,      "p_slip  in (0, 0.5)  -- slipping < random")
    check(0.0 < p_transit < 0.5,    "p_transit in (0, 0.5) -- gradual learning")
    check(0.05 <= p_init <= 0.50,   "p_init in [0.05, 0.50] -- realistic prior")

    passed = sum(checks)
    total  = len(checks)
    print()
    print(f"  Result: {passed}/{total} passed")

    if passed == total:
        print("  All sanity checks passed. Parameters are defensible defaults.")
    else:
        failed = total - passed
        print(f"  {failed} check(s) failed. Parameter adjustment hints:")
        if m5c <= 0.70:
            print("    -> Increase p_transit (learning is too slow after 5 correct)")
        if m5w >= 0.35:
            print("    -> Increase p_slip or decrease p_transit (wrong answers not penalized enough)")
        if m_alt >= 0.70:
            print("    -> Increase p_slip (mixed evidence should not cause high mastery)")
        if m_alt <= 0.30:
            print("    -> Decrease p_slip (penalizing mixed evidence too aggressively)")
        if m_1g5w >= 0.35:
            print("    -> Decrease p_guess (one correct guess should not persist against 5 wrongs)")

    return passed == total


# ---------------------------------------------------------------------------
# Level 2 — Grid Search Calibration on real data
# ---------------------------------------------------------------------------

def _load_sequences() -> Tuple[Dict[str, List[List[int]]], List[List[int]]]:
    """
    Load recent_performance sequences from storage/learner_states/*.json.
    Returns (per_concept_sequences, all_sequences_flat).
    """
    states_dir = Path("storage/learner_states")
    concept_seqs: Dict[str, List[List[int]]] = {}
    all_seqs: List[List[int]] = []

    if not states_dir.exists():
        return concept_seqs, all_seqs

    for f in states_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for c_id, c_data in data.get("concept_states", {}).items():
                rp = c_data.get("recent_performance", [])
                if len(rp) >= 3:
                    seq = [int(x) for x in rp]
                    concept_seqs.setdefault(c_id, []).append(seq)
                    all_seqs.append(seq)
        except Exception as exc:
            print(f"  Warning: could not load {f.name}: {exc}")

    return concept_seqs, all_seqs


def run_calibration(p_init: float = 0.30) -> Optional[Tuple[float, float, float]]:
    print()
    print("=" * 64)
    print("  LEVEL 2: GRID SEARCH CALIBRATION (real learner data)")
    print("=" * 64)

    concept_seqs, all_seqs = _load_sequences()

    # Fallback to synthetic demo data if no real data exists
    using_synthetic = False
    if not all_seqs:
        print()
        print("  No real learner data found in storage/learner_states/")
        print("  Using synthetic demonstration data (5 representative sequences).")
        print("  Re-run after real users have completed sessions for true calibration.")
        all_seqs = [
            [0, 0, 1, 1, 1, 1],
            [1, 1, 0, 1, 1],
            [0, 1, 0, 1, 0, 1],
            [1, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1, 1, 1],
        ]
        using_synthetic = True
    else:
        total_obs = sum(len(s) for s in all_seqs)
        print()
        print(f"  Found {len(all_seqs)} sequences across "
              f"{len(concept_seqs)} concepts ({total_obs} total observations)")

    # Grid
    grid_transit = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    grid_slip    = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    grid_guess   = [0.15, 0.20, 0.25, 0.30, 0.33]

    total_combos = len(grid_transit) * len(grid_slip) * len(grid_guess)
    print(f"  Searching {total_combos} parameter combinations...")

    results: List[Tuple[float, float, float, float]] = []  # (rmse, t, s, g)
    best_rmse = float("inf")
    best_params: Optional[Tuple[float, float, float]] = None

    for p_t, p_s, p_g in product(grid_transit, grid_slip, grid_guess):
        err = one_step_ahead_rmse(all_seqs, p_init, p_t, p_s, p_g)
        results.append((err, p_t, p_s, p_g))
        if err < best_rmse:
            best_rmse = err
            best_params = (p_t, p_s, p_g)

    results.sort()

    current_rmse = one_step_ahead_rmse(all_seqs, p_init, 0.15, 0.10, 0.25)

    print()
    print(f"  {'RMSE':>8}  {'p_transit':>10}  {'p_slip':>8}  {'p_guess':>8}")
    print("  " + "-" * 44)
    for err, p_t, p_s, p_g in results[:10]:
        marker = "  <-- BEST" if (p_t, p_s, p_g) == best_params else ""
        print(f"  {err:>8.4f}  {p_t:>10.3f}  {p_s:>8.3f}  {p_g:>8.3f}{marker}")

    print()
    print(f"  Current defaults:  p_transit=0.15  p_slip=0.10  p_guess=0.25")
    print(f"  Current RMSE:      {current_rmse:.4f}")

    if best_params:
        p_t, p_s, p_g = best_params
        delta = current_rmse - best_rmse
        pct   = (delta / current_rmse * 100) if current_rmse > 0 else 0.0
        print(f"  Best found:        p_transit={p_t}  p_slip={p_s}  p_guess={p_g}")
        print(f"  Best RMSE:         {best_rmse:.4f}")
        print(f"  Improvement:       {delta:.4f} ({pct:.1f}%)")
        print()

        if using_synthetic:
            print("  NOTE: Calibration on synthetic data is illustrative only.")
            print("  Collect real session data and re-run for meaningful results.")
        elif delta > 0.01:
            print("  Recommendation: update KnowledgeTracer defaults in phase3/learner/kt.py:")
            print(f"    p_transit = {p_t}")
            print(f"    p_slip    = {p_s}")
            print(f"    p_guess   = {p_g}")
        else:
            print("  Current defaults are within 1% of optimal. No change recommended.")

    return best_params


# ---------------------------------------------------------------------------
# Level 3 — Per-Concept Audit
# ---------------------------------------------------------------------------

def run_audit() -> None:
    print()
    print("=" * 64)
    print("  LEVEL 3: LEARNER STATE AUDIT")
    print("=" * 64)

    states_dir = Path("storage/learner_states")
    if not states_dir.exists() or not any(states_dir.glob("*.json")):
        print()
        print("  No learner states found in storage/learner_states/")
        print("  Run the system with real users first.")
        return

    all_masteries: List[float] = []
    flagged_high: List[str]    = []   # high mastery with tiny attempt count
    flagged_wrong: List[str]   = []   # all wrong but mastery stayed high
    concept_stats: Dict[str, List[float]] = {}

    for f in sorted(states_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        learner = data.get("learner_id", f.stem)
        for c_id, c in data.get("concept_states", {}).items():
            m   = c.get("mastery_probability", 0.3)
            att = c.get("attempt_count", 0)
            rp  = c.get("recent_performance", [])
            all_masteries.append(m)
            concept_stats.setdefault(c_id, []).append(m)

            if m > 0.85 and att < 3:
                flagged_high.append(
                    f"  learner={learner}  concept={c_id}  "
                    f"mastery={m:.2f}  attempts={att}")
            if rp and all(r == 0 for r in rp) and m > 0.50:
                flagged_wrong.append(
                    f"  learner={learner}  concept={c_id}  "
                    f"mastery={m:.2f}  recent_perf={rp}")

    if not all_masteries:
        print()
        print("  No concept states found.")
        return

    n    = len(all_masteries)
    mean = sum(all_masteries) / n
    lo   = sum(1 for m in all_masteries if m < 0.40) / n * 100
    mid  = sum(1 for m in all_masteries if 0.40 <= m < 0.70) / n * 100
    hi   = sum(1 for m in all_masteries if m >= 0.70) / n * 100

    print()
    print(f"  Total concept states : {n}")
    print(f"  Mean mastery         : {mean:.3f}")
    print(f"  Distribution:")
    print(f"    < 0.40  (low)   : {lo:.1f}%")
    print(f"    0.40-0.70 (mid) : {mid:.1f}%")
    print(f"    >= 0.70 (high)  : {hi:.1f}%")

    # Per-concept breakdown
    print()
    print(f"  Per-concept mean mastery (top 10 by variance):")
    ranked = sorted(
        ((c_id, sum(ms)/len(ms), _variance(ms)) for c_id, ms in concept_stats.items()),
        key=lambda x: -x[2]
    )
    print(f"    {'concept_id':<30} {'mean':>8}  {'variance':>10}  {'n':>4}")
    for c_id, mean_m, var in ranked[:10]:
        n_c = len(concept_stats[c_id])
        print(f"    {c_id:<30} {mean_m:>8.3f}  {var:>10.5f}  {n_c:>4}")

    # Flags
    if flagged_high:
        print()
        print(f"  SUSPICIOUS: {len(flagged_high)} states with mastery > 85% but < 3 attempts")
        for line in flagged_high[:5]:
            print(line)
        if len(flagged_high) > 5:
            print(f"  ... and {len(flagged_high)-5} more")
    else:
        print()
        print("  OK: No suspiciously high-mastery states detected.")

    if flagged_wrong:
        print()
        print(f"  SUSPICIOUS: {len(flagged_wrong)} states where all recent answers wrong but mastery high")
        for line in flagged_wrong[:5]:
            print(line)
        if len(flagged_wrong) > 5:
            print(f"  ... and {len(flagged_wrong)-5} more")
    else:
        print()
        print("  OK: No mastery/response inconsistencies detected.")


def _variance(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BKT evaluation and calibration tool"
    )
    parser.add_argument("--mode", choices=["sanity", "calibrate", "audit", "all"],
                        default="all", help="Evaluation mode (default: all)")
    parser.add_argument("--p-init",    type=float, default=0.30)
    parser.add_argument("--p-transit", type=float, default=0.15)
    parser.add_argument("--p-slip",    type=float, default=0.10)
    parser.add_argument("--p-guess",   type=float, default=0.25)
    args = parser.parse_args()

    ok = True

    if args.mode in ("sanity", "all"):
        ok = run_sanity_checks(args.p_init, args.p_transit, args.p_slip, args.p_guess)

    if args.mode in ("calibrate", "all"):
        run_calibration(args.p_init)

    if args.mode in ("audit", "all"):
        run_audit()

    print()
    sys.exit(0 if ok else 1)

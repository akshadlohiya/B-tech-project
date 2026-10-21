"""Does the bias model improve *positions*, not just ranges?

    python -m uwb_ai.eval_positioning     # from ai-module/

Monte-Carlo on a 3-anchor room (matching the DW1000 kit). For each trial one
link is blocked; its measured signal diagnostics and bias are drawn from a
held-out UTIL trial of a randomly chosen material, the other links from held-out
LOS trials. Ranges = true distance + bias + LOS noise. Three solvers:
  * plain     -- unweighted least squares on raw ranges
  * rule      -- the current power-gap weight from location-engine/solver.py
                 (re-implemented here so this module stays standalone)
  * ai        -- ranges corrected by the bias model, then bias-weighted LS

The bias model is trained only on trials NOT used for drawing test links. The
split is stratified by material (a third of each material's trials are held
out), because there are only six trials per obstacle and a random split can
leave a material entirely untrained. Results are averaged over several seeds.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
from scipy.optimize import least_squares

from .nlos_model import NlosBiasModel, bias_to_weight, feature_matrix, make_estimator
from .util_loader import load_link_samples

ANCHORS = np.array([[0.0, 0.0], [6.0, 0.0], [3.0, 6.0]])   # 2D, metres
LOS_NOISE_M = 0.03


def rule_weight(power_dif, normal_gap_db=3.0, k=0.25):
    return 1.0 / (1.0 + k * np.maximum(0.0, power_dif - normal_gap_db))


def trial_material(link_materials) -> str:
    """A trial's obstacle material: its blocked links' material, else "none".
    (Not max(): "cardboard", "foam" and "metal" all sort before "none".)"""
    blocked = set(link_materials) - {"none"}
    return blocked.pop() if blocked else "none"


def solve(ranges, weights, seed):
    sw = np.sqrt(weights)
    res = least_squares(lambda p: sw * (np.linalg.norm(ANCHORS - p, axis=1) - ranges), seed)
    return res.x


def split_trials(s, rng) -> list:
    """Held-out trial ids: a third of each material's trials (at least one)."""
    trial_mat = {g: trial_material(s.material[s.group == g]) for g in np.unique(s.group)}
    test_trials = []
    for mat in sorted(set(trial_mat.values())):
        ids = [g for g, m in trial_mat.items() if m == mat]
        test_trials += list(rng.choice(ids, max(1, len(ids) // 3), replace=False))
    return test_trials


def run(n_trials: int = 2000, seed: int = 0, s=None) -> dict:
    s = load_link_samples() if s is None else s
    rng = np.random.default_rng(seed)
    is_test = np.isin(s.group, split_trials(s, rng))
    train = np.flatnonzero(~is_test)
    train = rng.choice(train, min(60000, len(train)), replace=False)
    model = NlosBiasModel("pd", make_estimator()).fit(feature_matrix(s, "pd")[train], s.bias[train])

    los_pool = np.flatnonzero(is_test & (s.nlos == 0))
    mats = sorted(set(s.material[is_test & (s.nlos == 1)]))
    errs = {m: [] for m in ("plain", "rule", "ai")}
    per_mat = {mat: {m: [] for m in errs} for mat in mats}
    centroid = ANCHORS.mean(axis=0)
    for _ in range(n_trials):
        tag = rng.uniform([0.5, 0.5], [5.5, 5.5])
        d = np.linalg.norm(ANCHORS - tag, axis=1)
        mat = mats[rng.integers(len(mats))]
        nlos_pool = np.flatnonzero(is_test & (s.material == mat))
        blocked = rng.integers(3)
        idx = rng.choice(los_pool, 3)
        idx[blocked] = rng.choice(nlos_pool)
        ranges = d + s.bias[idx] + rng.normal(0, LOS_NOISE_M, 3)
        pd_ = s.power_dif[idx]
        b_hat = model.predict(pd_[:, None])
        fixes = {
            "plain": solve(ranges, np.ones(3), centroid),
            "rule": solve(ranges, rule_weight(pd_), centroid),
            "ai": solve(ranges - b_hat, bias_to_weight(b_hat), centroid),
        }
        for m, p in fixes.items():
            e = float(np.linalg.norm(p - tag))
            errs[m].append(e)
            per_mat[mat][m].append(e)

    def summ(v):
        v = np.asarray(v)
        return {"rmse_m": round(float(np.sqrt(np.mean(v**2))), 4),
                "p50_m": round(float(np.median(v)), 4), "p90_m": round(float(np.quantile(v, 0.9)), 4)}
    return {"n_trials": n_trials, "overall": {m: summ(v) for m, v in errs.items()},
            "by_material": {mat: {m: summ(v)["rmse_m"] for m, v in d.items()} for mat, d in per_mat.items()}}


def run_seeds(n_seeds: int = 10, n_trials: int = 2000) -> dict:
    s = load_link_samples()
    runs = [run(n_trials, seed, s) for seed in range(n_seeds)]
    methods = list(runs[0]["overall"])
    mean = lambda vals: round(float(np.mean(vals)), 4)
    overall = {m: {k: mean([r["overall"][m][k] for r in runs]) for k in runs[0]["overall"][m]}
               for m in methods}
    mats = sorted({mat for r in runs for mat in r["by_material"]})
    by_mat = {mat: {m: mean([r["by_material"][mat][m] for r in runs if mat in r["by_material"]])
                    for m in methods} for mat in mats}
    wins = sum(r["overall"]["ai"]["rmse_m"] < r["overall"]["plain"]["rmse_m"] for r in runs)
    return {"n_seeds": n_seeds, "trials_per_seed": n_trials, "mean_overall": overall,
            "mean_rmse_by_material": by_mat, "ai_beats_plain_in_seeds": f"{wins}/{n_seeds}",
            "per_seed_rmse": [{m: r["overall"][m]["rmse_m"] for m in methods} for r in runs]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=10)
    args = ap.parse_args(argv)
    r = run_seeds(args.seeds, args.trials)
    print(json.dumps(r, indent=2))
    return r


if __name__ == "__main__":
    main()

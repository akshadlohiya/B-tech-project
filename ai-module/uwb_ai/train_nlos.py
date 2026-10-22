"""Train and evaluate the NLOS bias model on the UTIL identification dataset.

    python -m uwb_ai.train_nlos            # from ai-module/

Evaluation is grouped K-fold by *trial*: no test sample comes from a recording
the model has seen. Methods compared on residual range bias (m):
  * none    -- use the raw range (what the current solver does; its power-gap
               rule only re-weights and cannot shorten a range)
  * linear  -- linear regression on the same features
  * hgb     -- gradient-boosted trees (the deployed model)

Writes models/nlos_bias_<feature_set>.joblib and models/metrics.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold

from .nlos_model import FEATURE_SETS, NlosBiasModel, feature_matrix, make_estimator
from .util_loader import DEFAULT_ROOT, load_link_samples

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
METHODS = ("none", "linear", "hgb")


def _rms(e) -> float:
    return float(np.sqrt(np.mean(np.square(e))))


def cross_val_predict(samples, feature_set: str, folds: int = 5, max_train: int = 60000,
                      seed: int = 0) -> dict:
    """Out-of-fold bias predictions for each method."""
    X, y = feature_matrix(samples, feature_set), samples.bias
    rng = np.random.default_rng(seed)
    pred = {m: np.zeros(len(y)) for m in METHODS}
    for tr, te in GroupKFold(n_splits=folds).split(X, y, samples.group):
        if len(tr) > max_train:   # subsample for speed; the trees saturate well before this
            tr = rng.choice(tr, max_train, replace=False)
        pred["linear"][te] = np.maximum(LinearRegression().fit(X[tr], y[tr]).predict(X[te]), 0.0)
        pred["hgb"][te] = NlosBiasModel(feature_set, make_estimator(seed)).fit(X[tr], y[tr]).predict(X[te])
    return pred


def score(samples, pred: dict) -> dict:
    y = samples.bias
    out = {m: {"residual_rms_m": round(_rms(y - p), 4),
               "residual_mae_m": round(float(np.mean(np.abs(y - p))), 4)} for m, p in pred.items()}
    base = out["none"]["residual_rms_m"]
    for m in out:
        out[m]["rms_reduction_pct"] = round(100.0 * (1 - out[m]["residual_rms_m"] / base), 1)
    by_mat = {}
    for mat in sorted(set(samples.material)):
        k = samples.material == mat
        row = {"true_bias_m": round(float(y[k].mean()), 3)}
        for m, p in pred.items():
            row[f"{m}_rms_m"] = round(_rms(y[k] - p[k]), 3)
        by_mat["LOS" if mat == "none" else mat] = row
    out["by_material"] = by_mat
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--out", type=Path, default=MODEL_DIR)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--max-train", type=int, default=60000)
    args = ap.parse_args(argv)

    samples = load_link_samples(args.data)
    print(f"{len(samples)} link samples from {len(samples.trials)} trials "
          f"({samples.nlos.mean():.1%} blocked, {samples.harmful.mean():.1%} with bias > 5 cm)")
    report = {"dataset": "UTIL identification (anTag + LOS trials)", "n_samples": len(samples),
              "n_trials": len(samples.trials), "folds": args.folds, "feature_sets": {}}
    for fs in FEATURE_SETS:
        res = score(samples, cross_val_predict(samples, fs, args.folds, args.max_train))
        report["feature_sets"][fs] = res
        print(f"\n[{fs}]  features={list(FEATURE_SETS[fs])}")
        for m in METHODS:
            print(f"  {m:6s} " + "  ".join(f"{k}={v}" for k, v in res[m].items()))
        print("  residual bias RMS by material (m):")
        for mat, row in res["by_material"].items():
            print(f"    {mat:15s} " + "  ".join(f"{k}={v:.3f}" for k, v in row.items()))

        X = feature_matrix(samples, fs)
        idx = np.random.default_rng(0).choice(len(X), min(len(X), args.max_train), replace=False)
        # LOS power-gap baseline of the training radio: a deployment shifts its own
        # gaps by (this - its LOS baseline) so the model sees them on this scale.
        los_gap = round(float(np.median(samples.power_dif[samples.nlos == 0])), 3)
        model = NlosBiasModel(fs, make_estimator(), meta={"trained_on": report["dataset"], "cv": res["hgb"],
                                                          "los_gap_db": los_gap})
        model.fit(X[idx], samples.bias[idx]).save(args.out / f"nlos_bias_{fs}.joblib")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "metrics.json").write_text(json.dumps(report, indent=2))
    print(f"\nSaved models and metrics.json to {args.out}")
    return report


if __name__ == "__main__":
    main()

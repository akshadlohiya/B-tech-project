"""Train a TDOA measurement-error model from the real UTIL flight dataset.

This is the "learn from data" step for the generative TDOA simulator (sim_tdoa.py).
Where `calibrate_from_util.py` tuned the *range* sim's scalar noise, this fits a full
error *distribution* for **TDOA** measurements, so a synthetic simulator can reproduce
real UWB TDOA behaviour on ANY custom layout (e.g. the warehouse), not just replay the
recording.

Method
------
For every TDOA event we know the geometric truth (Vicon pose interpolated to the TDOA
timestamp, minus anchor survey geometry), so the error is

        err = tdoa_meas - ( d(tag, anchorB) - d(tag, anchorA) ).

Real UWB TDOA in clutter is a **heavy-tailed mixture**: a tight Gaussian "inlier" core
(clean LOS/near-LOS) plus a wide "outlier" component (NLOS / multipath). We fit a
two-component zero-mean Gaussian mixture by Expectation-Maximisation and save:

    { sigma_inlier, sigma_outlier, p_outlier, bias, n_samples, trials }

which sim_tdoa.py samples from. Train on a few trials, keep others for validation.

    python train_tdoa_model.py                 # train on the default trial set + save
    python train_tdoa_model.py --dry-run       # fit + print, do not write the model
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "anchor-source"))

from dataset_source import DatasetTdoaSource, load_anchor_survey, default_paths  # noqa: E402

MODEL_PATH = os.path.join(HERE, "tdoa_model.json")

# Trials to train on (spread across the four anchor constellations).
TRAIN_TRIALS = [
    ("const1", "trial1", "tdoa2"), ("const2", "trial1", "tdoa2"),
    ("const3", "trial1", "tdoa2"), ("const4", "trial1", "tdoa2"),
]


def _dist(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def collect_residuals(trials) -> Tuple[List[float], int]:
    res: List[float] = []
    used = 0
    for const, trial, scheme in trials:
        csv_path, survey = default_paths(const, trial, scheme)
        if not os.path.isfile(csv_path):
            continue
        anchors = load_anchor_survey(survey)
        src = DatasetTdoaSource(csv_path, anchors, with_truth=True)
        for e in src.events():
            if e.truth is None:
                continue
            true = _dist(e.truth, anchors[e.id_b]) - _dist(e.truth, anchors[e.id_a])
            res.append(e.tdoa - true)
        used += 1
    return res, used


def _npdf(x: float, s: float) -> float:
    return math.exp(-0.5 * (x / s) ** 2) / (s * math.sqrt(2 * math.pi))


def fit_mixture(res: List[float], iters: int = 100) -> dict:
    """Zero-mean 2-component Gaussian mixture via EM. Returns learned parameters."""
    n = len(res)
    bias = sum(res) / n
    xs = [x - bias for x in res]                    # remove any small systematic bias
    s_in, s_out, p_out = 0.1, 1.0, 0.1              # init
    for _ in range(iters):
        # E-step: responsibility that each sample came from the OUTLIER component
        r = []
        for x in xs:
            a = (1 - p_out) * _npdf(x, s_in)
            b = p_out * _npdf(x, s_out)
            r.append(b / (a + b) if (a + b) > 0 else 1.0)
        sr = sum(r)
        # M-step
        p_out_new = sr / n
        v_out = sum(ri * x * x for ri, x in zip(r, xs)) / max(sr, 1e-9)
        v_in = sum((1 - ri) * x * x for ri, x in zip(r, xs)) / max(n - sr, 1e-9)
        s_out_new, s_in_new = math.sqrt(v_out), math.sqrt(v_in)
        if (abs(s_in_new - s_in) + abs(s_out_new - s_out)
                + abs(p_out_new - p_out)) < 1e-6:
            s_in, s_out, p_out = s_in_new, s_out_new, p_out_new
            break
        s_in, s_out, p_out = s_in_new, s_out_new, p_out_new
    return {
        "schema": "tdoa.model/1",
        "sigma_inlier_m": round(s_in, 4),
        "sigma_outlier_m": round(s_out, 4),
        "p_outlier": round(p_out, 4),
        "bias_m": round(bias, 4),
        "n_samples": n,
        "source": "UTIL-IJRR2024",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="fit + print, do not save")
    ap.add_argument("--out", default=MODEL_PATH)
    args = ap.parse_args()

    res, used = collect_residuals(TRAIN_TRIALS)
    if not res:
        raise SystemExit("no training data — extract the UTIL flight-dataset first.")
    model = fit_mixture(res)
    model["trials"] = used

    print("Trained TDOA error model (UTIL flight data)")
    print("-" * 46)
    print(f"  trials used     : {used}")
    print(f"  samples         : {model['n_samples']}")
    print(f"  inlier sigma    : {model['sigma_inlier_m']:.3f} m")
    print(f"  outlier sigma   : {model['sigma_outlier_m']:.3f} m")
    print(f"  outlier fraction: {model['p_outlier'] * 100:.1f} %")
    print(f"  systematic bias : {model['bias_m']:+.3f} m")

    if args.dry_run:
        print("\n  (dry run — model not written)")
    else:
        with open(args.out, "w") as f:
            json.dump(model, f, indent=2)
            f.write("\n")
        print(f"\n  saved -> {args.out}")


if __name__ == "__main__":
    main()

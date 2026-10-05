"""Benchmark the TDOA EKF on a real UTIL flight trial.

Runs DatasetTdoaSource -> TdoaEKF and reports position RMSE against the mm-accurate
Vicon ground truth. This is the validation deliverable for the walled-off TDOA track:
"we implemented and validated an EKF on real hardware-grade UWB measurements."

    python run_tdoa_ekf.py                          # const1 / trial1 / tdoa2
    python run_tdoa_ekf.py --const const2 --trial trial3 --scheme tdoa3
    python run_tdoa_ekf.py --sigma-tdoa 0.15 --sigma-a 3.0 --gate 12
"""
from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "anchor-source"))

from dataset_source import DatasetTdoaSource, load_anchor_survey, default_paths  # noqa: E402
from ekf_tdoa import TdoaEKF, cold_start_position                                # noqa: E402


def run(csv_path: str, survey_path: str, sigma_tdoa: float, sigma_a: float,
        gate: float, warmup: int = 200, verbose: bool = True) -> dict:
    anchors = load_anchor_survey(survey_path)
    src = DatasetTdoaSource(csv_path, anchors, with_truth=True)
    events = list(src.events())

    # Cold start: batch-solve an initial position from the first `warmup` events
    # (neutral anchor-centroid seed — does NOT use ground truth).
    centroid = tuple(sum(a[k] for a in anchors.values()) / len(anchors) for k in range(3))
    warm = [(e.tdoa, anchors[e.id_a], anchors[e.id_b]) for e in events[:warmup]]
    init = cold_start_position(warm, seed=(centroid[0], centroid[1], centroid[2]))

    ekf = TdoaEKF(sigma_a=sigma_a, sigma_tdoa=sigma_tdoa, gate=gate, init_pos=init)

    sq_err = []
    last_t = events[0].t
    for e in events:
        ekf.predict(e.t - last_t)
        last_t = e.t
        ekf.update(e.tdoa, anchors[e.id_a], anchors[e.id_b])
        if e.truth is not None and ekf.position is not None:
            p = ekf.position
            sq_err.append((p[0] - e.truth[0]) ** 2 + (p[1] - e.truth[1]) ** 2
                          + (p[2] - e.truth[2]) ** 2)

    # discard the convergence transient from the headline number
    stable = sq_err[warmup:] if len(sq_err) > warmup else sq_err
    rmse = math.sqrt(sum(stable) / len(stable)) if stable else float("nan")
    errs2d = None
    result = {
        "trial": os.path.basename(csv_path),
        "events": len(events),
        "anchors": len(anchors),
        "used": ekf.n_used,
        "rejected": ekf.n_rejected,
        "reject_pct": round(100 * ekf.n_rejected / max(1, ekf.n_used + ekf.n_rejected), 1),
        "rmse_3d_m": round(rmse, 3),
    }
    if verbose:
        print(f"TDOA-EKF on {result['trial']}")
        print(f"  events={result['events']}  anchors={result['anchors']}  "
              f"used={result['used']}  gated_outliers={result['reject_pct']}%")
        print(f"  cold-start init = ({init[0]:.2f}, {init[1]:.2f}, {init[2]:.2f})")
        print(f"  3D position RMSE vs Vicon = {result['rmse_3d_m']:.3f} m")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--const", default="const1")
    ap.add_argument("--trial", default="trial1")
    ap.add_argument("--scheme", default="tdoa2", choices=["tdoa2", "tdoa3"])
    ap.add_argument("--csv", default=None, help="explicit CSV path (overrides const/trial)")
    ap.add_argument("--survey", default=None, help="explicit anchor survey path")
    ap.add_argument("--sigma-tdoa", type=float, default=0.15)
    ap.add_argument("--sigma-a", type=float, default=3.0)
    ap.add_argument("--gate", type=float, default=12.0)
    args = ap.parse_args()

    csv_path, survey_path = default_paths(args.const, args.trial, args.scheme)
    if args.csv:
        csv_path = args.csv
    if args.survey:
        survey_path = args.survey
    if not os.path.isfile(csv_path):
        raise SystemExit(f"trial not found: {csv_path}\n"
                         "Extract the UTIL flight-dataset first "
                         "(DOCS/datasets/util-uwb-dataset/setupscript.bash).")
    run(csv_path, survey_path, args.sigma_tdoa, args.sigma_a, args.gate)


if __name__ == "__main__":
    main()

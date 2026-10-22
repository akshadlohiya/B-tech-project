"""Benchmark NLOS handling: power-gap rule vs the learned AI bias model.

    python location-engine/run_nlos_bench.py                       # config/site.json
    python location-engine/run_nlos_bench.py --site backend/maps/demo.json
    python location-engine/run_nlos_bench.py --readings 6000 --seeds 3

Both modes run the real LocationEngine (solver + Kalman filter) on the *same*
seeded simulator readings, so the only difference is ranging.nlosModel. Errors
are 2D distances to the simulator's ground truth, in centimetres.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
for _p in ("anchor-source", "shared", "location-engine"):
    sys.path.insert(0, str(_ROOT / _p))

import sim_anchors                   # noqa: E402
from engine import LocationEngine    # noqa: E402


def sim_stream(site: dict, n: int, seed: int) -> list:
    """n (reading dict, truth) pairs from the simulator, without real-time pacing."""
    random.seed(seed)
    real_sleep, sim_anchors.time.sleep = sim_anchors.time.sleep, lambda _s: None
    try:
        it = sim_anchors.SimAnchorSource(site).cycles()
        return [(r.to_dict(), t) for r, t in (next(it) for _ in range(n))]
    finally:
        sim_anchors.time.sleep = real_sleep


def evaluate(site: dict, stream: list, mode: str) -> dict:
    site = copy.deepcopy(site)
    site["ranging"]["nlosModel"] = mode
    eng = LocationEngine(site)
    filt, raw = [], []
    for reading, truth in stream:
        out = eng.estimate(reading, truth)
        if out is not None and "error" in out:
            filt.append(out["error"])
            raw.append(out["rawError"])
    f, r = np.asarray(filt) * 100, np.asarray(raw) * 100
    return {"method": eng.nlos_method, "fixes": len(f),
            "mean_cm": round(float(f.mean()), 1), "p50_cm": round(float(np.median(f)), 1),
            "p90_cm": round(float(np.quantile(f, 0.9)), 1), "raw_mean_cm": round(float(r.mean()), 1)}


def run(site: dict, readings: int = 3000, seeds: int = 3) -> dict:
    out = {}
    for mode in ("rule", "ai"):
        runs = [evaluate(site, sim_stream(site, readings, s), mode) for s in range(seeds)]
        keys = [k for k in runs[0] if k.endswith("_cm")]
        out[mode] = {"method": runs[0]["method"], **{k: round(float(np.mean([x[k] for x in runs])), 1) for k in keys}}
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", type=Path, default=_ROOT / "config" / "site.json")
    ap.add_argument("--readings", type=int, default=3000)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args(argv)
    res = run(json.loads(args.site.read_text()), args.readings, args.seeds)
    print(f"{args.site.name}: {args.readings} readings x {args.seeds} seeds (Kalman-filtered error)")
    for mode, r in res.items():
        print(f"  {mode:4s} [{r['method']}]  mean {r['mean_cm']:5.1f}  p50 {r['p50_cm']:5.1f}  "
              f"p90 {r['p90_cm']:5.1f} cm   (raw solve mean {r['raw_mean_cm']:5.1f} cm)")
    return res


if __name__ == "__main__":
    main()

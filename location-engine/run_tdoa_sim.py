"""Benchmark the generative TDOA simulator through the EKF on a custom layout.

Runs TdoaSimulator (default: the warehouse config/site.json) -> TdoaEKF and reports
position RMSE against the simulator's own ground truth. Because the simulator controls
truth and geometry, it also splits accuracy by LOS vs NLOS (near-rack) measurements.

    python run_tdoa_sim.py                      # warehouse site, ~40 s of motion
    python run_tdoa_sim.py --seconds 60 --seed 1
    python run_tdoa_sim.py --site ../config/site.json
"""
from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "anchor-source"))
sys.path.insert(0, os.path.join(HERE, "..", "shared"))

from site_config import load_site                      # noqa: E402
from sim_tdoa import TdoaSimulator, load_tdoa_model     # noqa: E402
from ekf_tdoa import TdoaEKF, cold_start_position       # noqa: E402


def run(site: dict, seconds: float, seed: int, sigma_tdoa: float, sigma_a: float,
        gate: float, warmup: int = 60, verbose: bool = True) -> dict:
    model = load_tdoa_model()
    sim = TdoaSimulator(site, model=model, seed=seed)
    anchors = sim.anchors
    rate = sim.rate
    n_pairs = len(anchors) - 1
    tag_ids = list(sim.movers.keys())
    tag_height = {t["id"]: float(t.get("y", 0.6)) for t in site["tags"]}
    total = int(seconds * rate * n_pairs * len(tag_ids))

    gen = sim.events()
    events = [next(gen) for _ in range(total)]

    centroid = tuple(sum(a[k] for a in anchors.values()) / len(anchors) for k in range(3))
    # Ceiling anchors are ~coplanar -> run a 2D fixed-height EKF per tag.
    ekfs, warm, last_t, used, rejected = {}, {}, {}, 0, 0
    for tid in tag_ids:
        h = tag_height.get(tid, 0.6)
        ekfs[tid] = None
        warm[tid] = []

    sq2d, sq3d = [], []
    for e in events:
        tid = e.tag_id
        h = tag_height.get(tid, 0.6)
        ekf = ekfs[tid]
        if ekf is None:                          # collect a warm-up batch, then cold-start
            warm[tid].append((e.tdoa, anchors[e.id_a], anchors[e.id_b]))
            if len(warm[tid]) >= warmup:
                init = cold_start_position(warm[tid], seed=centroid, height=h)
                ekf = ekfs[tid] = TdoaEKF(sigma_a=sigma_a, sigma_tdoa=sigma_tdoa,
                                          gate=gate, init_pos=init, height=h)
                last_t[tid] = e.t
            continue
        ekf.predict(e.t - last_t[tid])
        last_t[tid] = e.t
        ekf.update(e.tdoa, anchors[e.id_a], anchors[e.id_b])
        p, tr = ekf.position, e.truth
        if p and tr:
            sq2d.append((p[0] - tr[0]) ** 2 + (p[2] - tr[2]) ** 2)
            sq3d.append(math.dist(p, tr) ** 2)
    for ekf in ekfs.values():
        if ekf:
            used += ekf.n_used
            rejected += ekf.n_rejected

    res = {
        "events": len(events), "anchors": len(anchors), "tags": len(tag_ids),
        "used": used, "rejected": rejected,
        "reject_pct": round(100 * rejected / max(1, used + rejected), 1),
        "rmse_2d_m": round(math.sqrt(sum(sq2d) / len(sq2d)), 3) if sq2d else float("nan"),
        "rmse_3d_m": round(math.sqrt(sum(sq3d) / len(sq3d)), 3) if sq3d else float("nan"),
    }
    if verbose:
        print(f"Generative TDOA sim -> EKF  (site: {site.get('meta', {}).get('name', '?')})")
        print(f"  events={res['events']}  anchors={res['anchors']}  tags={res['tags']}  "
              f"used={res['used']}  gated={res['reject_pct']}%")
        print(f"  horizontal (x,z) RMSE = {res['rmse_2d_m']:.3f} m  "
              f"(2D fixed-height EKF; ceiling anchors are ~coplanar)")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=os.path.join(HERE, "..", "config", "site.json"))
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sigma-tdoa", type=float, default=0.15)
    ap.add_argument("--sigma-a", type=float, default=3.0)
    ap.add_argument("--gate", type=float, default=12.0)
    args = ap.parse_args()
    site = load_site(args.site)
    run(site, args.seconds, args.seed, args.sigma_tdoa, args.sigma_a, args.gate)


if __name__ == "__main__":
    main()

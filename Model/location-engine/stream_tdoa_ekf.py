"""Stream a TDOA-EKF track into the live 3D twin — from real data OR the simulator.

Integrates the TDOA track with the existing visualiser: it runs a TDOA stream through
the EKF and pushes estimates to the same backend hub / digital twin the range sim uses,
so you can WATCH the track (EKF estimate + ground-truth overlay + live error).

    --source dataset  (default): replay a real UTIL flight trial (fixed geometry/motion).
    --source sim               : the GENERATIVE TdoaSimulator on an editable layout
                                 (default the warehouse) with a model learned from UTIL.

    python stream_tdoa_ekf.py                          # real UTIL replay  -> ?map=util
    python stream_tdoa_ekf.py --source sim             # synthetic warehouse -> ?map=wh-tdoa
    python stream_tdoa_ekf.py --source sim --loop --speed 2

Reuses the platform as-is: registers a `uwb.site/1` map, then emits `update_location`
(the same schema the range gateway emits), tagged with that map key.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import Callable, Dict, Iterable, Iterator, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "anchor-source"))
sys.path.insert(0, os.path.join(HERE, "..", "shared"))

from dataset_source import (DatasetTdoaSource, load_anchor_survey, default_paths,   # noqa: E402
                            build_util_site, to_site_frame, TdoaEvent)
from ekf_tdoa import TdoaEKF, cold_start_position                                    # noqa: E402

Vec3 = tuple


def _identity(p):
    return p


def frames_from_events(
    events: Iterable[TdoaEvent], anchors: Dict, map_key: str, floor_id: str,
    name_of: Callable[[str], str], height_of: Callable[[str], Optional[float]],
    convert: Callable = _identity, emit_rate: float = 20.0, warmup: int = 60,
    sigma_tdoa: float = 0.15, sigma_a: float = 3.0, gate: float = 12.0,
) -> Iterator[Dict]:
    """Run a per-tag EKF over a TDOA event stream, yielding twin `update_location` frames.

    Handles multiple tags (each its own EKF, cold-started from its own warm-up batch) and
    both 3D (height_of -> None) and 2D fixed-height (height_of -> h) estimation. Positions
    are mapped into the twin's site frame via `convert`.
    """
    centroid = tuple(sum(a[k] for a in anchors.values()) / len(anchors) for k in range(3))
    ekfs: Dict[str, Optional[TdoaEKF]] = {}
    warm: Dict[str, list] = {}
    last_t: Dict[str, float] = {}
    next_emit: Dict[str, float] = {}
    for e in events:
        tid = e.tag_id
        if tid not in ekfs:
            ekfs[tid] = None
            warm[tid] = []
            next_emit[tid] = e.t
        ekf = ekfs[tid]
        if ekf is None:
            warm[tid].append((e.tdoa, anchors[e.id_a], anchors[e.id_b]))
            if len(warm[tid]) >= warmup:
                h = height_of(tid)
                init = cold_start_position(warm[tid], seed=centroid, height=h)
                ekfs[tid] = TdoaEKF(sigma_a=sigma_a, sigma_tdoa=sigma_tdoa, gate=gate,
                                    init_pos=init, height=h)
                last_t[tid] = e.t
            continue
        ekf.predict(e.t - last_t[tid])
        last_t[tid] = e.t
        ekf.update(e.tdoa, anchors[e.id_a], anchors[e.id_b])
        if e.t < next_emit[tid] or ekf.position is None:
            continue
        next_emit[tid] = e.t + 1.0 / emit_rate
        px, py, pz = convert(ekf.position)
        vx, vy, vz = ekf.velocity or (0.0, 0.0, 0.0)
        payload: Dict = {
            "tagId": tid, "name": name_of(tid), "mapKey": map_key, "battery": 100,
            "floorId": floor_id, "t": e.t,
            "pos": {"x": round(px, 3), "y": round(py, 3), "z": round(pz, 3)},
            "vel": {"vx": round(vx, 3), "vz": round(vz, 3),
                    "speed": round(math.sqrt(vx * vx + vy * vy + vz * vz), 3)},
        }
        if e.truth is not None:
            tx, ty, tz = convert(e.truth)
            payload["truth"] = {"x": round(tx, 3), "z": round(tz, 3), "y": round(ty, 3)}
            payload["error"] = round(math.dist(ekf.position, e.truth), 3)
        yield payload


# ---- dataset (real UTIL replay) ---------------------------------------------
def replay_frames(csv_path: str, survey_path: str, map_key: str = "util", **kw) -> Iterator[Dict]:
    anchors = load_anchor_survey(survey_path)
    src = DatasetTdoaSource(csv_path, anchors, with_truth=True)
    return frames_from_events(
        src.events(), anchors, map_key=map_key, floor_id="f_util",
        name_of=lambda _t: "UTIL Drone", height_of=lambda _t: None,   # 3D
        convert=to_site_frame, **kw)


# ---- generative simulator ----------------------------------------------------
def sim_frames(site: dict, map_key: str, seed: int = 0, **kw) -> Iterator[Dict]:
    from sim_tdoa import TdoaSimulator, load_tdoa_model
    sim = TdoaSimulator(site, model=load_tdoa_model(), seed=seed)
    names = {t["id"]: t.get("name", t["id"]) for t in site["tags"]}
    heights = {t["id"]: float(t.get("y", 0.6)) for t in site["tags"]}
    return frames_from_events(
        sim.events(), sim.anchors, map_key=map_key, floor_id=site["floor"]["id"],
        name_of=lambda tid: names.get(tid, tid), height_of=lambda tid: heights.get(tid, 0.6),
        convert=_identity, **kw)   # sim already in site frame


def register_map(backend_url: str, site: dict, map_key: str) -> None:
    import requests
    site = dict(site)
    site["key"] = map_key
    r = requests.put(f"{backend_url}/api/maps/{map_key}", json=site, timeout=5)
    r.raise_for_status()
    print(f"[stream] registered map '{map_key}' ({len(site['anchors'])} anchors) — "
          f"open the twin at ?map={map_key}")


def _pace_and_emit(frames: Iterator[Dict], sio, speed: float) -> int:
    t0_wall = time.time()
    t0_trial: Optional[float] = None
    n = 0
    for payload in frames:
        if t0_trial is None:
            t0_trial = payload["t"]
        slp = (payload["t"] - t0_trial) / max(speed, 1e-6) - (time.time() - t0_wall)
        if slp > 0:
            time.sleep(slp)
        # ride out transient disconnects (client auto-reconnects); skip the frame
        # rather than crash if we are mid-reconnect.
        if not sio.connected:
            continue
        try:
            sio.emit("update_location", payload)
        except Exception:
            continue
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="dataset", choices=["dataset", "sim"])
    ap.add_argument("--const", default="const1")
    ap.add_argument("--trial", default="trial1")
    ap.add_argument("--scheme", default="tdoa2", choices=["tdoa2", "tdoa3"])
    ap.add_argument("--site", default=os.path.join(HERE, "..", "config", "site.json"),
                    help="site for --source sim")
    ap.add_argument("--backend", default=os.environ.get("BACKEND_URL", "http://localhost:3000"))
    ap.add_argument("--map-key", default=None)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--emit-rate", type=float, default=20.0)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    import socketio
    if args.source == "sim":
        from site_config import load_site
        site = load_site(args.site)
        map_key = args.map_key or "wh-tdoa"
        twin = dict(site)
        twin["meta"] = {**site.get("meta", {}), "name": site.get("meta", {}).get("name", "Site") + " (TDOA)"}
        register_map(args.backend, twin, map_key)
        make_frames = lambda: sim_frames(site, map_key=map_key, emit_rate=args.emit_rate)
        label = f"generative TDOA sim on {os.path.basename(args.site)}"
    else:
        csv_path, survey_path = default_paths(args.const, args.trial, args.scheme)
        if not os.path.isfile(csv_path):
            raise SystemExit(f"trial not found: {csv_path}")
        map_key = args.map_key or "util"
        register_map(args.backend, build_util_site(load_anchor_survey(survey_path), key=map_key), map_key)
        make_frames = lambda: replay_frames(csv_path, survey_path, map_key=map_key,
                                            emit_rate=args.emit_rate)
        label = f"UTIL replay {args.const}-{args.trial}-{args.scheme}"

    sio = socketio.Client(reconnection=True)
    sio.connect(args.backend)
    sio.emit("join_map", map_key)
    print(f"[stream] streaming {label} at {args.speed}x -> ?map={map_key}")
    try:
        while True:
            n = _pace_and_emit(make_frames(), sio, args.speed)
            print(f"[stream] pass complete ({n} frames)")
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sio.disconnect()


if __name__ == "__main__":
    main()

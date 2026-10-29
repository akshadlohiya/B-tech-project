"""Record and analyse real DW1000 hardware runs (PI_SETUP.md steps 12-13).

Listens to the backend like the viewer does, so it runs alongside the gateway, from
the Pi or any laptop on the hotspot. Every reading (raw ranges + powers) and every
solved position is appended to a CSV, tagged with a label such as the taped point.

    # 1. log the tag standing on a taped point (repeat per point, same file)
    python calibration/hw_log.py record --backend http://10.76.162.90:3000 --map 4f41ed2f96 \\
        --label P1 --seconds 30 --out calibration/logs/run1.csv

    # 2. LOS power baseline -> ranging.power.fpToRxDeltaLosDbm
    python calibration/hw_log.py baseline calibration/logs/run1.csv

    # 3. per-anchor range offset at a known point (antenna delay check)
    python calibration/hw_log.py ranges calibration/logs/run1.csv --label P1 --at 0,0.6,0 \\
        --backend http://10.76.162.90:3000 --map 4f41ed2f96

    # 4. positioning accuracy over all taped points (+ CDF chart for the report)
    python calibration/hw_log.py accuracy calibration/logs/run1.csv --points points.csv \\
        --plot report/hw_accuracy_cdf.png

points.csv has a header and one row per taped point: label,x,z (metres, map frame).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from typing import Dict, List, Tuple

import numpy as np

FIELDS = ["t", "label", "kind", "tag", "anchor", "range", "rx", "fp", "x", "z"]


# ----------------------------------------------------------------- recording
def record(backend: str, map_key: str, label: str, seconds: float, out: str, tag: str | None) -> int:
    import socketio   # only recording needs the backend client

    rows: List[dict] = []
    sio = socketio.Client()

    @sio.event
    def connect():
        sio.emit("join_map", map_key)

    @sio.on("reading_update")
    def _reading(d):
        if tag and d.get("tagId") != tag:
            return
        for r in d.get("ranges", []):
            rows.append({"t": d.get("t", time.time()), "label": label, "kind": "range", "tag": d["tagId"],
                         "anchor": r["anchorId"], "range": r["range"], "rx": r["rxPower"], "fp": r["fpPower"]})

    @sio.on("location_update")
    def _position(d):
        if tag and d.get("tagId") != tag:
            return
        rows.append({"t": time.time(), "label": label, "kind": "pos", "tag": d["tagId"],
                     "x": d["pos"]["x"], "z": d["pos"]["z"]})

    sio.connect(backend)
    print(f"[hw_log] recording '{label}' for {seconds:.0f} s from {backend} map={map_key} ...")
    time.sleep(seconds)
    sio.disconnect()

    new_file = not os.path.exists(out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    n_pos = sum(r["kind"] == "pos" for r in rows)
    print(f"[hw_log] {len(rows) - n_pos} ranges, {n_pos} positions ({n_pos / seconds:.1f}/s) -> {out}")
    return len(rows)


def load(path: str) -> List[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fetch_anchors(backend: str, map_key: str) -> Dict[str, Tuple[float, float, float]]:
    with urllib.request.urlopen(f"{backend}/api/maps/{map_key}", timeout=10) as r:
        m = json.load(r)
    return {a["id"]: (float(a["x"]), float(a["y"]), float(a["z"])) for a in m["anchors"]}


# ----------------------------------------------------------------- analysis
def baseline(rows: List[dict]) -> Dict[str, float]:
    """Median rxPower - fpPower per anchor and overall (dB). Log it in clear LOS."""
    gaps = defaultdict(list)
    for r in rows:
        if r["kind"] == "range":
            g = float(r["rx"]) - float(r["fp"])
            gaps[r["anchor"]].append(g)
            gaps["all"].append(g)
    return {a: float(np.median(v)) for a, v in sorted(gaps.items())}


def range_offsets(rows: List[dict], label: str, at: Tuple[float, float, float],
                  anchors: Dict[str, Tuple[float, float, float]]) -> Dict[str, dict]:
    """Per anchor: measured range minus the true distance from point `at` (metres)."""
    meas = defaultdict(list)
    for r in rows:
        if r["kind"] == "range" and r["label"] == label:
            meas[r["anchor"]].append(float(r["range"]))
    out = {}
    for a, v in sorted(meas.items()):
        true = math.dist(at, anchors[a])
        v = np.asarray(v)
        out[a] = {"n": int(v.size), "true_m": true, "mean_m": float(v.mean()),
                  "offset_m": float(v.mean() - true), "std_m": float(v.std())}
    return out


def accuracy(rows: List[dict], points: Dict[str, Tuple[float, float]]) -> dict:
    """Horizontal position error per taped point and overall (metres)."""
    per_point, all_err = {}, []
    for label, (px, pz) in points.items():
        e = [math.hypot(float(r["x"]) - px, float(r["z"]) - pz)
             for r in rows if r["kind"] == "pos" and r["label"] == label]
        if e:
            per_point[label] = {"n": len(e), "mean_m": float(np.mean(e)), "max_m": float(np.max(e))}
            all_err += e
    if not all_err:
        return {"points": per_point, "n": 0}
    a = np.asarray(all_err)
    return {"points": per_point, "n": int(a.size), "errors": a.tolist(),
            "rmse_m": float(np.sqrt(np.mean(a ** 2))), "p50_m": float(np.median(a)),
            "p90_m": float(np.quantile(a, .9)), "p95_m": float(np.quantile(a, .95))}


def load_points(path: str) -> Dict[str, Tuple[float, float]]:
    return {r["label"]: (float(r["x"]), float(r["z"])) for r in load(path)}


def plot_cdf(errors: List[float], out: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    e = np.sort(100 * np.asarray(errors))
    fig, ax = plt.subplots(figsize=(5, 3.4), dpi=150)
    ax.plot(e, np.arange(1, e.size + 1) / e.size, lw=2)
    ax.set_xlabel("Horizontal position error (cm)")
    ax.set_ylabel("Fraction of fixes")
    ax.set_ylim(0, 1)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(out)
    print(f"[hw_log] CDF chart -> {out}")


# ----------------------------------------------------------------- CLI
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record", help="log readings + positions from the backend")
    p.add_argument("--backend", default="http://localhost:3000")
    p.add_argument("--map", required=True)
    p.add_argument("--label", required=True, help="e.g. the taped point name, P1")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--tag", help="only this tag id (default: all)")
    p.add_argument("--out", required=True)

    p = sub.add_parser("baseline", help="LOS rx-fp power gap -> fpToRxDeltaLosDbm")
    p.add_argument("csv")

    p = sub.add_parser("ranges", help="per-anchor range offset at a known point")
    p.add_argument("csv")
    p.add_argument("--label", required=True)
    p.add_argument("--at", required=True, help="x,y,z of the tag in metres")
    p.add_argument("--backend", default="http://localhost:3000")
    p.add_argument("--map", required=True)

    p = sub.add_parser("accuracy", help="position error over taped points")
    p.add_argument("csv")
    p.add_argument("--points", required=True, help="CSV with label,x,z")
    p.add_argument("--plot", help="write an error CDF PNG here")

    args = ap.parse_args(argv)
    if args.cmd == "record":
        record(args.backend, args.map, args.label, args.seconds, args.out, args.tag)
    elif args.cmd == "baseline":
        b = baseline(load(args.csv))
        if not b:
            sys.exit("no range rows in file")
        for a, g in b.items():
            print(f"  {a:4} median rx-fp gap {g:5.2f} dB")
        print(f'set ranging.power.fpToRxDeltaLosDbm = {-b["all"]:.1f}')
    elif args.cmd == "ranges":
        at = tuple(float(v) for v in args.at.split(","))
        res = range_offsets(load(args.csv), args.label, at, fetch_anchors(args.backend, args.map))
        for a, r in res.items():
            print(f"  {a:4} n={r['n']:4}  true {r['true_m']:.3f} m  measured {r['mean_m']:.3f} m  "
                  f"offset {100 * r['offset_m']:+6.1f} cm  std {100 * r['std_m']:.1f} cm")
        print("A steady offset per anchor is antenna delay: recalibrate that anchor's ANTENNA_DELAY.")
    elif args.cmd == "accuracy":
        res = accuracy(load(args.csv), load_points(args.points))
        for lb, r in res["points"].items():
            print(f"  {lb:6} n={r['n']:4}  mean {100 * r['mean_m']:5.1f} cm  max {100 * r['max_m']:5.1f} cm")
        if not res["n"]:
            sys.exit("no position rows match the labels in the points file")
        print(f"overall n={res['n']}  RMSE {100 * res['rmse_m']:.1f} cm  P50 {100 * res['p50_m']:.1f}  "
              f"P90 {100 * res['p90_m']:.1f}  P95 {100 * res['p95_m']:.1f} cm")
        if args.plot:
            plot_cdf(res["errors"], args.plot)


if __name__ == "__main__":
    main()

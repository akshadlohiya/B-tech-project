"""Dataset anchor source — replays the real UTIL flight dataset as a TDOA stream.

This is the **walled-off TDOA track** (see DOCS/IMPLEMENTATION_PLAN.md). It is NOT
on the live warehouse critical path: our MaUWB_DW3000 hardware emits DS-TWR *ranges*,
which the range-based SimAnchorSource + WLS solver handle. This source instead replays
UTIL's raw *time-difference-of-arrival* measurements (real Decawave DWM1000 data, mm
Vicon ground truth) so we can implement and validate a TDOA EKF on genuine hardware
noise — a literature-standard second estimator to benchmark against.

Data reality (verified empirically)
-----------------------------------
UTIL's flight CSV is a long-format event log: each row is one TDOA event
(``t_tdoa, idA, idB, tdoa_meas``) but the ``pose_*`` columns carry the *most recent*
Vicon sample, NOT the pose at the TDOA instant. Using the raw row pose gives a 1.2 m
median error (stale); **interpolating the pose stream to each TDOA timestamp** drops
that to ~0.09 m. So we build a pose interpolator and sample it at every TDOA time.

``tdoa_meas`` is the range difference ``d(tag, anchorB) - d(tag, anchorA)`` in metres
(sign verified against surveyed geometry).
"""
from __future__ import annotations

import bisect
import csv
import os
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

Vec3 = Tuple[float, float, float]


@dataclass
class TdoaEvent:
    t: float                      # measurement time (s)
    id_a: int                     # reference anchor id
    id_b: int                     # second anchor id
    tdoa: float                   # measured d(tag,B) - d(tag,A), metres
    truth: Optional[Vec3] = None  # interpolated Vicon position (eval only)
    tag_id: str = "tag"           # which tag this measurement belongs to


def load_anchor_survey(path: str) -> Dict[int, Vec3]:
    """Parse ``anchor_constX_survey.txt`` -> {anchor_id: (x, y, z)} in metres."""
    anchors: Dict[int, Vec3] = {}
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) >= 4 and p[0].startswith("an") and p[0].endswith("_p"):
                anchors[int(p[0][2:-2])] = (float(p[1]), float(p[2]), float(p[3]))
    if not anchors:
        raise ValueError(f"no anchor positions parsed from {path}")
    return anchors


class _PoseInterpolator:
    """Linear interpolation of the Vicon pose stream, sampled at any query time."""

    def __init__(self, times: List[float], points: List[Vec3]):
        self._t = times
        self._p = points

    def at(self, t: float) -> Vec3:
        i = bisect.bisect_left(self._t, t)
        if i <= 0:
            return self._p[0]
        if i >= len(self._t):
            return self._p[-1]
        t0, t1 = self._t[i - 1], self._t[i]
        a = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        p0, p1 = self._p[i - 1], self._p[i]
        return (p0[0] + a * (p1[0] - p0[0]),
                p0[1] + a * (p1[1] - p0[1]),
                p0[2] + a * (p1[2] - p0[2]))


class DatasetTdoaSource:
    """Replays one UTIL flight trial as a stream of ``TdoaEvent``.

    Parameters
    ----------
    csv_path      : path to a ``const*-trial*-tdoa*.csv`` file.
    anchors       : {id: (x,y,z)} from :func:`load_anchor_survey`.
    with_truth    : attach interpolated Vicon ground truth to each event (for scoring).
    """

    name = "dataset"

    def __init__(self, csv_path: str, anchors: Dict[int, Vec3], with_truth: bool = True):
        self.csv_path = csv_path
        self.anchors = anchors
        self.with_truth = with_truth
        self._events: List[Tuple[float, int, int, float]] = []
        self._pose: Optional[_PoseInterpolator] = None
        self._load()

    def _load(self) -> None:
        pose_t: List[float] = []
        pose_p: List[Vec3] = []
        last_pt = None
        with open(self.csv_path) as f:
            for row in csv.DictReader(f):
                try:
                    ta = float(row["t_tdoa"])
                    ia, ib = int(float(row["idA"])), int(float(row["idB"]))
                    meas = float(row["tdoa_meas"])
                    tp = float(row["t_pose"])
                    pp = (float(row["pose_x"]), float(row["pose_y"]), float(row["pose_z"]))
                except (KeyError, ValueError):
                    continue
                if ia in self.anchors and ib in self.anchors:
                    self._events.append((ta, ia, ib, meas))
                if tp != last_pt:            # dedup the forward-filled pose column
                    pose_t.append(tp)
                    pose_p.append(pp)
                    last_pt = tp
        if not self._events:
            raise ValueError(f"no usable TDOA events in {self.csv_path}")
        # ensure monotonic pose times for bisect
        order = sorted(range(len(pose_t)), key=lambda i: pose_t[i])
        self._pose = _PoseInterpolator([pose_t[i] for i in order], [pose_p[i] for i in order])

    def events(self) -> Iterator[TdoaEvent]:
        for t, ia, ib, meas in self._events:
            truth = self._pose.at(t) if (self.with_truth and self._pose) else None
            yield TdoaEvent(t=t, id_a=ia, id_b=ib, tdoa=meas, truth=truth, tag_id="drone")

    def __len__(self) -> int:
        return len(self._events)

  
def to_site_frame(p: Vec3) -> Vec3:
    """UTIL frame (x, y, z=height) -> project site frame (x=east, y=up, z=north).

    UTIL logs the vertical axis last; our twin uses y as up. So (ux, uy, uz) maps to
    (x=ux, y=uz, z=uy). Applied identically to anchors, ground truth and EKF output so
    everything lines up in the 3D twin.
    """
    return (p[0], p[2], p[1])


def build_util_site(anchors: Dict[int, Vec3], name: str = "UTIL Flight Arena",
                    key: str = "util") -> dict:
    """Build a `uwb.site/1` map for the twin from the UTIL anchor survey.

    Renders the real ~8x8 m flight arena with the eight surveyed anchors and one flying
    tag, so the TDOA-EKF replay can be watched in the same 3D digital twin as the sim.
    """
    xs = [to_site_frame(p)[0] for p in anchors.values()]
    zs = [to_site_frame(p)[2] for p in anchors.values()]
    hs = [to_site_frame(p)[1] for p in anchors.values()]
    pad = 1.5
    size_x = max(4.0, (max(xs) - min(xs)) + 2 * pad)
    size_z = max(4.0, (max(zs) - min(zs)) + 2 * pad)
    site_anchors = []
    for aid in sorted(anchors):
        x, y, z = to_site_frame(anchors[aid])
        site_anchors.append({"id": f"an{aid}", "label": f"an{aid}", "x": round(x, 3),
                             "y": round(y, 3), "z": round(z, 3), "provenance": "measured"})
    return {
        "schema": "uwb.site/1",
        "key": key,
        "meta": {"name": name, "units": "meters",
                 "note": "Real UTIL flight arena (DWM1000, Vicon truth). TDOA-EKF replay."},
        "floor": {"id": "f_util", "label": "UTIL Arena", "sizeX": round(size_x, 1),
                  "sizeZ": round(size_z, 1), "ceilingHeight": round(max(hs) + 0.5, 1),
                  "provenance": "measured"},
        "anchors": site_anchors,
        "walls": [],
        "zones": [],
        "tags": [{"id": "drone", "name": "UTIL Drone", "role": "asset", "battery": 100,
                  "y": 1.0, "provenance": "measured"}],
        "ranging": {"mode": "TDOA", "updateRateHz": 20, "assumedTagHeightM": 1.0,
                    "note": "TDOA replay — position comes from the EKF, not the range solver."},
    }


# Convenience: locate the extracted dataset relative to the repo.
def default_paths(const: str = "const1", trial: str = "trial1", scheme: str = "tdoa2"):
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.normpath(os.path.join(
        here, "..", "..", "DOCS", "datasets", "util-uwb-dataset", "dataset", "flight-dataset"))
    csv_path = os.path.join(base, "csv-data", const, f"{const}-{trial}-{scheme}.csv")
    survey = os.path.join(base, "survey-results", f"anchor_{const}_survey.txt")
    return csv_path, survey

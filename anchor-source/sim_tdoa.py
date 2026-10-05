"""Generative TDOA simulator — synthetic UTIL-style TDOA for ANY custom layout.

This plays the same role as the UTIL replay (`DatasetTdoaSource`) but is *generative*:
it produces synthetic TDOA measurements for an editable site (e.g. the warehouse) using
an error model **learned from the real dataset** (`train_tdoa_model.py` ->
`tdoa_model.json`), instead of hand-tuned constants or a fixed recording.

It yields `TdoaEvent(t, id_a, id_b, tdoa, truth)` — the SAME contract as the replay — so
it feeds the same `TdoaEKF` and the same twin streamer.

Error model
-----------
- **Core noise**: a two-component Gaussian mixture learned from UTIL (tight inlier core +
  wide NLOS/outlier tail), plus a small systematic bias.
- **Geometry-aware NLOS**: for each tag->anchor link we test wall occlusion
  (`blocking_walls`) and, when blocked, add a POSITIVE material-dependent excess to that
  link's range (reusing the per-material calibration in `site["ranging"]["materials"]`)
  and raise the outlier probability — so passing behind a metal rack degrades the TDOA
  realistically. Open (LOS) sites fall back to the global learned mixture.

Pairing: TDOA2 scheme — anchor[0] is the reference; each cycle emits one event per other
anchor a_i with `tdoa = d(tag, a_i) - d(tag, ref)` (sign matches UTIL / the EKF).
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from geometry import blocking_walls
from dataset_source import TdoaEvent
from sim_anchors import _TagMover

Vec3 = Tuple[float, float, float]

DEFAULT_MODEL = {"sigma_inlier_m": 0.14, "sigma_outlier_m": 0.32,
                 "p_outlier": 0.11, "bias_m": 0.0}


class TdoaSimulator:
    name = "sim-tdoa"

    def __init__(self, site: Dict[str, Any], model: Optional[Dict[str, Any]] = None,
                 seed: Optional[int] = None):
        if len(site["anchors"]) < 3:
            raise ValueError("TDOA needs >= 3 anchors")
        self.site = site
        self.walls = site.get("walls", [])
        self.materials = site.get("ranging", {}).get("materials", {})
        self.rate = float(site.get("ranging", {}).get("updateRateHz", 20))
        m = model or DEFAULT_MODEL
        self.s_in = float(m["sigma_inlier_m"])
        self.s_out = float(m["sigma_outlier_m"])
        self.p_out = float(m["p_outlier"])
        self.bias = float(m.get("bias_m", 0.0))
        self._rng = random.Random(seed)
        # anchor id -> position; anchors[0] is the TDOA reference
        self.anchors: Dict[Any, Vec3] = {a["id"]: (a["x"], a["y"], a["z"]) for a in site["anchors"]}
        self.ref_id = site["anchors"][0]["id"]
        self.movers = {t["id"]: _TagMover(t) for t in site["tags"] if t.get("waypoints")}
        if not self.movers:
            raise ValueError("TdoaSimulator needs at least one tag with waypoints")

    # -- link/NLOS helpers ----------------------------------------------------
    def _link(self, tag: Vec3, anchor: Vec3) -> Tuple[float, float, bool]:
        """Return (measured_range, extra_outlier_boost, blocked) for one tag->anchor link."""
        true_r = math.dist(tag, anchor)
        blockers = blocking_walls((tag[0], tag[2]), (anchor[0], anchor[2]), self.walls)
        if not blockers:
            return true_r, 0.0, False
        # worst blocking material decides the excess bias (always positive)
        excess = 0.0
        for w in blockers:
            mat = self.materials.get(w.get("material", ""))
            lo, hi = (mat["biasMinM"], mat["biasMaxM"]) if mat else (0.1, 0.4)
            excess += self._rng.uniform(lo, hi)
        return true_r + excess, 0.35 * len(blockers), True

    def _noise(self, p_outlier: float) -> float:
        std = self.s_out if self._rng.random() < p_outlier else self.s_in
        return self._rng.gauss(0.0, std) + self.bias

    # -- main generator -------------------------------------------------------
    def events(self, realtime: bool = False) -> Iterator[TdoaEvent]:
        dt = 1.0 / self.rate
        sim_t = time.time()
        ref_pos = self.anchors[self.ref_id]
        others = [a for a in self.site["anchors"] if a["id"] != self.ref_id]
        while True:
            loop_start = time.time()
            for tag_id, mover in self.movers.items():
                tx, ty, tz = mover.step(dt)
                tag = (tx, ty, tz)
                r_ref, boost_ref, _ = self._link(tag, ref_pos)
                for a in others:
                    a_pos = (a["x"], a["y"], a["z"])
                    r_i, boost_i, _ = self._link(tag, a_pos)
                    p_out = min(0.6, self.p_out + boost_ref + boost_i)
                    tdoa = (r_i - r_ref) + self._noise(p_out)   # d(B) - d(A) + noise
                    yield TdoaEvent(t=sim_t, id_a=self.ref_id, id_b=a["id"],
                                    tdoa=tdoa, truth=tag, tag_id=tag_id)
            sim_t += dt
            if realtime:
                elapsed = time.time() - loop_start
                if elapsed < dt:
                    time.sleep(dt - elapsed)


def load_tdoa_model(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the learned model; fall back to a sensible default if absent."""
    import json
    import os
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(here, "..", "calibration", "tdoa_model.json"))
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULT_MODEL)

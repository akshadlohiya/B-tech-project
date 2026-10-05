"""Location engine — reading -> estimated position.

Consumes the common-format ranges and produces the `update_location` payload the
dashboard renders. It is deliberately decoupled from the data source: give it a
site and feed it readings; it does not care whether they are simulated or real.

Phase 3 emits the raw multilateration estimate. Phase 4 will insert a Kalman
filter here, between the solver and the emitted position, without changing the
message shape.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solver import solve_position, nlos_weight  # noqa: E402
from kalman import ConstantVelocityKF          # noqa: E402


class LocationEngine:
    def __init__(self, site: Dict[str, Any]):
        self.load(site)

    def load(self, site: Dict[str, Any]) -> None:
        self.anchor_pos = {a["id"]: (a["x"], a["y"], a["z"]) for a in site["anchors"]}
        self.zones = site["zones"]
        self.tags = {t["id"]: t for t in site["tags"]}
        self.floor_id = site["floor"]["id"]
        rng = site["ranging"]
        self.assumed_h = float(rng.get("assumedTagHeightM", 0.6))
        # LOS power gap = -(fpToRxDeltaLosDbm); used as the NLOS-weighting baseline.
        self.normal_gap = -float(rng["power"]["fpToRxDeltaLosDbm"])
        kf = rng.get("kalman", {})
        self.kf_sigma_a = float(kf.get("processNoiseStd", 2.0))
        self.kf_sigma_m = float(kf.get("measurementNoiseStd", 0.5))
        self.seed: Dict[str, tuple] = {}         # tagId -> last (x, z), seeds the solver
        self.filters: Dict[str, ConstantVelocityKF] = {}   # tagId -> Kalman filter
        self.last_t: Dict[str, float] = {}       # tagId -> last reading timestamp

    def zone_of(self, x: float, z: float) -> Optional[str]:
        for zn in self.zones:
            if zn["xmin"] <= x <= zn["xmax"] and zn["zmin"] <= z <= zn["zmax"]:
                return zn["id"]
        return None

    def estimate(self, reading: Dict[str, Any], truth: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        tag_id = reading["tagId"]
        anchors_xyz, ranges, weights = [], [], []
        for r in reading["ranges"]:
            if not r.get("valid", True):
                continue
            ap = self.anchor_pos.get(r["anchorId"])
            if ap is None:
                continue
            anchors_xyz.append(ap)
            ranges.append(r["range"])
            weights.append(nlos_weight(r["rxPower"], r["fpPower"], self.normal_gap))

        if len(ranges) < 3:
            return None   # not enough anchors this cycle -> hold last (twin keeps old pos)

        est = solve_position(anchors_xyz, ranges, weights, self.assumed_h, self.seed.get(tag_id))
        if est is None:
            return None
        raw_x, raw_z = est["x"], est["z"]

        # --- Phase 4: Kalman filter fusion ------------------------------------
        t = reading.get("t") or 0.0
        dt = t - self.last_t.get(tag_id, t) if self.last_t.get(tag_id) else 1.0 / 5
        self.last_t[tag_id] = t
        kf = self.filters.get(tag_id)
        if kf is None:
            kf = self.filters[tag_id] = ConstantVelocityKF(self.kf_sigma_a, self.kf_sigma_m)
        state, P = kf.step(raw_x, raw_z, dt)
        fx, fz, vx, vz = float(state[0]), float(state[1]), float(state[2]), float(state[3])
        self.seed[tag_id] = (fx, fz)   # seed next solve from the smoothed position

        meta = self.tags.get(tag_id, {})
        name = (truth or {}).get("name") or meta.get("name", tag_id)
        battery = (truth or {}).get("battery")
        if battery is None:
            battery = reading.get("battery", meta.get("battery"))
        zone = self.zone_of(fx, fz)

        payload: Dict[str, Any] = {
            "tagId": tag_id,
            "name": name,
            "battery": battery,
            "floorId": self.floor_id,
            "pos": {"x": round(fx, 3), "y": round(self.assumed_h, 3), "z": round(fz, 3)},
            "raw": {"x": round(raw_x, 3), "z": round(raw_z, 3)},
            "vel": {"vx": round(vx, 3), "vz": round(vz, 3), "speed": round(math.hypot(vx, vz), 3)},
            "cov": {"sx": round(float(P[0, 0]) ** 0.5, 3), "sz": round(float(P[1, 1]) ** 0.5, 3)},
            "zone": zone,
            "residual": round(est["residual"], 3),
            "nAnchors": est["n"],
            "t": reading.get("t"),
        }
        truth_pos = (truth or {}).get("truth")
        if truth_pos:
            payload["truth"] = truth_pos
            payload["error"] = round(math.hypot(fx - truth_pos["x"], fz - truth_pos["z"]), 3)
            payload["rawError"] = round(math.hypot(raw_x - truth_pos["x"], raw_z - truth_pos["z"]), 3)
        return payload

"""Location engine — reading -> estimated position.

Consumes the common-format ranges and produces the `update_location` payload the
dashboard renders. It is deliberately decoupled from the data source: give it a
site and feed it readings; it does not care whether they are simulated or real.

Phase 3 emits the raw multilateration estimate; Phase 4 smooths it with a Kalman
filter. Phase 6 (the ai-module) adds, without changing any existing field:
  * learned NLOS correction: blocked ranges are shortened by the predicted bias,
    not only down-weighted (`ranging.nlosModel`: "ai" (default) or "rule")
  * geofence alerts (outside allowed zone, stale tag) in `alerts`
  * a short-horizon predicted position from the Kalman velocity in `ghost`
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solver import solve_position, nlos_weight  # noqa: E402
from kalman import ConstantVelocityKF          # noqa: E402
from nlos_ai import load_learned_nlos          # noqa: E402  (puts ai-module on sys.path)
from uwb_ai.zones import ZoneMonitor           # noqa: E402
from uwb_ai.predict import predict_ahead       # noqa: E402


def _alert_dict(a) -> Dict[str, Any]:
    return {"tagId": a.tag_id, "kind": a.kind, "zone": a.zone, "t": a.t, "message": a.message}


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

        # --- Phase 6: AI ------------------------------------------------------
        self.learned = None
        self.nlos_method = "rule"
        self.nlos_note = "power-gap rule (ranging.nlosModel = \"rule\")"
        if rng.get("nlosModel", "ai") == "ai":
            self.learned, self.nlos_note = load_learned_nlos(self.normal_gap)
            if self.learned is not None:
                self.nlos_method = "ai"
            else:
                self.nlos_note = f"power-gap rule (fallback: {self.nlos_note})"
        ai = site.get("ai", {})
        self.horizon_s = float(ai.get("predictHorizonS", 1.0))
        self.monitor = ZoneMonitor(site, stale_after_s=float(ai.get("staleAfterS", 5.0)))
        fl = site["floor"]
        self.bounds = (-fl["sizeX"] / 2, fl["sizeX"] / 2, -fl["sizeZ"] / 2, fl["sizeZ"] / 2)

    def zone_of(self, x: float, z: float) -> Optional[str]:
        for zn in self.zones:
            if zn["xmin"] <= x <= zn["xmax"] and zn["zmin"] <= z <= zn["zmax"]:
                return zn["id"]
        return None

    def estimate(self, reading: Dict[str, Any], truth: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        tag_id = reading["tagId"]
        anchors_xyz, ranges, weights, gaps, ids = [], [], [], [], []
        for r in reading["ranges"]:
            if not r.get("valid", True):
                continue
            ap = self.anchor_pos.get(r["anchorId"])
            if ap is None:
                continue
            anchors_xyz.append(ap)
            ranges.append(r["range"])
            weights.append(nlos_weight(r["rxPower"], r["fpPower"], self.normal_gap))
            gaps.append(r["rxPower"] - r["fpPower"])
            ids.append(r["anchorId"])

        if len(ranges) < 3:
            return None   # not enough anchors this cycle -> hold last (twin keeps old pos)

        nlos_info: Dict[str, Any] = {"method": self.nlos_method}
        if self.learned is not None and all(math.isfinite(g) for g in gaps):
            ranges, weights, bias = self.learned.correct(ranges, gaps)
            nlos_info["bias"] = {a: round(float(b), 3) for a, b in zip(ids, bias)}
        elif self.learned is not None:
            nlos_info["method"] = "rule"   # unusable power reading: rule for this cycle

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

        # --- Phase 6: geofence alerts + predicted position --------------------
        alerts = [_alert_dict(a) for a in self.monitor.update(tag_id, fx, fz, t)]
        ghost, ghost_r = predict_ahead((fx, fz), (vx, vz), self.horizon_s, P,
                                       process_std=self.kf_sigma_a, bounds=self.bounds)

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
            "nlos": nlos_info,
            "ghost": {"x": round(float(ghost[0]), 3), "z": round(float(ghost[1]), 3),
                      "r": round(ghost_r, 3), "horizonS": self.horizon_s},
            "alerts": alerts,
        }
        truth_pos = (truth or {}).get("truth")
        if truth_pos:
            payload["truth"] = truth_pos
            payload["error"] = round(math.hypot(fx - truth_pos["x"], fz - truth_pos["z"]), 3)
            payload["rawError"] = round(math.hypot(raw_x - truth_pos["x"], raw_z - truth_pos["z"]), 3)
        return payload

    def check_stale(self, now: float) -> list:
        """Stale-tag alerts (tags with no fix for `ai.staleAfterS`), as dicts."""
        return [_alert_dict(a) for a in self.monitor.check_stale(now)]

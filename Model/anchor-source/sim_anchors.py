"""Simulated anchor source — mimics real MaUWB_DW3000 behaviour.

It moves each tag along its waypoint route and, for every anchor, produces a
DS-TWR range reading that carries the same error sources a real deployment sees:

  * antenna-delay bias   — constant per node, removed only by calibration.
  * ranging noise        — Gaussian, larger under NLOS.
  * NLOS excess bias      — POSITIVE ONLY: a blocked path is always reported
                            longer than the truth (Project Diary, 11 Apr 2026).
                            MATERIAL-DEPENDENT: metal racking biases far more than a
                            wooden shelf, which biases more than a light carton — each
                            wall's `material` selects a UTIL-calibrated bias/noise from
                            `ranging.materials` (see Model/calibration/CALIBRATION.md).
  * power diagnostics     — rx/first-path power; the (rx - fp) gap widens under
                            NLOS, exactly the DW3000 register behaviour the solver
                            will later use to down-weight blocked ranges.
  * dropped readings      — occasional invalid entries, more likely under NLOS.
  * turn-by-turn timing   — anchors range one at a time, so each range carries its
                            own slightly staggered timestamp.

Everything numeric comes from config/site.json, so tuning against real hardware
is a data change, not a code change.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from reading import AnchorRange, TagReading
from geometry import blocking_walls


class _TagMover:
    """Walks a tag along its waypoint loop with pauses and sharp turns."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.waypoints: List[Tuple[float, float]] = [tuple(w) for w in cfg["waypoints"]]
        self.speed = float(cfg.get("speed", 1.0))
        self.pause = float(cfg.get("pauseAtWaypointSec", 0.0))
        self.y = float(cfg.get("y", 0.5))
        self.battery = float(cfg.get("battery", 100))
        self.i = 0                      # index of the waypoint we are heading TO
        self.pos = list(self.waypoints[0])
        self._pause_left = 0.0

    def step(self, dt: float) -> Tuple[float, float, float]:
        if self._pause_left > 0:
            self._pause_left -= dt
        else:
            target = self.waypoints[self.i]
            dx, dz = target[0] - self.pos[0], target[1] - self.pos[1]
            dist = math.hypot(dx, dz)
            travel = self.speed * dt
            if dist <= travel or dist < 1e-6:
                self.pos = list(target)
                self.i = (self.i + 1) % len(self.waypoints)
                self._pause_left = self.pause
            else:
                self.pos[0] += dx / dist * travel
                self.pos[1] += dz / dist * travel
        # slow, occasional battery drain
        if random.random() < 0.01 and self.battery > 5:
            self.battery -= 1
        # world coordinates: (x east, y up/height, z north)
        return self.pos[0], self.y, self.pos[1]


class SimAnchorSource:
    name = "sim"

    def __init__(self, site: Dict[str, Any]):
        self.site = site
        self.anchors = site["anchors"]
        self.walls = site["walls"]
        self.zones = site["zones"]
        self.floor_id = site["floor"]["id"]
        self.r = site["ranging"]
        self.power = self.r["power"]
        # Per-material NLOS physics (metal racking biases far more than a wooden
        # shelf); calibrated from UTIL. Falls back to the aggregate NLOS values for
        # any wall whose material is unknown -> backward compatible.
        self.materials = self.r.get("materials", {})
        self.rate = float(self.r.get("updateRateHz", 5))
        self.movers = {t["id"]: _TagMover(t) for t in site["tags"]}
        self.tag_cfg = {t["id"]: t for t in site["tags"]}
        self.seq = {t["id"]: 0 for t in site["tags"]}

    # -- helpers --------------------------------------------------------------
    def _zone_of(self, x: float, z: float) -> Optional[str]:
        for zn in self.zones:
            if zn["xmin"] <= x <= zn["xmax"] and zn["zmin"] <= z <= zn["zmax"]:
                return zn["id"]
        return None

    def _range_reading(self, anchor: Dict[str, Any], tx: float, ty: float, tz: float) -> AnchorRange:
        # true straight-line distance in 3D
        true_range = math.sqrt(
            (tx - anchor["x"]) ** 2 + (ty - anchor["y"]) ** 2 + (tz - anchor["z"]) ** 2
        )
        blockers = blocking_walls((tx, tz), (anchor["x"], anchor["z"]), self.walls)
        nlos = len(blockers) > 0

        # constant antenna-delay bias (a bias, not noise — calibration removes it)
        measured = true_range + float(anchor.get("antennaDelayBiasM", 0.0))

        if nlos:
            # Per-blocker, material-dependent excess bias (ALWAYS positive: the signal
            # detours around the obstacle). The random jitter uses the worst blocking
            # material's noise. Unknown materials fall back to the aggregate NLOS model.
            noise_std = self.r["nlosNoiseStdM"]
            excess = 0.0
            for w in blockers:
                m = self.materials.get(w.get("material", ""))
                if m:
                    excess += random.uniform(m["biasMinM"], m["biasMaxM"])
                    noise_std = max(noise_std, m["noiseStdM"])
                else:
                    excess += random.uniform(self.r["nlosBiasMinM"], self.r["nlosBiasMaxM"])
            measured += random.gauss(0.0, noise_std) + excess
            drop_p = self.r["dropProbNlos"]
        else:
            measured += random.gauss(0.0, self.r["losNoiseStdM"])
            drop_p = self.r["dropProbLos"]

        measured = max(0.0, min(measured, self.r["maxRangeM"]))

        # signal power model (dBm): falls with distance; NLOS attenuates further,
        # and attenuates the FIRST path more than total power -> widening gap.
        rx = self.power["rxPowerLosDbm"] + self.power["rxPowerPerMeterDbm"] * true_range
        fp = rx + self.power["fpToRxDeltaLosDbm"]
        if nlos:
            rx += self.power["nlosRxDropDbm"]
            fp += self.power["nlosRxDropDbm"] + self.power["nlosFpExtraAttenDbm"]

        valid = random.random() > drop_p
        return AnchorRange(
            anchor_id=anchor["id"], range_m=measured, rx_power_dbm=rx, fp_power_dbm=fp,
            nlos=nlos, valid=valid,
        )

    # -- main generator -------------------------------------------------------
    def cycles(self) -> Iterator[Tuple[TagReading, Optional[Dict[str, Any]]]]:
        dt = 1.0 / self.rate
        # spread anchor timestamps across the cycle (turn-by-turn ranging)
        slot = dt / max(1, len(self.anchors)) * 0.5
        # Simulated clock: timestamps advance by exactly `dt` each cycle, decoupled
        # from wall-clock. Downstream dt is then correct regardless of real-time
        # pacing (and offline analysis stays valid).
        sim_t = time.time()
        while True:
            loop_start = time.time()
            for tag_id, mover in self.movers.items():
                tx, ty, tz = mover.step(dt)
                self.seq[tag_id] += 1

                ranges: List[AnchorRange] = []
                for k, anchor in enumerate(self.anchors):
                    ar = self._range_reading(anchor, tx, ty, tz)
                    ar.t = sim_t + k * slot
                    ranges.append(ar)

                reading = TagReading(
                    tag_id=tag_id, seq=self.seq[tag_id], ranges=ranges,
                    source="sim", battery=round(mover.battery), t=sim_t,
                )
                cfg = self.tag_cfg[tag_id]
                zone = self._zone_of(tx, tz)
                truth = {
                    "tagId": tag_id,
                    "name": cfg["name"],
                    "battery": round(mover.battery),
                    "floorId": self.floor_id,
                    "pos": {"x": round(tx, 3), "y": round(ty, 3), "z": round(tz, 3)},
                    "truth": {"x": round(tx, 3), "z": round(tz, 3)},
                    "zone": zone,
                    "t": sim_t,
                }
                yield reading, truth

            sim_t += dt
            # pace the loop to the configured update rate (live streaming only)
            elapsed = time.time() - loop_start
            if elapsed < dt:
                time.sleep(dt - elapsed)

"""Common UWB reading data format.

This is the single contract that both the simulator and the real hardware must
emit. Because the shape is identical, everything downstream (the position solver,
the Kalman filter, the dashboard) does not care whether a reading came from a
simulated anchor or a physical MaUWB_DW3000 module.

Design decisions (see Project Diary, 17-19 Mar 2026):
  * Versioned:      every message carries SCHEMA so a mismatched producer is
                    caught immediately instead of silently corrupting fixes.
  * Range-based:    the DW3000 firmware performs DS-TWR ranging and reports a
                    distance per anchor, NOT raw time-of-arrival timestamps.
                    So the fundamental measurement is a range in metres.
  * Diagnostics:    rx_power / fp_power mirror the DW3000 power registers and let
                    the solver detect and down-weight NLOS (non-line-of-sight).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
import time

SCHEMA = "uwb.reading/1"


@dataclass
class AnchorRange:
    """One anchor -> tag range measurement from a single ranging exchange."""
    anchor_id: str
    range_m: float          # measured distance in metres (already includes real-world error)
    rx_power_dbm: float     # total received signal power
    fp_power_dbm: float     # first-path signal power; large (rx - fp) gap hints NLOS
    nlos: bool              # ground-truth NLOS flag (sim only; hardware infers it)
    valid: bool = True      # False => reading dropped / no first path detected
    t: float = field(default_factory=time.time)  # per-anchor timestamp (turn-by-turn ranging)

    def to_dict(self) -> dict:
        return {
            "anchorId": self.anchor_id,
            "range": round(self.range_m, 4),
            "rxPower": round(self.rx_power_dbm, 2),
            "fpPower": round(self.fp_power_dbm, 2),
            "nlos": self.nlos,
            "valid": self.valid,
            "t": self.t,
        }


@dataclass
class TagReading:
    """All anchor ranges gathered for one tag in one ranging cycle."""
    tag_id: str
    seq: int
    ranges: List[AnchorRange]
    source: str = "sim"                 # "sim" or "hardware" — provenance of the data
    battery: int | None = None          # tag-reported battery %, if available
    t: float = field(default_factory=time.time)
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "tagId": self.tag_id,
            "seq": self.seq,
            "source": self.source,
            "battery": self.battery,
            "t": self.t,
            "ranges": [r.to_dict() for r in self.ranges],
        }

    @staticmethod
    def from_dict(d: dict) -> "TagReading":
        if d.get("schema") != SCHEMA:
            raise ValueError(f"Unsupported reading schema: {d.get('schema')!r} (expected {SCHEMA!r})")
        ranges = [
            AnchorRange(
                anchor_id=r["anchorId"],
                range_m=r["range"],
                rx_power_dbm=r["rxPower"],
                fp_power_dbm=r["fpPower"],
                nlos=r.get("nlos", False),
                valid=r.get("valid", True),
                t=r.get("t", d.get("t", time.time())),
            )
            for r in d["ranges"]
        ]
        return TagReading(
            tag_id=d["tagId"], seq=d["seq"], ranges=ranges,
            source=d.get("source", "unknown"), battery=d.get("battery"),
            t=d.get("t", time.time()),
        )

"""Real-hardware anchor source (integration seam).

This is the ONLY file the team touches to go from simulation to real MaUWB_DW3000
hardware. It listens for range reports on the network and translates each packet
into the common `TagReading` format. Everything downstream — solver, Kalman
filter, dashboard — is unchanged (Project Diary, 23 Jul 2026: "the program that
will later replace guessed values with real measured ones").

Wiring on real hardware:
  * Each anchor node ranges to the tag (DS-TWR) and its ESP32 forwards the result
    over Wi-Fi as a small UDP/JSON datagram to this host.
  * Run this source with:  SOURCE=hardware python main.py

The only project-specific work is `_parse_packet()` below: map whatever field
names the node firmware sends onto AnchorRange. The default implementation
already accepts the recommended firmware payload shape.

Packets arrive one anchor at a time, so `CycleAssembler` groups them into one
reading per tag per ranging cycle. A cycle is released when every anchor has
reported, or when the cycle window has passed and at least MIN_ANCHORS have, so
a blocked or silent anchor does not freeze the tag. A repeat report from an
anchor already in the cycle means a new cycle has started.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    from reading import AnchorRange, TagReading
except ModuleNotFoundError:  # pragma: no cover - support IDE/runtime when repo root isn't on PYTHONPATH
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from reading import AnchorRange, TagReading

LISTEN_HOST = os.environ.get("UWB_UDP_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("UWB_UDP_PORT", "9000"))
MIN_ANCHORS = 3          # fewest ranges the solver can use for a 2D fix
WINDOW_FRACTION = 0.8    # cycle window = this share of one ranging period


class CycleAssembler:
    """Groups per-anchor ranges into one reading per tag per ranging cycle."""

    def __init__(self, n_anchors: int, window_s: float, min_anchors: int = MIN_ANCHORS):
        self.n_anchors = n_anchors
        self.window_s = window_s
        self.min_anchors = min(min_anchors, n_anchors)
        self._pending: Dict[str, Dict[str, AnchorRange]] = {}
        self._started: Dict[str, float] = {}

    def add(self, tag_id: str, ar: AnchorRange, now: float) -> List[Tuple[str, List[AnchorRange], float]]:
        """Add one range; -> cycles released by it, as (tag, ranges, cycle start time)."""
        out = []
        cycle = self._pending.get(tag_id)
        if cycle is not None and ar.anchor_id in cycle:   # anchor reported again: new cycle
            out += self._release(tag_id)
        if tag_id not in self._pending:
            self._pending[tag_id] = {}
            self._started[tag_id] = now
        self._pending[tag_id][ar.anchor_id] = ar
        if len(self._pending[tag_id]) >= self.n_anchors:
            out += self._release(tag_id)
        return out

    def flush(self, now: float) -> List[Tuple[str, List[AnchorRange], float]]:
        """Release cycles whose window has passed."""
        out = []
        for tag_id in [t for t, t0 in self._started.items() if now - t0 >= self.window_s]:
            out += self._release(tag_id)
        return out

    def _release(self, tag_id: str) -> List[Tuple[str, List[AnchorRange], float]]:
        ranges = list(self._pending.pop(tag_id).values())
        t0 = self._started.pop(tag_id)
        # too few anchors to solve: drop the cycle rather than mix it into the next one
        return [(tag_id, ranges, t0)] if len(ranges) >= self.min_anchors else []


class HardwareAnchorSource:
    name = "hardware"

    def __init__(self, site: Dict[str, Any]):
        self.site = site
        self.anchor_ids = [a["id"] for a in site["anchors"]]
        rate_hz = float(site.get("ranging", {}).get("updateRateHz", 5))
        self.assembler = CycleAssembler(len(self.anchor_ids), WINDOW_FRACTION / rate_hz)
        self._seq = defaultdict(int)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((LISTEN_HOST, LISTEN_PORT))
        self._sock.settimeout(self.assembler.window_s / 4)   # wake up to release timed-out cycles

    def close(self) -> None:
        """Free the UDP port so a rebuilt source (map reload) can bind it again."""
        self._sock.close()

    def _parse_packet(self, data: bytes) -> Optional[Tuple[str, AnchorRange]]:
        """Translate one node datagram into (tag_id, AnchorRange).

        Expected JSON (adjust field names here to match your firmware):
            {"tag":"T1","anchor":"A1","range":9.41,"rxPower":-83.2,"fpPower":-86.1}
        Missing power fields default so a bare-range node still works.
        """
        try:
            p = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        try:
            tag_id = str(p["tag"])
            ar = AnchorRange(
                anchor_id=str(p["anchor"]),
                range_m=float(p["range"]), 
                rx_power_dbm=float(p.get("rxPower", -85.0)),
                fp_power_dbm=float(p.get("fpPower", -88.0)),
                nlos=False,   # unknown on real hardware; solver infers from power gap
                valid=bool(p.get("valid", True)),
            )
        except (KeyError, ValueError):
            return None
        return tag_id, ar

    def cycles(self) -> Iterator[Tuple[TagReading, Optional[Dict[str, Any]]]]:
        while True:
            released = []
            try:
                data, _addr = self._sock.recvfrom(2048)
                parsed = self._parse_packet(data)
                if parsed is not None:
                    released += self.assembler.add(*parsed, now=time.time())
            except socket.timeout:
                pass
            released += self.assembler.flush(time.time())
            for tag_id, ranges, t0 in released:
                self._seq[tag_id] += 1
                reading = TagReading(
                    tag_id=tag_id, seq=self._seq[tag_id], ranges=ranges, source="hardware", t=t0,
                )
                yield reading, None   # hardware has no ground truth

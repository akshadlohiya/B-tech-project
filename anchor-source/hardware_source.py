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
"""
from __future__ import annotations

import json
import os
import socket
import sys
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


class HardwareAnchorSource:
    name = "hardware"

    def __init__(self, site: Dict[str, Any]):
        self.site = site
        self.anchor_ids = [a["id"] for a in site["anchors"]]
        self.expected = len(self.anchor_ids)
        self._seq = defaultdict(int)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((LISTEN_HOST, LISTEN_PORT))

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
        # Assemble per-anchor datagrams into one reading per tag. A reading is
        # released once all expected anchors have reported for that tag.
        pending: Dict[str, Dict[str, AnchorRange]] = defaultdict(dict)
        while True:
            data, _addr = self._sock.recvfrom(2048)
            parsed = self._parse_packet(data)
            if parsed is None:
                continue
            tag_id, ar = parsed
            pending[tag_id][ar.anchor_id] = ar
            if len(pending[tag_id]) >= self.expected:
                ranges: List[AnchorRange] = list(pending.pop(tag_id).values())
                self._seq[tag_id] += 1
                reading = TagReading(
                    tag_id=tag_id, seq=self._seq[tag_id], ranges=ranges, source="hardware",
                )
                yield reading, None   # hardware has no ground truth

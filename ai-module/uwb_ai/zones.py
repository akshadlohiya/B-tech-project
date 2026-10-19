"""Geofence / zone anomaly alerts (IMPLEMENTATION_PLAN.md, Phase 6).

Reads zones and per-tag `allowedZones` straight from config/site.json, so
there is no second copy of the map. Zones are axis-aligned rectangles in the
site's x/z plane (metres).

Alerts raised per tag:
  * "outside_allowed" -- the tag is in a zone not in its allowedZones
                         (or in no zone at all while it has an allow-list)
  * "stale"           -- no update for longer than `stale_after_s`

Each alert type fires once when the condition starts, not on every update.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Alert:
    tag_id: str
    kind: str        # "outside_allowed" | "stale"
    zone: Optional[str]
    t: float
    message: str


class ZoneMonitor:
    def __init__(self, site: dict, stale_after_s: float = 5.0):
        self.zones = list(site.get("zones", []))
        self.allowed: Dict[str, set] = {
            t["id"]: set(t["allowedZones"]) for t in site.get("tags", []) if t.get("allowedZones")
        }
        self.stale_after_s = stale_after_s
        self._last_seen: Dict[str, float] = {}
        self._active: Dict[str, set] = {}

    def zone_at(self, x: float, z: float) -> Optional[str]:
        for zn in self.zones:
            if zn["xmin"] <= x <= zn["xmax"] and zn["zmin"] <= z <= zn["zmax"]:
                return zn["id"]
        return None

    def _raise(self, tag_id: str, kind: str, zone, t: float, msg: str) -> List[Alert]:
        active = self._active.setdefault(tag_id, set())
        if kind in active:
            return []
        active.add(kind)
        return [Alert(tag_id, kind, zone, t, msg)]

    def _clear(self, tag_id: str, kind: str) -> None:
        self._active.get(tag_id, set()).discard(kind)

    def update(self, tag_id: str, x: float, z: float, t: float) -> List[Alert]:
        """Feed one position; returns newly raised alerts."""
        self._last_seen[tag_id] = t
        self._clear(tag_id, "stale")
        zone = self.zone_at(x, z)
        allowed = self.allowed.get(tag_id)
        if allowed is not None and zone not in allowed:
            where = zone or "an unmapped area"
            return self._raise(tag_id, "outside_allowed", zone, t, f"{tag_id} entered {where}")
        self._clear(tag_id, "outside_allowed")
        return []

    def check_stale(self, now: float) -> List[Alert]:
        out: List[Alert] = []
        for tag_id, seen in self._last_seen.items():
            if now - seen > self.stale_after_s:
                out += self._raise(tag_id, "stale", None, now,
                                   f"{tag_id} silent for {now - seen:.1f} s")
        return out

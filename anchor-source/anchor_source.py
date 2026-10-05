"""Anchor data source abstraction.

This is the seam that makes the simulator and real hardware interchangeable
(Project Diary, 28 Mar 2026 — "the switching part that lets us change between
fake and real readings easily").

An AnchorSource yields two kinds of things per ranging cycle:
  * a `TagReading`  — the common-format raw ranges (always).
  * a ground-truth position dict — ONLY the simulator knows this; it is used for
    the accuracy HUD and, until the solver lands in Phase 3, to drive the twin.
    Real hardware returns None here.

To go live on hardware, implement HardwareAnchorSource.poll() and select it with
SOURCE=hardware. Nothing downstream of this file changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional, Tuple, Dict, Any

from reading import TagReading  # noqa: E402  (added to sys.path by main.py)


class AnchorSource(ABC):
    name = "base"

    @abstractmethod
    def cycles(self) -> Iterator[Tuple[TagReading, Optional[Dict[str, Any]]]]:
        """Yield (reading, ground_truth_or_None) forever, paced in real time."""
        raise NotImplementedError


def make_source(kind: str, site: Dict[str, Any]) -> AnchorSource:
    kind = (kind or "sim").lower()
    if kind == "sim":
        from sim_anchors import SimAnchorSource
        return SimAnchorSource(site)
    if kind == "hardware":
        from hardware_source import HardwareAnchorSource
        return HardwareAnchorSource(site)
    raise ValueError(f"Unknown anchor source kind: {kind!r} (use 'sim' or 'hardware')")

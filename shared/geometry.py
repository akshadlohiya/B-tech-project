"""Small 2D geometry helpers, shared by the simulator and the map logic.

Line-of-sight is approximated in the floor plane (x, z): a tag->anchor path is
NLOS if the straight segment between them crosses any wall segment. This is a
deliberate simplification — a full 3D check would also consider wall/rack
heights vs the ray's elevation — but it captures the behaviour that matters:
racks between a tag and an anchor produce blocked, biased ranges.
"""
from __future__ import annotations

from typing import List, Tuple


def _ccw(ax: float, az: float, bx: float, bz: float, cx: float, cz: float) -> float:
    """Cross product of (b-a) x (c-a); sign tells orientation of a->b->c."""
    return (bx - ax) * (cz - az) - (bz - az) * (cx - ax)


def segments_intersect(
    p1: Tuple[float, float], p2: Tuple[float, float],
    q1: Tuple[float, float], q2: Tuple[float, float],
) -> bool:
    """True if segment p1p2 properly intersects segment q1q2 (2D)."""
    d1 = _ccw(q1[0], q1[1], q2[0], q2[1], p1[0], p1[1])
    d2 = _ccw(q1[0], q1[1], q2[0], q2[1], p2[0], p2[1])
    d3 = _ccw(p1[0], p1[1], p2[0], p2[1], q1[0], q1[1])
    d4 = _ccw(p1[0], p1[1], p2[0], p2[1], q2[0], q2[1])
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def blocking_walls(
    tag_xz: Tuple[float, float], anchor_xz: Tuple[float, float], walls: List[dict]
) -> List[dict]:
    """Return the wall dicts that block the tag->anchor path (empty => LOS).

    Returns the full wall objects (not just ids) so callers can read each blocker's
    ``material`` and model material-dependent NLOS error (metal racking biases a range
    far more than a wooden shelf). See geometry.py / calibration for the physics.
    """
    hits: List[dict] = []
    for w in walls:
        if not w.get("blocksLos", True):
            continue
        if segments_intersect(tag_xz, anchor_xz, (w["x1"], w["z1"]), (w["x2"], w["z2"])):
            hits.append(w)
    return hits


def path_is_blocked(
    tag_xz: Tuple[float, float], anchor_xz: Tuple[float, float], walls: List[dict]
) -> List[str]:
    """Return the ids of walls that block the tag->anchor path (empty => LOS)."""
    return [w["id"] for w in blocking_walls(tag_xz, anchor_xz, walls)]

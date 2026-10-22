"""Multilateration solver — turns per-anchor ranges into a position.

This is the "position calculation in a separate file that will not be changed"
(Project Diary, 27 Mar 2026). It knows nothing about sockets, simulation or the
dashboard — it takes anchors + ranges and returns an (x, y, z) estimate. The same
function serves simulated and real readings.

Approach (2D trilateration with height compensation):
  * Four ceiling anchors give stable *2D* geometry (item list, Note 1). Solving a
    full 3D position for a floor-level tag from near-coplanar ceiling anchors is
    ill-conditioned in height, so we solve for (x, z) at an assumed tag height and
    compensate each slant range for the known vertical drop to its anchor.
  * NLOS down-weighting: blocked ranges are biased long, so they are trusted less.
    The weight comes from the DW3000 power gap (rxPower - fpPower): a wide gap means
    the first path was attenuated -> likely NLOS. This is the real-hardware signal,
    so the solver behaves identically on simulated and physical data.
  * Weighted non-linear least squares (Levenberg-Marquardt) from a centroid / last
    known position seed.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import least_squares


def nlos_weight(rx_power_dbm: float, fp_power_dbm: float,
                normal_gap_db: float = 3.0, k: float = 0.25) -> float:
    """Trust weight in (0, 1] from the received/first-path power gap.

    LOS gap ~= normal_gap_db -> weight ~= 1. A wider gap (first path attenuated by
    an obstacle) drives the weight down so the biased range influences the fix less.
    """
    gap = rx_power_dbm - fp_power_dbm
    excess = max(0.0, gap - normal_gap_db)
    return 1.0 / (1.0 + k * excess)


def solve_position(
    anchors_xyz: Sequence[Tuple[float, float, float]],
    ranges_m: Sequence[float],
    weights: Optional[Sequence[float]] = None,
    assumed_height: float = 0.6,
    seed_xz: Optional[Tuple[float, float]] = None,
) -> Optional[dict]:
    """Estimate tag position from anchor ranges.

    Returns {x, y, z, residual, n} or None if under-determined (< 3 anchors).
    """
    n = len(ranges_m)
    if n < 3:
        return None

    A = np.array([[a[0], a[2]] for a in anchors_xyz], dtype=float)  # (x, z) plane
    anchor_y = np.array([a[1] for a in anchors_xyz], dtype=float)
    r = np.asarray(ranges_m, dtype=float)

    # Compensate each slant range for the vertical drop to its (ceiling) anchor.
    dz = anchor_y - assumed_height
    horiz = np.sqrt(np.maximum(r ** 2 - dz ** 2, 0.0))

    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    w = np.clip(w, 1e-3, None)
    sw = np.sqrt(w)

    def residuals(p):
        d = np.sqrt(((A - p) ** 2).sum(axis=1))
        return sw * (d - horiz)

    p0 = np.array(seed_xz, dtype=float) if seed_xz is not None else A.mean(axis=0)
    sol = least_squares(residuals, p0, method="lm", max_nfev=50)
    x, z = float(sol.x[0]), float(sol.x[1])
    rms = float(np.sqrt(np.mean(sol.fun ** 2)))
    return {"x": x, "y": assumed_height, "z": z, "residual": rms, "n": n}

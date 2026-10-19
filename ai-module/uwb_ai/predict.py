"""Short-horizon trajectory prediction (IMPLEMENTATION_PLAN.md, Phase 6).

Uses the Kalman filter's velocity state, so it costs nothing extra:
    p(t + dt) = p + v * dt
with the covariance grown under the same constant-velocity model, giving the
dashboard a "ghost" marker plus an uncertainty radius.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np


def predict_ahead(pos: Sequence[float], vel: Sequence[float], horizon_s: float,
                  cov: Optional[np.ndarray] = None, process_std: float = 2.0,
                  bounds: Optional[Tuple[float, float, float, float]] = None):
    """-> (predicted position (2,), 1-sigma radius or None).

    pos, vel: [x, z] and [vx, vz] from the Kalman state.
    cov:      optional 4x4 covariance of [x, z, vx, vz].
    bounds:   optional (xmin, xmax, zmin, zmax) to clamp the ghost to the floor.
    """
    if horizon_s < 0:
        raise ValueError("horizon_s must be >= 0")
    p = np.asarray(pos, dtype=float) + np.asarray(vel, dtype=float) * horizon_s
    if bounds is not None:
        p = np.clip(p, [bounds[0], bounds[2]], [bounds[1], bounds[3]])
    if cov is None:
        return p, None
    dt = horizon_s
    F = np.eye(4)
    F[0, 2] = F[1, 3] = dt
    G = np.array([[dt**2 / 2, 0], [0, dt**2 / 2], [dt, 0], [0, dt]])
    P = F @ np.asarray(cov, dtype=float) @ F.T + G @ (process_std**2 * np.eye(2)) @ G.T
    radius = float(np.sqrt(max(P[0, 0], P[1, 1])))
    return p, radius

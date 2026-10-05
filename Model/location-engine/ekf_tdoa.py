"""Extended Kalman Filter for raw UWB TDOA (the walled-off parallel estimator).

Why an EKF here (and not the CV-Kalman used on the live warehouse path)
----------------------------------------------------------------------
The range-based pipeline solves position first (WLS multilateration) and then smooths
it with a *linear* constant-velocity Kalman filter — adequate because our DS-TWR
hardware gives ranges. TDOA is different: each measurement is a *range difference*

        h(p) = ||p - a_B|| - ||p - a_A||

which is a nonlinear function of position, so it must be linearised each step — an
Extended KF. This module consumes a TDOA stream (real UTIL replay OR the generative
TdoaSimulator) and estimates position; it benchmarks a literature-standard TDOA
estimator, NOT the live warehouse path (see IMPLEMENTATION_PLAN).

Two modes
---------
- **3D** (``height=None``): full state ``[x, y, z, vx, vy, vz]`` — for well-spread
  anchors at varied heights (the UTIL drone arena).
- **2D fixed-height** (``height=h``): state ``[x, z, vx, vz]`` with the tag height held
  at ``h`` — for near-coplanar *ceiling* anchors (the warehouse), where TDOA cannot
  observe height. This mirrors the range solver's "solve 2D at an assumed height".

Robustness: a chi-square innovation gate rejects gross NLOS outliers.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np

Vec3 = Tuple[float, float, float]


class TdoaEKF:
    def __init__(
        self,
        sigma_a: float = 3.0,        # process (accel) noise std, m/s^2
        sigma_tdoa: float = 0.15,    # measurement noise std, m  (~UTIL LOS TDOA)
        gate: float = 12.0,          # chi-square(1 dof) innovation gate; None disables
        init_pos: Optional[Vec3] = None,
        init_pos_std: float = 3.0,
        init_vel_std: float = 1.0,
        height: Optional[float] = None,   # set -> 2D fixed-height mode
    ):
        self.sa2 = float(sigma_a) ** 2
        self.R = float(sigma_tdoa) ** 2
        self.gate = gate
        self.height = height
        self.nd = 3 if height is None else 2      # position dimensions
        self.ns = 2 * self.nd                     # state size
        self.x: Optional[np.ndarray] = None
        self.P: Optional[np.ndarray] = None
        self._init_pos = init_pos
        self._ips2 = float(init_pos_std) ** 2
        self._ivs2 = float(init_vel_std) ** 2
        self.n_used = 0
        self.n_rejected = 0

    # -- lifecycle ------------------------------------------------------------
    def initialize(self, pos: Vec3) -> None:
        if self.nd == 3:
            pos_part = [pos[0], pos[1], pos[2]]
        else:
            pos_part = [pos[0], pos[2]]           # (x, z); height is fixed
        self.x = np.array(pos_part + [0.0] * self.nd, dtype=float)
        self.P = np.diag([self._ips2] * self.nd + [self._ivs2] * self.nd)

    def _ensure(self) -> bool:
        if self.x is None:
            if self._init_pos is None:
                return False
            self.initialize(self._init_pos)
        return True

    def _pos3(self) -> np.ndarray:
        """Current estimate as a 3D point (inserting the fixed height in 2D mode)."""
        if self.nd == 3:
            return self.x[:3]
        return np.array([self.x[0], self.height, self.x[1]])

    # -- prediction -----------------------------------------------------------
    def predict(self, dt: float) -> None:
        if self.x is None:
            return
        dt = float(max(1e-4, min(dt, 1.0)))     # clamp against gaps / bad stamps
        nd = self.nd
        F = np.eye(self.ns)
        for i in range(nd):
            F[i, i + nd] = dt
        dt2, dt3, dt4 = dt * dt, dt ** 3, dt ** 4
        q_pp, q_pv, q_vv = dt4 / 4, dt3 / 2, dt2
        Q = np.zeros((self.ns, self.ns))
        for i in range(nd):
            Q[i, i] = self.sa2 * q_pp
            Q[i, i + nd] = Q[i + nd, i] = self.sa2 * q_pv
            Q[i + nd, i + nd] = self.sa2 * q_vv
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    # -- measurement update ---------------------------------------------------
    def update(self, tdoa: float, anchor_a: Vec3, anchor_b: Vec3) -> bool:
        """Fuse one TDOA = d(p,B) - d(p,A). Returns True if accepted (not gated)."""
        if not self._ensure():
            return False
        p = self._pos3()
        aA = np.asarray(anchor_a, dtype=float)
        aB = np.asarray(anchor_b, dtype=float)
        dA = np.linalg.norm(p - aA)
        dB = np.linalg.norm(p - aB)
        if dA < 1e-6 or dB < 1e-6:
            return False
        h = dB - dA
        grad3 = (p - aB) / dB - (p - aA) / dA          # d h / d position (3D)
        H = np.zeros((1, self.ns))
        if self.nd == 3:
            H[0, :3] = grad3
        else:
            H[0, 0], H[0, 1] = grad3[0], grad3[2]      # only x, z observable
        y = float(tdoa - h)                             # innovation
        S = float((H @ self.P @ H.T).item()) + self.R
        if self.gate is not None and (y * y) / S > self.gate:
            self.n_rejected += 1
            return False
        K = (self.P @ H.T) / S                          # (ns,1)
        self.x = self.x + (K.flatten() * y)
        self.P = (np.eye(self.ns) - K @ H) @ self.P
        self.n_used += 1
        return True

    # -- accessors ------------------------------------------------------------
    @property
    def position(self) -> Optional[Vec3]:
        if self.x is None:
            return None
        p = self._pos3()
        return (float(p[0]), float(p[1]), float(p[2]))

    @property
    def velocity(self) -> Optional[Vec3]:
        if self.x is None:
            return None
        if self.nd == 3:
            return (float(self.x[3]), float(self.x[4]), float(self.x[5]))
        return (float(self.x[2]), 0.0, float(self.x[3]))   # vx, vy=0, vz


def cold_start_position(
    measurements: Sequence[Tuple[float, Vec3, Vec3]],
    seed: Vec3,
    height: Optional[float] = None,
) -> Vec3:
    """Rough initial position from a batch of TDOA measurements (Gauss-Newton).

    `measurements` = [(tdoa, anchor_a, anchor_b), ...]. Avoids seeding the EKF from
    ground truth. With `height` set, the vertical is held fixed and only (x, z) is
    solved — the right choice for near-coplanar ceiling anchors.
    """
    p = np.array([seed[0], height if height is not None else seed[1], seed[2]], dtype=float)
    solve_2d = height is not None
    for _ in range(30):
        rows, res = [], []
        for tdoa, aA, aB in measurements:
            aA = np.asarray(aA, float); aB = np.asarray(aB, float)
            dA = np.linalg.norm(p - aA); dB = np.linalg.norm(p - aB)
            if dA < 1e-6 or dB < 1e-6:
                continue
            g = (p - aB) / dB - (p - aA) / dA
            rows.append([g[0], g[2]] if solve_2d else list(g))
            res.append(tdoa - (dB - dA))
        if len(rows) < (2 if solve_2d else 3):
            break
        J = np.array(rows); r = np.array(res)
        try:
            dp, *_ = np.linalg.lstsq(J, r, rcond=None)
        except np.linalg.LinAlgError:
            break
        if solve_2d:
            p[0] += dp[0]; p[2] += dp[1]
        else:
            p = p + dp
        if np.linalg.norm(dp) < 1e-3:
            break
    return (float(p[0]), float(p[1]), float(p[2]))

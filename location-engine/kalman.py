"""Constant-velocity Kalman filter — smooths the raw multilateration fixes.

The solver gives a jittery position each cycle. This filter fuses that stream over
time under a constant-velocity motion model, producing a smooth track, a velocity
estimate, and a position uncertainty (covariance). It sits between the solver and
the emitted position; the message shape is unchanged (see Project Diary, 20 Jan
and 08 Jul 2026 — "a filter to smooth the jumpy readings … also tracks speed").

State x = [px, pz, vx, vz]  (2D floor plane; height is the fixed assumed height).
Measurement = the solver's (px, pz).
"""
from __future__ import annotations

import numpy as np


class ConstantVelocityKF:
    def __init__(self, sigma_a: float = 2.0, sigma_m: float = 0.4):
        self.sa2 = float(sigma_a) ** 2                 # process (accel) noise power
        self.R = np.eye(2) * float(sigma_m) ** 2       # measurement noise cov
        self.H = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])
        self.x = None                                  # state vector (4,)
        self.P = None                                  # state covariance (4,4)

    def _init(self, px: float, pz: float) -> None:
        self.x = np.array([px, pz, 0.0, 0.0])
        self.P = np.diag([0.5, 0.5, 1.0, 1.0])

    def step(self, px: float, pz: float, dt: float):
        """Advance by dt and fuse measurement (px, pz). Returns (state, P)."""
        if self.x is None:
            self._init(px, pz)
            return self.x, self.P

        dt = float(max(1e-3, min(dt, 1.0)))   # clamp: guard against gaps/negatives
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        dt2, dt3, dt4 = dt * dt, dt ** 3, dt ** 4
        Q = self.sa2 * np.array([
            [dt4 / 4, 0, dt3 / 2, 0],
            [0, dt4 / 4, 0, dt3 / 2],
            [dt3 / 2, 0, dt2, 0],
            [0, dt3 / 2, 0, dt2],
        ])

        # predict
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

        # update with the measured position
        z = np.array([px, pz])
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P
        return self.x, self.P

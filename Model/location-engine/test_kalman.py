"""Tests for the constant-velocity Kalman filter. Run: pytest Model/location-engine -q"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kalman import ConstantVelocityKF  # noqa: E402


def test_smooths_noisy_straight_line():
    """A tag moving in a straight line with noisy fixes: filter beats raw."""
    random.seed(1)
    kf = ConstantVelocityKF(sigma_a=1.0, sigma_m=0.4)
    dt = 0.2
    raw_err_sum = filt_err_sum = 0.0
    n = 200
    for i in range(n):
        tx, tz = i * dt * 1.5, 3.0            # moving +x at 1.5 m/s, constant z
        mx = tx + random.gauss(0, 0.4)        # noisy measurement
        mz = tz + random.gauss(0, 0.4)
        state, _ = kf.step(mx, mz, dt)
        if i > 20:                            # let it converge
            raw_err_sum += math.hypot(mx - tx, mz - tz)
            filt_err_sum += math.hypot(state[0] - tx, state[1] - tz)
    raw_mean = raw_err_sum / (n - 21)
    filt_mean = filt_err_sum / (n - 21)
    assert filt_mean < raw_mean * 0.7, f"filter {filt_mean:.3f} not clearly better than raw {raw_mean:.3f}"


def test_tracks_velocity():
    kf = ConstantVelocityKF(sigma_a=1.0, sigma_m=0.2)
    dt, vx = 0.1, 2.0
    for i in range(150):
        kf.step(i * dt * vx, 0.0, dt)
    assert abs(kf.x[2] - vx) < 0.3, f"vx estimate {kf.x[2]:.2f} != {vx}"
    assert abs(kf.x[3]) < 0.3


def test_first_step_initialises_on_measurement():
    kf = ConstantVelocityKF()
    state, _ = kf.step(5.0, -2.0, 0.2)
    assert abs(state[0] - 5.0) < 1e-9 and abs(state[1] + 2.0) < 1e-9

"""Tests for the walled-off TDOA EKF track. Run: pytest Model/location-engine -q

- A synthetic test proves the EKF + cold-start recover a known point from clean TDOA
  geometry (no dataset needed, always runs).
- A real-data test runs the EKF on one UTIL flight trial and asserts a sane RMSE vs
  Vicon; it is skipped automatically when the dataset has not been extracted.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "anchor-source"))

from ekf_tdoa import TdoaEKF, cold_start_position          # noqa: E402
from dataset_source import default_paths                    # noqa: E402

# 8 anchors on a ~6 m cube-ish spread (like a UTIL constellation)
ANCHORS = [
    (-3.0, -4.0, 0.2), (-2.8, 3.5, 2.6), (3.5, 3.3, 0.2), (3.4, -3.7, 2.7),
    (-3.3, -3.9, 2.7), (3.3, -3.6, 0.2), (3.8, 3.6, 2.6), (-2.7, 3.2, 0.2),
]


def _tdoa(p, a, b):
    da = math.dist(p, a)
    db = math.dist(p, b)
    return db - da


def test_cold_start_recovers_point():
    """Batch Gauss-Newton finds a static point from clean TDOA, without truth seed."""
    true = (1.0, -0.5, 0.9)
    pairs = [(ANCHORS[i], ANCHORS[(i + 1) % len(ANCHORS)]) for i in range(len(ANCHORS))]
    meas = [(_tdoa(true, a, b), a, b) for a, b in pairs]
    centroid = tuple(sum(a[k] for a in ANCHORS) / len(ANCHORS) for k in range(3))
    est = cold_start_position(meas, seed=centroid)
    assert math.dist(est, true) < 0.05


def test_ekf_converges_on_synthetic_stream():
    """EKF tracks a slow-moving point from a noisy TDOA stream to < 10 cm."""
    import random
    random.seed(0)
    pairs = [(ANCHORS[i], ANCHORS[(i + 1) % len(ANCHORS)]) for i in range(len(ANCHORS))]
    ekf = TdoaEKF(sigma_a=1.0, sigma_tdoa=0.05, init_pos=(0.0, 0.0, 1.0))
    dt = 0.02
    errs = []
    for step in range(1500):
        t = step * dt
        true = (0.8 * math.sin(0.2 * t), 0.8 * math.cos(0.2 * t), 1.0)  # gentle circle
        a, b = pairs[step % len(pairs)]
        z = _tdoa(true, a, b) + random.gauss(0, 0.05)
        ekf.predict(dt)
        ekf.update(z, a, b)
        if step > 500 and ekf.position:
            errs.append(math.dist(ekf.position, true))
    assert errs and (sum(errs) / len(errs)) < 0.10


def test_gate_rejects_outliers():
    """An absurd TDOA measurement is rejected by the chi-square gate."""
    ekf = TdoaEKF(init_pos=(0.0, 0.0, 1.0), gate=12.0)
    a, b = ANCHORS[0], ANCHORS[1]
    for _ in range(50):                      # settle on the true value
        ekf.predict(0.02)
        ekf.update(_tdoa((0.0, 0.0, 1.0), a, b), a, b)
    before = ekf.n_rejected
    ekf.predict(0.02)
    accepted = ekf.update(_tdoa((0.0, 0.0, 1.0), a, b) + 50.0, a, b)  # 50 m off
    assert accepted is False and ekf.n_rejected == before + 1


@pytest.mark.parametrize("const,trial,scheme", [("const1", "trial1", "tdoa2")])
def test_ekf_on_real_util_trial(const, trial, scheme):
    csv_path, survey = default_paths(const, trial, scheme)
    if not os.path.isfile(csv_path):
        pytest.skip("UTIL flight-dataset not extracted")
    sys.path.insert(0, HERE)
    from run_tdoa_ekf import run
    res = run(csv_path, survey, sigma_tdoa=0.15, sigma_a=3.0, gate=12.0, verbose=False)
    # real DWM1000 drone data: literature-grade EKF lands well under half a metre
    assert res["rmse_3d_m"] < 0.5
    assert res["used"] > 1000


def test_build_util_site_is_valid_map():
    """The generated twin map matches the uwb.site/1 shape the backend validates."""
    from dataset_source import build_util_site
    anchors = {i: ANCHORS[i] for i in range(len(ANCHORS))}
    site = build_util_site(anchors)
    assert site["schema"] == "uwb.site/1"
    for k in ("floor", "anchors", "walls", "zones", "tags"):
        assert k in site
    assert len(site["anchors"]) == len(ANCHORS) and len(site["tags"]) == 1


def test_stream_frames_track_truth():
    """The twin-facing replay frames carry pos/truth/error and stay accurate."""
    csv_path, survey = default_paths("const1", "trial1", "tdoa2")
    if not os.path.isfile(csv_path):
        pytest.skip("UTIL flight-dataset not extracted")
    sys.path.insert(0, HERE)
    from stream_tdoa_ekf import replay_frames
    frames = list(replay_frames(csv_path, survey, emit_rate=20.0))
    assert len(frames) > 100
    f = frames[len(frames) // 2]
    assert {"pos", "truth", "error", "tagId", "mapKey"} <= set(f)
    good = [fr["error"] for fr in frames[200:] if "error" in fr]
    assert sum(good) / len(good) < 0.5           # mean 3D error under half a metre

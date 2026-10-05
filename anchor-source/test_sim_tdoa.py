"""Tests for the learned generative TDOA simulator. Run: pytest Model -q

Covers: the trainer's mixture fit, the simulator's learned noise level, geometry-aware
NLOS (metal wall biases a link), and an end-to-end sim -> EKF accuracy check. All run
without the dataset except the noted skip.
"""
from __future__ import annotations

import math
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "shared"))
sys.path.insert(0, os.path.join(HERE, "..", "location-engine"))
sys.path.insert(0, os.path.join(HERE, "..", "calibration"))

from sim_tdoa import TdoaSimulator                       # noqa: E402

MODEL = {"sigma_inlier_m": 0.10, "sigma_outlier_m": 0.50, "p_outlier": 0.10, "bias_m": 0.0}


def _site(walls=None, materials=None):
    return {
        "schema": "uwb.site/1",
        "floor": {"id": "f", "sizeX": 20, "sizeZ": 20, "ceilingHeight": 4},
        "anchors": [
            {"id": "A0", "x": -8, "y": 4, "z": -8}, {"id": "A1", "x": 8, "y": 4, "z": -8},
            {"id": "A2", "x": 8, "y": 4, "z": 8}, {"id": "A3", "x": -8, "y": 4, "z": 8},
        ],
        "walls": walls or [],
        "zones": [],
        "tags": [{"id": "T", "name": "T", "y": 0.5, "speed": 1.0,
                  "waypoints": [[-5, -5], [5, 5], [-5, -5]], "pauseAtWaypointSec": 0}],
        "ranging": {"updateRateHz": 10, "materials": materials or {}},
    }


def test_trainer_recovers_mixture():
    """fit_mixture recovers known mixture params from synthetic data."""
    from train_tdoa_model import fit_mixture
    rng = random.Random(0)
    data = []
    for _ in range(20000):
        s = 0.08 if rng.random() > 0.15 else 0.6
        data.append(rng.gauss(0.0, s))
    m = fit_mixture(data)
    assert abs(m["sigma_inlier_m"] - 0.08) < 0.03
    assert 0.08 <= m["p_outlier"] <= 0.25
    assert m["sigma_outlier_m"] > m["sigma_inlier_m"]


def test_sim_inlier_noise_matches_model():
    """The simulated TDOA inlier core has ~ the model's sigma_inlier (LOS site)."""
    sim = TdoaSimulator(_site(), model=MODEL, seed=1)
    anchors = sim.anchors
    res = []
    for i, e in enumerate(sim.events()):
        if i >= 4000:
            break
        true = math.dist(e.truth, anchors[e.id_b]) - math.dist(e.truth, anchors[e.id_a])
        res.append(e.tdoa - true)
    core = [r for r in res if abs(r) < 0.3]                 # drop outlier tail
    std = math.sqrt(sum(r * r for r in core) / len(core))
    assert 0.06 < std < 0.16                                # ~ 0.10


def test_geometry_aware_nlos_biases_blocked_link():
    """A tag->anchor link crossing a metal wall is biased long; LOS is not."""
    materials = {"metal": {"biasMinM": 0.2, "biasMaxM": 0.6, "noiseStdM": 0.06}}
    wall = {"id": "W", "x1": 0, "z1": -10, "x2": 0, "z2": 10, "blocksLos": True,
            "material": "metal"}
    sim = TdoaSimulator(_site(walls=[wall], materials=materials), model=MODEL, seed=2)
    tag = (-5.0, 0.5, 0.0)
    los_r, los_boost, los_blocked = sim._link(tag, (-8.0, 4.0, 0.0))   # same side, LOS
    nlos_r, nlos_boost, nlos_blocked = sim._link(tag, (8.0, 4.0, 0.0))  # crosses wall
    assert not los_blocked and los_boost == 0.0
    assert nlos_blocked and nlos_boost > 0.0
    true_nlos = math.dist(tag, (8.0, 4.0, 0.0))
    assert nlos_r > true_nlos + 0.15                       # positive excess bias added


def test_sim_ekf_recovers_trajectory():
    """End-to-end: generative sim -> 2D EKF tracks the tag to a sane RMSE (open site)."""
    from run_tdoa_sim import run
    res = run(_site(), seconds=30, seed=0, sigma_tdoa=0.15, sigma_a=3.0, gate=12.0,
              verbose=False)
    assert res["rmse_2d_m"] < 0.6
    assert res["used"] > 500

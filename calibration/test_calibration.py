"""Validation: the simulator now reproduces the UTIL-calibrated statistics.

Run:  pytest Model/calibration -q

These tests close the loop — they confirm that after calibration the *simulated*
readings carry the same LOS noise level and positive-only NLOS bias that were
measured on the real UTIL hardware, not the old guessed values.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "shared"))
sys.path.insert(0, os.path.join(HERE, "..", "anchor-source"))

from site_config import load_site          # noqa: E402
from sim_anchors import SimAnchorSource     # noqa: E402

SITE = os.path.join(HERE, "..", "config", "site.json")


def _collect(n_cycles: int = 400):
    """Return (los_residuals, nlos_residuals) of measured-minus-truth range error."""
    site = load_site(SITE)
    anchors = {a["id"]: a for a in site["anchors"]}
    src = SimAnchorSource(site)
    gen = src.cycles()
    los, nlos = [], []
    for _ in range(n_cycles):
        reading, truth = next(gen)
        p = truth["pos"]
        for ar in reading.ranges:
            a = anchors[ar.anchor_id]
            true_r = math.sqrt((p["x"] - a["x"]) ** 2 + (p["y"] - a["y"]) ** 2 + (p["z"] - a["z"]) ** 2)
            # remove the constant antenna-delay bias (calibration would cancel it)
            resid = ar.range_m - true_r - float(a.get("antennaDelayBiasM", 0.0))
            (nlos if ar.nlos else los).append(resid)
    return los, nlos


def _std(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def test_los_noise_matches_calibration():
    """LOS range noise std should track the UTIL-calibrated losNoiseStdM (~0.054 m)."""
    site = load_site(SITE)
    target = site["ranging"]["losNoiseStdM"]
    los, _ = _collect()
    assert len(los) > 500
    s = _std(los)
    # generous band: the sim draws Gaussian(0, target); confirm the calibrated
    # level is reproduced and we are nowhere near the old guessed 0.08.
    assert 0.6 * target <= s <= 1.5 * target, f"LOS std {s:.3f} vs target {target:.3f}"


def test_nlos_bias_is_positive_and_bounded():
    """NLOS ranges are biased LONG (positive), within the calibrated bias envelope."""
    site = load_site(SITE)
    r = site["ranging"]
    _, nlos = _collect()
    if len(nlos) < 50:
        pytest.skip("not enough NLOS samples in this geometry")
    mean_bias = sum(nlos) / len(nlos)
    assert mean_bias > 0, "blocked paths must be reported longer, not shorter"
    # mean should sit inside the calibrated excess-bias envelope (plus noise slack)
    assert mean_bias <= r["nlosBiasMaxM"] * 1.5 + r["nlosNoiseStdM"]


def test_calibration_provenance_recorded():
    """site.json must declare it was calibrated from real data, not guessed."""
    site = load_site(SITE)
    assert site["ranging"]["provenance"].startswith("calibrated:UTIL")


def _mean_nlos_bias_for(material: str, n: int = 3000) -> float:
    """Mean measured-minus-true range error for a path blocked by one `material` wall."""
    ranging = load_site(SITE)["ranging"]
    assert material in ranging.get("materials", {}), "per-material table missing"
    site = {
        "floor": {"id": "f"},
        "anchors": [{"id": "A", "x": 10.0, "y": 4.0, "z": 0.0, "antennaDelayBiasM": 0.0}],
        # one wall segment across the tag->anchor line at x=0
        "walls": [{"id": "W", "x1": 0.0, "z1": -5.0, "x2": 0.0, "z2": 5.0,
                   "blocksLos": True, "material": material}],
        "zones": [], "tags": [], "ranging": ranging,
    }
    src = SimAnchorSource(site)
    anchor = site["anchors"][0]
    true_r = math.sqrt((-10.0 - 10.0) ** 2 + (0.5 - 4.0) ** 2 + 0.0 ** 2)
    errs = []
    for _ in range(n):
        ar = src._range_reading(anchor, -10.0, 0.5, 0.0)  # tag at (-10, 0.5, 0)
        assert ar.nlos, "geometry should be NLOS (path crosses the wall)"
        errs.append(ar.range_m - true_r)
    return sum(errs) / len(errs)


def test_material_bias_ordering():
    """Metal racking must bias ranges more than wood, and wood more than light."""
    metal = _mean_nlos_bias_for("metal")
    wood = _mean_nlos_bias_for("wood")
    light = _mean_nlos_bias_for("light")
    assert metal > wood > light > 0, f"expected metal>wood>light>0, got {metal:.3f},{wood:.3f},{light:.3f}"

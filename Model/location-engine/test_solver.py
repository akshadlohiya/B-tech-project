"""Tests for the multilateration solver. Run:  pytest Model/location-engine -q"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solver import solve_position, nlos_weight  # noqa: E402

# Four ceiling anchors at the room corners, 4.6 m up.
ANCHORS = [(-14, 4.6, -14), (14, 4.6, -14), (-14, 4.6, 14), (14, 4.6, 14)]
HEIGHT = 0.5


def slant(anchor, x, z, y=HEIGHT):
    return math.sqrt((x - anchor[0]) ** 2 + (y - anchor[1]) ** 2 + (z - anchor[2]) ** 2)


def test_recovers_known_point_cleanly():
    tx, tz = 3.0, -5.0
    ranges = [slant(a, tx, tz) for a in ANCHORS]
    est = solve_position(ANCHORS, ranges, assumed_height=HEIGHT)
    assert est is not None
    err = math.hypot(est["x"] - tx, est["z"] - tz)
    assert err < 0.01, f"clean recovery error {err:.3f} m too large"


def test_returns_none_when_underdetermined():
    assert solve_position(ANCHORS[:2], [10.0, 12.0]) is None


def test_nlos_weight_downweights_wide_gap():
    los = nlos_weight(-80.0, -83.0)     # 3 dB gap
    nlos = nlos_weight(-92.0, -105.0)   # 13 dB gap
    assert los > 0.9
    assert nlos < los
    assert 0 < nlos < 1


def test_downweighting_beats_trusting_a_biased_anchor():
    """A single NLOS anchor biased long should hurt less when down-weighted."""
    tx, tz = -6.0, 8.0
    clean = [slant(a, tx, tz) for a in ANCHORS]
    biased = list(clean)
    biased[0] += 1.5  # anchor 0 blocked -> reads 1.5 m long

    weights = [nlos_weight(-92, -105)] + [nlos_weight(-80, -83)] * 3  # A0 = NLOS

    est_trust = solve_position(ANCHORS, biased, assumed_height=HEIGHT)
    est_weighted = solve_position(ANCHORS, biased, weights=weights, assumed_height=HEIGHT)
    err_trust = math.hypot(est_trust["x"] - tx, est_trust["z"] - tz)
    err_weighted = math.hypot(est_weighted["x"] - tx, est_weighted["z"] - tz)
    assert err_weighted < err_trust, f"weighted {err_weighted:.2f} !< trusted {err_trust:.2f}"

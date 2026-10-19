"""Tests for the standalone AI module. Run from ai-module/:  python -m pytest -q"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uwb_ai.nlos_model import MIN_WEIGHT, NlosBiasModel, bias_to_weight, make_estimator  # noqa: E402
from uwb_ai.predict import predict_ahead  # noqa: E402
from uwb_ai.util_loader import DEFAULT_ROOT, load_link_samples, segment_blocked  # noqa: E402
from uwb_ai.zones import ZoneMonitor  # noqa: E402

SITE = json.loads((ROOT.parent / "config" / "site.json").read_text())
MODEL_PATH = ROOT / "models" / "nlos_bias_pd.joblib"
needs_data = pytest.mark.skipif(not DEFAULT_ROOT.exists(), reason="UTIL dataset not extracted")
needs_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="run python -m uwb_ai.train_nlos first")


# ---------------------------------------------------------------- geometry
BOX = np.array([[-0.5, -0.5, 1.0], [0.5, -0.5, 1.0], [0.5, 0.5, 1.0], [-0.5, 0.5, 1.0]])

def test_segment_through_box_is_blocked():
    assert segment_blocked(np.array([-2, 0, 0.6]), np.array([2, 0, 0.6]), BOX)

def test_segment_beside_box_is_clear():
    assert not segment_blocked(np.array([-2, 1, 0.6]), np.array([2, 1, 0.6]), BOX)

def test_segment_above_box_is_clear():
    assert not segment_blocked(np.array([-2, 0, 1.5]), np.array([2, 0, 1.5]), BOX)


# ---------------------------------------------------------------- dataset
@pytest.fixture(scope="module")
def samples():
    return load_link_samples()

@needs_data
def test_loader_labels_are_consistent(samples):
    assert len(samples) > 100_000
    # every blocked link carries an obstacle material; every clear link is "none"
    assert set(samples.material[samples.nlos == 1]) - {"none"} == set(samples.material[samples.nlos == 1])
    assert set(samples.material[samples.nlos == 0]) == {"none"}
    assert np.all(samples.bias[samples.nlos == 0] == 0)

@needs_data
def test_metal_biases_but_foam_does_not(samples):
    assert samples.bias[samples.material == "metal"].mean() > 0.15
    assert abs(samples.bias[samples.material == "foam"].mean()) < 0.05

@needs_data
def test_range_would_leak(samples):
    """Guard for the leakage found during development: if NLOS links ever stop
    sharing one distance, range could become a legitimate feature."""
    assert len(np.unique(np.round(samples.distance[samples.nlos == 1], 2))) == 1


# ---------------------------------------------------------------- model
def _toy_model():
    rng = np.random.default_rng(0)
    pd_ = np.concatenate([rng.normal(12, 1.5, 3000), rng.normal(23, 2, 1000)])
    bias = np.concatenate([np.zeros(3000), rng.normal(0.3, 0.05, 1000)])
    return NlosBiasModel("pd", make_estimator()).fit(pd_[:, None], bias)

def test_model_learns_bias_and_never_negative():
    m = _toy_model()
    assert m.bias(-80.0, -103.0) > 0.2       # 23 dB gap -> NLOS-like
    assert m.bias(-80.0, -92.0) < 0.05       # 12 dB gap -> LOS-like
    assert np.all(m.predict(np.linspace(0, 40, 50)[:, None]) >= 0)

def test_correct_shortens_range_and_lowers_weight():
    m = _toy_model()
    r, w = m.correct(5.0, -80.0, -103.0)
    assert r < 5.0 and w < 0.5
    r, w = m.correct(5.0, -80.0, -92.0)
    assert r == pytest.approx(5.0, abs=0.05) and w > 0.8

def test_weight_is_monotonic_with_floor():
    w = bias_to_weight(np.linspace(0, 2, 50))
    assert w[0] == 1.0 and np.all(np.diff(w) <= 0) and w.min() == MIN_WEIGHT

def test_save_load_roundtrip(tmp_path):
    m = _toy_model()
    m.save(tmp_path / "m.joblib")
    m2 = NlosBiasModel.load(tmp_path / "m.joblib")
    assert m2.bias(-80, -103) == m.bias(-80, -103)

def test_snr_feature_set_requires_snr():
    m = NlosBiasModel("pd_snr", make_estimator()).fit(np.array([[10, 100], [20, 20]] * 50), np.array([0, 0.3] * 50))
    with pytest.raises(ValueError):
        m.bias(-80, -90)
    assert m.bias(-80, -90, snr=100) >= 0

@needs_model
def test_trained_model_on_dw1000_like_values():
    m = NlosBiasModel.load(MODEL_PATH)
    assert m.bias(-80.0, -103.5) > 0.1    # metal-like gap
    assert m.bias(-80.0, -92.0) < 0.06    # typical LOS gap


# ---------------------------------------------------------------- zones
def test_zone_lookup_matches_site():
    zm = ZoneMonitor(SITE)
    z = SITE["zones"][0]
    assert zm.zone_at((z["xmin"] + z["xmax"]) / 2, (z["zmin"] + z["zmax"]) / 2) == z["id"]

def test_outside_allowed_fires_once_then_clears():
    tag = SITE["tags"][0]
    zm = ZoneMonitor(SITE)
    allowed = next(z for z in SITE["zones"] if z["id"] in tag["allowedZones"])
    banned = next((z for z in SITE["zones"] if z["id"] not in tag["allowedZones"]), None)
    if banned is None:
        pytest.skip("site has no zone outside T1's allow-list")
    cx = lambda z: ((z["xmin"] + z["xmax"]) / 2, (z["zmin"] + z["zmax"]) / 2)
    assert zm.update(tag["id"], *cx(allowed), t=0) == []
    a = zm.update(tag["id"], *cx(banned), t=1)
    assert len(a) == 1 and a[0].kind == "outside_allowed" and a[0].zone == banned["id"]
    assert zm.update(tag["id"], *cx(banned), t=2) == []        # no repeat
    assert zm.update(tag["id"], *cx(allowed), t=3) == []        # back inside clears
    assert len(zm.update(tag["id"], *cx(banned), t=4)) == 1     # fires again

def test_stale_alert():
    zm = ZoneMonitor(SITE, stale_after_s=5)
    zm.update("T9", 0, 0, t=0)
    assert zm.check_stale(3) == []
    assert [a.kind for a in zm.check_stale(6)] == ["stale"]
    assert zm.check_stale(7) == []


# ---------------------------------------------------------------- prediction
def test_predict_constant_velocity():
    p, r = predict_ahead([1, 2], [0.5, -1], 2.0)
    assert np.allclose(p, [2, 0]) and r is None

def test_predict_uncertainty_grows_with_horizon():
    cov = np.eye(4) * 0.01
    _, r1 = predict_ahead([0, 0], [1, 0], 0.5, cov)
    _, r2 = predict_ahead([0, 0], [1, 0], 2.0, cov)
    assert r2 > r1 > 0

def test_predict_clamps_to_floor():
    p, _ = predict_ahead([14, 0], [5, 0], 2.0, bounds=(-15, 15, -15, 15))
    assert p[0] == 15

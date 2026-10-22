"""Tests for the AI integration in the location engine. Run:  pytest location-engine -q"""
import copy
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nlos_ai                                    # noqa: E402
from engine import LocationEngine                 # noqa: E402
from run_nlos_bench import evaluate, sim_stream   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SITE = json.loads((ROOT / "config" / "site.json").read_text())
needs_model = pytest.mark.skipif(nlos_ai.load_learned_nlos(3.0)[0] is None,
                                 reason="learned model or scikit-learn unavailable")


def site_with(**ranging):
    s = copy.deepcopy(SITE)
    s["ranging"].update(ranging)
    return s


def reading(tag="T1", gaps=(3, 3, 3, 3, 3), ranges=None, t=100.0):
    ranges = ranges or [10.0] * len(gaps)
    return {"tagId": tag, "t": t, "ranges": [
        {"anchorId": a["id"], "range": r, "rxPower": -80.0, "fpPower": -80.0 - g, "valid": True}
        for a, r, g in zip(SITE["anchors"], ranges, gaps)]}


# ---------------------------------------------------------------- learned model
@needs_model
def test_gaps_are_aligned_to_the_model_baseline():
    m, _ = nlos_ai.load_learned_nlos(3.0)
    assert m.shift_db == pytest.approx(m.model_los_gap_db - 3.0)
    assert m.bias(3.0) < 0.05          # site LOS gap -> ~no correction
    assert m.bias(13.0) > 0.15         # site NLOS gap (+10 dB) -> metal-like bias

@needs_model
def test_bias_is_the_model_prediction_on_shifted_gaps():
    from uwb_ai.nlos_model import NlosBiasModel
    m, _ = nlos_ai.load_learned_nlos(3.0)
    raw = NlosBiasModel.load(nlos_ai.DEFAULT_MODEL_PATH)
    g = np.random.default_rng(0).uniform(-10, 40, 500)
    assert np.array_equal(m.bias(g), raw.predict((g + m.shift_db)[:, None]))

def test_missing_model_falls_back_without_raising(tmp_path):
    m, why = nlos_ai.load_learned_nlos(3.0, tmp_path / "nope.joblib")
    assert m is None and "not found" in why


# ---------------------------------------------------------------- engine modes
@needs_model
def test_engine_uses_ai_by_default_and_rule_on_request():
    assert LocationEngine(SITE).nlos_method == "ai"
    s = copy.deepcopy(SITE)
    s["ranging"].pop("nlosModel", None)          # maps saved before the AI existed
    assert LocationEngine(s).nlos_method == "ai"
    assert LocationEngine(site_with(nlosModel="rule")).nlos_method == "rule"

def test_engine_falls_back_to_rule_when_model_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(nlos_ai, "DEFAULT_MODEL_PATH", tmp_path / "nope.joblib")
    eng = LocationEngine(SITE)
    assert eng.nlos_method == "rule" and "fallback" in eng.nlos_note
    assert eng.estimate(reading(), None)["nlos"]["method"] == "rule"

@needs_model
def test_ai_shortens_only_wide_gap_ranges():
    out = LocationEngine(SITE).estimate(reading(gaps=(3, 3, 13, 3, 3)), None)
    b = out["nlos"]["bias"]
    blocked = SITE["anchors"][2]["id"]
    assert b[blocked] > 0.15
    assert all(v < 0.05 for k, v in b.items() if k != blocked)

@needs_model
def test_unusable_power_reading_uses_rule_for_that_cycle():
    r = reading()
    r["ranges"][0]["fpPower"] = float("nan")
    eng = LocationEngine(site_with(nlosModel="ai"))
    eng.learned.correct = lambda *_: pytest.fail("AI must not see NaN gaps")
    out = eng.estimate(r, None)
    assert out["nlos"]["method"] == "rule" and "bias" not in out["nlos"]

def test_existing_payload_fields_are_unchanged():
    out = LocationEngine(SITE).estimate(reading(), {"truth": {"x": 0.0, "z": 0.0}})
    for k in ("tagId", "name", "battery", "floorId", "pos", "raw", "vel", "cov", "zone",
              "residual", "nAnchors", "t", "truth", "error", "rawError"):
        assert k in out
    assert set(out["pos"]) == {"x", "y", "z"}


# ---------------------------------------------------------------- end-to-end accuracy
@needs_model
def test_ai_beats_rule_on_the_site():
    stream = sim_stream(SITE, 1500, seed=0)
    rule, ai = evaluate(SITE, stream, "rule"), evaluate(SITE, stream, "ai")
    assert ai["method"] == "ai" and rule["method"] == "rule"
    assert ai["mean_cm"] < 0.7 * rule["mean_cm"]
    assert ai["p90_cm"] < rule["p90_cm"]

@needs_model
def test_ai_does_not_hurt_line_of_sight_tracking():
    s = copy.deepcopy(SITE)
    s["walls"] = []
    stream = sim_stream(s, 1500, seed=0)
    assert evaluate(s, stream, "ai")["mean_cm"] <= evaluate(s, stream, "rule")["mean_cm"] + 0.5

@needs_model
def test_kalman_still_smooths_ai_fixes():
    s = copy.deepcopy(SITE)
    s["walls"] = []
    stream = sim_stream(s, 1500, seed=0)
    eng = LocationEngine(s)
    steps = {"raw": [], "pos": []}
    prev = {}
    for rd, truth in stream:
        out = eng.estimate(rd, truth)
        if out is None:
            continue
        if out["tagId"] in prev:
            p = prev[out["tagId"]]
            steps["raw"].append(math.hypot(out["raw"]["x"] - p["raw"]["x"], out["raw"]["z"] - p["raw"]["z"]))
            steps["pos"].append(math.hypot(out["pos"]["x"] - p["pos"]["x"], out["pos"]["z"] - p["pos"]["z"]))
        prev[out["tagId"]] = out
    assert np.std(steps["pos"]) < np.std(steps["raw"])   # filtered track jitters less


# ---------------------------------------------------------------- alerts + ghost
def zone_site():
    s = copy.deepcopy(SITE)
    s["zones"] = [{"id": "OK", "xmin": -20, "xmax": 0, "zmin": -20, "zmax": 20},
                  {"id": "NO", "xmin": 0, "xmax": 20, "zmin": -20, "zmax": 20}]
    s["tags"][0]["allowedZones"] = ["OK"]
    return s

def ranges_to(site, x, z):
    h = site["ranging"]["assumedTagHeightM"]
    return [math.sqrt((a["x"] - x) ** 2 + (a["y"] - h) ** 2 + (a["z"] - z) ** 2) for a in site["anchors"]]

def test_engine_raises_geofence_alert_once():
    s = zone_site()
    eng = LocationEngine(s)
    tag = s["tags"][0]["id"]
    assert eng.estimate(reading(tag, ranges=ranges_to(s, -5, 0), t=1), None)["alerts"] == []
    kinds = []
    for i in range(30):   # walk into the banned zone; the Kalman track crosses x=0 on the way
        out = eng.estimate(reading(tag, ranges=ranges_to(s, 5, 0), t=1.2 + 0.2 * i), None)
        kinds += [(a["kind"], a["zone"], a["tagId"]) for a in out["alerts"]]
    assert kinds == [("outside_allowed", "NO", tag)]

def test_engine_reports_stale_tags():
    eng = LocationEngine(SITE)
    eng.estimate(reading(t=10.0), None)
    assert eng.check_stale(12.0) == []
    stale = eng.check_stale(20.0)
    assert [a["kind"] for a in stale] == ["stale"] and stale[0]["tagId"] == "T1"

def test_ghost_follows_kalman_velocity():
    s = copy.deepcopy(SITE)
    eng = LocationEngine(s)
    out = None
    for i in range(40):   # constant 1 m/s east
        x = -5 + 0.2 * i
        out = eng.estimate(reading(ranges=ranges_to(s, x, 0), t=0.2 * i), None)
    g, p, v = out["ghost"], out["pos"], out["vel"]
    assert g["horizonS"] == 1.0 and g["r"] > 0
    assert g["x"] == pytest.approx(p["x"] + v["vx"], abs=0.01)
    assert v["vx"] == pytest.approx(1.0, abs=0.15)

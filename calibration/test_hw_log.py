"""Tests for the hardware log analysis. Run:  pytest calibration/test_hw_log.py -q"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_log  # noqa: E402

ANCHORS = {"A1": (-3.0, 2.4, -3.0), "A2": (3.0, 2.4, -3.0), "A3": (0.0, 2.4, 3.0)}


def rng(label, anchor, r, rx=-80.0, fp=-83.0):
    return {"label": label, "kind": "range", "anchor": anchor, "range": str(r), "rx": str(rx), "fp": str(fp)}


def pos(label, x, z):
    return {"label": label, "kind": "pos", "x": str(x), "z": str(z)}


def test_baseline_is_median_gap_per_anchor():
    rows = [rng("P1", "A1", 4, rx=-80, fp=-89), rng("P1", "A1", 4, rx=-80, fp=-88),
            rng("P1", "A1", 4, rx=-80, fp=-99),   # one NLOS outlier does not move the median
            rng("P1", "A2", 4, rx=-82, fp=-91), pos("P1", 0, 0)]
    b = hw_log.baseline(rows)
    assert b["A1"] == pytest.approx(9.0)
    assert b["A2"] == pytest.approx(9.0)
    assert b["all"] == pytest.approx(9.0)


def test_range_offset_is_measured_minus_true_distance():
    at = (0.0, 0.6, 0.0)
    true = {a: math.dist(at, p) for a, p in ANCHORS.items()}
    rows = [rng("P1", a, true[a] + off) for a, off in (("A1", 0.10), ("A1", 0.12), ("A2", -0.05), ("A3", 0.0))]
    rows.append(rng("P2", "A1", 99.0))            # other point: ignored
    res = hw_log.range_offsets(rows, "P1", at, ANCHORS)
    assert res["A1"]["n"] == 2
    assert res["A1"]["offset_m"] == pytest.approx(0.11)
    assert res["A2"]["offset_m"] == pytest.approx(-0.05)
    assert res["A3"]["offset_m"] == pytest.approx(0.0, abs=1e-9)


def test_accuracy_per_point_and_overall():
    rows = [pos("P1", 0.03, 0.04), pos("P1", 0.0, 0.0), pos("P2", 1.0, 1.1), rng("P1", "A1", 5)]
    res = hw_log.accuracy(rows, {"P1": (0.0, 0.0), "P2": (1.0, 1.0), "P3": (2.0, 2.0)})
    assert res["n"] == 3
    assert res["points"]["P1"]["mean_m"] == pytest.approx(0.025)
    assert res["points"]["P2"]["max_m"] == pytest.approx(0.1)
    assert "P3" not in res["points"]               # never recorded
    assert res["rmse_m"] == pytest.approx(math.sqrt((0.05 ** 2 + 0 + 0.1 ** 2) / 3))


def test_record_and_cli_round_trip(tmp_path, monkeypatch, capsys):
    out = tmp_path / "run.csv"
    rows = [rng("P1", "A1", 4.2, rx=-80, fp=-86), pos("P1", 0.1, 0.0)]
    for r in rows:
        r.setdefault("t", "0")
        r.setdefault("tag", "T1")
    import csv
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, hw_log.FIELDS)
        w.writeheader()
        w.writerows(rows)
    hw_log.main(["baseline", str(out)])
    assert "fpToRxDeltaLosDbm = -6.0" in capsys.readouterr().out
    pts = tmp_path / "points.csv"
    pts.write_text("label,x,z\nP1,0,0\n")
    hw_log.main(["accuracy", str(out), "--points", str(pts), "--plot", str(tmp_path / "cdf.png")])
    assert "RMSE 10.0 cm" in capsys.readouterr().out
    assert (tmp_path / "cdf.png").exists()

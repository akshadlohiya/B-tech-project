"""Calibrate the simulator's ranging/noise model from the real UTIL dataset.

Why this exists
---------------
`SimAnchorSource` invents its noise from the `ranging` block of `config/site.json`,
and every value there was tagged *guessed*. This script replaces those guesses with
numbers **measured on real UWB hardware** (UTIL — Zhao et al., UofT DSL, IJRR 2024),
so the simulation lies the way real UWB actually lies. Because the sim reads its
model from config, calibration is a *data change, not a code change* (sim_anchors.py
docstring).

What the dataset gives us
-------------------------
UTIL's identification-dataset places a tag and two anchors at surveyed positions and
logs, per sample, the time-difference-of-arrival `tdoa12` (in METRES) plus power
diagnostics. The geometric truth is `true_tdoa = d(tag,an2) - d(tag,an1)`, so the
measurement error is `tdoa12 - true_tdoa`. A TDOA is a difference of two independent
noisy ranges, hence:

        var(tdoa) = 2 * var(range)   =>   sigma_range = sigma_tdoa / sqrt(2)

- **LOS trials** (distTest + angleTest) give the clean line-of-sight range noise.
- **NLOS trials** (an obstruction of a given material between anchor and tag) give
  the extra bias (a blocked path is reported LONGER) and the extra noise. UTIL logs
  six materials; the RF-transparent ones (cardboard/foam/plastic) barely differ from
  LOS, while metal / wooden shelving — the warehouse-relevant obstructions — carry
  the real NLOS penalty. We calibrate the NLOS model from the *obstructing* set.

Cross-radio caveat
------------------
UTIL uses Decawave DWM1000; our nodes are DW3000 (same family, not identical). The
*range-error statistics in metres transfer* (they are link-physics, not chip units);
UTIL's raw `power_dif` register does NOT map cleanly to our dBm power model (light
NLOS even lowers it), so we deliberately do NOT recalibrate the dBm power block here.
The fitted numbers are a calibrated prior; confirm on a few DW3000 traces later.

Usage
-----
    python calibrate_from_util.py                 # analyse + print, no writes
    python calibrate_from_util.py --apply         # also patch config/site.json
    python calibrate_from_util.py --dataset PATH  # point at the dataset root
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import statistics as st
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.normpath(os.path.join(
    HERE, "..", "..", "DOCS", "datasets", "util-uwb-dataset",
    "dataset", "identification-dataset"))
SITE_JSON = os.path.normpath(os.path.join(HERE, "..", "config", "site.json"))

# Materials whose obstruction actually attenuates the first path (warehouse-like:
# metal racking, wooden shelving/cabinets). The RF-transparent set is reported for
# completeness but excluded from the aggregate NLOS penalty fit.
OBSTRUCTING = ["metal", "wooden-shelf", "wooden-cabinet"]
TRANSPARENT = ["cardboard", "foam", "plastic"]

# Warehouse material CLASSES mapped to the UTIL obstruction materials that best
# represent them. Used to emit a per-material physics table so the simulator can
# model that steel racking biases ranges far more than a wooden shelf or a carton.
MATERIAL_CLASSES = {
    "metal": ["metal"],
    "wood": ["wooden-shelf", "wooden-cabinet"],
    "light": ["cardboard", "foam", "plastic"],
}


def read_pose(path: str) -> Dict[str, Tuple[float, float, float]]:
    out: Dict[str, Tuple[float, float, float]] = {}
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) >= 4 and p[0].endswith("_p"):
                out[p[0]] = (float(p[1]), float(p[2]), float(p[3]))
    return out


def _dist(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _trials(pattern: str) -> List[str]:
    return sorted(glob.glob(pattern))


def _trial_errors(data_csv: str, reject: float) -> Optional[List[float]]:
    """TDOA errors (metres) for one trial, or None if geometry is unavailable."""
    folder = os.path.dirname(data_csv)
    poses = glob.glob(os.path.join(folder, "*_pose.txt"))
    if not poses:
        return None
    pose = read_pose(poses[0])
    if not all(k in pose for k in ("an1_p", "an2_p", "tag_p")):
        return None
    true_tdoa = _dist(pose["tag_p"], pose["an2_p"]) - _dist(pose["tag_p"], pose["an1_p"])
    errs: List[float] = []
    with open(data_csv) as f:
        for row in csv.DictReader(f):
            try:
                e = float(row["tdoa12"]) - true_tdoa
            except (ValueError, KeyError):
                continue
            if abs(e) < reject:
                errs.append(e)
    return errs


def _pooled_std(values: List[float]) -> float:
    return st.pstdev(values) if len(values) > 1 else 0.0


def _pct(xs: List[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def _nlos_trial_stats(dataset: str, materials: List[str]) -> Tuple[List[float], List[float]]:
    """For a set of UTIL materials, return (per-trial |bias|, per-trial noise σ_range).

    In a static identification trial the per-trial mean error is the excess-path BIAS
    and the within-trial spread is the random NOISE, so the two are separated here.
    """
    biases: List[float] = []
    noise: List[float] = []
    for mat in materials:
        for csv_path in _trials(os.path.join(dataset, "nlos", "anTag", mat, "*", "*_data.csv")):
            e = _trial_errors(csv_path, reject=3.0)
            if not e or len(e) < 10:
                continue
            biases.append(abs(st.mean(e)))
            noise.append(_pooled_std(e) / math.sqrt(2))
    return biases, noise


def _material_table(dataset: str) -> Dict[str, Dict[str, float]]:
    """Per warehouse-material-class {biasMinM, biasMaxM, noiseStdM} from UTIL."""
    table: Dict[str, Dict[str, float]] = {}
    for cls, mats in MATERIAL_CLASSES.items():
        biases, noise = _nlos_trial_stats(dataset, mats)
        if not biases:
            continue
        table[cls] = {
            "biasMinM": round(_pct(biases, 0.10), 3),
            "biasMaxM": round(_pct(biases, 0.90), 3),
            "noiseStdM": round(max(_pct(noise, 0.75), 0.03), 3),
        }
    return table


def analyse(dataset: str) -> Dict[str, float]:
    # ---- LOS: pool distTest + angleTest -------------------------------------
    los_errs: List[float] = []
    for grp in ("los/distTest", "los/angleTest"):
        for csv_path in _trials(os.path.join(dataset, grp, "*", "*_data.csv")):
            e = _trial_errors(csv_path, reject=0.5)
            if e:
                los_errs += e
    sigma_tdoa_los = _pooled_std(los_errs)
    sigma_range_los = sigma_tdoa_los / math.sqrt(2)
    los_abs_mean = st.mean(abs(x) for x in los_errs)

    # ---- NLOS (obstructing materials): separate bias from random noise ------
    # In an identification trial the geometry is STATIC, so the per-trial mean error
    # is the excess-path BIAS and the within-trial spread is the random NOISE. The
    # key empirical finding: a blocked path adds a large positive bias but only
    # modestly more jitter, so we calibrate the two independently.
    trial_biases, trial_noise = _nlos_trial_stats(dataset, OBSTRUCTING)

    # p75 across obstructing trials: representative of a worse-than-typical block
    sigma_range_nlos = _pct(trial_noise, 0.75)
    nlos_bias_min = round(_pct(trial_biases, 0.10), 3)
    nlos_bias_max = round(_pct(trial_biases, 0.90), 3)

    return {
        "losNoiseStdM": round(sigma_range_los, 3),
        "nlosNoiseStdM": round(max(sigma_range_nlos, sigma_range_los), 3),
        "nlosBiasMinM": nlos_bias_min,
        "nlosBiasMaxM": nlos_bias_max,
        "materials": _material_table(dataset),
        "_los_abs_mean": round(los_abs_mean, 3),
        "_los_samples": len(los_errs),
        "_nlos_trials": len(trial_biases),
        "_nlos_bias_median": round(st.median(trial_biases), 3) if trial_biases else 0.0,
    }


def apply_to_site(cal: Dict[str, float], site_path: str) -> None:
    with open(site_path) as f:
        site = json.load(f)
    r = site["ranging"]
    for key in ("losNoiseStdM", "nlosNoiseStdM", "nlosBiasMinM", "nlosBiasMaxM"):
        r[key] = cal[key]
    if cal.get("materials"):
        r["materials"] = cal["materials"]
    r["provenance"] = "calibrated:UTIL-IJRR2024"
    r["calibrationNote"] = (
        "Range-noise model calibrated from the UTIL identification-dataset "
        "(DWM1000, LOS + obstructing-material NLOS). sigma_range = sigma_tdoa/sqrt(2). "
        "Power (dBm) block left as a DW3000 abstraction: UTIL power_dif units are "
        "cross-radio and do not map directly (recalibrate on DW3000 hardware)."
    )
    with open(site_path, "w") as f:
        json.dump(site, f, indent=2)
        f.write("\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=DEFAULT_DATASET, help="identification-dataset root")
    ap.add_argument("--site", default=SITE_JSON, help="config/site.json to patch")
    ap.add_argument("--apply", action="store_true", help="write calibrated values into site.json")
    args = ap.parse_args()

    if not os.path.isdir(args.dataset):
        raise SystemExit(f"dataset not found: {args.dataset}\n"
                         "Download via DOCS/datasets/util-uwb-dataset/setupscript.bash")

    cal = analyse(args.dataset)
    print("UTIL calibration (real DWM1000 identification data)")
    print("-" * 56)
    print(f"  LOS  : {cal['_los_samples']:>6} samples | sigma_range = {cal['losNoiseStdM']:.3f} m"
          f" | |err|mean = {cal['_los_abs_mean']:.3f} m")
    print(f"  NLOS : {cal['_nlos_trials']:>6} trials  | sigma_range = {cal['nlosNoiseStdM']:.3f} m"
          f" | excess bias {cal['nlosBiasMinM']:.2f}-{cal['nlosBiasMaxM']:.2f} m"
          f" (median {cal['_nlos_bias_median']:.2f})")
    print()
    print("  site.json ranging  (guessed -> calibrated)")
    guessed = {"losNoiseStdM": 0.08, "nlosNoiseStdM": 0.3, "nlosBiasMinM": 0.25, "nlosBiasMaxM": 1.2}
    for k, was in guessed.items():
        print(f"    {k:<15} {was:>5}  ->  {cal[k]:<6}")

    if cal.get("materials"):
        print("\n  per-material NLOS physics (biasMin-biasMax / noiseStd, metres)")
        for cls, m in cal["materials"].items():
            print(f"    {cls:<7} bias {m['biasMinM']:.3f}-{m['biasMaxM']:.3f}"
                  f"   noise {m['noiseStdM']:.3f}")

    if args.apply:
        apply_to_site(cal, args.site)
        print(f"\n  applied to {args.site}")
    else:
        print("\n  (dry run — pass --apply to write into site.json)")


if __name__ == "__main__":
    main()

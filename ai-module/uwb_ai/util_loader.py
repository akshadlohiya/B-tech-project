"""Load the UTIL identification dataset as labelled per-link samples.

UTIL (Zhao et al., IJRR 2024) records static DWM1000 (DW1000 silicon) trials:
two anchors, one tag, and optionally an obstacle of a known material. Each CSV
row carries, for the tag's reception from anchor k, an SNR value and a power
difference (total RX power minus first-path power, dB) -- the same diagnostic
our firmware reports as rxPower - fpPower.

The dataset does not say which tag-anchor link the obstacle blocks, so we
derive the label from geometry: a link is NLOS when the tag->anchor segment
passes through the obstacle prism given in the trial's pose file.

Not every blockage hurts. Foam, cardboard and plastic barely delay the first
path, while metal and wood add tens of centimetres. Each sample therefore also
carries the measured NLOS bias of its link, recovered from the TDOA error
(anchor 2 is never blocked, so tdoa12 - truth = -bias of the anchor-1 link),
and a `harmful` label: blocked AND bias > HARMFUL_BIAS_M.

Only the tag-side (anTag) and LOS trials are used. anAn trials block the
anchor-anchor link, which our DS-TWR system never uses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
HARMFUL_BIAS_M = 0.05   # ~LOS TDOA noise floor in UTIL; smaller biases are noise
DEFAULT_ROOT = REPO_ROOT / "DOCS" / "datasets" / "util-uwb-dataset" / "dataset" / "identification-dataset"


@dataclass
class Trial:
    name: str          # unique id, e.g. "nlos/anTag/metal/data1"
    material: str      # "none" for LOS trials
    an_p: List[np.ndarray]
    tag_p: np.ndarray
    obstacle: Optional[np.ndarray]   # (4, 3) top vertices; bottom is z = 0
    csv_path: Path


@dataclass
class LinkSamples:
    """Column arrays, one row per (CSV row, anchor) measurement."""
    snr: np.ndarray
    power_dif: np.ndarray
    distance: np.ndarray   # true tag-anchor distance (m) -- do NOT use as a
                           # feature: all UTIL NLOS links sit at 3.94 m
    nlos: np.ndarray       # 0/1 geometric label (path blocked)
    bias: np.ndarray       # measured range bias of the link (m), 0 if unblocked
    harmful: np.ndarray    # 0/1: blocked and bias > HARMFUL_BIAS_M
    group: np.ndarray      # trial index, for leakage-free splits
    material: np.ndarray   # str
    trials: List[str]

    def __len__(self) -> int:
        return len(self.nlos)


def _read_pose(path: Path) -> Dict[str, np.ndarray]:
    out = {}
    for line in path.read_text().splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 4:
            out[parts[0]] = np.array([float(v) for v in parts[1:]])
    return out


def _segments_intersect(p1, p2, q1, q2) -> bool:
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1, d2 = cross(q1, q2, p1), cross(q1, q2, p2)
    d3, d4 = cross(p1, p2, q1), cross(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _point_in_polygon(pt, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a[1] > pt[1]) != (b[1] > pt[1]):
            x = a[0] + (pt[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if pt[0] < x:
                inside = not inside
    return inside


def segment_blocked(a: np.ndarray, b: np.ndarray, obstacle_top: np.ndarray) -> bool:
    """True if segment a-b passes through the vertical prism under `obstacle_top`.

    The prism spans z in [0, top height]. Antennas in UTIL sit below the top of
    every obstacle, so a crossing in plan view is a real blockage; we still
    check the z of the crossing point to stay correct for tall geometry.
    """
    poly = obstacle_top[:, :2]
    # order vertices around the centroid so edges form a simple polygon
    c = poly.mean(axis=0)
    poly = poly[np.argsort(np.arctan2(poly[:, 1] - c[1], poly[:, 0] - c[0]))]
    top = obstacle_top[:, 2].min()
    hits_xy = _point_in_polygon(a[:2], poly) or _point_in_polygon(b[:2], poly) or any(
        _segments_intersect(a[:2], b[:2], poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))
    )
    if not hits_xy:
        return False
    return min(a[2], b[2]) < top


def discover_trials(root: Path = DEFAULT_ROOT) -> List[Trial]:
    trials: List[Trial] = []
    for dirpath, _dirs, files in sorted(os.walk(root)):
        d = Path(dirpath)
        rel = d.relative_to(root).as_posix()
        if "anAn" in rel:
            continue
        csvs = [f for f in files if f.endswith("_data.csv")]
        poses = [f for f in files if f.endswith("_pose.txt")]
        if not csvs or not poses:
            continue
        pose = _read_pose(d / poses[0])
        obs_keys = sorted(k for k in pose if k.startswith("obs_"))
        obstacle = np.stack([pose[k] for k in obs_keys]) if obs_keys else None
        material = rel.split("/")[2] if rel.startswith("nlos/anTag/") else "none"
        trials.append(Trial(
            name=rel, material=material,
            an_p=[pose["an1_p"], pose["an2_p"]], tag_p=pose["tag_p"],
            obstacle=obstacle, csv_path=d / csvs[0],
        ))
    return trials


def load_link_samples(root: Path = DEFAULT_ROOT) -> LinkSamples:
    cols = {k: [] for k in ("snr", "power_dif", "distance", "nlos", "bias", "group", "material")}
    names: List[str] = []
    for gi, tr in enumerate(discover_trials(root)):
        names.append(tr.name)
        data = np.genfromtxt(tr.csv_path, delimiter=",", names=True)
        tdoa12 = np.asarray(data["tdoa12"], dtype=float)
        gt12 = np.linalg.norm(tr.an_p[1] - tr.tag_p) - np.linalg.norm(tr.an_p[0] - tr.tag_p)
        an1_bias = -float(np.median(tdoa12[np.isfinite(tdoa12)] - gt12))
        for k in (1, 2):
            snr = np.asarray(data[f"snr_an{k}"], dtype=float)
            pd_ = np.asarray(data[f"power_dif_an{k}"], dtype=float)
            ok = np.isfinite(snr) & np.isfinite(pd_)
            n = int(ok.sum())
            if n == 0:
                continue
            an = tr.an_p[k - 1]
            blocked = tr.obstacle is not None and segment_blocked(tr.tag_p, an, tr.obstacle)
            cols["snr"].append(snr[ok])
            cols["power_dif"].append(pd_[ok])
            cols["distance"].append(np.full(n, float(np.linalg.norm(an - tr.tag_p))))
            cols["nlos"].append(np.full(n, int(blocked)))
            if blocked and k != 1:
                raise ValueError(f"{tr.name}: bias recovery assumes only anchor 1 is blocked")
            cols["bias"].append(np.full(n, an1_bias if blocked else 0.0))
            cols["group"].append(np.full(n, gi))
            cols["material"].append(np.full(n, tr.material if blocked else "none", dtype=object))
    if not names:
        raise FileNotFoundError(f"No UTIL identification trials found under {root}")
    return LinkSamples(
        snr=np.concatenate(cols["snr"]),
        power_dif=np.concatenate(cols["power_dif"]),
        distance=np.concatenate(cols["distance"]),
        nlos=np.concatenate(cols["nlos"]).astype(int),
        bias=np.concatenate(cols["bias"]),
        harmful=(np.concatenate(cols["nlos"]).astype(bool)
                 & (np.concatenate(cols["bias"]) > HARMFUL_BIAS_M)).astype(int),
        group=np.concatenate(cols["group"]).astype(int),
        material=np.concatenate(cols["material"]),
        trials=names,
    )

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


def segment_blocked(a: np.ndarray, b: np.ndarray, obstacle_top: np.ndarray) -> bool:
    """True if segment a-b passes through the vertical prism under `obstacle_top`.

    The prism spans z in [0, top height] over the (convex) footprint of the top
    vertices. The segment is clipped against every face (Cyrus-Beck), so the
    height is checked where the segment actually crosses the obstacle, and a
    segment that only touches a face or edge does not count as blocked.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    poly = obstacle_top[:, :2]
    # order vertices counter-clockwise around the centroid
    c = poly.mean(axis=0)
    poly = poly[np.argsort(np.arctan2(poly[:, 1] - c[1], poly[:, 0] - c[0]))]
    top = obstacle_top[:, 2].min()
    # inside <=> n . x + k >= 0 for every face (n, k)
    faces = [(np.array([0.0, 0.0, 1.0]), 0.0), (np.array([0.0, 0.0, -1.0]), top)]
    for i in range(len(poly)):
        e = poly[(i + 1) % len(poly)] - poly[i]
        n = np.array([-e[1], e[0], 0.0])           # inward normal of a CCW edge
        faces.append((n, -float(n[:2] @ poly[i])))
    d = b - a
    t0, t1 = 0.0, 1.0
    for n, k in faces:
        num, den = float(n @ a + k), float(n @ d)
        if den == 0.0:
            if num < 0:
                return False
        elif den > 0:
            t0 = max(t0, -num / den)
        else:
            t1 = min(t1, -num / den)
    return t1 - t0 > 1e-9


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

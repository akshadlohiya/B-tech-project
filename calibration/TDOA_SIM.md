# Learned generative TDOA simulator

A simulator that produces **synthetic TDOA measurements for any editable layout** (like
the warehouse) — the same role the UTIL replay plays, but generative and not tied to the
recorded geometry/motion. Its error model is **learned from the real UTIL dataset**, so
the synthetic measurements behave like real UWB TDOA. It feeds the same `TdoaEKF` and the
same 3D twin as the real replay.

## Pipeline

```
UTIL flight data ──train──► tdoa_model.json ──► TdoaSimulator(site) ──► TdoaEKF ──► twin / RMSE
(residuals vs Vicon)        (learned mixture)   (any layout, NLOS)     (per tag)
```

## 1. Training — `train_tdoa_model.py`

For every UTIL TDOA event the geometric truth is known (Vicon pose interpolated to the
TDOA timestamp, minus anchor survey geometry), so the error is
`err = tdoa_meas - (d(tag,B) - d(tag,A))`. Real UWB TDOA is **heavy-tailed** (clean core +
NLOS/multipath tail), so we fit a **zero-mean 2-component Gaussian mixture** by EM across
trials from all four constellations and save `tdoa_model.json`:

| param | learned value |
|---|---|
| `sigma_inlier_m`  | **0.137** |
| `sigma_outlier_m` | **0.316** |
| `p_outlier`       | **0.11** |
| `bias_m`          | +0.003 |

```bash
python Model/calibration/train_tdoa_model.py          # fit + save the model
python Model/calibration/train_tdoa_model.py --dry-run
```

## 2. Generative simulator — `Model/anchor-source/sim_tdoa.py`

`TdoaSimulator(site, model)` yields `TdoaEvent(t, id_a, id_b, tdoa, truth, tag_id)` — the
same contract as `DatasetTdoaSource`, so it drops into the EKF and streamer unchanged.

- **Motion**: reuses `_TagMover` (the range sim's waypoint mover) for each site tag.
- **Pairing**: TDOA2 scheme — anchor[0] is the reference; each cycle emits one event per
  other anchor `a_i` with `tdoa = d(tag, a_i) - d(tag, ref)`.
- **Core noise**: samples the learned mixture (inlier core, occasional wide outlier) + bias.
- **Geometry-aware NLOS**: for each tag→anchor link, `blocking_walls` tests wall occlusion;
  a blocked link gets a POSITIVE material-dependent excess (reusing `ranging.materials`
  from the range calibration) and a raised outlier probability — so passing behind a metal
  rack degrades the TDOA realistically. Open sites fall back to the global mixture.

## 3. Estimation — 2D fixed-height EKF

`TdoaEKF` now has two modes. The warehouse's ceiling anchors are **~coplanar**, so TDOA
cannot observe height; the sim runs the EKF in **2D fixed-height** mode (state `[x,z,vx,vz]`,
height held at the tag's known height) — mirroring how the range solver "solves 2D at an
assumed height". The UTIL drone (anchors at varied heights) still uses full **3D** mode.
Each tag gets its own EKF, cold-started (no ground truth) from a warm-up batch.

## Run it

```bash
# Offline accuracy benchmark (sim has ground truth):
python Model/location-engine/run_tdoa_sim.py                 # warehouse
python Model/location-engine/run_tdoa_sim.py --seconds 60 --seed 1

# Live in the 3D twin (backend + frontend running):
python Model/location-engine/stream_tdoa_ekf.py --source sim --loop --speed 2
#   -> registers "Demo Warehouse (TDOA)"; open  http://localhost:5173/?map=wh-tdoa
```

Runs side-by-side with the range-based `?map=demo` and the real `?map=util` replay.

## Accuracy (generative warehouse)

~**0.5 m horizontal (x,z) RMSE** on the 5 coplanar ceiling anchors with ~11 % outliers and
metal-rack NLOS. Higher than the range pipeline (~0.19 m) — expected: TDOA is a weaker
observation than DS-TWR ranges, and coplanar ceiling anchors are poor TDOA geometry. On the
UTIL drone arena (varied anchor heights, 3D) the same EKF gets ~0.18 m.

## Caveats

- The learned model is **DWM1000** (UTIL); our nodes are DW3000 — treat it as a calibrated
  prior, recalibrate on real DW3000 traces.
- TDOA needs ≥ 3 well-spread anchors; near-coplanar ceiling anchors give **weak height**
  observability (hence the 2D fixed-height mode) — the same constraint noted for the range
  solver. Spread anchors in height to enable full 3D TDOA.

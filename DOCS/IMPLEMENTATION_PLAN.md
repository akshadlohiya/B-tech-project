# UWB RTLS — Real TDOA + Kalman + Digital Twin

## Context

The goal is a real-time indoor location system: UWB **tags** on items, ceiling **anchors**, and a
3D **digital twin** showing live movement. The vision calls for **UWB → TDOA → Kalman filter →
(basic AI)**, minimizing latency and maximizing accuracy.

A working scaffold already exists under `Model/` (backend relay, Python emulator, Three.js twin),
but it **takes a shortcut**: `emulator/pi_emulator.py` computes each tag's *true* position and sends
it straight to the frontend. The measured `distances` are displayed but never used to *solve* for
position. So today there is **no TDOA multilateration, no measurement noise, no Kalman filter, and
no AI** — the "accuracy" is fake because nothing is estimated.

This plan makes the pipeline real: the source emits only noisy per-anchor measurements, a location
engine solves position via TDOA multilateration and smooths it with a Kalman filter, and the twin
visualizes the estimate (with uncertainty and error-vs-truth). The ingest layer is architected so a
real anchor feed replaces the simulator without rewrites ("hardware-ready sim"). Coordinates move
from GPS lat/lon to **local meters**, which is standard and accurate for cm-scale indoor RTLS.

## Target Architecture

```
[ Anchor Source ]        [ Location Engine ]            [ Backend ]      [ Frontend Twin ]
 sim OR real      raw     TDOA multilateration  estimate  Socket.io   pos/vel/cov  Three.js
 anchors (Pi)  ───────►   → Kalman filter       ───────►  relay      ──────────►  digital twin
              per-anchor  → (AI: zones/predict)                                    + uncertainty
              TOA/ranges                                                           + trails + error
```

- **Anchor Source** and **Location Engine** are separate Python modules behind an `AnchorSource`
  interface. Default: run as **one process** (source feeds engine via an in-process queue) to keep
  the current 3-terminal workflow. A documented seam allows splitting the source onto a real gateway
  (Pi reading DW3000/DWM1000 timestamps) later — swap `SimAnchorSource` for `HardwareAnchorSource`,
  no engine changes.
- **Backend** stays a thin relay (minimal change).
- **Frontend** becomes a pure visualizer of *estimated* state.

## Hardware reality (locks the measurement model)

The chosen hardware — **Makerfabs MaUWB_DW3000** — runs firmware that performs **DS-TWR ranging**
and reports a **distance per anchor plus signal-power diagnostics** (received power, first-path
power). It does *not* expose raw TDOA time-of-arrival timestamps, and DS-TWR cancels clock drift so
no anchor time-sync is needed. To keep hardware integration near-zero, the pipeline is **range-based
multilateration**, and the simulator emits exactly what the module emits.

> **⭐ CURRENT IMPORTANT POINT — data-driven NLOS error model (revised after council review).**
> The high-value, transferable use of real UWB data is **NLOS / measurement-noise calibration**, not
> a second estimator. Our DW3000 firmware *does* report power diagnostics (received power, first-path
> power) per range, so the seam this plugs into already exists. Plan of record:
> 1. **Fit a data-driven noise model** — variance (and NLOS likelihood) as a function of the
>    power-difference diagnostic — on UTIL's labelled LOS/NLOS data with mm ground truth. Use it to
>    (a) make the **simulator's** injected noise behave like real UWB, and (b) replace the hand-tuned
>    `nlos_weight` constants in our range-based WLS solver with a *fitted* curve.
> 2. Report one honest, defensible number: "NLOS weighting calibrated on real UWB error reduced
>    RMSE by X%." Frame UTIL as **real-data validation of the estimator + NLOS model**, *not* "our
>    system runs on this data."
>
> **Raw-TDOA + EKF is DEMOTED back to an optional, walled-off track** (was over-promoted). Our
> hardware emits DS-TWR ranges, and a constant-velocity Kalman filter on ranges is adequate for slow
> warehouse motion — an EKF only earns its place for the raw-TDOA observation model, which this
> hardware cannot produce. If built at all, the TDOA-EKF is a **separate UTIL-only module** kept off
> the critical path, purely to claim "implemented + validated an EKF on real hardware-grade data."
>
> **Two caveats the calibration must respect (council blind-spots):**
> - **Cross-radio gap:** UTIL is DWM1000; our nodes are DW3000. Power-difference registers, antenna,
>   and bandwidth differ, so the fitted curve is a *starting prior that needs DW3000 recalibration*,
>   not a direct transplant. Trajectory/end-to-end results do **not** transfer (drone 3D motion ≠
>   slow ceiling-anchor warehouse); never claim end-to-end equivalence.
> - **No in-situ ground truth:** without a Vicon-equivalent in the warehouse the ported model can't be
>   validated on the real rig. Collect a handful of self-measured, NLOS-labelled DS-TWR traces from
>   our own DW3000 (tape-measured truth) just to confirm the transfer direction holds.

## Data Contracts

Raw measurement (source → engine) — per-anchor **range + power diagnostics** (schema `uwb.reading/1`):
```json
{ "schema": "uwb.reading/1", "tagId": "T1", "seq": 1423, "source": "sim", "t": 1757500000.12,
  "ranges": [ {"anchorId": "A1", "range": 9.41, "rxPower": -83.2, "fpPower": -86.1,
               "nlos": false, "valid": true, "t": 1757500000.11}, ... ] }
```
The `range` already includes real-world error: antenna-delay **bias**, Gaussian noise, and — under
NLOS — a **positive-only** excess bias (a blocked path is always reported longer). The `rxPower −
fpPower` gap is the DW3000 diagnostic the solver uses to detect and down-weight NLOS. **No ground
truth** reaches the solver.

Estimate (engine → backend → frontend):
```json
{ "tagId": "Tag_A", "name": "Forklift", "battery": 85, "floorId": "...",
  "pos": {"x":.., "y":.., "z":..}, "vel": {"vx":.., "vy":.., "vz":..},
  "cov": {"sx":.., "sz":.., "sxz":..},          // uncertainty ellipse
  "raw": {"x":.., "z":..},                        // pre-Kalman multilateration (for compare)
  "truth": {"x":.., "z":..},                      // sim only — accuracy HUD
  "zone": "Aisle-2", "alerts": [] }               // AI (optional phase)
```

## Shared Site Config (the "labeled map")

Single source of truth used by both engine and frontend: `Model/config/site.json` — anchor
positions (meters), floor dimensions/labels, and named **zones** (rectangles) for labeling and
geofencing. This replaces the hardcoded lat/lon anchor lists in both `pi_emulator.py` and `App.jsx`.

## Implementation Phases

### Phase 1 — Foundation & framework ✅ DONE
- `Model/config/site.json` — shared source of truth in metres (anchors, walls, labelled zones, tag
  routes, ranging/noise model) with provenance tags.
- `Model/shared/` — versioned `reading.py` data format + `DATA_FORMAT.md`, `site_config.py` loader,
  `geometry.py` (2D LOS occlusion test).
- `Model/anchor-source/` — `AnchorSource` interface + factory switch; `SimAnchorSource` with
  realistic DS-TWR ranging (LOS/NLOS via wall occlusion, antenna-delay bias, positive-only NLOS
  bias, power diagnostics, dropped readings, waypoint motion); `HardwareAnchorSource` UDP stub;
  `main.py` entrypoint (`SOURCE=sim|hardware`).
- `Model/backend/server.js` — serves `/api/site`; relays `reading`/`location_update`.
- `Model/frontend/src/App.jsx` — config-driven twin in metres; walls, labelled zones, anchors; live
  tag positions; green/red anchor range lines showing LOS/NLOS.
- Phase 1 drives the twin from simulator ground truth (`update_location`) so the map is live; the
  solver replaces this in Phase 3.

### Phase 3 — Range multilateration solver ✅ DONE
- `Model/location-engine/solver.py`: 2D trilateration with height compensation +
  `scipy.optimize.least_squares` (LM) on weighted range residuals; **NLOS down-weighting from the
  DW3000 power gap** (`nlos_weight`); centroid/last-position seed. Tested in `test_solver.py`
  (recovers a known point < 1 cm; weighting beats trusting a biased anchor).
- `Model/location-engine/engine.py`: `LocationEngine.estimate(reading, truth)` → `update_location`
  payload (pos, zone, residual, error-vs-truth). Runs **in the gateway process** (`anchor-source/main.py`),
  matching how a real Pi gateway would ingest + solve. Replaces the Phase 1 truth-driven position.
- Measured accuracy on simulated LOS/NLOS data: **~0.6–0.7 m median raw error** (Phase 4 Kalman
  will smooth this).
- **Bonus (user request): interactive twin** — click anchors/tags for a details panel, and an
  **Edit Map** editor to add/remove/move anchors and tags. Saves via `PUT /api/site`; backend
  broadcasts `site_updated`; the gateway + dashboard reload live (no restart).

### Phase 4 — Kalman filter fusion ✅ DONE
- `Model/location-engine/kalman.py`: 2D constant-velocity KF (state x,z,vx,vz), predict/update,
  covariance out; tuned via `ranging.kalman` in config. Tested in `test_kalman.py`.
- Integrated in `engine.py`: per-tag filter, `dt` from a simulated clock; emits filtered `pos`,
  `raw` solve, `vel`+speed, `cov`, and both `error`/`rawError`. Frontend: "Raw fix + uncertainty"
  toggle shows the jittery raw ghost + 2σ ring vs the smooth Kalman track; speed + filtered-vs-raw
  error in the panels.
- Result: **~4–5% mean-accuracy gain** (bias-limited — NLOS bias is systematic, not filterable),
  plus velocity, uncertainty, and much smoother tracks. Fixed the sim to stamp readings with a
  simulated clock so `dt` is correct regardless of real-time pacing.

#### (original Phase 4 plan)
- `Model/location-engine/kalman.py`: constant-velocity KF, state `[x,y,z,vx,vy,vz]`, per-tag
  instances. Predict(dt) → update with the solver's position; output smoothed pos, vel, covariance.
  (Two-stage solve-then-filter — simplest robust design and the plan of record. **EKF-on-raw-TDOA is
  an optional, walled-off UTIL-only module**, off the critical path — CV-Kalman on ranges is adequate
  for slow warehouse motion. The high-value real-data work is NLOS noise-model calibration, not a
  second estimator; see the ⭐ callout under "Hardware reality" and the "Datasets" section.)
- `Model/location-engine/engine.py`: glue — consume raw → solve → filter → geofence → emit estimate
  to backend. Includes `SimAnchorSource` wiring for the default single-process run.

### Phase 5 — Digital twin upgrades ✅ DONE
- Fading **motion trails** of the Kalman-estimated path (per-tag gradient) + optional dashed
  **true-path overlay** (sim ground truth) for side-by-side comparison — `Trails` in `three3d.jsx`,
  histories accumulated in `Viewer3D.jsx`.
- **Live accuracy HUD** (`AccuracyHUD` in `Viewer3D.jsx`): running Kalman-vs-raw mean, median, p90,
  % improvement, plus a per-tag error sparkline over time.
- Uncertainty ring (`cov`) and zone labels landed in Phases 4/1. Toggles for trails / true path /
  raw / accuracy in the viewer HUD.

### Phase 6 — Basic AI (optional, recommended)
**Recommendation: geofence/zone anomaly detection as the headline AI feature** (reliable, visual,
directly serves the inventory use case), plus **near-free short-horizon trajectory prediction** that
reuses the Kalman velocity state to render a "ghost" predicted marker.
- `Model/location-engine/ai/zones.py`: map position → zone; raise `alerts` when an item leaves its
  allowed zone / goes stale; `predict.py`: `pos + vel·Δt` ghost marker.

### Docs
- Update `Model/STARTUP_GUIDE.md` for the new folder names/commands; keep the 3-terminal flow.

## Reuse Notes
- Trajectory motion (velocity, `bounds`, bounce) — reuse from `emulator/pi_emulator.py`.
- Battery drain, tag metadata (`name`, `floor`) — reuse from `pi_emulator.py` tag table.
- Warehouse geometry, `UwbTag`/`ReceiverPi`/`PlayerMover` components, HUD/telemetry panels — reuse
  from `frontend/src/App.jsx`; only the coordinate source and added overlays change.
- Backend `server.js` relay pattern is fine as-is — it broadcasts whatever the engine emits.

## Datasets (real UWB error for NLOS calibration)

Real, published UWB data lets us calibrate and validate without waiting on hardware. Primary use is
the **NLOS / noise-model calibration** above — the transferable part — not a TDOA estimator.

- **UTIL — Ultra-wideband Time-difference-of-arrival Indoor Localization dataset** *(primary)*.
  Zhao, Goudar, Qiao, Schoellig (UofT UTIAS DSL / IJRR 2024). Decawave **DWM1000** modules (same
  DW-chip *family* as our DW3000 — related but **not identical**; see cross-radio caveat). Contains
  **raw UWB TDOA measurements**, **SNR + power-difference** values (LOS/NLOS) — the exact diagnostic
  our power-gap NLOS down-weighting keys on — plus IMU, ToF altitude, and **mm-accurate Vicon ground
  truth** (~150 min of flights, 4 anchor constellations). Ships a reference EKF and Python/MATLAB
  parsers. Local copy: **`DOCS/datasets/util-uwb-dataset/`** (parsers) + raw data (see download note).
  - Project page: https://utiasdsl.github.io/util-uwb-dataset/
  - Code/parsers: https://github.com/utiasDSL/util-uwb-dataset
  - Paper: https://arxiv.org/abs/2203.14471

- **Fallback / cross-check:** various UWB TDoA RTLS papers publish measurement sets (e.g. MDPI
  *Sensors* RTLS-TDoA studies). UTIL is primary because it uniquely bundles raw measurements + NLOS
  power diagnostics + mm ground truth + an EKF baseline.

**How it plugs in (primary — NLOS/noise calibration): ✅ DONE.** Implemented in
`Model/calibration/calibrate_from_util.py`: derives real range-error statistics from UTIL's
identification-dataset (TDOA truth from surveyed geometry; `σ_range = σ_tdoa/√2`) and patches the
`ranging` block of `config/site.json` (provenance now `calibrated:UTIL-IJRR2024`). Calibrated:
`losNoiseStdM` 0.08→**0.054**, `nlosNoiseStdM` 0.30→**0.054**, `nlosBiasMinM/MaxM` 0.25/1.2→
**0.026/0.399**. Key finding: **NLOS is a positive bias (~0.03–0.40 m), not extra noise** — the sim's
noise model now reflects real DWM1000 behaviour. Because `SimAnchorSource` reads its model from
config, this was a data change, not a code change. Validated in `Model/calibration/test_calibration.py`
(sim output reproduces the calibrated LOS σ and positive-only NLOS bias). Full write-up:
`Model/calibration/CALIBRATION.md`. *Not* recalibrated: the dBm power block (UTIL `power_dif` units
are cross-radio; the WLS `nlos_weight` operates on our own consistent dBm gap).

**How it plugs in (optional — walled-off TDOA-EKF module): ✅ BUILT.**
- `Model/anchor-source/dataset_source.py` — `DatasetTdoaSource` replays a UTIL flight trial as a
  stream of `TdoaEvent(t, idA, idB, tdoa, truth)`. Critical detail: UTIL's CSV is a long-format event
  log whose `pose_*` column is *not* synced to the TDOA row, so ground truth is **interpolated to each
  TDOA timestamp** (raw row pose → 1.2 m error; interpolated → ~0.09 m). Anchor geometry from the
  `survey-results` files.
- `Model/location-engine/ekf_tdoa.py` — `TdoaEKF`: 3D constant-velocity EKF whose nonlinear
  measurement `h(p)=‖p−a_B‖−‖p−a_A‖` is linearised each step (hence *Extended* KF, vs the linear CV
  Kalman on the range path). Chi-square innovation gate rejects NLOS outliers; `cold_start_position`
  Gauss-Newton seeds the filter **without** using ground truth.
- `Model/location-engine/run_tdoa_ekf.py` — benchmark runner; `test_ekf_tdoa.py` — synthetic +
  real-trial tests (real test auto-skips if the dataset isn't extracted).

**Result (real DWM1000 flight data, vs mm Vicon):** 3D position RMSE **~0.18–0.20 m** on clean trials
(const1/const2), **0.33 m** on the cluttered const3 constellation where the gate rejects ~3 % of
measurements as outliers — literature-consistent. This stays **off the live warehouse critical path**;
the range-based DS-TWR pipeline remains the deliverable.

**How it plugs in (generative TDOA simulator): ✅ BUILT.** A *learned* TDOA simulator that runs on any
editable layout (not just the recording), so the warehouse can be driven by TDOA+EKF as well as
ranges+WLS. See `Model/calibration/TDOA_SIM.md`.
- `Model/calibration/train_tdoa_model.py` — fits a 2-component Gaussian mixture (inlier core + NLOS
  tail) to UTIL TDOA residuals via EM → `tdoa_model.json` (σ_inlier 0.137 m, σ_outlier 0.316 m,
  p_outlier 0.11).
- `Model/anchor-source/sim_tdoa.py` — `TdoaSimulator` yields `TdoaEvent`s for a site using the learned
  model + **geometry-aware NLOS** (reuses `blocking_walls` + per-material `ranging.materials`: a metal
  rack biases a link more than wood/light). Reuses `_TagMover` for motion.
- `TdoaEKF` gained a **2D fixed-height mode** for near-coplanar ceiling anchors (weak height
  observability), per-tag; the UTIL drone still uses full 3D.
- Run: `run_tdoa_sim.py` (RMSE benchmark, ~0.5 m horizontal on the warehouse) and
  `stream_tdoa_ekf.py --source sim` (live twin at `?map=wh-tdoa`, alongside `demo` and `util`).

**Cross-radio + no-truth caveats:** the fitted curve is calibrated on DWM1000 and is a *prior needing
DW3000 recalibration*, not a transplant; trajectory/end-to-end results do not transfer (drone vs
warehouse). With no warehouse Vicon, collect a few tape-measured, NLOS-labelled DS-TWR traces from
our own DW3000 to confirm the transfer holds.

## Known Constraints
- **Height (z) observability is weak** with 4 roughly co-planar ceiling anchors — solve full 3D when
  geometry allows, fall back to fixed-height 2D otherwise. More/spread-out anchors improve this.
- Phase 6 (AI) is optional and cleanly separable; it was de-prioritized in scoping.

## Verification
- **Unit tests** (pytest): solver recovers a known point from clean geometry (< 1 cm); solver + KF
  reduce mean error vs raw on a noisy known trajectory (target: filtered mean error < ~20 cm).
- **End-to-end**: start backend, start the Python engine (sim source), start the frontend. Confirm:
  tags tracked live; raw multilateration visibly jitters while the Kalman track is smooth; accuracy
  HUD shows filtered error < raw error; zone alerts fire on boundary crossings (if Phase 6 built).
- **Hardware-readiness check**: confirm swapping `SimAnchorSource` → `HardwareAnchorSource` is the
  only change needed to accept a real anchor feed (interface compiles, engine untouched).

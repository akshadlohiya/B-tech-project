# PPT Presentation Outline — UWB Indoor RTLS + Live 3D Digital Twin
**Format:** Follows the TY B.Tech. project report flow (Problem → Literature → Gap → Design → Methodology → Results → Conclusion).
**Suggested length:** 18–22 slides · ~15–18 min talk · one idea per slide, visuals over text.

---

## SLIDE 1 — Title
- **Title:** UWB Indoor Real-Time Location System with a Live 3D Digital Twin
- Subtitle: T.Y. B.Tech. Project · Department of CSE, COEP Technological University, Pune
- Team members + MIS numbers · Guide: Prof. `<name>` · Nov–Dec 2025
- COEP logo (`COEP_Tech_University_Logo.jpg`)

## SLIDE 2 — Agenda / Outline
- Problem & Motivation → Objectives → Literature Survey → Research Gap → Proposed System → Architecture → Methodology → Calibration → Results → Testing → Status → Conclusion → Future Work
- *(1 line each; sets the map for the audience)*

## SLIDE 3 — Problem Statement
- Indoors, **GPS is blocked**; Wi-Fi/BLE give **metre-to-tens-of-metre** error (narrowband, multipath).
- Warehouses/hospitals/factories need to know **where assets & people are, live, indoors**.
- **Problem:** build an end-to-end indoor RTLS that ranges tags, solves position from noisy/partly-NLOS ranges, smooths it, and visualises it live — architected so the *same software* runs on simulator today and real hardware tomorrow.

## SLIDE 4 — Motivation
- **Why UWB:** ultra-short wideband pulses → fine time resolution + strong multipath rejection → **cm-to-dm accuracy**.
- **Why a digital twin:** raw coordinates aren't legible; operators need to *see* items move on a labelled 3D floor.
- **Use cases:** asset tracking, worker safety, geofencing, inventory location.
- Speaker note: contrast a BLE "somewhere in this aisle" vs UWB "this pallet, this spot."

## SLIDE 5 — Objectives
1. Single **versioned data contract** shared by simulator & hardware (interchangeable).
2. **Hardware-faithful UWB simulator** (DS-TWR, LOS/NLOS, bias, power diagnostics, drops).
3. **Multilateration solver** with **NLOS down-weighting** from the DW3000 power gap.
4. **Constant-velocity Kalman filter** → smooth track + velocity + uncertainty.
5. **Config-driven 3D digital twin** (trails, uncertainty rings, zones, accuracy HUD).
6. **Calibrate & validate** noise/NLOS model on real mm-ground-truth UWB data (UTIL).
7. Keep hardware integration to a **single drop-in file**.

## SLIDE 6 — Background: How UWB Positioning Works
- Two observation models:
  - **TWR / DS-TWR (range-based):** direct distance per anchor; *double-sided* cancels clock drift → **no anchor time-sync** needed. ← *our hardware*
  - **TDOA:** synchronised anchors compare arrival times → hyperbolas; scales to many tags but needs tight sync.
- Diagram: tag + 4 ceiling anchors, range circles intersecting.

## SLIDE 7 — The NLOS Problem (the core technical challenge)
- Blocked first path → signal arrives via reflection → range reported **longer**.
- **NLOS error is a positive BIAS, not zero-mean noise** → cannot be averaged/filtered away.
- **Key diagnostic:** DW3000 exposes **received power** & **first-path power**; a large `rxPower − fpPower` gap ⇒ likely NLOS → the signal we use to **down-weight** bad links.
- Visual: LOS vs NLOS ray with a "+bias" arrow.

## SLIDE 8 — Literature Survey
| Work | Focus | Relevance |
|---|---|---|
| Paszek et al., *Sensors* 2021 | UWB LOS/NLOS **simulator** + accuracy analysis | Blueprint for a hardware-faithful sim |
| *Appl. Sci.* 2025 (15-02689) | **NLOS-exclusion** positioning (RMSE 0.124 m, ~24% ↑) | NLOS-aware weighting = biggest lever |
| *Appl. Sci.* 2024 (14-11005) | UWB RTLS deployment & error study | Geometry / error-budget guidance |
| Zhao et al., IJRR 2024 — **UTIL** | Raw TDOA + power-diff + **mm Vicon truth** (DWM1000) | Real-data calibration + EKF validation |
| *Alexandria Eng. J.* 2018 | UWB error modelling | Supporting error model |

## SLIDE 9 — Reference Dataset: UTIL
- UofT UTIAS DSL, IJRR 2024 · Decawave **DWM1000** · 4 anchor constellations, ~150 min flights.
- Provides: **raw TDOA**, **SNR/power-difference (LOS/NLOS labels)**, IMU, altitude, **mm Vicon ground truth**, reference EKF + parsers.
- **Cross-radio caveat:** DWM1000 ≠ our DW3000 → fitted model is a **prior needing recalibration**, not a transplant.

## SLIDE 10 — Research Gap (the "why this project")
- Existing sims often **shortcut**: they display measured distances but send *true* position to the UI → **no real solve, no NLOS handling, fake accuracy**.
- NLOS weighting constants are usually **hand-tuned**, not data-fitted.
- Sim and hardware paths are typically **separate codebases** → costly hardware bring-up.
- **Our gap-closing contributions:**
  1. A pipeline that **actually estimates** position from noisy ranges.
  2. **Data-driven** NLOS/noise model fitted on real mm-truth data.
  3. **One codebase** — sim ↔ hardware behind a single interface.

## SLIDE 11 — Proposed System (overview)
- One-line pipeline:
  `Anchor Source → Location Engine → Backend Hub → Frontend Digital Twin`
- **Core principle:** *one codebase, sim or hardware* — identical versioned data format, so everything downstream is source-agnostic.
- Callout: develop & validate fully **before** hardware arrives; hardware = 1 file.

## SLIDE 12 — System Architecture (diagram slide)
- `anchor-source` (sim OR real, DS-TWR) → `location-engine` (multilateration + Kalman) → `backend` (Socket.IO relay + `/api/site`) → `frontend` (React + Three.js twin).
- Note the `AnchorSource` interface seam: `SimAnchorSource` ↔ `HardwareAnchorSource` (`SOURCE=sim|hardware`).
- Use the architecture figure from the report.

## SLIDE 13 — Data Contracts & Shared Site Config
- **Reading** (`uwb.reading/1`): per-anchor `range` + `rxPower`/`fpPower` + `nlos`/`valid`. *No ground truth to the solver.*
- **Estimate**: `pos`, `vel`, `cov` (uncertainty), `raw` (pre-Kalman), `truth` (sim only), `zone`, `alerts`.
- **`site.json`** = single source of truth (metres): anchors, walls+material, zones, tag routes, ranging/noise model — every value **provenance-tagged** (guessed/measured/tested/calibrated).

## SLIDE 14 — Methodology 1: Simulator + Solver
- **SimAnchorSource** injects: antenna-delay bias, Gaussian noise, wall-occlusion LOS/NLOS, **positive-only NLOS bias (per material)**, power diagnostics, dropped readings; waypoint motion, simulated clock.
- **Solver (WLS):** minimise Σ wᵢ(‖p−aᵢ‖ − rᵢ)² via `scipy least_squares` (LM); **weights down-weight NLOS** by the power gap; centroid/last-pos seed.
- Verified: recovers a known point to **< 1 cm**; beats trusting a biased anchor.

## SLIDE 15 — Methodology 2: Kalman Filter + Digital Twin
- **CV Kalman** per tag, state `[x, z, vx, vz]`: predict(dt) → update with raw fix → smooth pos + velocity + covariance (tuned in config).
- NLOS bias is *systematic* → modest headline gain (~4–5%) but big usability win: smoother tracks, velocity, uncertainty.
- **Twin:** live tags, fading trails + true-path overlay, uncertainty rings, zone labels, **live accuracy HUD** (Kalman-vs-raw mean/median/p90/%↑), green/red LOS/NLOS anchor lines; **interactive Edit-Map** with hot-reload.
- Insert `twin_screenshot.png`.

## SLIDE 16 — Data-Driven NLOS Calibration (highlight)
- `calibrate_from_util.py` fits real range-error stats from UTIL (σ_range = σ_tdoa/√2) → patches `site.json` (`calibrated:UTIL-IJRR2024`).
- **Finding:** NLOS ≈ **positive bias 0.03–0.40 m**, *not* extra noise.

| Parameter | Before | After |
|---|---|---|
| LOS noise σ (m) | 0.08 | **0.054** |
| NLOS noise σ (m) | 0.30 | **0.054** |
| NLOS bias min/max (m) | 0.25 / 1.20 | **0.026 / 0.399** |

- Because the sim reads its model from config, this was a **data change, not code change**.

## SLIDE 17 — Optional Track: TDOA-EKF on Real Data
- Walled-off, **off the delivery critical path**, to prove an EKF on hardware-grade data.
- `DatasetTdoaSource` replays UTIL flights (truth **interpolated** to each TDOA timestamp: 1.2 m → ~0.09 m).
- `TdoaEKF`: 3D CV-EKF, h(p)=‖p−a_B‖−‖p−a_A‖ linearised each step; **chi-square gate** rejects NLOS outliers; Gauss–Newton cold start (no truth used).
- Plus a **generative TDOA simulator** (learned 2-component Gaussian mixture) → runs on any editable layout (`?map=wh-tdoa`).

## SLIDE 18 — Results
| Configuration | Error | Notes |
|---|---|---|
| Range solver, sim LOS/NLOS | ~0.6–0.7 m median raw | Weighted multilateration |
| + CV Kalman | ~4–5% mean ↑ | Bias-limited; adds vel/cov/smoothness |
| TDOA-EKF, real UTIL const1/2 | **~0.18–0.20 m** RMSE | Clean, vs mm Vicon |
| TDOA-EKF, real UTIL const3 | ~0.33 m RMSE | Cluttered; gate drops ~3% |
| Generative TDOA sim (warehouse) | ~0.5 m horiz. RMSE | Learned model, editable layout |
- Takeaway: bias dominates → **weighting + calibration** matter more than a heavier filter.

## SLIDE 19 — Testing & Verification
- **21 automated tests (pytest), all passing.**
- Solver recovers known point < 1 cm & beats biased anchor; Kalman reduces mean error on noisy trajectory; calibration reproduces LOS σ + positive-only NLOS bias; EKF on synthetic + real trials.
- **End-to-end demo:** raw fix visibly jitters, Kalman track smooth, HUD shows filtered < raw.
- **Hardware-readiness check:** swapping `SimAnchorSource → HardwareAnchorSource` is the *only* change; engine untouched.

## SLIDE 20 — Implementation Status
| Phase | Status |
|---|---|
| 1. Foundation & framework | ✅ Done |
| 3. Range multilateration solver | ✅ Done |
| 4. Kalman filter fusion | ✅ Done |
| 5. Digital-twin upgrades | ✅ Done |
| UTIL calibration | ✅ Done |
| TDOA-EKF (walled-off) | ✅ Built |
| Generative TDOA sim | ✅ Built |
| 6. Basic AI (zones/predict) | ⬜ Pending (optional) |

## SLIDE 21 — Conclusion
- Delivered a **complete, tested, hardware-ready** UWB RTLS + live 3D twin.
- Distinctive contributions: **one-codebase** sim↔hardware architecture, and **data-driven NLOS calibration** on real mm-truth data (NLOS = positive bias).
- EKF validated on real DWM1000 flights at **~0.18–0.20 m** RMSE.
- Verified by **21 tests** + live end-to-end demo.

## SLIDE 22 — Limitations & Future Work
- **Limitations:** cross-radio gap (DWM1000→DW3000 needs recalibration); no in-situ warehouse ground truth yet; weak height (z) observability with co-planar anchors; `HardwareAnchorSource` still a UDP stub.
- **Future work:**
  1. **Phase 6 AI** — geofence/zone anomaly alerts + short-horizon trajectory prediction (rides on Kalman velocity).
  2. Hardware bring-up + re-tune noise/power on DW3000.
  3. In-situ validation (tape-measured NLOS-labelled traces).
  4. More/spread-out anchors → better height & accuracy.

## SLIDE 23 — References (+ Thank You / Q&A)
- Paszek 2021 (*Sensors*); Appl. Sci. 2025 & 2024; Zhao et al. UTIL (IJRR 2024); Alexandria Eng. J. 2018; Makerfabs MaUWB_DW3000 docs.
- "Thank you — Questions?"

---

### Design notes for whoever builds the deck
- **Visual-first:** each slide = 1 diagram/screenshot + ≤5 bullets. Move detail to speaker notes.
- **Live demo** between Slide 18 and 19 if a projector allows (start backend → engine → frontend; toggle "Raw fix + uncertainty").
- **Assets ready in `SS/`:** `COEP_Tech_University_Logo.jpg`, `twin_screenshot.png`. Add a solver/architecture diagram and an accuracy bar chart for extra polish.
- **Colour key:** green = LOS / good, red = NLOS / alert — reuse consistently.

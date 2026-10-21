# ai-module: the AI component (standalone, not yet integrated)

This module is self-contained: it imports nothing from `anchor-source/`, `location-engine/` or `backend/`.
It only reads `config/site.json` and the UTIL dataset in `DOCS/datasets/`.
Integrate it only after the tests and evaluation below look right on real DW1000 data.

## What's here

| File | Role |
|---|---|
| `uwb_ai/util_loader.py` | Turns the UTIL identification dataset (real DWM1000 = DW1000 silicon) into ~298k labelled per-link samples. LOS/NLOS comes from obstacle geometry; the **measured NLOS range bias** comes from the TDOA error. |
| `uwb_ai/nlos_model.py` | `NlosBiasModel`: a gradient-boosted regressor that predicts a link's NLOS range bias from its power gap (and optionally SNR), then returns the corrected range and a trust weight. |
| `uwb_ai/train_nlos.py` | Trains it with grouped cross-validation by trial, compares it against "no correction" and linear regression, and writes `models/`. |
| `uwb_ai/eval_positioning.py` | Monte Carlo test on a 3-anchor room: plain LS vs the current power-gap rule vs the AI model, using held-out real UTIL links. |
| `uwb_ai/zones.py` | Geofence alerts (outside allowed zone, stale tag), driven by `config/site.json`. Plan Phase 6. |
| `uwb_ai/predict.py` | Short-horizon "ghost" prediction from the Kalman velocity, with an uncertainty radius. Plan Phase 6. |
| `tests/test_ai.py` | 37 tests. |

## Run
```bash
cd ai-module
../.venv/bin/pip install -r requirements.txt
../.venv/bin/python -m uwb_ai.train_nlos          # ~25 s, writes models/
../.venv/bin/python -m uwb_ai.eval_positioning    # ~3 min, 10 seeds
../.venv/bin/python -m pytest -q tests
```

## Results (UTIL, grouped by trial, nothing tested on a recording it trained on)

**Range bias** (5-fold CV, `pd` features):

| Method | Residual bias RMS | Reduction |
|---|---|---|
| none (raw range; the current solver can only re-weight) | 0.095 m | — |
| linear regression | 0.085 m | 11% |
| **gradient boosting** | **0.075 m** | **22%** |

The gain comes almost entirely from metal (0.34 → 0.22 m). On LOS links the model costs about 2 cm of over-correction.

**2D positioning, 3 anchors, one blocked link** (mean over 10 seeds × 2000 trials):

| Solver | RMSE | P50 | P90 |
|---|---|---|---|
| plain LS | 0.120 m | 0.049 m | 0.203 m |
| power-gap rule (current) | 0.113 m | 0.050 m | 0.187 m |
| **AI bias model** | **0.092 m** | **0.045 m** | **0.126 m** |

The AI model gives a 23% lower RMSE and a 38% lower P90 than plain LS, and beats it in 9 of 10 seeds. Almost all of the gain is on metal (0.230 → 0.136 m RMSE); on foam and cardboard it costs about 6 mm from over-correction. There are just 6 trials per obstacle material, so per-seed results still vary.

(Earlier numbers in this file, "5 of 10 seeds", came from a split bug: `max()` over material names put cardboard/foam/metal trials into the LOS pool, so some seeds held out no metal trial and others left only two to train on. Fixed and guarded by `test_eval_split_holds_out_every_material`.)

## Findings worth putting in the paper
1. **Blocked ≠ biased.** Foam, cardboard and plastic block the path but add < 3 cm of bias. Metal adds about 32 cm, wooden shelves about 16 cm and cabinets about 7 cm. That is why the model predicts *bias* rather than classifying LOS/NLOS.
2. **Leakage trap.** Every UTIL NLOS link is 3.94 m long, so a classifier given range scores 97%, which is meaningless. Range is excluded as a feature, and a test guards this.
3. **The limit of the power gap.** Wood-caused bias is invisible in power gap and SNR. Catching it would need channel-impulse-response (CIR) features (see `wang2026cir`, `yao2026xgboost` in the paper's bib).

## Why not YOLO?
YOLO detects objects in **camera images**. This system has no camera, and the project diary dropped camera-based counting (15 Oct 2025) for cost reasons. Using it would mean buying a camera and building a separate vision pipeline that does nothing for UWB accuracy. The AI here works on the radio data the DW1000 already produces, so it improves the core metric (position error) at no hardware cost. A camera + YOLO add-on (e.g. checking which item is at a tracked location) is possible later, but it is a separate feature.

## Integration plan (not done yet)
1. On the real hardware, collect labelled LOS/NLOS ranges at known points (paper experiments E1/E3). Run `train_nlos` on UTIL + your own data, because DW1000 module/antenna differences shift the power gap.
2. In `location-engine/engine.py`, swap `nlos_weight(...)` for `NlosBiasModel.correct(range, rxPower, fpPower)`. Use the corrected range and weight, and keep the rule as a fallback when the model file is missing.
3. Have the engine call `ZoneMonitor.update` and `predict_ahead`, and fill the `alerts` field that `shared/DATA_FORMAT.md` already reserves.
4. Optional: make the firmware send DW1000 receive quality so the `pd_snr` model can be used.

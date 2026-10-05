# Simulator calibration from real UWB data (UTIL)

The simulator's ranging noise used to be **guessed**. It is now **calibrated from real
hardware measurements** — the [UTIL dataset](https://utiasdsl.github.io/util-uwb-dataset/)
(Zhao, Goudar, Qiao, Schoellig; UofT Dynamic Systems Lab, IJRR 2024), collected on
Decawave DWM1000 modules. This makes `SimAnchorSource` inject noise that matches how
real UWB actually behaves, so accuracy numbers from the simulator mean something.

## How it works

UTIL's `identification-dataset` places a tag and two anchors at surveyed positions and
logs the time-difference-of-arrival `tdoa12` (in **metres**) per sample. The geometric
truth is `true_tdoa = d(tag, an2) − d(tag, an1)`, so the measurement error is
`tdoa12 − true_tdoa`. A TDOA is a difference of two independent noisy ranges, so:

```
var(tdoa) = 2 · var(range)   ⇒   σ_range = σ_tdoa / √2
```

- **LOS** (distTest + angleTest, 50 240 samples) → clean line-of-sight range noise.
- **NLOS** (an obstruction of a known material between anchor and tag) → the excess
  bias and extra noise. UTIL logs six materials; the RF-transparent ones
  (cardboard/foam/plastic) behave like LOS, while **metal and wooden shelving** — the
  warehouse-relevant obstructions — carry the real penalty, so the NLOS model is fit
  from that obstructing set.

## Key finding

**NLOS is almost entirely a positive *bias*, not extra noise.** Behind an obstruction
the within-trial jitter stays ≈ LOS level (~0.05 m even behind metal), but the range is
reported **0.03–0.40 m longer** (a blocked first path detours around the obstacle). The
old model over-stated NLOS *noise* (0.30 m) and its bias ceiling (1.2 m); reality is a
tighter, bias-dominated error.

## Calibrated values (`config/site.json` → `ranging`)

| field           | guessed | calibrated | source |
|-----------------|:-------:|:----------:|--------|
| `losNoiseStdM`  | 0.08    | **0.054**  | LOS σ_tdoa/√2, 24 trials |
| `nlosNoiseStdM` | 0.30    | **0.054**  | p75 of obstructing within-trial σ_range |
| `nlosBiasMinM`  | 0.25    | **0.026**  | p10 of per-trial excess bias |
| `nlosBiasMaxM`  | 1.20    | **0.399**  | p90 of per-trial excess bias |

`provenance` is now `calibrated:UTIL-IJRR2024`.

## Reproduce

```bash
python Model/calibration/calibrate_from_util.py            # analyse + print only
python Model/calibration/calibrate_from_util.py --apply    # write into site.json
pytest Model/calibration -q                                # confirm the sim matches
```

The validation tests generate simulated readings and check that the LOS noise level and
positive-only NLOS bias match the calibrated targets.

## Caveats (do not over-claim)

- **Cross-radio.** UTIL is DWM1000; our nodes are DW3000 (same family, not identical).
  The **range-error statistics (metres) transfer** — they are link physics. UTIL's raw
  `power_dif` register does **not** map cleanly to our dBm power block (light NLOS even
  lowers it), so the dBm power model is deliberately left as a DW3000 abstraction and
  is *not* calibrated here. Treat the fitted numbers as a prior to be re-checked on a
  few real DW3000 traces.
- **Motion does not transfer.** UTIL trajectories are from a flying drone; only the
  per-measurement error statistics are used, never end-to-end trajectory results.
## Per-material NLOS model

UTIL shows the NLOS penalty is strongly **material-dependent**, so the simulator now
models it per wall. Each wall in `site.json` carries a `material`, and `ranging.materials`
holds the calibrated physics per class (metres):

| class | biasMin–biasMax | noiseStd | UTIL source materials |
|-------|:---------------:|:--------:|-----------------------|
| metal | 0.198 – 0.583   | 0.060    | metal |
| wood  | 0.026 – 0.244   | 0.048    | wooden-shelf, wooden-cabinet |
| light | 0.001 – 0.046   | 0.038    | cardboard, foam, plastic |

In the demo warehouse the storage **racks are `metal`** and the perimeter **walls are
`wood`**. `SimAnchorSource` sums a per-blocker positive bias from the blocking wall's
material and uses the worst blocker's noise; walls with an unknown material fall back to
the aggregate NLOS values, so the change is backward compatible. Ordering
(metal > wood > light) is asserted in `test_calibration.py::test_material_bias_ordering`.
The cross-radio and motion caveats above apply equally to these per-material numbers.

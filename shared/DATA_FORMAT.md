# Common UWB Data Format (v1)

The whole point of this format is that **simulated readings and real hardware
readings are byte-for-byte identical to the software** (Project Diary, 10-17 Mar
2026). Swap the data source; nothing downstream changes.

## Why range-based, not TDOA timestamps

The chosen hardware — **Makerfabs MaUWB_DW3000** (ESP32 + DW3000 + STM32) — runs
firmware that performs **DS-TWR** (double-sided two-way ranging) and reports a
**distance per anchor**, plus signal-power diagnostics. It does *not* hand back
raw time-of-arrival timestamps. DS-TWR also cancels device clock drift, so the
anchors need no time synchronisation. To keep hardware integration near-zero, the
simulator emits exactly what the module emits: **ranges + power registers**.

## `reading` message (source -> backend -> engine)

```jsonc
{
  "schema": "uwb.reading/1",   // version guard; mismatched producers are rejected
  "tagId":  "T1",
  "seq":    1423,               // monotonic per tag
  "source": "sim",             // "sim" | "hardware"  (provenance of the data)
  "t":      1757500000.123,     // cycle timestamp (epoch seconds)
  "ranges": [
    {
      "anchorId": "A1",
      "range":    9.4127,        // metres, INCLUDING real-world error (bias + noise + NLOS)
      "rxPower":  -83.2,         // dBm, total received power
      "fpPower":  -86.1,         // dBm, first-path power; big (rx - fp) gap => likely NLOS
      "nlos":     false,         // ground-truth flag (sim only; hardware must infer this)
      "valid":    true,          // false => dropped / no first path
      "t":        1757500000.121 // per-anchor timestamp (ranging is turn-by-turn, not simultaneous)
    }
    // ... one entry per anchor that answered
  ]
}
```

### Real-world effects the simulator bakes into `range`
- **Antenna-delay bias** — a constant per-node offset (20-50 cm) removed only by
  calibration, never by filtering. Modelled as `anchors[].antennaDelayBiasM`.
- **NLOS is positive-only** — a blocked path is always reported *longer* than the
  truth, never shorter (Project Diary, 11 Apr 2026).
- **Ranging noise** — Gaussian, larger under NLOS.
- **Dropped readings** — occasional invalid entries, more frequent under NLOS.

## `location_update` message (position for the dashboard)

Phase 1 fills `pos` from ground truth so the twin renders immediately; from
Phase 3 the location engine replaces it with the solved + Kalman-filtered
estimate. The shape stays the same, so the frontend never changes.

```jsonc
{
  "tagId": "T1", "name": "Forklift", "battery": 85, "floorId": "f_floor1",
  "pos":   { "x": -11.0, "y": 0.5, "z": 3.2 },   // metres
  "truth": { "x": -11.0, "z": 3.2 },              // sim only, for the accuracy HUD
  "zone":  "Z_AISLE1",
  "t":     1757500000.123,
  // Phase 6 (AI) — added fields; everything above is unchanged
  "nlos":   { "method": "ai",                      // "ai" | "rule" (ranging.nlosModel, or fallback)
              "bias": { "A1": 0.02, "A3": 0.28 } }, // predicted NLOS bias subtracted per anchor (m), ai only
  "ghost":  { "x": -10.1, "z": 3.4, "r": 0.6, "horizonS": 1.0 },  // predicted position + 1σ radius
  "alerts": []                                      // alerts newly raised by this update (see below)
}
```

## `alert` message (engine -> backend -> dashboard)

Raised once when the condition starts (geofence from `tags[].allowedZones`), also
inside `location_update.alerts`. The backend keeps the last 50 per map and replays
them in `initial_state.alerts`.

```jsonc
{ "tagId": "T1", "kind": "outside_allowed",   // or "stale" (no fix for ai.staleAfterS)
  "zone": "Z_AISLE2",                         // null for stale / unmapped area
  "t": 1757500000.123, "message": "T1 entered Z_AISLE2", "mapKey": "demo" }
```

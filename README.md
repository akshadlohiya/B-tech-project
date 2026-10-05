# UWB Indoor RTLS + Digital Twin

A cost-effective **Ultra-Wideband (UWB) Real-Time Location System** that tracks
tagged items to centimetre accuracy indoors — where GPS and BLE fail — and shows
them moving live on a 3D **digital twin** of the floor.

Tags on items are ranged by ceiling-mounted **anchors** (Makerfabs MaUWB_DW3000).
A position engine turns those ranges into smooth tracks (multilateration +
Kalman filter), and a browser dashboard renders the labelled room, the anchors,
and every tag in real time.

## Core principle: one codebase, sim or hardware
The software is built so the **exact same code runs against the simulator and the
real hardware** — they emit an identical, versioned data format (`shared/DATA_FORMAT.md`).
Swap the data source; nothing downstream changes. This lets development and
testing proceed before hardware arrives, and keeps hardware integration to a
single file.

## Architecture
```
 anchor-source  ──readings──►  backend (hub)  ──►  frontend (digital twin)
  sim OR real    ranges +      Socket.IO relay      Three.js, config-driven
  (DS-TWR)       power diag.    + /api/site          room / anchors / zones
```

- **`Model/config/site.json`** — single source of truth (metres): anchors, walls,
  labelled zones, tag routes, and the ranging/noise model. Values tagged
  *guessed / measured / tested*.
- **`Model/anchor-source/`** — the data producer. `SimAnchorSource` models realistic
  UWB behaviour (LOS/NLOS via wall occlusion, antenna-delay bias, positive-only
  NLOS bias, signal-power diagnostics, dropped readings). `HardwareAnchorSource`
  is the drop-in seam for the real MaUWB_DW3000 nodes.
- **`Model/backend/`** — thin Socket.IO hub; also serves the site config.
- **`Model/frontend/`** — React + Three.js digital twin; draws live tags with
  green/red anchor range lines showing LOS vs NLOS.

## Mapping platform
The dashboard is now a standalone indoor-mapping tool (Mappedin-style):
- **Map library** — create/list/delete maps; each map has an unguessable **share key**.
- **2D floorplan editor** — draw walls, areas/zones, place anchors, lay out tag routes; **Save & Apply**
  hot-reloads the simulator, solver and 3D twin.
- **Live 3D viewer** — open `?map=KEY` to watch that map's live tracking; **Share** the key so
  anyone can view. Maps live in the backend store (`Model/backend/maps/`), independent of the code.
- The gateway runs one map at a time: `MAP=<key> python main.py`.

## Status
**Phases 1, 3, 4, 5 complete:**
- Local-metre coordinates, shared versioned data format, hardware-ready simulator with realistic
  LOS/NLOS, config-driven digital twin.
- **Range multilateration solver** (`Model/location-engine/`) with NLOS down-weighting from the
  DW3000 power gap — turns raw ranges into a live position estimate (~0.6 m median raw error).
- **Constant-velocity Kalman filter** fusing the raw fixes into a smooth track with velocity and an
  uncertainty ring; toggle "Raw fix + uncertainty" in the viewer to see raw-vs-filtered live.
- **Digital-twin analytics:** fading motion trails (estimated path) + optional true-path overlay,
  and a live accuracy HUD (Kalman-vs-raw mean/median/p90 + per-tag error sparklines).
- **Interactive twin:** click anchors/tags for details; **Edit Map** to add/remove/move anchors
  and tags, persisted to `site.json` with live reload of the simulator, solver and dashboard.

Next: basic AI — geofence/zone anomaly alerts + short-horizon trajectory prediction (rides on the
Kalman velocity). See `DOCS/IMPLEMENTATION_PLAN.md`.

## Run it
See **`Model/STARTUP_GUIDE.md`** — three terminals (backend, anchor-source, frontend).

# 🚀 UWB RTLS Digital Twin — Startup Guide

The system runs as three services that talk to each other. Start each in its own
terminal. The same commands work whether the data comes from the **simulator** or
from **real hardware** — only one environment variable changes.

```
 anchor-source  ──readings──►  backend (hub)  ──►  frontend (digital twin)
  (sim OR real)                 Socket.IO + /api/site        Three.js
```

---

## Step 1 — Backend hub (Node.js)
Central relay. Broadcasts positions/readings to the dashboard and serves the
shared site config at `/api/site`.

```bash
cd backend
npm install          # first time only
npm start
```
Expect: `WebSocket Hub Server running on port 3000`.

---

## Step 2 — Gateway: anchor source + location engine (Python)
Produces the UWB range readings **and solves them into positions** (Phase 3
multilateration + NLOS down-weighting), then streams both to the hub. By default
it **simulates** the anchors with realistic LOS/NLOS behaviour, antenna-delay
bias and dropped readings. On real hardware this same process runs on the Pi.

First-time setup (once, from the repo root) creates the shared project venv:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then run the source with the venv active:
```bash
source .venv/bin/activate     # from the repo root (Windows: .venv\Scripts\activate)
cd Model/anchor-source
python main.py                # simulated anchors
```
Expect a line like: `[anchor-source] site='Demo Warehouse — Floor 1' source='sim' tags=3 anchors=4`.

### Switching to real hardware later
No code changes downstream — just run the hardware source instead:
```bash
SOURCE=hardware python main.py              # listens for node UDP packets
```
The MaUWB_DW3000 nodes forward their DS-TWR ranges as UDP/JSON to this host
(default port `9000`, configurable via `UWB_UDP_PORT`). The only file to adapt to
your firmware's field names is `hardware_source.py::_parse_packet`.

---

## Step 3 — Frontend digital twin (React + Three.js)

```bash
cd frontend
npm install          # first time only
npm run dev
```
Open the printed URL (usually `http://localhost:5173`). You land on the **Map
Library**:
- **Create** a new map, or open the seeded **demo** map.
- **✎ Edit** opens the **2D floorplan editor** — draw walls, areas, drop anchors,
  and lay out tag routes, then **Save & Apply** (the sim/solver/twin reload live).
- **▶ View** opens the **live 3D twin** for that map — tags move with green/red/grey
  LOS/NLOS range lines. Click any anchor or tag for details.
- **🔗 Share** copies a link like `…?map=KEY`; anyone with the key + server can
  watch that map's live tracking.

### Running the gateway for a specific map
The gateway simulates/solves **one** map (default `demo`). To run it for another:
```bash
MAP=<mapKey> python main.py
```

---

## Watching the real-data TDOA-EKF in the twin (optional track)

Besides the simulator, you can replay a **real UTIL flight trial** (real DWM1000 UWB,
TDOA measurements, mm Vicon truth) through the Extended Kalman Filter and watch it in
the same 3D twin. Keep the backend (Step 1) and frontend (Step 3) running, then instead
of the sim gateway run:

```bash
source .venv/bin/activate
cd Model/location-engine
python stream_tdoa_ekf.py               # registers the "UTIL Flight Arena" map + streams
python stream_tdoa_ekf.py --speed 4     # 4x faster replay
python stream_tdoa_ekf.py --const const3 --trial trial1   # a cluttered constellation
```

It prints `open the twin at ?map=util`. In the dashboard open the **UTIL Flight Arena**
map (or visit `http://localhost:5173/?map=util`) to watch the drone fly with the EKF
estimate and the Vicon ground-truth overlay.

**Generative TDOA simulator (editable layouts).** The same streamer can run a *synthetic*
TDOA simulator — with an error model **learned from the dataset** — on any layout, e.g.
the warehouse:
```bash
python stream_tdoa_ekf.py --source sim --loop --speed 2   # -> ?map=wh-tdoa
python run_tdoa_sim.py                                     # offline RMSE benchmark
```
Open `http://localhost:5173/?map=wh-tdoa` to watch the warehouse tracked via TDOA+EKF
(vs the range-based `?map=demo`). Unlike the fixed UTIL replay, this layout **is** editable
(same site.json / Edit Map). See `Model/calibration/TDOA_SIM.md`.

Offline (no browser) you can just print the accuracy:
```bash
python run_tdoa_ekf.py                   # 3D RMSE vs Vicon for one trial
```
This is a **walled-off track**: the geometry and motion are *real recordings*, so anchors
and the tag can't be moved here (that would falsify the measurements). Use the simulator
for editable layouts. See `DOCS/IMPLEMENTATION_PLAN.md` (Datasets) and
`Model/calibration/CALIBRATION.md`.

## Editing the site
Two ways to change the space:
- **In the dashboard:** click **✎ Edit Map** (left panel) to add/remove/move anchors and tags,
  then **Save & Apply**. This writes `config/site.json` and hot-reloads the simulator, solver and
  twin — no restart. Click any anchor or tag to inspect its live details.
- **By hand:** edit **`config/site.json`** (metres): anchor coordinates, walls/racks, labelled
  zones, tag routes and the ranging/noise model. Both the simulator and the dashboard read this one
  file. Values are tagged `guessed` / `measured` / `tested` so the team knows what still needs
  on-site measurement.

## Data format
The message contract shared by simulator and hardware is documented in
**`shared/DATA_FORMAT.md`** (schema `uwb.reading/1`).

---

### 🛑 Troubleshooting
- **Twin says OFFLINE / empty** — make sure the backend (Step 1) is running; the
  dashboard fetches `http://localhost:3000/api/site` and connects over Socket.IO.
- **No tags moving** — check the anchor-source terminal for the connected message;
  if it says "hub not up yet", start the backend first.

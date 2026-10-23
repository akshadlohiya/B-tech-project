# 🚀 UWB RTLS Digital Twin & Edge Tracking — Startup Guide

The system runs as three services that talk to each other. Start each in its own
terminal. The same commands work whether the data comes from the **simulator** or
from **real hardware** — only one environment variable changes.

```
 anchor-source  ──readings──►  backend (hub)  ──►  frontend (digital twin)
  (sim OR real)                 Socket.IO + /api/site        Three.js
```

---

## Quick start — one command
From the repo root, after the one-time Python venv setup in Step 2:
```bash
./run.sh                  # backend -> simulator gateway -> frontend
SOURCE=hardware ./run.sh  # same, but with real MaUWB_DW3000 nodes
```
It installs the Node dependencies on first run, stops any copies of these services
already running from this checkout, and stops all three on Ctrl+C. Then open
`http://localhost:5173`. The steps below start each service by hand instead.

---

## Step 1 — Backend hub (Node.js + SQLite)
Central relay. Broadcasts positions/readings to the dashboard, serves the
shared site config at `/api/site`, manages maps at `/api/maps`, and stores location
history in SQLite at `rtls_warehouse.db`.

```bash
cd backend
npm install          # first time only
npm start
```
Expect: `Unified UWB RTLS & Digital Twin Server Running on port 3000`.

### REST & Health Endpoints:
- `http://localhost:3000/health` — Server health, uptime, and database records.
- `http://localhost:3000/api/maps` — Multi-room map configurations.
- `http://localhost:3000/api/database` — Raw SQLite location history records.
- `http://localhost:3000/api/tags` — Latest coordinates for each tag.
- `http://localhost:3000/api/analytics` — Active tag counts and server metrics.

---

## Step 2 — Gateway: anchor source + location engine (Python)
Produces the UWB range readings **and solves them into positions** (multilateration
+ NLOS down-weighting + GBDT AI model), then streams both to the hub. By default
it **simulates** the anchors with realistic LOS/NLOS behaviour, antenna-delay
bias and dropped readings. On real hardware this same process runs on the Pi.

First-time setup (once, from the repo root) creates the shared project venv:
```bash
python -m venv .venv
.venv\Scripts\activate          # On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Then run the source with the venv active:
```bash
cd anchor-source
python main.py                # simulated anchors
```
Expect lines like `[gateway] map='Demo Warehouse — Floor 1' ... source='sim' tags=3 anchors=5` and
`[gateway] NLOS handling: learned bias model (nlos_bias_pd.joblib)`.

### Switching to real hardware
No code changes downstream — just run the hardware source:
```bash
SOURCE=hardware python main.py              # listens for node UDP packets on port 9000
```
See [`PI_SETUP.md`](PI_SETUP.md) and [`RASPBERRY_PI_GUIDE.md`](RASPBERRY_PI_GUIDE.md).

---

## Step 3 — Frontend digital twin (React 19 + Three.js)

```bash
cd frontend
npm install          # first time only
npm run dev
```
Open the printed URL (usually `http://localhost:5173`). You land on the **Map Library**:
- **Create** a new map, or open the seeded **demo** map.
- **✎ Edit Floorplan** opens the **2D floorplan editor** — draw walls, areas, drop anchors,
  and lay out tag routes, then **Save & Apply** (the sim/solver/twin reload live).
- **▶ View 3D** opens the **live 3D twin** for that map — tags move with green/red/grey
  LOS/NLOS range lines. Click any anchor or tag for details.
- **🎮 Launch 3D Warehouse Simulation** opens the first-person WASD interactive 3D warehouse
  with industrial shelving, mezzanine, forklift, pallet jack, employee, and drone models
  (direct URL: `http://localhost:5173/?mode=classic`).
- **🔗 Share** copies a link like `…?map=KEY` for sharing.

---

## Step 4 — Raspberry Pi 4 Edge Automation & Wi-Fi Tracking

### One-Click Remote Pi Initialization
To automatically discover your Raspberry Pi 4 on your local network, sync backend files over SSH, start the systemd edge service, and stream live database logs:
```bash
python init_pi.py
```
*(Windows users can simply double-click `start_pi.bat`)*

### Running the Raspberry Pi Wi-Fi RSSI Distance Tracker:
```bash
cd raspberry_pi
python pi_wifi_tracker.py --server http://<PI_OR_PC_IP>:3000
```
To calibrate the Wi-Fi signal path-loss at 1 meter:
```bash
python pi_wifi_tracker.py --calibrate
```

---

## Step 5 — Real-Data TDOA-EKF in the Twin (Optional Track)

Replay a **real UTIL flight trial** (real DWM1000 UWB, TDOA measurements, mm Vicon truth) through the Extended Kalman Filter and watch it in the 3D twin:
```bash
cd location-engine
python stream_tdoa_ekf.py               # registers "UTIL Flight Arena" map + streams
python stream_tdoa_ekf.py --speed 4     # 4x replay speed
```
Open `http://localhost:5173/?map=util` in your browser.

Generative TDOA simulator on editable layouts:
```bash
python stream_tdoa_ekf.py --source sim --loop --speed 2   # -> ?map=wh-tdoa
```
Open `http://localhost:5173/?map=wh-tdoa`.

---

## Troubleshooting
- **Twin says OFFLINE / empty:** Ensure the backend (Step 1) is running on port 3000.
- **No tags moving:** Check the anchor-source terminal. Start the backend first before starting anchor-source.
- **sqlite3 module not found warning:** The backend will run in memory. Run `npm install` inside `backend/` to enable SQLite file persistence.

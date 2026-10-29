# 🍓 Raspberry Pi 4 Model B - RTLS Edge Server, Ingestion & Database Guide

Your **Raspberry Pi 4 Model B (4 GB RAM)** is now configured as the **Central RTLS Server, Gateway & Database Hub** for your warehouse! It detects UWB tags/nodes, runs real-time trilateration and zone analytics, stores location history in an embedded **SQLite database**, and broadcasts live updates to the 3D dashboard.

---

## 🏗️ Architecture: Raspberry Pi as Central Brain

```
┌────────────────────────────────────────────────────────┐
│             UWB TAGS & SENSOR NODES                    │
│   (ESP32 UWB, Arduino, Mobile Wi-Fi Pi, Emulators)     │
└──────────────────────────┬─────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼ (HTTP REST)      ▼ (WebSockets)     ▼ (UDP 5005)
   POST /api/telemetry   update_location   Low-latency stream
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│             RASPBERRY PI 4 EDGE SERVER                 │
│               http://192.168.1.40:3000                 │
│                                                        │
│  1. Ingestion: HTTP REST + WebSockets + UDP (5005)     │
│  2. Analytics: 3D Trilateration & Geofence Zones       │
│  3. Database:  SQLite (rtls_warehouse.db)              │
│     - tags, location_history, alerts                   │
│  4. Broadcast: Socket.io -> 3D Web Dashboard           │
└──────────────────────────┬─────────────────────────────┘
                           │ (Live WebSockets)
                           ▼
┌────────────────────────────────────────────────────────┐
│             REACT THREE.JS 3D DASHBOARD                │
│    (Open in browser on Laptop, Phone, or Tablet)       │
│  - Live 3D warehouse tracking                          │
│  - Database status & active tags counter               │
│  - Geofence zone badges & alert notifications          │
└────────────────────────────────────────────────────────┘
```

---

## 🔌 How External Nodes / Microcontrollers Send Data

Any microcontroller (like **ESP32**, **ESP8266**, **Arduino with Wi-Fi/Ethernet**, or a Python script) can easily report its position to the Raspberry Pi:

### Method 1: HTTP REST API (Recommended for ESP32 / Microcontrollers)
Send an HTTP `POST` request to `http://192.168.1.40:3000/api/telemetry`:

```json
POST http://192.168.1.40:3000/api/telemetry
Content-Type: application/json

{
  "tagId": "ESP32_UWB_01",
  "name": "Forklift Sensor Node",
  "battery": 92,
  "distances": {
    "R1": 4.5,
    "R2": 7.2,
    "R3": 8.1,
    "R4": 5.0
  }
}
```
*The Raspberry Pi automatically runs trilateration, solves for $(X, Y, Z)$, determines the warehouse zone, saves the point to SQLite, and updates the website instantly!*

### Method 2: High-Speed UDP Broadcast (Port 5005)
For high-rate UWB anchors (e.g. 50–100 Hz), send raw JSON datagrams to `192.168.1.40:5005`.

### Method 3: WebSockets (Socket.io)
Emit `update_location` with standard tag payload over `http://192.168.1.40:3000`.

---

## 📊 REST API Endpoints on the Raspberry Pi

| Endpoint | Method | Description |
|---|---|---|
| `/health` | `GET` | Server status, uptime, active tags count |
| `/api/tags` | `GET` | Current state of all active tags |
| `/api/history/:tagId` | `GET` | Historical breadcrumb points for a specific tag |
| `/api/analytics` | `GET` | Database summary (total tags, history records, status) |
| `/api/events` | `GET` | Recent system events & perimeter alerts |
| `/api/telemetry` | `POST` | Ingestion endpoint for external nodes/tags |

---

## 🚀 How to Run the Whole System

### 1. The Raspberry Pi Server (Already Running!)
The server is installed as a systemd background service on the Raspberry Pi (`rtls-server.service`). It starts automatically on boot!
- Check status: `sudo systemctl status rtls-server.service`
- Restart server: `sudo systemctl restart rtls-server.service`
- Stop server: `sudo systemctl stop rtls-server.service`

### 2. View the 3D Dashboard on Your Laptop
On your laptop:
```bash
cd frontend
npm run dev
```
Open `http://localhost:5173` in your browser. It connects automatically to the Raspberry Pi over your Wi-Fi!

### 3. Run the Mobile Wi-Fi Tracker on the Raspberry Pi
To track the physical Raspberry Pi moving in real time:
```bash
ssh akshad@192.168.1.40
cd /home/akshad/B-tech-project/raspberry_pi
source venv/bin/activate
python3 pi_wifi_tracker.py --server http://localhost:3000
```

### 4. Run the Multi-Tag Simulation on Laptop (Optional)
To see the Forklift, Drone, and Pallet Jack moving alongside your real hardware:
```bash
cd emulator
python pi_emulator.py --server http://192.168.1.40:3000
```

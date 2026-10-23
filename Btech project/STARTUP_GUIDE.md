# 🚀 3D RTLS Warehouse Dashboard - Startup Guide

This project can be launched in two modes:
1. **Hardware Mode (With Raspberry Pi 4 as Central Edge Server & Database)**
2. **Local Emulation Mode (Everything running on PC/Laptop)**

---

## 🍓 Mode 1: Start with Raspberry Pi 4 (Recommended)

When using your physical **Raspberry Pi 4 Model B**:

### Step 1: Connect and Initialize Raspberry Pi from this Laptop
Simply run the initializer script (or double-click `start_pi.bat`):
```bash
python init_pi.py
```
- It automatically searches the network for your Raspberry Pi (`akshad.local` / `192.168.1.40`).
- It waits until the Pi joins Wi-Fi.
- It logs in over SSH, syncs the backend files, initializes the SQLite database (`tag_locations`), and starts the service.
- It opens a live monitor showing incoming tag coordinates in real time!

### Step 2: Start the 3D Dashboard Website
In another terminal:
```bash
cd frontend
npm run dev
```
Open `http://localhost:5173` in your browser.

### Step 3: Run the Multi-Tag Simulation or Wi-Fi Tracker
- **On Laptop (Simulated Tags)**:
  ```bash
  cd emulator
  python pi_emulator.py --server http://192.168.1.40:3000
  ```
- **On Raspberry Pi (Real Physical Tag)**:
  ```bash
  ssh akshad@192.168.1.40
  cd /home/akshad/B-tech-project/raspberry_pi
  source venv/bin/activate
  python3 pi_wifi_tracker.py --server http://localhost:3000
  ```

---

## 💻 Mode 2: Local Emulation Mode (Without Raspberry Pi)

If the Raspberry Pi is powered off, you can run the whole stack locally on your laptop:

1. **Start Backend**:
   ```bash
   cd backend
   npm start
   ```
2. **Start Multi-Tag Simulation**:
   ```bash
   cd emulator
   python pi_emulator.py
   ```
3. **Start 3D Visualizer**:
   ```bash
   cd frontend
   npm run dev
   ```

---

## 🛑 Troubleshooting & Quick Tips
- If the Raspberry Pi changes IP address, `init_pi.py` automatically resolves `akshad.local` via mDNS!
- To query the database directly in your browser:
  Open `http://192.168.1.40:3000/api/database` to see all stored coordinate logs.

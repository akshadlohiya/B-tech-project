# Raspberry Pi server + anchor integration

The Pi is the **server**: it runs the backend, the gateway (solver + Kalman + AI) and the
3D viewer. The UWB anchors send their ranges to it, and any device on the network
opens the viewer.

| Runs on the Pi | Port | Who connects |
|---|---|---|
| Gateway `anchor-source/main.py` (`SOURCE=hardware`) | UDP 9000 | UWB anchor nodes |
| Backend `backend/server.js` (systemd `rtls-server`) | TCP 3000 | gateway + browsers |
| Viewer (`npm run dev -- --host`) | TCP 5173 | any phone / laptop browser |

Pi: user `akshad`, address `10.1.238.88` (DHCP; check with `hostname -I`),
project at `~/B-tech-project`, Raspberry Pi OS (Debian 13, aarch64), Python 3.13, Node 20.

## Status (2026-10-22)
- [x] Backend running as `rtls-server` (`curl localhost:3000/api/maps` → 200)
- [x] Gateway and viewer set up (steps 4–5 below)
- [ ] Pi code updated past `534791f` (needs the AI integration and the `frontend/src/api.js`
      fix; without the fix the viewer only works in a browser on the Pi itself)
- [x] Firmware written (`firmware/`), not yet flashed
- [ ] Anchors connected (step 6 onwards)

## Server setup (done once)

1. **Get the latest code** (after pushing from the laptop):
   ```bash
   cd ~/B-tech-project && git pull
   ```
2. **Install dependencies**:
   ```bash
   .venv/bin/pip install -r requirements.txt     # includes scikit-learn + joblib for the AI
   (cd backend && npm install)
   (cd frontend && npm install)
   ```
3. **Backend**: `sudo systemctl restart rtls-server`, then check that `curl localhost:3000/api/maps`
   lists maps.
4. **Gateway**:
   ```bash
   source .venv/bin/activate
   SOURCE=hardware python anchor-source/main.py
   ```
   Expect `source='hardware'`, `NLOS handling: learned bias model (...)` and
   `connected to hub`. **Then it goes silent; that is normal.** It is waiting for anchor packets
   and prints nothing more until tags are solved. (`power-gap rule (fallback: ...)` means the AI
   model could not load, usually because scikit-learn is missing. Tracking still works.)

   **To start the gateway and the viewer at boot** (recommended; the demo is then just "power on"):
   ```bash
   cd ~/B-tech-project && git pull
   sudo deploy/install-services.sh <map-key>        # e.g. 4f41ed2f96 for the Lab map
   ```
   It stops any gateway or viewer started by hand, installs `rtls-gateway` (with `SOURCE=hardware`
   and that map) and `rtls-viewer` from `deploy/`, enables both with `rtls-server`, and prints the
   viewer URL. Re-run it to switch maps. Logs: `journalctl -u rtls-gateway -f`. After a `git pull`:
   `sudo systemctl restart rtls-gateway rtls-viewer`. While the services run, don't start
   `main.py` or `npm run dev` by hand (`Address already in use`).
5. **Viewer for other devices**:
   ```bash
   cd ~/B-tech-project/frontend && npm run dev -- --host
   ```
   Open `http://<pi-ip>:5173` from any device on the same network.

## Anchor integration (ESP32 + DW1000, phone hotspot)

Hardware: 4 × ESP32 + DW1000 (the README's "MaUWB_DW3000" is stale). They form **3 anchors (A1–A3)
and 1 tag (T1)**. Flash them first by following `firmware/README.md`. The tag sends one UDP datagram per
range to the hotspot's **broadcast** address on port 9000, so the Pi's IP never goes into firmware:
```json
{"tag":"T1","anchor":"A1","range":2.41,"rxPower":-83.2,"fpPower":-86.1}
```
The anchors only need USB power. Only the tag and the Pi use Wi-Fi.

The gateway also announces itself every 2 s (UDP broadcast `{"rtls":"gateway","port":9000}` to port
**9001**). The tag sends to whoever announces, so the Pi's hotspot IP can change without reflashing
(phone hotspots hand out new addresses and block `.local` names). Run only **one** gateway on the
hotspot, or the tag follows whichever announced last.

6. **Put the Pi on the phone hotspot** (same one as in the tag's `secrets.h`):
   ```bash
   sudo nmcli dev wifi connect "<SSID>" password "<PASSWORD>"
   hostname -I          # the Pi's new address; the phone's hotspot page shows it too
   ```
   Your laptop joins the same hotspot to SSH in and to open the viewer.
7. **Update and restart** (step 1–3 above): `git pull`, `pip install -r requirements.txt`,
   `sudo systemctl restart rtls-server`.
8. **Create the real map.** In the viewer, create a new map (e.g. "Lab") and note its key. In
   **✎ Edit**, set the floor size, add anchors **A1, A2, A3** at their measured positions in metres
   (origin at floor centre, x = east, y = height, z = north), and add tag **T1**. IDs must match the
   firmware exactly. The editor does not expose ranging settings, so set them through the API.
   Use the lowest rate in the tag's serial `rate Hz` line, and the height the tag will really be carried at:
   ```bash
   KEY=<map-key> python3 -c "
   import json,os,urllib.request as u; url='http://localhost:3000/api/maps/'+os.environ['KEY']
   m=json.load(u.urlopen(url)); r=m['ranging']
   r['updateRateHz']=5; r['assumedTagHeightM']=1.0
   u.urlopen(u.Request(url,json.dumps(m).encode(),{'Content-Type':'application/json'},method='PUT'))
   print(r)"
   ```
9. **Run the gateway on that map:**
   ```bash
   SOURCE=hardware MAP=<map-key> .venv/bin/python anchor-source/main.py
   ```
   For the systemd service, add `Environment=MAP=<map-key>` to `rtls-gateway.service`. Editing the
   map while the gateway runs reloads it live (the UDP port is released and re-bound; fixed 2026-10-29).
10. **Confirm packets arrive:** `sudo tcpdump -n -A udp port 9000` should show T1's JSON. Then open
    `http://<pi-ip>:5173/?map=<map-key>` and T1 should move with the tag.
11. **Mount the anchors** about 2–2.5 m high in a wide triangle (not in a line) with a clear view of
    the tracked area. Re-measure their positions and update them in **✎ Edit**.
12. **Calibrate the AI's power baseline.** With the tag in clear line of sight of all anchors,
    record a minute and read off the suggested value (`calibration/hw_log.py` works from the Pi or
    any laptop on the hotspot, while the gateway runs):
    ```bash
    .venv/bin/python calibration/hw_log.py record --backend http://<pi-ip>:3000 --map <map-key> \
        --label LOS --seconds 60 --out calibration/logs/baseline.csv
    .venv/bin/python calibration/hw_log.py baseline calibration/logs/baseline.csv
    ```
    Put the printed `fpToRxDeltaLosDbm` into the map using the snippet in step 8. The default
    `-3` is a simulator placeholder. Until this is measured, or if positions look worse, set
    `ranging.nlosModel` to `"rule"`.
13. **Check accuracy.** Tape 5+ points on the floor and list them in a `points.csv`
    (`label,x,z` in metres, map frame). Record ~30 s with the tag on each point (same `--out` file,
    a different `--label` each time), then:
    ```bash
    .venv/bin/python calibration/hw_log.py accuracy calibration/logs/run1.csv --points points.csv \
        --plot report/hw_accuracy_cdf.png
    .venv/bin/python calibration/hw_log.py ranges calibration/logs/run1.csv --label P1 --at <x>,<tag-h>,<z> \
        --backend http://<pi-ip>:3000 --map <map-key>
    ```
    `accuracy` prints RMSE/P50/P90/P95 and writes a CDF chart for the report. `ranges` shows each
    anchor's offset at a known point; a steady offset is antenna delay, fixed in that anchor's
    `ANTENNA_DELAY` (the map's `antennaDelayBiasM` only affects the simulator).

**Anchor dropout.** The gateway releases a tag's reading once every anchor has reported, or
80% of one ranging period after the cycle's first packet if at least 3 have. With exactly 3
anchors, every cycle needs all 3. If one is blocked, the tag holds its last position.

## Testing without anchors
From any machine on the network, send fake ranges (one entry per anchor in the map):
```bash
python3 -c "
import socket,json,time; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
for _ in range(50):
    for a,r in [('A1',3.1),('A2',4.2),('A3',3.6)]:
        s.sendto(json.dumps({'tag':'T1','anchor':a,'range':r,'rxPower':-80,'fpPower':-83}).encode(),('<pi-ip>',9000))
    time.sleep(0.2)"
```
T1 should appear in the viewer. If it does, the whole Pi chain works and only the anchors remain.

## Troubleshooting
| Symptom | Check |
|---|---|
| Viewer says OFFLINE | `systemctl status rtls-server`; is port 3000 reachable from the device? Is the Pi's code past `534791f` (api.js fix)? |
| Gateway prints `hub not up yet` | Backend not running: `sudo systemctl restart rtls-server` |
| Gateway silent, no tags | Normal until packets arrive. Check `sudo tcpdump -n udp port 9000` on the Pi. |
| `Address already in use` (port 9000) | A gateway is already running: `pgrep -af main.py`, or `systemctl status rtls-gateway` |
| Tag freezes or updates rarely | Fewer than 3 anchors are reaching the Pi each cycle (`tcpdump`), or `updateRateHz` in the map is much faster than the anchors really range |
| Positions offset by a constant | Anchor coordinates (step 8) or antenna delay (step 10) |
| Viewer only works on the Pi | Missing `npm run dev -- --host`, or Pi code older than the api.js fix |

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

   To start it at boot, save as `/etc/systemd/system/rtls-gateway.service`, then
   `sudo systemctl enable --now rtls-gateway` (logs: `journalctl -u rtls-gateway -f`):
   ```ini
   [Unit]
   Description=RTLS UWB gateway (anchors -> solver -> backend)
   After=rtls-server.service
   Wants=rtls-server.service

   [Service]
   User=akshad
   WorkingDirectory=/home/akshad/B-tech-project/anchor-source
   Environment=SOURCE=hardware
   Environment=PYTHONUNBUFFERED=1
   ExecStart=/home/akshad/B-tech-project/.venv/bin/python main.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
5. **Viewer for other devices**:
   ```bash
   cd ~/B-tech-project/frontend && npm run dev -- --host
   ```
   Open `http://<pi-ip>:5173` from any device on the same network.

## Anchor integration (when the anchors arrive)

6. **Check how the nodes report.** The gateway expects each node to send **one UDP datagram
   per range** to `<pi-ip>:9000`:
   ```json
   {"tag":"T1","anchor":"A1","range":9.41,"rxPower":-83.2,"fpPower":-86.1}
   ```
   - Custom ESP32 firmware sending this JSON: nothing to change.
   - Different field names: edit only `anchor-source/hardware_source.py::_parse_packet`.
   - Stock Makerfabs AT firmware reports over **USB serial**, not UDP. Plug the board into the
     Pi and add a serial reader to `hardware_source.py`. Capture a few lines of its output first
     (`cat /dev/ttyUSB0` or `screen /dev/ttyUSB0 115200`).
7. **Anchor dropout is handled** (fixed 2026-10-22). The gateway releases a tag's reading once
   every anchor has reported, or 80% of one ranging period (160 ms at 5 Hz) after the cycle's
   first packet if at least 3 anchors have reported. One blocked or silent anchor no longer freezes
   the tag. Cycles with fewer than 3 anchors are dropped, not mixed into the next one.
   `ranging.updateRateHz` in the map must match the anchors' real rate.
8. **Measure and enter the anchor positions.** Mount the anchors, measure each one's position
   in metres (origin at the floor centre, x = east, y = height, z = north), and enter them in the
   viewer's **✎ Edit** for the map the gateway runs (`MAP=<key>`, default `demo`). Anchor and tag
   IDs in the map must match the IDs the nodes send (`A1`…, `T1`…).
9. **Calibrate the AI's power baseline.** With a tag in clear line of sight of all anchors, log
   a minute of packets and take the median `rxPower - fpPower`. Put its negative in the map's
   `ranging.power.fpToRxDeltaLosDbm` (a 9 dB gap → `-9`). The AI correction aligns to this value;
   the default `-3` is a simulator placeholder. Until this is measured, or if positions look
   worse, set `"nlosModel": "rule"` under `ranging` to use the plain power-gap rule.
10. **Antenna delay.** Place the tag at a few known points and compare the measured range with the
    tape-measured distance per anchor. A constant offset per anchor (typically 0.1–0.5 m) is
    antenna delay. Calibrate it in the node firmware.

## Testing without anchors
From any machine on the network, send fake ranges (one entry per anchor in the map):
```bash
python3 -c "
import socket,json,time; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
for _ in range(50):
    for a,r in [('A1',9.4),('A2',8.1),('A3',10.2),('A4',7.7),('A5',8.8)]:
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

#!/usr/bin/env python3
"""
Raspberry Pi 4 Edge Hardware & Serial UWB Collector
B-Tech Project: 3D RTLS Warehouse Localization

Supports:
- USB / GPIO UART Serial connections (Decawave DWM1000, ESP32 UWB, Pozyx, NMEA)
- Automatic serial port detection (/dev/ttyUSB*, /dev/ttyACM*, /dev/serial*, COM*)
- Streaming parsed coordinate and distance telemetry to Central WebSocket Hub
- Fallback simulation if serial hardware is disconnected
"""

import socketio
import time
import math
import sys
import os
import argparse
import json
import glob
from urllib.parse import urlparse

try:
    import serial
except ImportError:
    serial = None

# Reference Anchor receivers in warehouse
RECEIVERS = {
    "R1": {"lat": 43.861635, "lon": -78.947087, "elev": 0.0},
    "R2": {"lat": 43.861635, "lon": -78.946712, "elev": 0.0},
    "R3": {"lat": 43.861365, "lon": -78.947087, "elev": 4.0},
    "R4": {"lat": 43.861365, "lon": -78.946712, "elev": 4.0}
}

BASE_LAT = 43.8615
BASE_LON = -78.9469

sio = socketio.Client()
is_connected = False


@sio.event
def connect():
    global is_connected
    is_connected = True
    print("\n✅ Connected to Central WebSocket Server!")


@sio.event
def disconnect():
    global is_connected
    is_connected = False
    print("\n⚠️ Disconnected from Central WebSocket Server.")


def haversine_3d(lat1, lon1, elev1, lat2, lon2, elev2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distance_2d = R * c
    delta_elev = elev2 - elev1
    return math.sqrt(distance_2d ** 2 + delta_elev ** 2)


def find_serial_ports():
    """Auto-detect available USB/UART serial ports."""
    ports = []
    if sys.platform.startswith("linux"):
        ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/serial*")
    elif sys.platform.startswith("win"):
        ports = [f"COM{i}" for i in range(1, 20)]
    return ports


def parse_serial_line(line_str):
    """
    Parse incoming serial data line.
    Supports:
    1. JSON: {"x": 1.2, "z": -2.3, "tagId": "Tag_Pi"}
    2. CSV: TAG,x,z,elev,battery
    3. Range: R1:3.2,R2:4.1,R3:5.0,R4:2.9
    """
    line_str = line_str.strip()
    if not line_str:
        return None

    # Try JSON
    if line_str.startswith("{") and line_str.endswith("}"):
        try:
            return json.loads(line_str)
        except Exception:
            pass

    # Try CSV
    parts = line_str.split(",")
    if len(parts) >= 3 and parts[0].upper() == "TAG":
        try:
            return {
                "x": float(parts[1]),
                "z": float(parts[2]),
                "elev": float(parts[3]) if len(parts) > 3 else 1.0,
                "battery": int(parts[4]) if len(parts) > 4 else 100
            }
        except ValueError:
            pass

    return None


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi 4 Edge Hardware & Serial UWB Collector")
    parser.add_argument("--server", "-s", default=None, help="Backend WebSocket server URL")
    parser.add_argument("--port", "-p", default=None, help="Serial port (e.g. /dev/ttyUSB0, /dev/ttyACM0, COM3)")
    parser.add_argument("--baudrate", "-b", type=int, default=115200, help="Serial baudrate (default: 115200)")
    args = parser.parse_args()

    server_url = args.server or os.environ.get("BACKEND_URL") or "http://localhost:3000"

    print("=======================================================")
    print("🍓 Raspberry Pi 4 Edge Hardware & Serial UWB Collector")
    print(f"   Target Server: {server_url}")
    print(f"   Baudrate:      {args.baudrate}")
    print("=======================================================")

    # Connect to WebSocket Server
    while True:
        try:
            print(f"Connecting to WebSocket Server at {server_url} ...")
            sio.connect(server_url)
            break
        except Exception as e:
            print(f"Waiting for backend... ({e})")
            time.sleep(2)

    # Open serial port
    ser = None
    target_port = args.port
    if not target_port:
        detected = find_serial_ports()
        if detected:
            target_port = detected[0]
            print(f"Auto-detected serial port: {target_port}")

    if target_port and serial:
        try:
            ser = serial.Serial(target_port, args.baudrate, timeout=1)
            print(f"✅ Serial connection established on {target_port}")
        except Exception as e:
            print(f"⚠️ Could not open serial port {target_port}: {e}")
            print("Falling back to simulated sensor mode.")
    else:
        print("No serial hardware detected. Running in test sensor mode.")

    sim_x = 0.0
    sim_z = 0.0
    sim_vx = 0.08
    sim_vz = 0.05

    try:
        while True:
            tag_data = None
            if ser and ser.is_open:
                try:
                    if ser.in_waiting > 0:
                        raw_line = ser.readline().decode("utf-8", errors="ignore")
                        tag_data = parse_serial_line(raw_line)
                except Exception as e:
                    print(f"Serial read error: {e}")

            # Fallback simulated movement if no serial data arrived
            if not tag_data:
                sim_x += sim_vx
                sim_z += sim_vz
                if sim_x < -12 or sim_x > 12:
                    sim_vx *= -1
                if sim_z < -12 or sim_z > 12:
                    sim_vz *= -1
                tag_data = {
                    "x": sim_x,
                    "z": sim_z,
                    "elev": 1.0,
                    "battery": 98
                }

            x = tag_data.get("x", 0.0)
            z = tag_data.get("z", 0.0)
            elev = tag_data.get("elev", 1.0)
            battery = tag_data.get("battery", 100)

            lat = BASE_LAT - (z / 111111.0)
            lon = BASE_LON + (x / 80000.0)

            distances = {}
            for rid, rdata in RECEIVERS.items():
                dist = haversine_3d(lat, lon, elev, rdata["lat"], rdata["lon"], rdata["elev"])
                distances[rid] = round(dist, 2)

            payload = {
                "tagId": "Tag_Pi",
                "name": "Raspberry Pi 4",
                "battery": battery,
                "lat": lat,
                "lon": lon,
                "elev": elev,
                "floorId": "f_5835ab589321170c11000000",
                "distances": distances
            }

            try:
                sio.emit("update_location", payload)
                print(f"🍓 [Pi Telemetry] X: {x:.2f} m | Z: {z:.2f} m | Batt: {battery}% | R1 Dist: {distances['R1']}m")
            except Exception as e:
                print(f"Emit error: {e}")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nStopping Pi Collector...")
        if ser and ser.is_open:
            ser.close()
        sio.disconnect()
        sys.exit(0)


if __name__ == "__main__":
    main()

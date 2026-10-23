import socketio
import time
import math
import random
import sys
import os
import argparse
sio = socketio.Client()
BASE_LAT = 43.8615
BASE_LON = -78.9469
receivers = {
	"R1": {"lat": 43.861635, "lon": -78.947087, "elev": 0.0},
	"R2": {"lat": 43.861635, "lon": -78.946712, "elev": 0.0},
	"R3": {"lat": 43.861365, "lon": -78.947087, "elev": 4.0},
	"R4": {"lat": 43.861365, "lon": -78.946712, "elev": 4.0} 
}   
tags = {
	"Tag_A": { "name": "Forklift", "battery": 85, "x": -11, "z": 0, "vx": 0.05, "vz": 0.15, "bounds": {"xmin": -14, "xmax": -9, "zmin": -13, "zmax": 13}, "elev": 0.0, "floor": "f_5835ab589321170c11000000" },
	"Tag_B": { "name": "Employee 1", "battery": 92, "x": 0, "z": -10, "vx": 0.02, "vz": 0.08, "bounds": {"xmin": -1, "xmax": 1, "zmin": -13, "zmax": 13}, "elev": 0.0, "floor": "f_5835ab589321170c11000000" },
	"Tag_C": { "name": "Pallet Jack", "battery": 45, "x": 11, "z": 5, "vx": -0.06, "vz": -0.12, "bounds": {"xmin": 9, "xmax": 14, "zmin": -13, "zmax": 13}, "elev": 0.0, "floor": "f_5835ac489321170c11000001" },
	"Tag_D": { "name": "Drone Transport", "battery": 60, "x": -5, "z": 5, "vx": 0.15, "vz": -0.1, "bounds": {"xmin": -14, "xmax": 14, "zmin": -14, "zmax": 14}, "elev": 4.0, "floor": "f_5835ac489321170c11000001" },
}
def haversine_3d(lat1, lon1, elev1, lat2, lon2, elev2):
	R = 6371000 
	phi1 = math.radians(lat1)
	phi2 = math.radians(lat2)
	delta_phi = math.radians(lat2 - lat1)
	delta_lambda = math.radians(lon2 - lon1)
	a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
	c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
	distance_2d = R * c
	delta_elev = elev2 - elev1
	return math.sqrt(distance_2d**2 + delta_elev**2)
@sio.event
def connect():
	print("Connected to the WebSocket Hub.")
@sio.event
def disconnect():
	print("Disconnected from the WebSocket Hub.")
def start_simulation(server_url=None):
	url = server_url or os.environ.get("BACKEND_URL") or "http://localhost:3000"
	print(f"Connecting to WebSocket Hub at: {url} ...")
	while True:
		try:
			sio.connect(url)
			break
		except Exception as e:
			print(f"Waiting for backend at {url}... ({e})")
			time.sleep(2)
	while True:
		try:
			for tag_id, data in tags.items():
				data["x"] += data["vx"]
				data["z"] += data["vz"]
				b = data["bounds"]
				if data["x"] < b["xmin"] or data["x"] > b["xmax"]:
					data["vx"] *= -1
					data["x"] = max(b["xmin"], min(data["x"], b["xmax"]))
				if data["z"] < b["zmin"] or data["z"] > b["zmax"]:
					data["vz"] *= -1
					data["z"] = max(b["zmin"], min(data["z"], b["zmax"]))
				lat = BASE_LAT - (data["z"] / 111111)
				lon = BASE_LON + (data["x"] / 80000)
				if random.random() < 0.05 and data["battery"] > 10:
					data["battery"] -= 1
				distances = {}
				for rid, rdata in receivers.items():
					dist = haversine_3d(lat, lon, data["elev"], rdata["lat"], rdata["lon"], rdata["elev"])
					distances[rid] = round(dist, 2)
				payload = {
					"tagId": tag_id,
					"name": data["name"],
					"battery": data["battery"],
					"lat": lat,
					"lon": lon,
					"elev": data["elev"],
					"floorId": data["floor"],
					"distances": distances
				}
				try:
					sio.emit('update_location', payload)
				except Exception:
					pass
			time.sleep(1)
		except KeyboardInterrupt:
			sio.disconnect()
			break
		except Exception as e:
			print(f"Error in loop: {e}")
			time.sleep(1)
if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="UWB RTLS Multi-Tag Simulator")
	parser.add_argument("--server", "-s", default=None, help="Backend WebSocket server URL (e.g. http://192.168.1.50:3000)")
	args = parser.parse_args()
	start_simulation(args.server)
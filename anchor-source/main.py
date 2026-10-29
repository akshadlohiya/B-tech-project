"""Gateway entrypoint: data source -> location engine -> hub.

Loads the shared site config, picks a data source (sim or hardware), solves each
reading into a position estimate, and streams both to the backend hub.

    python main.py                 # simulate every map in the library, concurrently
    MAP=demo,abc123 python main.py # only these maps
    SOURCE=hardware python main.py # real MaUWB_DW3000 nodes over UDP (one map)

On real hardware this same process runs on the gateway/Pi: it ingests readings and
runs the identical solver — nothing downstream changes.

Each map runs on its own thread. It also hot-reloads: when the dashboard edits a
map (backend broadcasts `map_updated`), that map's source and engine rebuild live,
and maps created or deleted in the library (`maps_changed`) start or stop without
a restart. Maps fed by another producer (`meta.producer`, e.g. the TDOA streamer)
are skipped.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_SHARED_DIR = _PROJECT_ROOT / "shared"
_ENGINE_DIR = _PROJECT_ROOT / "location-engine"

for _path in (_HERE, _SHARED_DIR, _ENGINE_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

import socketio  # noqa: E402
import requests  # noqa: E402


def _load_module(module_name: str, filename: str, search_roots: tuple[Path, ...]) -> object:
    for root in search_roots:
        module_path = root / filename
        if module_path.exists():
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module
    raise ModuleNotFoundError(f"Could not resolve {module_name!r} from {filename!r}")

site_config = _load_module("site_config", "site_config.py", (_SHARED_DIR,))
anchor_source = _load_module("anchor_source", "anchor_source.py", (_HERE,))
engine = _load_module("engine", "engine.py", (_ENGINE_DIR,))

load_site = site_config.load_site
make_source = anchor_source.make_source
LocationEngine = engine.LocationEngine

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:3000")
SOURCE_KIND = os.environ.get("SOURCE", "sim")
# Which maps this gateway runs: "all" (every map in the library, picking up new
# ones as they are created), or a comma-separated list of keys. Real hardware
# listens on a single UDP port, so it can only feed one map.
MAP_SPEC = os.environ.get("MAP", "all" if SOURCE_KIND == "sim" else "demo")

sio = socketio.Client(reconnection=True)
_runners: dict = {}            # mapKey -> MapRunner
_runners_lock = threading.Lock()
_sync_requested = threading.Event()


def load_map(key: str, fallback: bool = True) -> Optional[dict]:
    """Fetch the map document from the backend; optionally fall back to the local file."""
    try:
        r = requests.get(f"{BACKEND_URL}/api/maps/{key}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        if not fallback:
            print(f"[gateway] could not fetch map '{key}' ({exc})")
            return None
        print(f"[gateway] could not fetch map '{key}' ({exc}); falling back to local site.json")
        return load_site()


def wanted_keys() -> set:
    """The map keys this gateway should be running right now."""
    if MAP_SPEC.strip().lower() != "all":
        return {k.strip() for k in MAP_SPEC.split(",") if k.strip()}
    try:
        r = requests.get(f"{BACKEND_URL}/api/maps", timeout=5)
        r.raise_for_status()
    except Exception as exc:
        print(f"[gateway] could not list maps ({exc})")
        with _runners_lock:
            return set(_runners)   # keep whatever is running
    # Maps fed by another producer (e.g. the TDOA/EKF streamer) are left alone.
    return {m["key"] for m in r.json() if m.get("producer") in (None, "gateway")}


class MapRunner(threading.Thread):
    """Simulates/solves one map and streams it to the hub, on its own thread."""

    def __init__(self, key: str):
        super().__init__(name=f"map-{key}", daemon=True)
        self.key = key
        self.stop_event = threading.Event()
        self.reload_requested = False

    def _build(self):
        site = load_map(self.key, fallback=(self.key == "demo"))
        if site is None:
            return None
        source = make_source(SOURCE_KIND, site)
        engine = LocationEngine(site)
        print(f"[gateway] map='{site.get('meta', {}).get('name', self.key)}' key='{self.key}' "
              f"source='{source.name}' tags={len(site['tags'])} anchors={len(site['anchors'])}")
        print(f"[gateway] [{self.key}] NLOS handling: {engine.nlos_note}")
        return source, engine, source.cycles()

    def run(self) -> None:
        try:
            built = self._build()
            if built is None:
                return
            source, engine, cycles = built
            while not self.stop_event.is_set():
                if self.reload_requested:
                    self.reload_requested = False
                    source.close()   # hardware: free UDP 9000 before the new source binds it
                    built = self._build()
                    if built is None:
                        return
                    source, engine, cycles = built

                reading, truth = next(cycles)
                reading_dict = reading.to_dict()
                reading_dict["mapKey"] = self.key
                estimate = engine.estimate(reading_dict, truth)
                if estimate is not None:
                    estimate["mapKey"] = self.key
                alerts = (estimate["alerts"] if estimate is not None else []) + engine.check_stale(reading_dict["t"])
                # ride out transient disconnects: the client auto-reconnects, so skip
                # emitting mid-reconnect rather than crashing on BadNamespaceError.
                if sio.connected:
                    try:
                        sio.emit("reading", reading_dict)
                        if estimate is not None:
                            sio.emit("update_location", estimate)
                        for alert in alerts:
                            sio.emit("alert", {**alert, "mapKey": self.key})
                    except Exception:
                        pass
        except StopIteration:
            pass
        except Exception as exc:   # one bad map must not take the others down
            print(f"[gateway] map '{self.key}' stopped: {exc!r}")
        finally:
            try:
                source.close()
            except Exception:
                pass
            with _runners_lock:
                if _runners.get(self.key) is self:
                    del _runners[self.key]


def sync_runners() -> None:
    """Start runners for new maps and stop runners for deleted ones."""
    want = wanted_keys()
    if SOURCE_KIND != "sim" and len(want) > 1:
        print(f"[gateway] SOURCE={SOURCE_KIND} can only feed one map; set MAP=<key> (got {sorted(want)})")
        want = set(sorted(want)[:1])
    with _runners_lock:
        for key in set(_runners) - want:
            print(f"[gateway] map '{key}' removed — stopping")
            _runners.pop(key).stop_event.set()
        for key in want - set(_runners):
            runner = _runners[key] = MapRunner(key)
            runner.start()
            if sio.connected:
                sio.emit("join_map", key)   # so we receive map_updated for this map


@sio.event
def connect():
    print(f"[gateway] connected to hub at {BACKEND_URL}")
    with _runners_lock:
        keys = list(_runners)
    for key in keys:
        sio.emit("join_map", key)
    _sync_requested.set()   # pick up maps created while we were disconnected


@sio.event
def disconnect():
    print("[gateway] disconnected from hub")


@sio.on("map_updated")
def _on_map_updated(data=None):
    key = (data or {}).get("key")
    with _runners_lock:
        targets = [r for k, r in _runners.items() if key is None or k == key]
    for runner in targets:
        runner.reload_requested = True
        print(f"[gateway] map '{runner.key}' changed — reloading source + engine")


@sio.on("maps_changed")
def _on_maps_changed(data=None):
    _sync_requested.set()


def main() -> None:
    while True:
        try:
            sio.connect(BACKEND_URL)
            break
        except Exception:
            print(f"[gateway] hub not up yet, retrying {BACKEND_URL} ...")
            time.sleep(2)

    try:
        while True:
            sync_runners()
            # resync on a create/delete broadcast, or every 10 s as a fallback
            _sync_requested.wait(timeout=10)
            _sync_requested.clear()
    except KeyboardInterrupt:
        pass
    finally:
        with _runners_lock:
            for runner in _runners.values():
                runner.stop_event.set()
        sio.disconnect()


if __name__ == "__main__":
    main()

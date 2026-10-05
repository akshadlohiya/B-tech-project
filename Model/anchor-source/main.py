"""Gateway entrypoint: data source -> location engine -> hub.

Loads the shared site config, picks a data source (sim or hardware), solves each
reading into a position estimate, and streams both to the backend hub.

    python main.py                 # simulated anchors (default)
    SOURCE=hardware python main.py # real MaUWB_DW3000 nodes over UDP

On real hardware this same process runs on the gateway/Pi: it ingests readings and
runs the identical solver — nothing downstream changes.

It also hot-reloads: when the dashboard edits the site (backend broadcasts
`site_updated`), the source and engine rebuild live without a restart.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

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
MAP_KEY = os.environ.get("MAP", "demo")   # which map this gateway runs

sio = socketio.Client(reconnection=True)
_reload_requested = False


def load_map(key: str) -> dict:
    """Fetch the map document from the backend; fall back to the local file."""
    try:
        r = requests.get(f"{BACKEND_URL}/api/maps/{key}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"[gateway] could not fetch map '{key}' ({exc}); falling back to local site.json")
        return load_site()


@sio.event
def connect():
    print(f"[gateway] connected to hub at {BACKEND_URL}")
    sio.emit("join_map", MAP_KEY)   # so we receive map_updated for our map


@sio.event
def disconnect():
    print("[gateway] disconnected from hub")


@sio.on("map_updated")
def _on_map_updated(data=None):
    global _reload_requested
    if not data or data.get("key") == MAP_KEY:
        _reload_requested = True
        print(f"[gateway] map '{MAP_KEY}' changed — reloading source + engine")


def _build():
    site = load_map(MAP_KEY)
    source = make_source(SOURCE_KIND, site)
    engine = LocationEngine(site)
    print(f"[gateway] map='{site.get('meta', {}).get('name', MAP_KEY)}' key='{MAP_KEY}' "
          f"source='{source.name}' tags={len(site['tags'])} anchors={len(site['anchors'])}")
    return source, engine, source.cycles()


def main() -> None:
    global _reload_requested
    source, engine, cycles = _build()

    while True:
        try:
            sio.connect(BACKEND_URL)
            break
        except Exception:
            print(f"[gateway] hub not up yet, retrying {BACKEND_URL} ...")
            time.sleep(2)

    try:
        while True:
            if _reload_requested:
                _reload_requested = False
                source, engine, cycles = _build()

            reading, truth = next(cycles)
            reading_dict = reading.to_dict()
            reading_dict["mapKey"] = MAP_KEY
            estimate = engine.estimate(reading_dict, truth)
            if estimate is not None:
                estimate["mapKey"] = MAP_KEY
            # ride out transient disconnects: the client auto-reconnects, so skip
            # emitting mid-reconnect rather than crashing on BadNamespaceError.
            if sio.connected:
                try:
                    sio.emit("reading", reading_dict)
                    if estimate is not None:
                        sio.emit("update_location", estimate)
                except Exception:
                    pass
    except (KeyboardInterrupt, StopIteration):
        pass
    finally:
        sio.disconnect()


if __name__ == "__main__":
    main()

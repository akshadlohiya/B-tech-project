"""Tests for the hardware source's cycle assembly. Run:  pytest anchor-source -q"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "shared"))

import hardware_source  # noqa: E402
from hardware_source import CycleAssembler, HardwareAnchorSource  # noqa: E402
from reading import AnchorRange  # noqa: E402

ANCHORS = ["A1", "A2", "A3", "A4", "A5"]


def ar(anchor, r=5.0):
    return AnchorRange(anchor_id=anchor, range_m=r, rx_power_dbm=-80.0, fp_power_dbm=-83.0, nlos=False)


def ids(released):
    return [(tag, sorted(a.anchor_id for a in ranges)) for tag, ranges, _t in released]


# ---------------------------------------------------------------- assembler
def test_full_cycle_released_immediately():
    asm = CycleAssembler(5, window_s=0.16)
    out = []
    for i, a in enumerate(ANCHORS):
        out += asm.add("T1", ar(a), now=i * 0.01)
    assert ids(out) == [("T1", ANCHORS)]

def test_silent_anchor_does_not_freeze_the_tag():
    asm = CycleAssembler(5, window_s=0.16)
    for i, a in enumerate(ANCHORS[:4]):          # A5 blocked
        assert asm.add("T1", ar(a), now=i * 0.01) == []
    assert asm.flush(now=0.1) == []              # still inside the window
    assert ids(asm.flush(now=0.17)) == [("T1", ANCHORS[:4])]

def test_repeat_anchor_starts_a_new_cycle_without_mixing():
    asm = CycleAssembler(5, window_s=10.0)       # window never expires here
    for a in ANCHORS[:3]:
        asm.add("T1", ar(a, r=1.0), now=0.0)
    out = asm.add("T1", ar("A1", r=2.0), now=0.2)   # A1 again: previous cycle is over
    assert ids(out) == [("T1", ANCHORS[:3])]
    assert all(x.range_m == 1.0 for x in out[0][1])  # no range from the new cycle leaked in
    out = []
    for a in ANCHORS[1:]:
        out += asm.add("T1", ar(a, r=2.0), now=0.25)
    assert ids(out) == [("T1", ANCHORS)] and all(x.range_m == 2.0 for x in out[0][1])

def test_cycle_with_too_few_anchors_is_dropped():
    asm = CycleAssembler(5, window_s=0.16)
    asm.add("T1", ar("A1"), now=0.0)
    asm.add("T1", ar("A2"), now=0.01)
    assert asm.flush(now=1.0) == []
    assert asm.add("T1", ar("A1"), now=1.1) == []   # old partial cycle is gone, not merged

def test_tags_are_assembled_independently():
    asm = CycleAssembler(3, window_s=0.16)
    out = []
    for a in ANCHORS[:3]:
        out += asm.add("T1", ar(a), now=0.0)
        out += asm.add("T2", ar(a), now=0.0)
    assert sorted(ids(out)) == [("T1", ANCHORS[:3]), ("T2", ANCHORS[:3])]

def test_cycle_time_is_its_first_packet():
    asm = CycleAssembler(3, window_s=0.16)
    asm.add("T1", ar("A1"), now=5.00)
    asm.add("T1", ar("A2"), now=5.03)
    (_tag, _ranges, t0), = asm.add("T1", ar("A3"), now=5.06)
    assert t0 == 5.00

def test_site_with_fewer_than_three_anchors_still_releases():
    asm = CycleAssembler(2, window_s=0.16)
    asm.add("T1", ar("A1"), now=0.0)
    assert len(asm.add("T1", ar("A2"), now=0.0)) == 1


# ---------------------------------------------------------------- over real UDP
def test_udp_source_keeps_tracking_with_a_silent_anchor(monkeypatch):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(hardware_source, "LISTEN_HOST", "127.0.0.1")
    monkeypatch.setattr(hardware_source, "LISTEN_PORT", port)
    site = {"anchors": [{"id": a} for a in ANCHORS], "ranging": {"updateRateHz": 5}}
    src = HardwareAnchorSource(site)

    def send():
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for cycle in range(5):
            for a in ANCHORS[:4]:   # A5 never answers
                pkt = {"tag": "T1", "anchor": a, "range": 5.0 + cycle, "rxPower": -80, "fpPower": -83}
                tx.sendto(json.dumps(pkt).encode(), ("127.0.0.1", port))
            time.sleep(0.2)
        tx.close()

    threading.Thread(target=send, daemon=True).start()
    it = src.cycles()
    readings = [next(it)[0] for _ in range(5)]
    src._sock.close()
    assert [r.seq for r in readings] == [1, 2, 3, 4, 5]
    for cycle, r in enumerate(readings):
        assert sorted(x.anchor_id for x in r.ranges) == ANCHORS[:4]
        assert {x.range_m for x in r.ranges} == {5.0 + cycle}
        assert r.source == "hardware"


def test_closed_source_frees_the_port_for_a_map_reload(monkeypatch):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(hardware_source, "LISTEN_HOST", "127.0.0.1")
    monkeypatch.setattr(hardware_source, "LISTEN_PORT", port)
    site = {"anchors": [{"id": a} for a in ANCHORS[:3]], "ranging": {"updateRateHz": 5}}
    old = HardwareAnchorSource(site)
    try:
        HardwareAnchorSource(site)
        assert False, "expected OSError when binding port twice"
    except OSError:
        pass
    old.close()
    HardwareAnchorSource(site).close()    # rebuilt source binds the same port


if __name__ == "__main__":
    test_full_cycle_released_immediately()
    test_silent_anchor_does_not_freeze_the_tag()
    test_repeat_anchor_starts_a_new_cycle_without_mixing()
    test_cycle_with_too_few_anchors_is_dropped()
    test_tags_are_assembled_independently()
    test_cycle_time_is_its_first_packet()
    test_site_with_fewer_than_three_anchors_still_releases()
    class _MockMonkeyPatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)
    test_udp_source_keeps_tracking_with_a_silent_anchor(_MockMonkeyPatch())
    test_closed_source_frees_the_port_for_a_map_reload(_MockMonkeyPatch())
    print("All test_hardware_source tests passed!")

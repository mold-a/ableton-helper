"""End-to-end: the real Remote Script (over fake Live objects) <-TCP-> TcpBridge <-> SoundEngine/agent.

Every other test exercises one side of the bridge against an emulation of the other side.
This one runs the actual Remote Script dispatcher and socket server, pumped from a thread
that plays the role of Live's main thread, and drives it with the real backend client.
"""

import json
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for p in (os.path.join(ROOT, "remote_script"), os.path.join(ROOT, "remote_script", "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

rs_fakes = pytest.importorskip("rs_fakes")

from abhelper.bridge.client import TcpBridge  # noqa: E402
from abhelper.sound import SoundEngine, SoundRequest  # noqa: E402

CATALOG = json.loads(open(os.path.join(ROOT, "backend", "abhelper", "sound", "data", "device_catalog.json"),
                          encoding="utf-8").read())["devices"]
TYPE_INT = {"instrument": 1, "audio_effect": 2, "midi_effect": 4}


def device_from_catalog(name):
    spec = CATALOG.get(name)
    if spec is None:
        raise RuntimeError("unknown device %s" % name)
    params = []
    for p in spec.get("parameters", []):
        if p["name"] == "Device On":
            continue
        items = p.get("value_items") or None
        lo, hi = float(p.get("min", 0.0)), float(p.get("max", 1.0))
        params.append(rs_fakes.FakeParam(p["name"], float(p.get("default", lo)), lo, hi, items=items))
    return rs_fakes.FakeDevice(name, spec.get("class_name"), TYPE_INT.get(spec.get("type"), 0), params)


class CatalogTrack(rs_fakes.FakeTrack):
    """A Live 12.3+ track whose insert_device builds devices with the catalog's parameters."""

    def insert_device(self, name, index=None):
        dev = device_from_catalog(name)
        if dev.type == 1:
            self.devices = [d for d in self.devices if d.type != 1]
            self.devices.insert(0, dev)
        else:
            self.devices.insert(len(self.devices) if index is None else index, dev)
        return dev


@pytest.fixture
def live(monkeypatch):
    """Start the Remote Script on an ephemeral port and pump it like Live's main thread."""
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "0")
    # Inside Live `import Live` provides Live.Clip.MidiNoteSpecification; stand it in here.
    monkeypatch.setitem(sys.modules, "Live", rs_fakes.FakeLive)
    import AbletonHelper

    song, app = rs_fakes.make_world(midi_tracks=1)
    song._track_class = CatalogTrack
    surface = AbletonHelper.create_instance(rs_fakes.FakeCInstance(song, app))
    port = surface.server.port if hasattr(surface.server, "port") else surface.server.address[1]
    stop = threading.Event()

    def main_thread():
        while not stop.is_set():
            surface.update_display()
            time.sleep(0.01)

    t = threading.Thread(target=main_thread, daemon=True)
    t.start()
    bridge = TcpBridge("127.0.0.1", port, timeout=10.0)
    try:
        yield song, bridge
    finally:
        bridge.close()
        stop.set()
        t.join(2)
        surface.disconnect()


def test_ping_over_real_socket(live):
    song, bridge = live
    info = bridge.call("ping")
    assert info["pong"] is True
    assert info["live_version"].startswith("12.")


def test_create_bayan_through_real_remote_script(live):
    song, bridge = live
    engine = SoundEngine(bridge)
    res = engine.create_sound(SoundRequest(description="хочу звук баяна", strategy="recipe"))

    assert res.ok, res.to_dict()
    assert res.recipe_id == "bayan"
    track = song.tracks[res.track_index]
    assert track.name == "Баян"
    names = [d.name for d in track.devices]
    assert names[0] == "Operator"
    assert len(names) > 1, "effects chain should be loaded"
    assert res.unmatched_parameters == [], res.unmatched_parameters
    # parameters really changed inside the fake Live device, not just in the engine's bookkeeping
    op = track.devices[0]
    algo = next(p for p in op.parameters if p.name == "Algorithm")
    assert algo.value == 10
    # demo clip with notes
    assert res.demo_clip_slot is not None
    clip = track.clip_slots[res.demo_clip_slot].clip
    assert clip is not None and len(clip.notes) > 0
    assert not any("демо" in w.lower() for w in res.warnings), res.warnings


def test_demo_clip_failure_is_reported_not_fatal(live, monkeypatch):
    """Without the Live module add_notes is unsupported: the sound must still be created."""
    monkeypatch.delitem(sys.modules, "Live")
    song, bridge = live
    res = SoundEngine(bridge).create_sound(SoundRequest(description="рояль", strategy="recipe"))
    assert res.ok and res.track_index is not None
    assert res.warnings, "the failed demo clip must surface as a warning"


def test_agent_tool_executor_over_real_remote_script(live):
    """The agent's tool layer (what the LLM calls) works over the real bridge."""
    from abhelper.agent.tools import ToolExecutor
    from abhelper.knowledge import KnowledgeBase

    song, bridge = live
    ex = ToolExecutor(bridge, SoundEngine(bridge), KnowledgeBase(), None)
    found = ex.execute("search_sound_library", {"query": "гармошка"})
    assert found.ok and "bayan" in found.model_content()
    created = ex.execute("create_sound", {"description": "звук баяна", "recipe_id": "bayan", "strategy": "recipe"})
    assert created.ok, created.model_content()
    overview = ex.execute("get_session_overview", {})
    assert overview.ok and "Баян" in overview.model_content()

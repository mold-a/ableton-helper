"""The Control Surface glue with a fake c_instance (no Live)."""
import json
import socket
import sys
import time
import types

import pytest

from rs_fakes import FakeCInstance, make_world


def make_surface(monkeypatch, port=0, **world):
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", str(port))
    import AbletonHelper
    song, app = make_world(**world)
    c = FakeCInstance(song, app)
    surface = AbletonHelper.create_instance(c)
    return surface, c, song, app


def roundtrip(surface, port, command, params=None):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(json.dumps({"id": "1", "command": command, "params": params or {}}).encode() + b"\n")
    import threading
    out = []

    def reader():
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(65536)
        out.append(json.loads(buf.split(b"\n")[0]))

    t = threading.Thread(target=reader)
    t.start()
    deadline = time.time() + 5
    while t.is_alive() and time.time() < deadline:
        surface.update_display()
        time.sleep(0.005)
    t.join(1)
    s.close()
    return out[0]


def test_create_instance_serves_requests_and_disconnects(monkeypatch):
    surface, c, song, app = make_surface(monkeypatch)
    try:
        assert type(surface).__name__ == "AbletonHelper"
        port = surface.server.port
        assert any("listening" in m for m in c.shown)
        env = roundtrip(surface, port, "create_midi_track", {"name": "Баян"})
        assert env["ok"] and song.tracks[-1].name == "Баян"
    finally:
        surface.disconnect()
    assert surface.server is None
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_update_display_advances_browser_index(monkeypatch):
    import AbletonHelper.surface as surf
    monkeypatch.setattr(surf, "INDEX_START_DELAY", 0.0)
    surface, c, song, app = make_surface(monkeypatch)
    try:
        for _ in range(50):
            surface.update_display()
            if surface.index.status()["complete"]:
                break
        assert surface.index.status()["complete"] and surface.index.status()["indexed"] == 11
    finally:
        surface.disconnect()


def test_port_from_env_and_invalid_env(monkeypatch):
    from AbletonHelper.surface import read_port
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "12345")
    assert read_port() == 12345
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "abc")
    assert read_port() == 9888
    monkeypatch.delenv("ABHELPER_BRIDGE_PORT")
    assert read_port() == 9888


def test_busy_port_does_not_crash(monkeypatch):
    first, c1, _s, _a = make_surface(monkeypatch)
    try:
        busy = first.server.port
        second, c2, _s2, _a2 = make_surface(monkeypatch, port=busy)
        assert second.server is None
        assert any("cannot listen" in m for m in c2.messages)
        second.update_display()    # must not raise
        second.disconnect()
    finally:
        first.disconnect()


def test_exceptions_never_escape_update_display(monkeypatch):
    surface, c, song, app = make_surface(monkeypatch)
    try:
        def boom(*a, **k):
            raise RuntimeError("x")
        surface.server.process_pending = boom
        surface.update_display()
        assert any("tick failed" in m for m in c.messages)
    finally:
        surface.disconnect()


def test_control_surface_base_class_is_injectable(monkeypatch):
    fake_fw = types.ModuleType("_Framework")
    fake_cs = types.ModuleType("_Framework.ControlSurface")

    class FakeControlSurface(object):
        def __init__(self, c_instance):
            self._c_instance = c_instance
            self.base_called = True

        def song(self):
            return self._c_instance.song()

        def application(self):
            return self._c_instance.application()

        def log_message(self, *m):
            self._c_instance.log_message(" ".join(m))

        def show_message(self, m):
            self._c_instance.show_message(m)

        def update_display(self):
            pass

        def disconnect(self):
            pass

    fake_cs.ControlSurface = FakeControlSurface
    monkeypatch.setitem(sys.modules, "_Framework", fake_fw)
    monkeypatch.setitem(sys.modules, "_Framework.ControlSurface", fake_cs)
    import importlib
    import AbletonHelper.surface as surf
    try:
        importlib.reload(surf)
        assert issubclass(surf.AbletonHelper, FakeControlSurface)
        monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "0")
        song, app = make_world()
        s = surf.AbletonHelper(FakeCInstance(song, app))
        assert s.base_called and s.server is not None
        s.disconnect()
    finally:
        monkeypatch.delitem(sys.modules, "_Framework")
        monkeypatch.delitem(sys.modules, "_Framework.ControlSurface")
        importlib.reload(surf)

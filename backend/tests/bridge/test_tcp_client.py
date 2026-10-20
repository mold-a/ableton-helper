import json
import socket
import threading
import time

import pytest

from abhelper.bridge import BridgeCommandError, BridgeConnectionError
from abhelper.bridge.client import SerializedBridge, TcpBridge


class FakeLiveServer:
    """Tiny JSON-lines TCP server standing in for the Remote Script."""

    def __init__(self, handler=None):
        self.handler = handler or self.default_handler
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.requests = []
        self.connections = 0
        self.conns = []
        self._stop = False
        self.t = threading.Thread(target=self._accept, daemon=True)
        self.t.start()

    @staticmethod
    def default_handler(req):
        cmd = req["command"]
        if cmd == "ping":
            return {"ok": True, "result": {"pong": True, "script_version": "0.1.0", "live_version": "12.1.5"}}
        if cmd == "echo":
            return {"ok": True, "result": {"params": req.get("params")}}
        if cmd == "boom":
            return {"ok": False, "error": {"code": "not_found", "message": "Track 7 does not exist"}}
        return {"ok": True, "result": {}}

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            self.conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        buf = b""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    req = json.loads(line.decode())
                    self.requests.append(req)
                    resp = self.handler(req)
                    if resp is None:
                        continue  # no reply
                    if resp == "DROP":
                        conn.close()
                        return
                    if resp == "GARBAGE":
                        conn.sendall(b"not json\n")
                        continue
                    resp = dict(resp, id=req["id"])
                    conn.sendall(json.dumps(resp, ensure_ascii=False).encode() + b"\n")
        except OSError:
            pass

    def drop_all(self):
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        self.conns = []

    def close(self):
        self._stop = True
        self.sock.close()
        self.drop_all()


@pytest.fixture
def server():
    s = FakeLiveServer()
    yield s
    s.close()


def test_call_roundtrip_and_ping_handshake(server):
    b = TcpBridge(port=server.port)
    assert not b.is_connected()  # lazy
    out = b.call("echo", {"name": "Баян"})
    assert out == {"params": {"name": "Баян"}}
    assert b.is_connected()
    assert b.script_version == "0.1.0" and b.live_version == "12.1.5"
    assert [r["command"] for r in server.requests] == ["ping", "echo"]
    assert len({r["id"] for r in server.requests}) == 2
    b.close()
    assert not b.is_connected()


def test_error_mapping(server):
    b = TcpBridge(port=server.port)
    with pytest.raises(BridgeCommandError) as e:
        b.call("boom")
    assert e.value.code == "not_found"
    assert "Track 7" in e.value.message
    assert b.call("echo") == {"params": {}}  # connection still usable after ok=false


def test_connection_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    b = TcpBridge(port=port)
    with pytest.raises(BridgeConnectionError):
        b.call("ping")
    assert b.probe() is None
    assert not b.is_connected()


def test_probe_returns_ping(server):
    assert TcpBridge(port=server.port).probe()["live_version"] == "12.1.5"


def test_reconnect_when_server_dropped_idle_connection(server):
    b = TcpBridge(port=server.port)
    b.call("echo")
    assert server.connections == 1
    server.drop_all()
    time.sleep(0.1)
    assert b.call("echo", {"a": 1}) == {"params": {"a": 1}}  # transparent reconnect, request sent once
    assert server.connections == 2
    assert [r["command"] for r in server.requests].count("echo") == 2


def test_no_resend_when_connection_drops_mid_request():
    def handler(req):
        if req["command"] == "ping":
            return FakeLiveServer.default_handler(req)
        return "DROP"

    s = FakeLiveServer(handler)
    try:
        b = TcpBridge(port=s.port)
        with pytest.raises(BridgeConnectionError):
            b.call("create_midi_track")
        time.sleep(0.1)
        assert [r["command"] for r in s.requests].count("create_midi_track") == 1  # NOT retried
    finally:
        s.close()


def test_per_call_deadline_is_total_not_per_read():
    # server trickles a partial line forever; the deadline must still fire on time
    def handler(req):
        if req["command"] == "ping":
            return FakeLiveServer.default_handler(req)
        return None  # never replies

    s = FakeLiveServer(handler)
    try:
        b = TcpBridge(port=s.port, timeout=15)
        t0 = time.monotonic()
        with pytest.raises(BridgeConnectionError):
            b.call("slow", timeout=0.4)
        assert 0.3 < time.monotonic() - t0 < 2.0
        assert not b.is_connected()  # socket dropped so a late reply can't desync the stream
    finally:
        s.close()


def test_timeout_override_allows_slow_reply():
    def handler(req):
        if req["command"] == "slow":
            time.sleep(0.5)
        return FakeLiveServer.default_handler(req) if req["command"] == "ping" else {"ok": True, "result": {"x": 1}}

    s = FakeLiveServer(handler)
    try:
        b = TcpBridge(port=s.port, timeout=0.2)
        with pytest.raises(BridgeConnectionError):
            b.call("slow")
        assert b.call("slow", timeout=5) == {"x": 1}
    finally:
        s.close()


def test_concurrent_calls_are_serialised(server):
    b = TcpBridge(port=server.port)
    results = {}

    def work(i):
        results[i] = b.call("echo", {"i": i})

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == {i: {"params": {"i": i}} for i in range(20)}
    assert server.connections == 1


def test_invalid_json_reply_is_connection_error():
    def handler(req):
        return "GARBAGE" if req["command"] == "echo" else FakeLiveServer.default_handler(req)

    s = FakeLiveServer(handler)
    try:
        b = TcpBridge(port=s.port)
        with pytest.raises(BridgeConnectionError):
            b.call("echo")
        assert not b.is_connected()
    finally:
        s.close()


def test_serialized_bridge_wraps_fake():
    from abhelper.bridge.fake import FakeBridge

    fb = FakeBridge()
    sb = SerializedBridge(fb)
    assert sb.call("ping")["pong"] is True
    assert sb.is_connected()
    assert sb.tracks is fb.tracks

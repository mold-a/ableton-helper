"""End-to-end: real TCP client -> BridgeServer -> fake 'main thread' pumping update_display."""
import json
import socket
import threading
import time

import pytest

from AbletonHelper.server import BridgeServer
from rs_fakes import FakeCInstance, make_dispatcher, make_world


class Pump(object):
    """Stands in for Live's main thread calling update_display() every few ms."""

    def __init__(self, fn, interval=0.005):
        self.fn = fn
        self.interval = interval
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread_ident = None

    def _run(self):
        self.thread_ident = threading.get_ident()
        while not self.stop.is_set():
            if not self.paused.is_set():
                self.fn()
            time.sleep(self.interval)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(2)


class Client(object):
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.buf = b""

    def send_raw(self, data):
        self.sock.sendall(data)

    def send(self, obj):
        self.send_raw(json.dumps(obj).encode("utf-8") + b"\n")

    def recv(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def call(self, command, params=None, rid="1"):
        self.send({"id": rid, "command": command, "params": params or {}})
        return self.recv()

    def close(self):
        self.sock.close()


@pytest.fixture
def stack():
    song, app = make_world()
    d = make_dispatcher(song, app)
    server = BridgeServer(0, log=lambda m: None, request_timeout=1.0)
    port = server.start()
    pump = Pump(lambda: server.process_pending(d.handle, 0.03))
    pump.__enter__()
    yield server, port, d, pump, song
    pump.__exit__()
    server.stop()


def test_roundtrip_and_main_thread_only(stack):
    server, port, d, pump, song = stack
    seen = []
    orig = d.commands["ping"]

    def spy(ctx, params):
        seen.append(threading.get_ident())
        return orig(ctx, params)

    d.commands["ping"] = spy
    c = Client(port)
    env = c.call("ping", rid="abc")
    assert env["id"] == "abc" and env["ok"] and env["result"]["pong"] is True
    assert seen == [pump.thread_ident] and seen[0] != threading.get_ident()
    c.close()


def test_pipelined_requests_stay_in_order_and_unicode(stack):
    server, port, d, pump, song = stack
    c = Client(port)
    msgs = [{"id": str(i), "command": "create_midi_track", "params": {"name": "Баян %d" % i}} for i in range(5)]
    c.send_raw(b"".join(json.dumps(m, ensure_ascii=False).encode("utf-8") + b"\n" for m in msgs))
    replies = [c.recv() for _ in msgs]
    assert [r["id"] for r in replies] == ["0", "1", "2", "3", "4"]
    assert [r["result"]["track_index"] for r in replies] == [1, 2, 3, 4, 5]
    assert song.tracks[3].name == "Баян 2"
    c.close()


def test_multiple_clients(stack):
    server, port, d, pump, song = stack
    clients = [Client(port) for _ in range(4)]
    for i, c in enumerate(clients):
        c.send({"id": "c%d" % i, "command": "get_session_info"})
    for i, c in enumerate(clients):
        r = c.recv()
        assert r["id"] == "c%d" % i and r["result"]["track_count"] == 1
    for c in clients:
        c.close()


def test_bad_json_and_non_object(stack):
    server, port, d, pump, song = stack
    c = Client(port)
    c.send_raw(b"{not json\n")
    assert c.recv()["error"]["code"] == "bad_request"
    c.send_raw(b"[1,2]\n\n")
    assert c.recv()["error"]["code"] == "bad_request"
    c.send_raw(b"\xff\xfe\n")
    assert c.recv()["error"]["code"] == "bad_request"
    c.send({"id": "x"})
    r = c.recv()
    assert r["id"] == "x" and r["error"]["code"] == "bad_request"
    assert c.call("ping")["ok"]     # connection still usable
    c.close()


def test_line_too_long_is_rejected_and_dropped():
    song, app = make_world()
    d = make_dispatcher(song, app)
    server = BridgeServer(0, log=lambda m: None, max_line_bytes=1000)
    port = server.start()
    try:
        with Pump(lambda: server.process_pending(d.handle)):
            c = Client(port)
            c.send_raw(b"x" * 3000)                       # no newline yet: over the limit
            assert c.recv()["error"]["code"] == "bad_request"
            c.send_raw(b"y" * 500 + b"\n")                # the rest of the long line is dropped silently
            assert c.call("ping")["ok"]
            c.send_raw(b"z" * 1500 + b"\n")               # complete long line in one go
            assert c.recv()["error"]["code"] == "bad_request"
            assert c.call("ping", rid="after")["id"] == "after"
            c.close()
    finally:
        server.stop()


def test_timeout_when_main_thread_is_stuck(stack):
    server, port, d, pump, song = stack
    pump.paused.set()
    time.sleep(0.05)
    c = Client(port)
    t0 = time.time()
    env = c.call("ping", rid="slow")
    assert env["id"] == "slow" and env["ok"] is False and env["error"]["code"] == "timeout"
    assert 0.9 < time.time() - t0 < 3
    pump.paused.clear()
    time.sleep(0.1)
    # the abandoned request must not be executed late, and the connection keeps working
    assert server.pending_count() == 0
    assert c.call("ping", rid="ok")["ok"]
    c.close()


def test_batch_executes_in_a_single_tick(stack):
    server, port, d, pump, song = stack
    ticks = []
    orig = d.commands["create_midi_track"]

    def spy(ctx, params):
        ticks.append(threading.get_ident())
        pump.paused.set()          # would stall the next tick; a batch must already be done
        return orig(ctx, params)

    d.commands["create_midi_track"] = spy
    c = Client(port)
    pump.paused.clear()
    env = c.call("batch", {"commands": [{"command": "create_midi_track"}, {"command": "create_midi_track"}]})
    assert [r["ok"] for r in env["result"]["results"]] == [True, True]
    pump.paused.clear()
    c.close()


def test_process_pending_respects_budget_but_does_at_least_one():
    ticks = {"t": 0.0}

    def clock():
        ticks["t"] += 0.02
        return ticks["t"]

    server = BridgeServer(0, log=lambda m: None, clock=clock, request_timeout=5)
    done = []

    def submitter(n):
        done.append(server.submit({"id": str(n), "command": "x"}))

    threads = [threading.Thread(target=submitter, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    while server.pending_count() < 5:
        time.sleep(0.01)
    n = server.process_pending(lambda r: {"id": r["id"], "ok": True, "result": {}}, budget=0.05)
    assert 1 <= n < 5
    while server.process_pending(lambda r: {"id": r["id"], "ok": True, "result": {}}, budget=1000) == 0 and len(done) < 5:
        pass
    for t in threads:
        t.join(2)
    assert len(done) == 5


def test_executor_crash_becomes_internal_error():
    server = BridgeServer(0, log=lambda m: None, request_timeout=5)
    out = []
    t = threading.Thread(target=lambda: out.append(server.submit({"id": "9", "command": "x"})))
    t.start()
    while server.pending_count() < 1:
        time.sleep(0.005)

    def boom(request):
        raise ValueError("bad")

    server.process_pending(boom)
    t.join(2)
    assert out[0]["error"]["code"] == "internal" and out[0]["id"] == "9"


def test_stop_closes_sockets_and_frees_port():
    server = BridgeServer(0, log=lambda m: None)
    port = server.start()
    c = Client(port)
    server.stop()
    c.sock.settimeout(3)
    try:
        assert c.sock.recv(10) == b""
    except ConnectionResetError:
        pass
    s = socket.socket()
    s.bind(("127.0.0.1", port))    # port is free again
    s.close()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_port_in_use_raises():
    a = BridgeServer(0, log=lambda m: None)
    port = a.start()
    try:
        with pytest.raises(OSError):
            BridgeServer(port, log=lambda m: None).start()
    finally:
        a.stop()


def test_binds_loopback_only():
    server = BridgeServer(0, log=lambda m: None)
    server.start()
    try:
        assert server._listener.getsockname()[0] == "127.0.0.1"
    finally:
        server.stop()

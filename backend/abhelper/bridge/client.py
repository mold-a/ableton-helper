"""TCP client for the AbletonHelper Remote Script (protocol: docs/PROTOCOL.md).

Design notes
------------
* Lazy connect (connect timeout ~2 s), newline-delimited JSON, one request at a time
  (a lock serialises callers, so it is thread-safe).
* Every request has ONE deadline (``time.monotonic()`` based) shared by all ``recv``
  calls of that request. The socket timeout is recomputed from the remaining time on
  each read, so a per-call ``timeout=`` is honoured (a known pitfall in similar
  projects is resetting the timeout on every read).
* Retry policy: a request is only ever re-sent when it provably did NOT reach the
  server (the connection was already dead before we wrote, or ``send`` itself failed).
  If the connection drops while waiting for the reply, the command may have executed,
  so we raise ``BridgeConnectionError`` instead of resending.
"""

from __future__ import annotations

import itertools
import json
import logging
import select
import socket
import threading
import time
from typing import Any

from .base import BridgeCommandError, BridgeConnectionError, BridgeError

log = logging.getLogger(__name__)

EXPECTED_SCRIPT_MAJOR = "0"
MAX_LINE_BYTES = 16 * 1024 * 1024


class _NotSent(BridgeConnectionError):
    """Internal: the request was not (fully) written; safe to retry on a new socket."""


class TcpBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 9888, timeout: float = 15.0,
                 connect_timeout: float = 2.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.connect_timeout = float(connect_timeout)
        self.script_version: str | None = None
        self.live_version: str | None = None
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._buf = b""
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ Bridge API
    def call(self, command: str, params: dict | None = None, timeout: float | None = None) -> dict:
        budget = self.timeout if timeout is None else float(timeout)
        with self._lock:
            for attempt in (0, 1):
                self._ensure_connected()
                try:
                    return self._request(command, params or {}, budget)
                except _NotSent as e:
                    self._drop()
                    if attempt == 1:
                        raise BridgeConnectionError(str(e)) from e
                    log.debug("bridge: request not sent (%s); reconnecting once", e)
            raise BridgeConnectionError("unreachable")  # pragma: no cover

    def is_connected(self) -> bool:
        with self._lock:
            return self._sock is not None and self._socket_alive()

    def close(self) -> None:
        with self._lock:
            self._drop()

    # ------------------------------------------------------------------ extras
    def probe(self, timeout: float = 2.0) -> dict | None:
        """Ping the Remote Script. Returns the ping result, or None if unreachable."""
        try:
            return self.call("ping", timeout=timeout)
        except BridgeError:
            return None

    # ------------------------------------------------------------------ internals
    def _drop(self) -> None:
        sock, self._sock, self._buf = self._sock, None, b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _socket_alive(self) -> bool:
        """True if the idle socket looks usable (no EOF / stray data pending)."""
        sock = self._sock
        if sock is None:
            return False
        try:
            readable, _, _ = select.select([sock], [], [], 0)
            if not readable:
                return True
            # Readable while idle means EOF or unsolicited data: don't trust it.
            return False
        except (OSError, ValueError):
            return False

    def _ensure_connected(self) -> None:
        if self._sock is not None and not self._socket_alive():
            self._drop()
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as e:
            raise BridgeConnectionError(
                f"Cannot connect to Ableton bridge at {self.host}:{self.port}: {e}"
            ) from e
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self._sock = sock
        self._buf = b""
        self._handshake()

    def _handshake(self) -> None:
        """Ping on connect: record versions, warn on a major-version mismatch."""
        try:
            info = self._request("ping", {}, self.connect_timeout)
        except BridgeCommandError:
            return  # old/odd server without ping: still usable
        except BridgeConnectionError:
            self._drop()
            raise
        if isinstance(info, dict):
            self.script_version = info.get("script_version")
            self.live_version = info.get("live_version")
            if self.script_version and str(self.script_version).split(".")[0] != EXPECTED_SCRIPT_MAJOR:
                log.warning("Remote Script version %s differs in major version from the one this "
                            "backend expects (%s.x); reinstall the Remote Script.",
                            self.script_version, EXPECTED_SCRIPT_MAJOR)

    def _request(self, command: str, params: dict, budget: float) -> dict:
        sock = self._sock
        assert sock is not None
        req_id = str(next(self._ids))
        deadline = time.monotonic() + budget
        line = json.dumps({"id": req_id, "command": command, "params": params},
                          ensure_ascii=False).encode("utf-8") + b"\n"
        # --- send (failure here means the request was not processed)
        try:
            sock.settimeout(max(0.05, budget))
            sock.sendall(line)
        except (OSError, ValueError) as e:
            raise _NotSent(f"send failed: {e}") from e
        # --- receive (failure here is ambiguous: never resend)
        while True:
            reply = self._read_line(sock, deadline, command)
            try:
                msg = json.loads(reply.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                self._drop()
                raise BridgeConnectionError(f"Invalid reply from bridge for '{command}': {e}") from e
            if not isinstance(msg, dict):
                self._drop()
                raise BridgeConnectionError(f"Invalid reply from bridge for '{command}'")
            if str(msg.get("id")) != req_id and msg.get("id") is not None:
                log.debug("bridge: dropping stale reply id=%s (waiting for %s)", msg.get("id"), req_id)
                continue
            if msg.get("ok"):
                result = msg.get("result")
                if isinstance(result, dict):
                    return result
                return {} if result is None else {"value": result}
            err = msg.get("error")
            if isinstance(err, dict):
                raise BridgeCommandError(str(err.get("code", "internal")), str(err.get("message", "")))
            raise BridgeCommandError("internal", str(err) if err else "unknown error")

    def _read_line(self, sock: socket.socket, deadline: float, command: str) -> bytes:
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                if line.strip():
                    return line
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._drop()  # a late reply would desynchronise the stream
                raise BridgeConnectionError(f"Timed out waiting for bridge reply to '{command}'")
            try:
                sock.settimeout(remaining)
                chunk = sock.recv(65536)
            except socket.timeout as e:
                self._drop()
                raise BridgeConnectionError(f"Timed out waiting for bridge reply to '{command}'") from e
            except OSError as e:
                self._drop()
                raise BridgeConnectionError(f"Connection to Ableton lost during '{command}': {e}") from e
            if not chunk:
                self._drop()
                raise BridgeConnectionError(f"Ableton bridge closed the connection during '{command}'")
            self._buf += chunk
            if len(self._buf) > MAX_LINE_BYTES:
                self._drop()
                raise BridgeConnectionError("Bridge reply too large")


class SerializedBridge:
    """Wrap a non-thread-safe Bridge (e.g. FakeBridge) so concurrent HTTP workers are serialised."""

    def __init__(self, inner: Any):
        self._inner = inner
        self._lock = threading.RLock()

    def call(self, command: str, params: dict | None = None, timeout: float | None = None) -> dict:
        with self._lock:
            return self._inner.call(command, params, timeout)

    def is_connected(self) -> bool:
        return self._inner.is_connected()

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

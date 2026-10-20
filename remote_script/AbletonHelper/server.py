"""TCP server with newline-delimited JSON framing. No Live imports.

Socket threads never touch the Live API: they put requests into a queue and wait
for the main thread (which calls process_pending() from update_display()).
"""

import json
import queue
import socket
import sys
import threading
import time
import traceback

from .constants import HOST, MAX_LINE_BYTES, REQUEST_TIMEOUT
from .dispatcher import BAD_REQUEST, INTERNAL, TIMEOUT, error_envelope

MAX_CLIENTS = 32


class _Pending(object):
    def __init__(self, request):
        self.request = request
        self.event = threading.Event()
        self.reply = None
        self.lock = threading.Lock()
        self.started = False
        self.abandoned = False


class BridgeServer(object):
    def __init__(self, port, host=HOST, log=None, request_timeout=REQUEST_TIMEOUT,
                 max_line_bytes=MAX_LINE_BYTES, clock=None):
        self.host = host
        self.port = port
        self.request_timeout = request_timeout
        self.max_line_bytes = max_line_bytes
        self._log = log
        self._clock = clock or time.monotonic
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._listener = None
        self._accept_thread = None
        self._clients = set()
        self._clients_lock = threading.Lock()
        self.last_drain = None   # clock() of the last process_pending call

    # ------------------------------------------------------------ lifecycle
    def log(self, message):
        if self._log is not None:
            try:
                self._log(message)
            except Exception:
                pass

    def start(self):
        """Bind and start the accept thread. Returns the actual port. Raises OSError."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if not sys.platform.startswith("win"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(8)
            sock.settimeout(0.5)
        except Exception:
            sock.close()
            raise
        self._listener = sock
        self.port = sock.getsockname()[1]
        self._stop.clear()
        self._accept_thread = threading.Thread(target=self._accept_loop, name="AbletonHelper-accept")
        self._accept_thread.daemon = True
        self._accept_thread.start()
        return self.port

    def stop(self):
        self._stop.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
        # Release anybody still waiting for the main thread.
        while True:
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                break
            pending.reply = error_envelope(_request_id(pending.request), INTERNAL, "Remote Script is shutting down")
            pending.event.set()
        thread = self._accept_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)
        self._accept_thread = None

    # ------------------------------------------------------------ main thread side
    def pending_count(self):
        return self._queue.qsize()

    def process_pending(self, executor, budget=0.03):
        """Run queued requests via executor(request) -> envelope until the time budget is used.

        Always processes at least one request when any is waiting. Returns the number processed.
        """
        start = self._clock()
        self.last_drain = start
        done = 0
        while True:
            if done > 0 and self._clock() - start >= budget:
                break
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                break
            with pending.lock:
                if pending.abandoned:
                    continue
                pending.started = True
            try:
                reply = executor(pending.request)
            except Exception as exc:
                self.log("Executor crashed: %s" % traceback.format_exc())
                reply = error_envelope(_request_id(pending.request), INTERNAL, str(exc) or exc.__class__.__name__)
            pending.reply = reply
            pending.event.set()
            done += 1
        return done

    # ------------------------------------------------------------ socket threads
    def _accept_loop(self):
        while not self._stop.is_set():
            listener = self._listener
            if listener is None:
                break
            try:
                conn, addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                self.log("Accept failed: %s" % traceback.format_exc())
                break
            with self._clients_lock:
                too_many = len(self._clients) >= MAX_CLIENTS
                if not too_many:
                    self._clients.add(conn)
            if too_many:
                self.log("Too many clients, refusing %s" % (addr,))
                try:
                    conn.close()
                except Exception:
                    pass
                continue
            thread = threading.Thread(target=self._serve_client, args=(conn,), name="AbletonHelper-client")
            thread.daemon = True
            thread.start()

    def _serve_client(self, conn):
        try:
            self._client_loop(conn)
        except Exception:
            self.log("Client thread crashed: %s" % traceback.format_exc())
        finally:
            with self._clients_lock:
                self._clients.discard(conn)
            try:
                conn.close()
            except Exception:
                pass

    def _client_loop(self, conn):
        conn.settimeout(0.5)
        buf = bytearray()
        discarding = False
        while not self._stop.is_set():
            try:
                data = conn.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            buf.extend(data)
            while True:
                newline = buf.find(b"\n")
                if newline < 0:
                    if discarding:
                        del buf[:]
                    elif len(buf) > self.max_line_bytes:
                        if not self._send(conn, error_envelope(None, BAD_REQUEST, "Line exceeds %d bytes" % self.max_line_bytes)):
                            return
                        discarding = True
                        del buf[:]
                    break
                line = bytes(buf[:newline])
                del buf[:newline + 1]
                if discarding:
                    discarding = False
                    continue
                if len(line) > self.max_line_bytes:
                    if not self._send(conn, error_envelope(None, BAD_REQUEST, "Line exceeds %d bytes" % self.max_line_bytes)):
                        return
                    continue
                if not line.strip():
                    continue
                reply = self._handle_line(line)
                if not self._send(conn, reply):
                    return

    def _handle_line(self, line):
        try:
            request = json.loads(line.decode("utf-8"))
        except Exception:
            return error_envelope(None, BAD_REQUEST, "Invalid JSON")
        if not isinstance(request, dict):
            return error_envelope(None, BAD_REQUEST, "Request must be a JSON object")
        return self.submit(request)

    def submit(self, request):
        """Queue a request for the main thread and wait for the reply (socket thread)."""
        pending = _Pending(request)
        self._queue.put(pending)
        if not pending.event.wait(self.request_timeout):
            with pending.lock:
                started = pending.started
                if not started:
                    pending.abandoned = True
            if not started:
                return error_envelope(_request_id(request), TIMEOUT,
                                      "Live main thread did not process the request in %.0f s" % self.request_timeout)
            if not pending.event.wait(self.request_timeout):
                return error_envelope(_request_id(request), TIMEOUT, "Request execution took too long")
        return pending.reply

    def _send(self, conn, envelope):
        try:
            payload = json.dumps(envelope, ensure_ascii=False)
        except Exception as exc:
            payload = json.dumps(error_envelope(envelope.get("id") if isinstance(envelope, dict) else None,
                                                INTERNAL, "Result is not serializable: %s" % exc))
        try:
            conn.sendall(payload.encode("utf-8") + b"\n")
            return True
        except Exception:
            return False


def _request_id(request):
    return request.get("id") if isinstance(request, dict) else None

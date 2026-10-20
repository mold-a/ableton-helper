"""Thin Live glue: the Control Surface that owns the server, dispatcher and browser index.

Everything with real logic lives in other modules; this file only wires them together
and keeps exceptions from escaping into Live.
"""

import os
import time
import traceback

from .browser_index import BrowserIndex
from .constants import (DEFAULT_PORT, INDEX_BUDGET, INDEX_START_DELAY, PORT_ENV_VAR,
                        SCRIPT_VERSION, TICK_BUDGET)
from .context import Context
from .dispatcher import Dispatcher
from .server import BridgeServer

try:  # Live 11 / 12 ship _Framework; tests inject a fake module or use the fallback below
    from _Framework.ControlSurface import ControlSurface as _BaseControlSurface
except Exception:
    try:
        from ableton.v2.control_surface import ControlSurface as _BaseControlSurface
    except Exception:
        _BaseControlSurface = None


if _BaseControlSurface is None:
    class _BaseControlSurface(object):
        """Minimal stand-in used outside Live (tests, syntax checks)."""

        def __init__(self, c_instance, *args, **kwargs):
            self._c_instance = c_instance

        def song(self):
            return self._c_instance.song()

        def application(self):
            getter = getattr(self._c_instance, "application", None)
            if callable(getter):
                return getter()
            import Live  # noqa
            return Live.Application.get_application()

        def log_message(self, *message):
            fn = getattr(self._c_instance, "log_message", None)
            if callable(fn):
                fn(" ".join(str(m) for m in message))

        def show_message(self, message):
            fn = getattr(self._c_instance, "show_message", None)
            if callable(fn):
                fn(message)

        def update_display(self):
            pass

        def disconnect(self):
            pass


def read_port():
    raw = os.environ.get(PORT_ENV_VAR)
    if raw:
        try:
            port = int(raw)
            if 0 <= port <= 65535:
                return port
        except ValueError:
            pass
    return DEFAULT_PORT


class AbletonHelper(_BaseControlSurface):
    """MIDI Remote Script entry object (Control Surface 'AbletonHelper')."""

    def __init__(self, c_instance):
        super(AbletonHelper, self).__init__(c_instance)
        self.server = None
        self.index = None
        self.dispatcher = None
        self.ctx = None
        self._last_stall_log = 0.0
        try:
            self._startup()
        except Exception:
            self.log_message("AbletonHelper: startup failed:\n" + traceback.format_exc())

    # ------------------------------------------------------------ setup
    def _startup(self):
        port = read_port()
        song = self.song()
        app = self.application()
        self.index = BrowserIndex(app, log=self.log_message)
        self.ctx = Context(song, app, self.index, log=self.log_message)
        self.dispatcher = Dispatcher(self.ctx)
        self.index.start(INDEX_START_DELAY)
        self.server = BridgeServer(port, log=self.log_message)
        try:
            actual = self.server.start()
        except OSError as exc:
            self.server = None
            self.log_message("AbletonHelper: cannot listen on 127.0.0.1:%s: %s" % (port, exc))
            self.show_message("AbletonHelper: port %s is busy (see Log.txt)" % port)
            return
        self.log_message("AbletonHelper %s: listening on 127.0.0.1:%s" % (SCRIPT_VERSION, actual))
        self.show_message("AbletonHelper: listening on %s" % actual)

    # ------------------------------------------------------------ Live callbacks
    def update_display(self):
        """Called by Live ~every 100 ms on the main thread: drain requests, advance the index."""
        try:
            super(AbletonHelper, self).update_display()
        except Exception:
            pass
        try:
            self.tick()
        except Exception:
            self.log_message("AbletonHelper: tick failed:\n" + traceback.format_exc())

    def tick(self):
        """One unit of main-thread work (also called directly by tests)."""
        if self.server is None or self.dispatcher is None:
            return
        self.server.process_pending(self.dispatcher.handle, TICK_BUDGET)
        if self.server.pending_count() == 0 and self.index is not None:
            self.index.step(INDEX_BUDGET)
        elif self.server.pending_count() > 0:
            now = time.monotonic()
            if now - self._last_stall_log > 30.0:
                self._last_stall_log = now
                self.log_message("AbletonHelper: %d request(s) still queued after a tick" % self.server.pending_count())

    def disconnect(self):
        self.log_message("AbletonHelper: disconnecting")
        try:
            if self.server is not None:
                self.server.stop()
        except Exception:
            self.log_message("AbletonHelper: error while stopping server:\n" + traceback.format_exc())
        self.server = None
        try:
            super(AbletonHelper, self).disconnect()
        except Exception:
            pass

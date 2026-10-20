"""Shared helpers for the sound tests (imported as a plain module; basename is unique on purpose)."""

from __future__ import annotations

from abhelper.bridge.base import BridgeCommandError, BridgeConnectionError
from abhelper.bridge.fake import FakeBridge


class ScriptedBridge(FakeBridge):
    """FakeBridge where chosen commands can be made to fail.

    fail: {command: exception | callable(params) -> exception | None}
    """

    def __init__(self, *args, fail: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail = dict(fail or {})

    def call(self, command, params=None, timeout=None):
        rule = self.fail.get(command)
        if rule is not None:
            exc = rule(dict(params or {})) if callable(rule) else rule
            if exc is not None:
                self.calls.append((command, dict(params or {})))
                raise exc
        return super().call(command, params, timeout)


def missing_devices(*names: str):
    """A `fail` rule for load_device: the given devices are 'not available in this Live'."""
    wanted = {n.lower() for n in names}

    def rule(params):
        if str(params.get("device_name", "")).lower() in wanted:
            return BridgeCommandError("not_found", f"Device '{params.get('device_name')}' not found in browser")
        return None

    return rule


def offline():
    return BridgeConnectionError("connection refused")


class FakeClock:
    """Deterministic replacement for time.monotonic / time.sleep."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SlowIndexBridge(ScriptedBridge):
    """Browser index reports incomplete for the first `incomplete_polls` status/search calls."""

    def __init__(self, *args, incomplete_polls: int = 3, **kwargs):
        super().__init__(*args, **kwargs)
        self.remaining = incomplete_polls

    def _cmd_browser_status(self):
        s = super()._cmd_browser_status()
        if self.remaining > 0:
            self.remaining -= 1
            s["complete"] = False
            s["scanning"] = True
        return s

    def _cmd_browser_search(self, *a, **kw):
        res = super()._cmd_browser_search(*a, **kw)
        if self.remaining > 0:
            self.remaining -= 1
            return {"items": [], "index_complete": False}
        return res

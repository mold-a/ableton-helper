"""Bridge interface: how the backend talks to the AbletonHelper Remote Script.

The wire protocol is described in docs/PROTOCOL.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class BridgeError(Exception):
    """Base class for all bridge errors."""


class BridgeConnectionError(BridgeError):
    """Live is not running, the Remote Script is not enabled, or the socket dropped."""


class BridgeCommandError(BridgeError):
    """The Remote Script answered ok=false."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@runtime_checkable
class Bridge(Protocol):
    def call(self, command: str, params: dict | None = None, timeout: float | None = None) -> dict:
        """Run a command and return its `result`. Raises BridgeCommandError on ok=false."""
        ...

    def is_connected(self) -> bool: ...

    def close(self) -> None: ...

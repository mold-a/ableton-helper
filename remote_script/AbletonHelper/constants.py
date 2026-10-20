"""Shared constants of the AbletonHelper Remote Script."""

SCRIPT_VERSION = "0.1.0"
DEFAULT_PORT = 9888
PORT_ENV_VAR = "ABHELPER_BRIDGE_PORT"
HOST = "127.0.0.1"

REQUEST_TIMEOUT = 10.0          # seconds a socket thread waits for the main thread
MAX_LINE_BYTES = 1024 * 1024    # 1 MB per JSON line
TICK_BUDGET = 0.030             # seconds of command processing per update_display tick
INDEX_BUDGET = 0.020            # seconds of browser indexing per tick
INDEX_START_DELAY = 2.0         # seconds after init before the index scan starts

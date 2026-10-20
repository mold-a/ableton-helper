"""Set a Live parameter by the value Live *displays* ("1.3 kHz", "25 ms", "-6 dB", "30 %").

Most native-device parameters are exposed to the API as a normalised 0..1 value on a
device-specific curve (log for frequencies, exp for times...). Live can format any raw
value with ``DeviceParameter.str_for_value(raw)``, so a display target is resolved by
bisection over [min, max] against that formatter. This module is the reference
implementation shared by FakeBridge; the Remote Script ports the same algorithm
(remote_script/AbletonHelper/display.py) with Python 3.7 syntax. Grammar: docs/PROTOCOL.md.
"""

from __future__ import annotations

import math
import re
from typing import Callable

# unit token (lower-case) -> (dimension, factor to the canonical unit)
UNITS: dict[str, tuple[str, float]] = {
    "hz": ("freq", 1.0), "khz": ("freq", 1000.0), "k": ("freq", 1000.0),
    "ms": ("time", 1.0), "s": ("time", 1000.0), "sec": ("time", 1000.0),
    "db": ("level", 1.0),
    "%": ("percent", 1.0),
    "st": ("semitones", 1.0), "ct": ("cents", 1.0), "cents": ("cents", 1.0),
    "°": ("degrees", 1.0), "deg": ("degrees", 1.0),
    ":1": ("ratio", 1.0),
    "": ("number", 1.0),
}

_NUMBER = re.compile(r"([-+]?(?:inf|\d+(?:[.,]\d+)?|[.,]\d+))", re.IGNORECASE)


_PAN = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([LR])$", re.IGNORECASE)


class DisplayError(ValueError):
    pass


def parse_display(text: str) -> tuple[float, str]:
    """'2.53 kHz' -> (2530.0, 'freq'); '-inf dB' -> (-inf, 'level'); '4.00 : 1' -> (4.0, 'ratio')."""
    s = str(text).strip()
    if s.upper() == "C":                       # pan centre
        return 0.0, "pan"
    pan = _PAN.match(s)
    if pan:                                    # "50L" -> -50, "50R" -> +50
        value = float(pan.group(1).replace(",", "."))
        return (-value if pan.group(2).upper() == "L" else value), "pan"
    m = _NUMBER.search(s)
    if not m:
        raise DisplayError(f"no number in display {text!r}")
    raw = m.group(1).lower().replace(",", ".")
    if raw.lstrip("+-") == "inf":
        number = -math.inf if raw.startswith("-") else math.inf
    else:
        number = float(raw)
    unit = re.sub(r"\s+", "", s[m.end():]).lower()
    if unit not in UNITS:
        # tolerate trailing decorations ("ms." / "Hz)") but keep unknown units distinct
        stripped = re.sub(r"[^a-z%°:1]", "", unit)
        unit = stripped if stripped in UNITS else unit
    dim, factor = UNITS.get(unit, (unit, 1.0))
    return number * factor, dim


def solve_display(target: str, lo: float, hi: float, formatter: Callable[[float], str],
                  iterations: int = 48) -> float:
    """Raw value in [lo, hi] whose formatted display is closest to ``target``.

    Raises DisplayError when the parameter's display is not numeric or the units differ.
    Assumes the display is monotonic over [lo, hi] (true for Live's continuous params).
    """
    want, want_dim = parse_display(target)
    v_lo, dim_lo = parse_display(formatter(lo))
    v_hi, dim_hi = parse_display(formatter(hi))
    # Some devices omit the unit on part of the range (Analog cutoff: " 834" .. "1.9k"):
    # a bare number then means the parameter's own unit, already in its base scale.
    dims = {dim_lo, dim_hi} - {"number"} if want_dim != "number" else set()
    if dims and want_dim not in dims:
        raise DisplayError(f"unit mismatch: target {target!r}, parameter shows {formatter(lo)!r}..{formatter(hi)!r}")
    increasing = v_hi >= v_lo
    if math.isinf(want):
        return lo if (want < 0) == increasing else hi
    if (want <= v_lo) == increasing and want != v_lo:
        return lo
    if (want >= v_hi) == increasing and want != v_hi:
        return hi
    a, b = lo, hi
    for _ in range(iterations):
        mid = (a + b) / 2.0
        v_mid, _dim = parse_display(formatter(mid))
        if (v_mid < want) == increasing:
            a = mid
        else:
            b = mid
    # pick the end whose display is closer (displays are rounded, so plateaus are normal)
    va, _ = parse_display(formatter(a))
    vb, _ = parse_display(formatter(b))
    return a if abs(va - want) <= abs(vb - want) else b


def format_display(value: float, dim: str) -> str:
    """Canonical formatting used by FakeBridge (close to Live's own style)."""
    if dim == "freq":
        return f"{value / 1000:.2f} kHz" if value >= 1000 else f"{value:.1f} Hz"
    if dim == "time":
        return f"{value / 1000:.2f} s" if value >= 1000 else f"{value:.1f} ms"
    if dim == "level":
        return "-inf dB" if value == -math.inf or value < -69.5 else f"{value:.1f} dB"
    if dim == "percent":
        return f"{value:.0f} %"
    if dim == "ratio":
        return f"{value:.2f} : 1"
    suffix = {"semitones": " st", "cents": " ct", "degrees": "°"}.get(dim, "")
    return f"{value:.2f}{suffix}"

# -*- coding: utf-8 -*-
"""Set a Live parameter by the value Live *displays* ("1.3 kHz", "25 ms", "-6 dB", "30 %").

Most native-device parameters are exposed to the API as a normalised 0..1 value on a
device-specific curve. Live formats any raw value with DeviceParameter.str_for_value(raw),
so a display target is resolved by bisection over [min, max] against that formatter.
Python 3.7 port of backend/abhelper/bridge/displayval.py (same grammar and semantics,
see docs/PROTOCOL.md).
"""

import math
import re

# unit token (lower-case) -> (dimension, factor to the canonical unit)
UNITS = {
    "hz": ("freq", 1.0), "khz": ("freq", 1000.0),
    "ms": ("time", 1.0), "s": ("time", 1000.0), "sec": ("time", 1000.0),
    "db": ("level", 1.0),
    "%": ("percent", 1.0),
    "st": ("semitones", 1.0), "ct": ("cents", 1.0), "cents": ("cents", 1.0),
    u"°": ("degrees", 1.0), "deg": ("degrees", 1.0),
    ":1": ("ratio", 1.0),
    "": ("number", 1.0),
}

_NUMBER = re.compile(r"([-+]?(?:inf|\d+(?:[.,]\d+)?|[.,]\d+))", re.IGNORECASE)
_UNIT_JUNK = re.compile(u"[^a-z%°:1]")


class DisplayError(ValueError):
    pass


def parse_display(text):
    """'2.53 kHz' -> (2530.0, 'freq'); '-inf dB' -> (-inf, 'level'); '4.00 : 1' -> (4.0, 'ratio')."""
    s = str(text).strip()
    m = _NUMBER.search(s)
    if not m:
        raise DisplayError("no number in display %r" % (text,))
    raw = m.group(1).lower().replace(",", ".")
    if raw.lstrip("+-") == "inf":
        number = -math.inf if raw.startswith("-") else math.inf
    else:
        number = float(raw)
    unit = re.sub(r"\s+", "", s[m.end():]).lower()
    if unit not in UNITS:
        # tolerate trailing decorations ("ms." / "Hz)") but keep unknown units distinct
        stripped = _UNIT_JUNK.sub("", unit)
        unit = stripped if stripped in UNITS else unit
    dim, factor = UNITS.get(unit, (unit, 1.0))
    return number * factor, dim


def solve_display(target, lo, hi, formatter, iterations=48):
    """Raw value in [lo, hi] whose formatted display is closest to `target`.

    Raises DisplayError when the parameter's display is not numeric or the units differ.
    Assumes the display is monotonic over [lo, hi] (true for Live's continuous params).
    """
    want, want_dim = parse_display(target)
    v_lo, dim_lo = parse_display(formatter(lo))
    v_hi, dim_hi = parse_display(formatter(hi))
    dims = set([dim_lo, dim_hi]) - set(["number"]) if want_dim != "number" else set()
    if dims and want_dim not in dims:
        raise DisplayError("unit mismatch: target %r, parameter shows %r..%r" % (
            target, formatter(lo), formatter(hi)))
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

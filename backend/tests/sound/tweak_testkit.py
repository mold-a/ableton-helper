"""FakeBridge built from the REAL Live 11.3.25 catalog with injected display curves (for sound/tweaks tests)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from abhelper.bridge.displayval import parse_display
from abhelper.bridge.fake import FakeBridge
from abhelper.sound.roles import load_roles

CATALOG = Path(__file__).resolve().parents[2] / "abhelper" / "sound" / "data" / "device_catalog.json"

_HZ = {"unit": "Hz", "scale": "log", "min": 20, "max": 20000}
_PCT = {"unit": "%", "scale": "lin", "min": 0, "max": 100}
_MS_ATTACK = {"unit": "ms", "scale": "log", "min": 0.1, "max": 20000}
_MS = {"unit": "ms", "scale": "log", "min": 1, "max": 20000}
_DB_VOL = {"unit": "dB", "scale": "lin", "min": -70, "max": 6}

ROLE_CURVES = {
    "cutoff": _HZ,
    "resonance": _PCT,
    "filter_env_amount": {"unit": "%", "scale": "lin", "min": -100, "max": 100},
    "attack": _MS_ATTACK,
    "decay": _MS,
    "release": _MS,
    "sustain": _PCT,
    "volume": _DB_VOL,
    "output_gain": {"unit": "dB", "scale": "lin", "min": -35, "max": 35},
    "wet": _PCT,
    "decay_time": {"unit": "ms", "scale": "log", "min": 200, "max": 60000},
    "room_size": _PCT,
    "predelay": {"unit": "ms", "scale": "log", "min": 1, "max": 250},
    "width": _PCT,
    "tone": _PCT,
    "warmth": _PCT,
    "feedback": _PCT,
    "transients": {"unit": "%", "scale": "lin", "min": -100, "max": 100},
    "unison": _PCT,
    "detune": _PCT,
    "sub_level": _PCT,
    "vibrato_amount": _PCT,
}
DRIVE_CURVES = {
    "Operator": {"unit": "dB", "scale": "lin", "min": 0, "max": 24},
    "Simpler": {"unit": "dB", "scale": "lin", "min": 0, "max": 24},
    "Auto Filter": {"unit": "dB", "scale": "lin", "min": 0, "max": 24},
    "Saturator": {"unit": "dB", "scale": "lin", "min": -36, "max": 36},
    "Overdrive": _PCT, "Drum Buss": _PCT, "Wavetable": _PCT,
}
WIDTH_UTILITY = {"unit": "%", "scale": "lin", "min": 0, "max": 200}


def curved_catalog(skip: tuple[str, ...] = ()) -> dict:
    """Real catalog + display curves on every role parameter (except roles/devices listed in ``skip``)."""
    cat = copy.deepcopy(json.loads(CATALOG.read_text(encoding="utf-8"))["devices"])
    # These unit tests pin the display curves themselves; real calibration samples are exercised
    # separately (test_sound_tweaks_real_displays.py).
    for dev in cat.values():
        for p in dev.get("parameters", []):
            p.pop("display_samples", None)
    book = load_roles()
    for dev_name, roles in book.devices.items():
        by_name = {p["name"]: p for p in cat[dev_name]["parameters"]}
        for role, plist in roles.roles.items():
            if role in skip or dev_name in skip:
                continue
            curve = DRIVE_CURVES.get(dev_name) if role == "drive" else ROLE_CURVES.get(role)
            if role == "width" and dev_name == "Utility":
                curve = WIDTH_UTILITY
            if curve is None:
                continue
            for rp in plist:
                p = by_name[rp.name]
                if not p.get("is_quantized"):
                    p["display_curve"] = dict(curve)
    return cat


def make_bridge(*devices: str, catalog: dict | None = None, state: dict | None = None, bridge_cls=FakeBridge,
                **kw) -> FakeBridge:
    """A bridge with one MIDI track (index 0) holding ``devices`` in order. ``state``: {device_index: {param: value}}."""
    bridge = bridge_cls(device_catalog=catalog or curved_catalog(), **kw)
    bridge.call("create_midi_track", {"name": "Test"})
    for name in devices:
        bridge.call("load_device", {"track_index": 0, "device_name": name})
    for di, values in (state or {}).items():
        res = bridge.call("set_device_parameters", {"track_index": 0, "device_index": di, "values": values})
        assert not res["failed"], res["failed"]
    return bridge


def param(bridge: FakeBridge, device_index: int, name: str, track_index: int = 0) -> dict:
    res = bridge.call("get_device_parameters", {"track_index": track_index, "device_index": device_index})
    return next(p for p in res["parameters"] if p["name"] == name)


def shown(bridge: FakeBridge, device_index: int, name: str) -> str:
    return param(bridge, device_index, name)["display"]


def num(bridge: FakeBridge, device_index: int, name: str) -> float:
    """Displayed value in canonical units (Hz, ms, dB, %)."""
    return parse_display(shown(bridge, device_index, name))[0]


def device_names(bridge: FakeBridge, track_index: int = 0) -> list[str]:
    return [d.name for d in bridge.tracks[track_index].devices]


def writes(bridge: FakeBridge) -> list[dict]:
    """All set_device_parameters payloads sent so far."""
    return [p for c, p in bridge.calls if c == "set_device_parameters"]

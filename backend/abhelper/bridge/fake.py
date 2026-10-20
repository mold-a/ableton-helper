"""In-memory emulation of the AbletonHelper Remote Script (docs/PROTOCOL.md).

Used by tests and by `abhelper serve --fake` so the whole stack runs without Live.
It is a behavioural model, not a byte-exact replica of Live: devices come from a
catalog, presets from a small fake browser tree.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import BridgeCommandError
from .displayval import DisplayError, format_display, parse_display, solve_display

SCRIPT_VERSION = "0.1.0"
LIVE_VERSION = "12.1.0 (fake)"

CATALOG_PATH = Path(__file__).resolve().parent.parent / "sound" / "data" / "device_catalog.json"

# Native devices the fake knows even without a catalog (name -> type).
BUILTIN_DEVICES: dict[str, str] = {
    **{n: "instrument" for n in (
        "Operator", "Wavetable", "Analog", "Drift", "Meld", "Electric", "Tension",
        "Collision", "Simpler", "Sampler", "Drum Rack", "Instrument Rack", "Impulse",
        "Bass", "Poli", "Emit", "Tree Tone", "Vector FM", "Vector Grain",
    )},
    **{n: "audio_effect" for n in (
        "Reverb", "Hybrid Reverb", "Delay", "Echo", "Chorus-Ensemble", "Phaser-Flanger",
        "EQ Eight", "EQ Three", "Auto Filter", "Compressor", "Glue Compressor", "Saturator",
        "Overdrive", "Pedal", "Amp", "Cabinet", "Utility", "Limiter", "Redux", "Erosion",
        "Vinyl Distortion", "Corpus", "Resonators", "Auto Pan", "Auto Pan-Tremolo",
        "Roar", "Spectral Resonator", "Drum Buss", "Channel EQ", "Vocoder", "Grain Delay",
    )},
    **{n: "midi_effect" for n in ("Arpeggiator", "Chord", "Scale", "Random", "Velocity", "Note Length", "Pitch")},
}

DEFAULT_BROWSER: list[dict[str, Any]] = [
    {"path": "sounds/Piano & Keys/Grand Piano.adg", "loads": ["Instrument Rack"]},
    {"path": "sounds/Piano & Keys/Electric Piano Mk I.adg", "loads": ["Instrument Rack"]},
    {"path": "sounds/Strings/Warm Strings Ensemble.adg", "loads": ["Instrument Rack"]},
    {"path": "sounds/Pad/Analog Pad Soft.adv", "loads": ["Analog"]},
    {"path": "sounds/Bass/Sub Bass Deep.adv", "loads": ["Operator"]},
    {"path": "sounds/Synth Lead/Saw Lead Bright.adv", "loads": ["Wavetable"]},
    {"path": "drums/Drum Rack/808 Core Kit.adg", "loads": ["Drum Rack"]},
    {"path": "drums/Drum Rack/Acoustic Kit Studio.adg", "loads": ["Drum Rack"]},
    {"path": "samples/One Shots/Accordion C3.wav", "loads": ["Simpler"]},
    {"path": "instruments/Operator", "is_device": True, "loads": ["Operator"]},
    {"path": "instruments/Wavetable", "is_device": True, "loads": ["Wavetable"]},
    {"path": "audio_effects/Reverb", "is_device": True, "loads": ["Reverb"]},
]

CATEGORIES = [
    "instruments", "sounds", "drums", "audio_effects", "midi_effects", "max_for_live",
    "plugins", "clips", "samples", "packs", "user_library", "current_project", "user_folders",
]


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.]+", "", s.lower())


@dataclass
class FakeParam:
    name: str
    min: float = 0.0
    max: float = 1.0
    default: float = 0.0
    is_quantized: bool = False
    value_items: list[str] = field(default_factory=list)
    value: float = 0.0
    # How Live displays this parameter (from calibration): [[raw, "2.53 kHz"], ...] sorted by raw,
    # or a curve {"unit": "Hz", "scale": "log", "min": 10, "max": 22000}. Absent = unknown.
    display_samples: list = field(default_factory=list)
    display_curve: dict | None = None

    def str_for_value(self, raw: float) -> str:
        if self.is_quantized and self.value_items:
            i = int(round(raw))
            return self.value_items[i] if 0 <= i < len(self.value_items) else str(i)
        if self.display_samples:
            pts = [(float(r), *parse_display(t)) for r, t in self.display_samples]
            dim = next((d for _r, _v, d in pts if d != "number"), "number")
            if raw <= pts[0][0]:
                return format_display(pts[0][1], dim)
            for (r0, v0, _), (r1, v1, _) in zip(pts, pts[1:]):
                if raw <= r1:
                    if math.isinf(v0) or math.isinf(v1):
                        return format_display(v1 if raw > r0 else v0, dim)
                    t = (raw - r0) / (r1 - r0) if r1 != r0 else 0.0
                    if v0 > 0 and v1 > 0 and dim in ("freq", "time"):   # Live's curves are ~exponential
                        return format_display(v0 * (v1 / v0) ** t, dim)
                    return format_display(v0 + t * (v1 - v0), dim)
            return format_display(pts[-1][1], dim)
        if self.display_curve:
            c = self.display_curve
            factor, dim = parse_display(f"1 {c.get('unit', '')}")
            lo, hi = float(c["min"]) * factor, float(c["max"]) * factor
            t = (raw - self.min) / (self.max - self.min) if self.max != self.min else 0.0
            v = lo * (hi / lo) ** t if c.get("scale") == "log" and lo > 0 else lo + t * (hi - lo)
            return format_display(v, dim)
        return f"{raw:.2f}"

    @property
    def display_known(self) -> bool:
        return bool(self.display_samples or self.display_curve) or self.is_quantized

    def to_dict(self, index: int) -> dict:
        display = self.str_for_value(self.value)
        return {
            "index": index, "name": self.name, "value": self.value, "min": self.min,
            "max": self.max, "default": self.default, "display": display,
            "is_quantized": self.is_quantized, "value_items": list(self.value_items),
        }


@dataclass
class FakeDevice:
    name: str
    class_name: str
    type: str
    parameters: list[FakeParam]
    enabled: bool = True

    def summary(self, index: int) -> dict:
        return {"index": index, "name": self.name, "class_name": self.class_name, "type": self.type}


@dataclass
class FakeClip:
    length: float
    name: str = ""
    notes: list[dict] = field(default_factory=list)
    is_playing: bool = False


@dataclass
class FakeTrack:
    name: str
    type: str  # midi | audio
    color_index: int = 0
    devices: list[FakeDevice] = field(default_factory=list)
    slots: list[FakeClip | None] = field(default_factory=lambda: [None] * 8)
    mute: bool = False
    solo: bool = False
    arm: bool = False
    volume: float = 0.85
    pan: float = 0.0


class FakeBridge:
    """Implements the Bridge protocol against an in-memory Live set."""

    def __init__(
        self,
        device_catalog: dict[str, dict] | None = None,
        browser_items: list[dict] | None = None,
        tracks: int = 0,
        capabilities: dict[str, bool] | None = None,
    ):
        if device_catalog is None:
            device_catalog = self._load_default_catalog()
        self.device_catalog = device_catalog
        self.browser = [self._make_item(i) for i in (browser_items if browser_items is not None else DEFAULT_BROWSER)]
        self.tracks: list[FakeTrack] = []
        self.selected_track_index: int | None = None
        self.tempo = 120.0
        self.is_playing = False
        self.undo_stack: list[list[FakeTrack]] = []
        self.calls: list[tuple[str, dict]] = []
        self.connected = True
        self.capabilities = {"insert_device": True, "create_audio_clip": True, "add_new_notes": True, "browser": True}
        if capabilities:
            self.capabilities.update(capabilities)
        for i in range(tracks):
            self.tracks.append(FakeTrack(name=f"{i + 1}-MIDI", type="midi"))

    # ------------------------------------------------------------------ Bridge API
    def call(self, command: str, params: dict | None = None, timeout: float | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            raise BridgeCommandError("unknown_command", f"Unknown command: {command}")
        return handler(**params) if params else handler()

    def is_connected(self) -> bool:
        return self.connected

    def close(self) -> None:
        pass

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _load_default_catalog() -> dict[str, dict]:
        if CATALOG_PATH.exists():
            try:
                data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
                return data.get("devices", data)
            except (OSError, ValueError):
                return {}
        return {}

    @staticmethod
    def _make_item(spec: dict) -> dict:
        path = spec["path"]
        name = spec.get("name") or path.rsplit("/", 1)[-1]
        category = spec.get("category") or path.split("/", 1)[0]
        is_device = bool(spec.get("is_device", False))
        return {
            "name": name,
            "uri": spec.get("uri") or f"fake:{path}",
            "path": path,
            "category": category,
            "is_loadable": spec.get("is_loadable", True),
            "is_device": is_device,
            "is_folder": False,
            "_loads": list(spec.get("loads", ["Instrument Rack"])),
        }

    @staticmethod
    def _public_item(item: dict) -> dict:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    def _snapshot(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.tracks))

    def _track(self, track_index: Any) -> FakeTrack:
        if not isinstance(track_index, int) or isinstance(track_index, bool):
            raise BridgeCommandError("bad_request", "track_index must be int")
        idx = len(self.tracks) - 1 if track_index == -1 else track_index
        if not 0 <= idx < len(self.tracks):
            raise BridgeCommandError("not_found", f"Track {track_index} does not exist")
        return self.tracks[idx]

    def _index_of(self, track_index: int) -> int:
        return len(self.tracks) - 1 if track_index == -1 else track_index

    def _device(self, track_index: int, device_index: Any) -> FakeDevice:
        track = self._track(track_index)
        if not isinstance(device_index, int) or not 0 <= device_index < len(track.devices):
            raise BridgeCommandError("not_found", f"Device {device_index} does not exist on track {track_index}")
        return track.devices[device_index]

    def _new_device(self, name: str) -> FakeDevice:
        spec = self.device_catalog.get(name)
        if spec is None:
            lowered = {k.lower(): k for k in self.device_catalog}
            if name.lower() in lowered:
                name = lowered[name.lower()]
                spec = self.device_catalog[name]
        if spec is None and name not in BUILTIN_DEVICES:
            raise BridgeCommandError("not_found", f"Device '{name}' not found in browser")
        spec = spec or {}
        params = [FakeParam(name="Device On", min=0, max=1, default=1, is_quantized=True,
                            value_items=["Off", "On"], value=1)]
        for p in spec.get("parameters", []):
            fp = FakeParam(
                name=p["name"], min=float(p.get("min", 0.0)), max=float(p.get("max", 1.0)),
                default=float(p.get("default", p.get("min", 0.0))),
                is_quantized=bool(p.get("is_quantized", bool(p.get("value_items")))),
                value_items=list(p.get("value_items", [])),
                display_samples=list(p.get("display_samples") or []),
                display_curve=p.get("display_curve"),
            )
            fp.value = fp.default
            if fp.name != "Device On":
                params.append(fp)
        return FakeDevice(
            name=name,
            class_name=spec.get("class_name", name.replace(" ", "")),
            type=spec.get("type", BUILTIN_DEVICES.get(name, "unknown")),
            parameters=params,
        )

    def _find_param(self, device: FakeDevice, key: Any) -> tuple[int, FakeParam]:
        if isinstance(key, int) and not isinstance(key, bool):
            if 0 <= key < len(device.parameters):
                return key, device.parameters[key]
            raise BridgeCommandError("not_found", f"Parameter index {key} out of range")
        if not isinstance(key, str):
            raise BridgeCommandError("bad_request", "parameter must be int or str")
        for matcher in (lambda p: p.name == key, lambda p: p.name.lower() == key.lower(),
                        lambda p: _norm(p.name) == _norm(key)):
            for i, p in enumerate(device.parameters):
                if matcher(p):
                    return i, p
        raise BridgeCommandError("not_found", f"Parameter '{key}' not found on {device.name}")

    @staticmethod
    def _coerce_value(p: FakeParam, value: Any) -> float:
        if isinstance(value, dict) and "display" in value:
            target = value["display"]
            if not isinstance(target, str):
                raise BridgeCommandError("bad_request", "'display' must be a string like \"1.3 kHz\"")
            if p.is_quantized and p.value_items:
                return FakeBridge._coerce_value(p, target)
            if not p.display_known:
                # Unknown display curve (catalog without calibration samples): accept, land mid-range.
                p.approximate_display = True  # type: ignore[attr-defined]
                return p.min + 0.5 * (p.max - p.min)
            try:
                return solve_display(target, p.min, p.max, p.str_for_value)
            except DisplayError as e:
                raise BridgeCommandError("bad_request", f"Parameter '{p.name}': {e}")
        if isinstance(value, dict) and "norm" in value:
            v = p.min + float(value["norm"]) * (p.max - p.min)
        elif isinstance(value, str):
            if not p.is_quantized:
                raise BridgeCommandError("bad_request", f"Parameter '{p.name}' is not quantized; string value not allowed")
            items = [s.lower() for s in p.value_items]
            if value.lower() not in items:
                raise BridgeCommandError("bad_request", f"'{value}' is not one of {p.value_items}")
            v = float(items.index(value.lower()))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            v = float(value)
        else:
            raise BridgeCommandError("bad_request", f"Unsupported value {value!r}")
        v = max(p.min, min(p.max, v))
        if p.is_quantized:
            v = float(round(v))
        return v

    def _track_summary(self, i: int) -> dict:
        t = self.tracks[i]
        return {
            "index": i, "name": t.name, "type": t.type, "color_index": t.color_index,
            "is_selected": self.selected_track_index == i, "mute": t.mute, "solo": t.solo, "arm": t.arm,
            "devices": [d.summary(j) for j, d in enumerate(t.devices)],
        }

    def _slot(self, track: FakeTrack, slot_index: Any) -> int:
        if not isinstance(slot_index, int) or not 0 <= slot_index < len(track.slots):
            raise BridgeCommandError("not_found", f"Clip slot {slot_index} does not exist")
        return slot_index

    # ------------------------------------------------------------------ service
    def _cmd_ping(self) -> dict:
        return {"pong": True, "script_version": SCRIPT_VERSION, "live_version": LIVE_VERSION}

    def _cmd_get_capabilities(self) -> dict:
        return dict(self.capabilities)

    def _cmd_batch(self, commands: list, stop_on_error: bool = True) -> dict:
        results = []
        for c in commands:
            try:
                results.append({"ok": True, "result": self.call(c["command"], c.get("params"))})
            except BridgeCommandError as e:
                results.append({"ok": False, "error": {"code": e.code, "message": e.message}})
                if stop_on_error:
                    break
        return {"results": results}

    # ------------------------------------------------------------------ song
    def _cmd_get_session_info(self) -> dict:
        return {
            "tempo": self.tempo, "signature": [4, 4], "is_playing": self.is_playing,
            "track_count": len(self.tracks), "return_track_count": 2,
            "selected_track_index": self.selected_track_index,
            "tracks": [self._track_summary(i) for i in range(len(self.tracks))],
        }

    def _cmd_set_tempo(self, tempo: float) -> dict:
        if not 20 <= float(tempo) <= 999:
            raise BridgeCommandError("bad_request", "tempo must be within 20..999")
        self.tempo = float(tempo)
        return {"tempo": self.tempo}

    def _cmd_start_playback(self) -> dict:
        self.is_playing = True
        return {"is_playing": True}

    def _cmd_stop_playback(self) -> dict:
        self.is_playing = False
        return {"is_playing": False}

    def _cmd_undo(self) -> dict:
        if not self.undo_stack:
            return {"done": False}
        self.tracks = self.undo_stack.pop()
        if self.selected_track_index is not None and self.selected_track_index >= len(self.tracks):
            self.selected_track_index = len(self.tracks) - 1 if self.tracks else None
        return {"done": True}

    def _cmd_redo(self) -> dict:
        return {"done": False}

    # ------------------------------------------------------------------ tracks
    def _cmd_get_track_info(self, track_index: int) -> dict:
        t = self._track(track_index)
        i = self._index_of(track_index)
        info = self._track_summary(i)
        info["clip_slots"] = [
            {"index": s, "has_clip": c is not None, "clip_name": c.name if c else None,
             "clip_length": c.length if c else None, "is_playing": bool(c and c.is_playing)}
            for s, c in enumerate(t.slots)
        ]
        return info

    def _create_track(self, kind: str, index: int = -1, name: str | None = None, color_index: int | None = None) -> dict:
        self._snapshot()
        n = len(self.tracks)
        pos = n if index == -1 or index > n else max(0, index)
        track = FakeTrack(name=name or f"{pos + 1}-{kind.upper()}", type=kind)
        if color_index is not None:
            track.color_index = int(color_index)
        self.tracks.insert(pos, track)
        self.selected_track_index = pos
        return {"track_index": pos}

    def _cmd_create_midi_track(self, index: int = -1, name: str | None = None, color_index: int | None = None) -> dict:
        return self._create_track("midi", index, name, color_index)

    def _cmd_create_audio_track(self, index: int = -1, name: str | None = None, color_index: int | None = None) -> dict:
        return self._create_track("audio", index, name, color_index)

    def _cmd_delete_track(self, track_index: int) -> dict:
        self._track(track_index)
        self._snapshot()
        del self.tracks[self._index_of(track_index)]
        if self.selected_track_index is not None and self.selected_track_index >= len(self.tracks):
            self.selected_track_index = len(self.tracks) - 1 if self.tracks else None
        return {"deleted": True}

    def _cmd_set_track_name(self, track_index: int, name: str) -> dict:
        self._track(track_index).name = str(name)
        return {"name": str(name)}

    def _cmd_set_track_color(self, track_index: int, color_index: int) -> dict:
        if not 0 <= int(color_index) <= 69:
            raise BridgeCommandError("bad_request", "color_index must be within 0..69")
        self._track(track_index).color_index = int(color_index)
        return {"color_index": int(color_index)}

    def _cmd_select_track(self, track_index: int) -> dict:
        self._track(track_index)
        self.selected_track_index = self._index_of(track_index)
        return {"selected": True}

    def _cmd_set_track_mixer(self, track_index: int, volume=None, pan=None, mute=None, solo=None, arm=None) -> dict:
        t = self._track(track_index)
        if volume is not None:
            t.volume = max(0.0, min(1.0, float(volume)))
        if pan is not None:
            t.pan = max(-1.0, min(1.0, float(pan)))
        if mute is not None:
            t.mute = bool(mute)
        if solo is not None:
            t.solo = bool(solo)
        if arm is not None:
            t.arm = bool(arm)
        return {"volume": t.volume, "pan": t.pan, "mute": t.mute, "solo": t.solo, "arm": t.arm}

    # ------------------------------------------------------------------ devices
    def _cmd_load_device(self, track_index: int, device_name: str, position: int = -1) -> dict:
        t = self._track(track_index)
        dev = self._new_device(device_name)
        if dev.type == "instrument" and t.type == "audio":
            raise BridgeCommandError("bad_request", "Cannot load an instrument on an audio track")
        self._snapshot()
        if dev.type == "instrument":
            # Live replaces an existing instrument on a MIDI track.
            t.devices = [d for d in t.devices if d.type != "instrument"]
            pos = 0 if position == -1 else max(0, min(position, len(t.devices)))
        else:
            pos = len(t.devices) if position == -1 or not self.capabilities["insert_device"] else max(0, min(position, len(t.devices)))
        t.devices.insert(pos, dev)
        return {"device_index": pos, "name": dev.name, "class_name": dev.class_name}

    def _cmd_delete_device(self, track_index: int, device_index: int) -> dict:
        self._device(track_index, device_index)
        self._snapshot()
        del self._track(track_index).devices[device_index]
        return {"deleted": True}

    def _cmd_get_device_parameters(self, track_index: int, device_index: int) -> dict:
        d = self._device(track_index, device_index)
        return {
            "device": {"name": d.name, "class_name": d.class_name, "type": d.type},
            "parameters": [p.to_dict(i) for i, p in enumerate(d.parameters)],
        }

    def _cmd_set_device_parameter(self, track_index: int, device_index: int, parameter: Any, value: Any) -> dict:
        d = self._device(track_index, device_index)
        i, p = self._find_param(d, parameter)
        p.value = self._coerce_value(p, value)
        return p.to_dict(i)

    def _cmd_set_device_parameters(self, track_index: int, device_index: int, values: dict) -> dict:
        d = self._device(track_index, device_index)
        applied, failed = [], []
        for key, value in values.items():
            k: Any = int(key) if isinstance(key, str) and key.isdigit() else key
            try:
                i, p = self._find_param(d, k)
                p.value = self._coerce_value(p, value)
                applied.append(p.to_dict(i))
            except BridgeCommandError as e:
                failed.append({"parameter": key, "code": e.code, "message": e.message})
        return {"applied": applied, "failed": failed}

    def _cmd_get_parameter_displays(self, track_index: int, device_index: int, samples: int = 9) -> dict:
        d = self._device(track_index, device_index)
        n = max(2, min(33, int(samples)))
        out = []
        for i, p in enumerate(d.parameters):
            if p.is_quantized:
                continue
            raws = [p.min + (p.max - p.min) * k / (n - 1) for k in range(n)]
            out.append({"index": i, "name": p.name, "samples": [[r, p.str_for_value(r)] for r in raws]})
        return {"parameters": out}

    def _cmd_set_device_enabled(self, track_index: int, device_index: int, enabled: bool) -> dict:
        self._device(track_index, device_index).enabled = bool(enabled)
        return {"enabled": bool(enabled)}

    # ------------------------------------------------------------------ browser
    def _cmd_browser_status(self) -> dict:
        return {"indexed": len(self.browser), "complete": True, "scanning": False, "truncated": False}

    def _cmd_browser_rescan(self, categories: list | None = None) -> dict:
        return {"started": True}

    def _cmd_browser_search(self, query: str, categories: list | None = None,
                            loadable_only: bool = True, limit: int = 25) -> dict:
        words = [w for w in str(query).lower().split() if w]
        hits = []
        for item in self.browser:
            if categories and item["category"] not in categories:
                continue
            if loadable_only and not item["is_loadable"]:
                continue
            path = item["path"].lower()
            if words and all(w in path for w in words):
                name_hits = sum(w in item["name"].lower() for w in words)
                hits.append((-name_hits, len(item["path"]), item))
        hits.sort(key=lambda h: (h[0], h[1]))
        return {"items": [self._public_item(h[2]) for h in hits[: int(limit)]], "index_complete": True}

    def _cmd_browser_list(self, path: str | None = None) -> dict:
        if not path:
            return {"items": [{"name": c, "uri": f"fake:{c}", "path": c, "category": c, "is_loadable": False,
                               "is_device": False, "is_folder": True} for c in CATEGORIES]}
        prefix = path.rstrip("/") + "/"
        children: dict[str, dict] = {}
        for item in self.browser:
            if not item["path"].startswith(prefix):
                continue
            rest = item["path"][len(prefix):]
            head = rest.split("/", 1)[0]
            if "/" in rest:
                children.setdefault(head, {"name": head, "uri": f"fake:{prefix}{head}", "path": prefix + head,
                                           "category": item["category"], "is_loadable": False,
                                           "is_device": False, "is_folder": True})
            else:
                children[head] = self._public_item(item)
        return {"items": list(children.values())}

    def _cmd_load_browser_item(self, track_index: int, uri: str | None = None, path: str | None = None) -> dict:
        t = self._track(track_index)
        item = next((i for i in self.browser if (uri and i["uri"] == uri) or (path and i["path"] == path)), None)
        if item is None:
            raise BridgeCommandError("not_found", f"Browser item not found: {uri or path}")
        self._snapshot()
        for name in item["_loads"]:
            dev = self._new_device(name)
            if dev.type == "instrument":
                t.devices = [d for d in t.devices if d.type != "instrument"]
                t.devices.insert(0, dev)
            else:
                t.devices.append(dev)
        return {"loaded": True, "name": item["name"], "devices": [d.summary(j) for j, d in enumerate(t.devices)]}

    # ------------------------------------------------------------------ clips
    def _cmd_create_clip(self, track_index: int, slot_index: int | None = None, length: float = 4.0,
                         name: str | None = None, overwrite: bool = False) -> dict:
        t = self._track(track_index)
        if t.type != "midi":
            raise BridgeCommandError("bad_request", "create_clip requires a MIDI track")
        if slot_index is None:
            slot_index = next((i for i, c in enumerate(t.slots) if c is None), None)
            if slot_index is None:
                t.slots.append(None)
                slot_index = len(t.slots) - 1
        self._slot(t, slot_index)
        if t.slots[slot_index] is not None and not overwrite:
            raise BridgeCommandError("conflict", f"Slot {slot_index} already has a clip")
        if float(length) <= 0:
            raise BridgeCommandError("bad_request", "length must be > 0")
        self._snapshot()
        t.slots[slot_index] = FakeClip(length=float(length), name=name or "")
        return {"slot_index": slot_index, "length": float(length)}

    def _clip(self, track_index: int, slot_index: int) -> FakeClip:
        t = self._track(track_index)
        self._slot(t, slot_index)
        clip = t.slots[slot_index]
        if clip is None:
            raise BridgeCommandError("not_found", f"No clip in slot {slot_index}")
        return clip

    def _cmd_add_notes(self, track_index: int, slot_index: int, notes: list, replace: bool = False) -> dict:
        clip = self._clip(track_index, slot_index)
        parsed = []
        for n in notes:
            try:
                pitch = int(n["pitch"])
                start = float(n["start"])
                duration = float(n["duration"])
            except (KeyError, TypeError, ValueError):
                raise BridgeCommandError("bad_request", f"Invalid note: {n!r}")
            if not 0 <= pitch <= 127 or duration <= 0 or start < 0:
                raise BridgeCommandError("bad_request", f"Invalid note: {n!r}")
            velocity = int(n.get("velocity", 100))
            parsed.append({"pitch": pitch, "start": start, "duration": duration,
                           "velocity": max(1, min(127, velocity)), "mute": bool(n.get("mute", False))})
        if replace:
            clip.notes = []
        clip.notes.extend(parsed)
        return {"added": len(parsed)}

    def _cmd_get_clip_notes(self, track_index: int, slot_index: int) -> dict:
        clip = self._clip(track_index, slot_index)
        return {"notes": [dict(n) for n in clip.notes], "length": clip.length}

    def _cmd_set_clip_name(self, track_index: int, slot_index: int, name: str) -> dict:
        self._clip(track_index, slot_index).name = str(name)
        return {"name": str(name)}

    def _cmd_fire_clip(self, track_index: int, slot_index: int) -> dict:
        self._clip(track_index, slot_index).is_playing = True
        self.is_playing = True
        return {"ok": True}

    def _cmd_stop_clip(self, track_index: int, slot_index: int) -> dict:
        self._clip(track_index, slot_index).is_playing = False
        return {"ok": True}

    def _cmd_delete_clip(self, track_index: int, slot_index: int) -> dict:
        self._clip(track_index, slot_index)
        self._snapshot()
        self._track(track_index).slots[slot_index] = None
        return {"deleted": True}

    def _cmd_create_audio_clip(self, track_index: int, slot_index: int, file_path: str) -> dict:
        if not self.capabilities["create_audio_clip"]:
            raise BridgeCommandError("unsupported", "create_audio_clip requires Live 12")
        t = self._track(track_index)
        if t.type != "audio":
            raise BridgeCommandError("bad_request", "create_audio_clip requires an audio track")
        self._slot(t, slot_index)
        t.slots[slot_index] = FakeClip(length=4.0, name=Path(file_path).stem)
        return {"slot_index": slot_index}

"""Calibration: dump the *real* parameter names/ranges of devices from a running Live.

The bundled data/device_catalog.json is hand-written from memory of Live 11/12 and is marked
`verified: false`. Run `dump_device_catalog` against a live bridge (the CLI owned by another
module calls it) to produce a verified catalog; `merge_catalog` folds it into the bundled one.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
from pathlib import Path
from typing import Callable

from abhelper.bridge.base import BridgeCommandError, BridgeError

from .library import RecipeLibrary

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "device_catalog.json"
TEMP_TRACK_NAME = "_abhelper_calibration"
DISPLAY_SAMPLES = 9


def load_catalog(path: Path | str = CATALOG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_catalog(catalog: dict, path: Path | str = CATALOG_PATH) -> None:
    Path(path).write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def recipe_device_names(library: RecipeLibrary | None = None) -> list[str]:
    """Every device (instrument, fallback or effect) mentioned by the recipe library."""
    library = library or RecipeLibrary.load_default()
    names: set[str] = set()
    for r in library.all():
        inst = r.get("instrument", {})
        names.add(inst.get("device", ""))
        names.update(inst.get("fallback_devices") or [])
        names.update(fx.get("device", "") for fx in r.get("effects") or [])
    names.discard("")
    return sorted(names)


def dump_device_catalog(bridge, device_names: list[str],
                        progress: Callable[[str], None] | None = None) -> dict:
    """Load each device onto a temporary MIDI track and record its parameters.

    The temporary track (and every loaded device) is removed again, also on errors.
    """
    say = progress or (lambda _msg: None)
    try:
        live_version = bridge.call("ping").get("live_version")
    except BridgeCommandError:
        live_version = None

    devices: dict[str, dict] = {}
    failed: dict[str, str] = {}
    no_displays = False   # old Remote Script without get_parameter_displays
    track_index: int | None = None
    try:
        track_index = bridge.call("create_midi_track", {"name": TEMP_TRACK_NAME})["track_index"]
        for name in device_names:
            say(f"{name}…")
            device_index: int | None = None
            try:
                loaded = bridge.call("load_device", {"track_index": track_index, "device_name": name})
                device_index = loaded["device_index"]
                data = bridge.call("get_device_parameters", {"track_index": track_index, "device_index": device_index})
                dev = data.get("device", {})
                samples_by_index: dict[int, list] = {}
                if not no_displays:
                    try:
                        shown = bridge.call("get_parameter_displays", {
                            "track_index": track_index, "device_index": device_index, "samples": DISPLAY_SAMPLES})
                        for entry in shown.get("parameters", []):
                            samples_by_index[int(entry["index"])] = [[float(r), str(t)] for r, t in entry.get("samples", [])]
                    except BridgeCommandError as exc:
                        if exc.code != "unknown_command":
                            raise
                        no_displays = True
                        say("Remote Script has no get_parameter_displays (old version): no display samples")
                devices[name] = {
                    "class_name": dev.get("class_name", loaded.get("class_name", name)),
                    "type": dev.get("type", "unknown"),
                    "parameters": [],
                }
                for i, p in enumerate(data.get("parameters", [])):
                    entry = {
                        "name": p["name"], "min": p.get("min"), "max": p.get("max"),
                        "default": p.get("default"), "is_quantized": bool(p.get("is_quantized", False)),
                        "value_items": list(p.get("value_items") or []),
                    }
                    idx = p.get("index", i)
                    if not entry["is_quantized"] and idx in samples_by_index:
                        entry["display_samples"] = samples_by_index[idx]
                    devices[name]["parameters"].append(entry)
            except BridgeCommandError as exc:
                failed[name] = f"{exc.code}: {exc.message}"
            finally:
                if device_index is not None:
                    try:
                        bridge.call("delete_device", {"track_index": track_index, "device_index": device_index})
                    except BridgeError:
                        pass
    finally:
        if track_index is not None:
            try:
                bridge.call("delete_track", {"track_index": track_index})
            except BridgeError:
                pass

    meta = {
        "verified": True,
        "live_version": live_version,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "note": "Dumped from a running Live via get_device_parameters and get_parameter_displays.",
    }
    if no_displays:
        meta["note"] += " The Remote Script is too old for get_parameter_displays: no display_samples recorded."
    if failed:
        meta["failed"] = failed
    return {"_meta": meta, "devices": devices}


def merge_catalog(old: dict, new: dict) -> dict:
    """Devices from `new` override `old`; devices only in `old` are kept."""
    merged = copy.deepcopy(old) if old else {"_meta": {}, "devices": {}}
    merged.setdefault("devices", {})
    merged["devices"].update(copy.deepcopy(new.get("devices", {})))
    meta = dict(merged.get("_meta", {}))
    new_meta = new.get("_meta", {})
    meta.update({k: v for k, v in new_meta.items() if k != "failed"})
    # a device that was dumped successfully this time is no longer "failed"
    failed = dict(old.get("_meta", {}).get("failed", {})) if old else {}
    failed.update(new_meta.get("failed", {}))
    failed = {k: v for k, v in failed.items() if k not in new.get("devices", {})}
    if failed:
        meta["failed"] = failed
    else:
        meta.pop("failed", None)
    # "verified" only if every remaining device also came from a live dump
    only_old = set(old.get("devices", {})) - set(new.get("devices", {})) if old else set()
    old_verified = bool(old.get("_meta", {}).get("verified")) if old else True
    meta["verified"] = bool(new_meta.get("verified")) and (old_verified or not only_old)
    if only_old and not old_verified:
        meta["note"] = "Partially verified: devices not in the latest dump come from the hand-written catalog."
    merged["_meta"] = meta
    return merged

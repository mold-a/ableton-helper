"""Hand-written validation of sound recipes (docs/INTERFACES.md, section 3).

No third-party dependencies: `validate_recipe` returns a list of human-readable
error strings, an empty list means the recipe is valid.
"""

from __future__ import annotations

import re
from typing import Any

CATEGORIES = (
    "keys", "piano", "organ", "strings", "brass", "woodwind", "reed", "plucked", "guitar",
    "bass", "lead", "pad", "bell", "mallet", "choir", "fx", "drums", "percussion", "ethnic",
    "synth",
)
DEMO_STYLES = ("chords", "melody", "bass", "arp", "drums", "pad", "single")
DEMO_SCALES = ("major", "minor", "dorian", "phrygian", "mixolydian", "harmonic_minor")
DEMO_VARIANTS = ("default", "four_on_floor", "boom_bap", "trap", "rock", "lofi", "waltz")

ID_RE = re.compile(r"^[a-z0-9_]+$")


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check_value(value: Any, where: str, errors: list[str]) -> None:
    """A parameter value: raw number, a quantized item name or {"norm": 0..1}."""
    if _is_number(value):
        return
    if isinstance(value, str):
        if not value.strip():
            errors.append(f"{where}: empty string value")
        return
    if isinstance(value, dict):
        if set(value) != {"norm"} or not _is_number(value["norm"]):
            errors.append(f'{where}: object value must be exactly {{"norm": 0..1}}')
        elif not 0.0 <= float(value["norm"]) <= 1.0:
            errors.append(f"{where}: norm {value['norm']} is outside 0..1")
        return
    errors.append(f"{where}: unsupported value {value!r} (number, string or {{'norm': x}})")


def _check_params(params: Any, where: str, errors: list[str]) -> None:
    if not isinstance(params, dict):
        errors.append(f"{where}: must be an object {{parameter: value}}")
        return
    for key, value in params.items():
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{where}: parameter names must be non-empty strings")
            continue
        _check_value(value, f"{where}.{key}", errors)


def _check_notes(notes: Any, where: str, length: float | None, errors: list[str]) -> None:
    if not isinstance(notes, list) or not notes:
        errors.append(f"{where}: must be a non-empty list of notes")
        return
    for i, n in enumerate(notes):
        w = f"{where}[{i}]"
        if not isinstance(n, dict):
            errors.append(f"{w}: note must be an object")
            continue
        pitch, start, dur = n.get("pitch"), n.get("start"), n.get("duration")
        if not isinstance(pitch, int) or isinstance(pitch, bool) or not 0 <= pitch <= 127:
            errors.append(f"{w}.pitch: integer 0..127 required")
        if not _is_number(start) or start < 0:
            errors.append(f"{w}.start: number >= 0 required")
        if not _is_number(dur) or dur <= 0:
            errors.append(f"{w}.duration: number > 0 required")
        vel = n.get("velocity", 100)
        if not _is_number(vel) or not 1 <= vel <= 127:
            errors.append(f"{w}.velocity: 1..127 required")
        if length and _is_number(start) and _is_number(dur) and start + dur > length + 1e-9:
            errors.append(f"{w}: ends after clip length {length}")


def _check_device_name(name: Any, where: str, errors: list[str]) -> None:
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{where}: device name must be a non-empty string")


def validate_recipe(recipe: dict, custom: bool = False) -> list[str]:
    """Validate a recipe dict. `custom=True` relaxes the library requirements
    (id / aliases / name / category may be omitted) for recipes authored by the LLM.
    """
    errors: list[str] = []
    if not isinstance(recipe, dict):
        return ["recipe must be an object"]

    # id
    rid = recipe.get("id")
    if rid is None:
        if not custom:
            errors.append("id: required")
    elif not isinstance(rid, str) or not ID_RE.match(rid):
        errors.append("id: must match [a-z0-9_]+")

    if "version" in recipe and (not isinstance(recipe["version"], int) or isinstance(recipe["version"], bool)):
        errors.append("version: must be an integer")

    # name
    name = recipe.get("name")
    if name is None:
        if not custom:
            errors.append("name.en: required")
    elif not isinstance(name, dict):
        errors.append("name: must be an object {ru?, en}")
    else:
        if not custom and not (isinstance(name.get("en"), str) and name["en"].strip()):
            errors.append("name.en: required non-empty string")
        for lang, v in name.items():
            if not isinstance(v, str) or not v.strip():
                errors.append(f"name.{lang}: must be a non-empty string")

    # category
    cat = recipe.get("category")
    if cat is None:
        if not custom:
            errors.append("category: required")
    elif cat not in CATEGORIES:
        errors.append(f"category: '{cat}' is not one of {', '.join(CATEGORIES)}")

    # aliases / tags / preset_search
    aliases = recipe.get("aliases")
    if aliases is None:
        if not custom:
            errors.append("aliases: at least one alias required")
    elif not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        errors.append("aliases: must be a list of non-empty strings")
    elif not custom and not aliases:
        errors.append("aliases: at least one alias required")
    for key in ("tags", "preset_search"):
        v = recipe.get(key)
        if v is not None and (not isinstance(v, list) or not all(isinstance(a, str) and a.strip() for a in v)):
            errors.append(f"{key}: must be a list of non-empty strings")

    desc = recipe.get("description")
    if desc is not None:
        if not isinstance(desc, dict) or not all(isinstance(v, str) for v in desc.values()):
            errors.append("description: must be an object {ru?, en?} of strings")
    notes_txt = recipe.get("sound_design_notes")
    if notes_txt is not None and not isinstance(notes_txt, str):
        errors.append("sound_design_notes: must be a string")

    # track
    track = recipe.get("track")
    if track is not None:
        if not isinstance(track, dict):
            errors.append("track: must be an object")
        else:
            if "name" in track and (not isinstance(track["name"], str) or not track["name"].strip()):
                errors.append("track.name: must be a non-empty string")
            ci = track.get("color_index")
            if ci is not None and (not isinstance(ci, int) or isinstance(ci, bool) or not 0 <= ci <= 69):
                errors.append("track.color_index: integer 0..69 required")

    # instrument
    inst = recipe.get("instrument")
    if not isinstance(inst, dict):
        errors.append("instrument: required object")
    else:
        _check_device_name(inst.get("device"), "instrument.device", errors)
        fb = inst.get("fallback_devices")
        if fb is not None:
            if not isinstance(fb, list):
                errors.append("instrument.fallback_devices: must be a list")
            else:
                for i, d in enumerate(fb):
                    _check_device_name(d, f"instrument.fallback_devices[{i}]", errors)
        if "parameters" in inst:
            _check_params(inst["parameters"], "instrument.parameters", errors)
        fbp = inst.get("fallback_parameters")
        if fbp is not None:
            if not isinstance(fbp, dict):
                errors.append("instrument.fallback_parameters: must be {device: {parameter: value}}")
            else:
                for dev, params in fbp.items():
                    _check_params(params, f"instrument.fallback_parameters.{dev}", errors)

    # effects
    effects = recipe.get("effects")
    if effects is not None:
        if not isinstance(effects, list):
            errors.append("effects: must be a list")
        else:
            for i, fx in enumerate(effects):
                if not isinstance(fx, dict):
                    errors.append(f"effects[{i}]: must be an object")
                    continue
                _check_device_name(fx.get("device"), f"effects[{i}].device", errors)
                if "parameters" in fx:
                    _check_params(fx["parameters"], f"effects[{i}].parameters", errors)

    # demo
    demo = recipe.get("demo")
    if demo is not None:
        if not isinstance(demo, dict):
            errors.append("demo: must be an object")
        else:
            style = demo.get("style")
            if style is not None and style not in DEMO_STYLES:
                errors.append(f"demo.style: '{style}' is not one of {', '.join(DEMO_STYLES)}")
            root = demo.get("root")
            if root is not None and (not isinstance(root, int) or isinstance(root, bool) or not 0 <= root <= 127):
                errors.append("demo.root: integer 0..127 required")
            length = demo.get("length")
            if length is not None and (not _is_number(length) or not 0 < length <= 128):
                errors.append("demo.length: number in (0, 128] required")
            scale = demo.get("scale")
            if scale is not None and scale not in DEMO_SCALES:
                errors.append(f"demo.scale: '{scale}' is not one of {', '.join(DEMO_SCALES)}")
            variant = demo.get("variant")
            if variant is not None and variant not in DEMO_VARIANTS:
                errors.append(f"demo.variant: '{variant}' is not one of {', '.join(DEMO_VARIANTS)}")
            if demo.get("notes") is not None:
                _check_notes(demo["notes"], "demo.notes", float(length) if _is_number(length) else None, errors)
    return errors

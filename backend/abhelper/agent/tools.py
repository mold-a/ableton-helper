"""LLM tool schemas (the model's manual) and their executors.

Tool names are fixed by docs/INTERFACES.md §4. There is deliberately no open-ended
eval/exec tool: the tool list is closed.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..bridge.base import BridgeCommandError, BridgeConnectionError

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- limits
MAX_PARAMS = 120
MAX_BROWSER_ITEMS = 15
MAX_TRACKS = 60
MAX_NOTES = 2000
MAX_HELP_CHARS = 1800
MAX_RESULT_CHARS = 24000
LONG_TIMEOUT = 30.0  # browser / device loading can be slow in Live

BRIDGE_OFFLINE_MESSAGE = (
    "Нет связи с Ableton Live: Remote Script «AbletonHelper» не отвечает. Убедитесь, что Live запущен, "
    "скрипт установлен, и в Live: Preferences → Link, Tempo & MIDI → Control Surface выбран «AbletonHelper» "
    "(порт 9888). Пока Live не подключён, можно отвечать только на вопросы по справке."
)
ENGINE_MISSING_MESSAGE = "Звуковой движок недоступен (модуль abhelper.sound не загружен)."


# --------------------------------------------------------------------------- schemas
_TRACK_INDEX = {
    "type": "integer",
    "description": "0-based index of the track in the Set (the 'index' from get_session_overview). -1 means the last track.",
}
_DEVICE_INDEX = {
    "type": "integer",
    "description": "0-based index of the device in the track's device chain (the 'index' from get_session_overview/get_track_details).",
}

CUSTOM_RECIPE_DESCRIPTION = """\
Build a brand-new sound from your own synthesis design when search_sound_library has no fitting recipe, \
then create it on a new MIDI track (with effects and a demo clip). The engine loads the instrument, applies \
parameters with fuzzy name matching, adds the effect chain and writes a demo clip. Check `unmatched_parameters` \
in the result and fix them via get_device_parameters + set_device_parameters.

Recipe object (JSON):
- instrument (required): {"device": <native Live instrument name>, "fallback_devices": [names tried if the \
main one is missing], "parameters": {<parameter name as in Live's UI>: value}}. Devices: "Operator", \
"Wavetable", "Analog", "Drift", "Electric", "Tension", "Collision", "Simpler", "Sampler", "Drum Rack". \
Native devices only, never VST/AU/Max for Live.
- value formats: a number (raw value), a string (item of a dropdown parameter, e.g. "Saw D"), or \
{"norm": 0..1} (position within the parameter's range; the safest way to set continuous parameters).
- effects (optional, ordered): [{"device": "Chorus-Ensemble" | "Reverb" | "EQ Eight" | "Saturator" | "Delay" | \
"Echo" | "Auto Filter" | "Compressor" | ..., "parameters": {...}}].
- name: {"ru": "...", "en": "..."}; category: one of keys, piano, organ, strings, brass, woodwind, reed, \
plucked, guitar, bass, lead, pad, bell, mallet, choir, fx, drums, percussion, ethnic, synth.
- track: {"name": "<track name>", "color_index": 0..69}.
- preset_search (optional): list of terms to look for a close preset in Live's browser.
- demo: {"style": chords|melody|bass|arp|drums|pad|single, "root": <MIDI pitch>, "length": <beats>, \
"notes": [{"pitch", "start", "duration", "velocity"}]} - a demo clip to audition the sound.
- sound_design_notes: one or two sentences on why these settings imitate the target sound.

Example (reedy accordion-like tone):
{"name": {"ru": "Гармонь", "en": "Reed accordion"}, "category": "reed", \
"instrument": {"device": "Operator", "fallback_devices": ["Wavetable"], "parameters": {"Algorithm": 10, \
"Osc-A Wave": "Saw D", "Filter Freq": {"norm": 0.55}, "Ae Attack": {"norm": 0.12}}}, \
"effects": [{"device": "Chorus-Ensemble", "parameters": {"Dry/Wet": {"norm": 0.3}}}, \
{"device": "Reverb", "parameters": {"Dry/Wet": {"norm": 0.18}}}], \
"track": {"name": "Гармонь"}, "demo": {"style": "chords", "root": 57, "length": 8}, \
"sound_design_notes": "Two slightly detuned saw voices (musette) through a soft low-pass with a gentle attack."}

Parameter names differ between Live versions; if unsure, create the sound with fewer parameters and then \
tune using get_device_parameters. Invalid recipes are rejected with a list of errors: fix them and retry."""

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_session_overview",
        "description": (
            "Read the current Ableton Live Set: tempo, time signature, whether it is playing, and every track "
            "with its index, name, type (midi/audio/group), flags (mute/solo/arm) and device chain (names and "
            "indices). Use it before changing anything in an existing Set, to find which track the user means "
            "('make it brighter' usually refers to the most recently created or selected track), to resolve "
            "track/device indices for other tools, and to answer questions about the user's project. No inputs."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_track_details",
        "description": (
            "Details of one track: type, mute/solo/arm, full device chain (index, name, class) and its clip "
            "slots (which slots hold clips, their names and lengths, which is playing). Use it to find a free "
            "clip slot, to see what instrument/effects a track has before editing, or to inspect a track "
            "the user is asking about."
        ),
        "input_schema": {"type": "object", "properties": {"track_index": _TRACK_INDEX},
                         "required": ["track_index"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "search_sound_library",
        "description": (
            "Search the built-in library of sound recipes (ready-made instrument + parameters + effects + demo "
            "clip) by the user's words in Russian or English, e.g. 'баян', 'accordion', 'тёплый пэд', "
            "'808 bass'. Returns matches with recipe_id, name, category and score (0..1; above ~0.6 is a "
            "good match). This is always the FIRST step for a sound request. Pass the best recipe_id to "
            "create_sound. If nothing matches well, use design_custom_sound instead."
        ),
        "input_schema": {"type": "object", "properties": {"query": {
            "type": "string", "description": "What sound the user wants, in their own words (RU or EN)."}},
            "required": ["query"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "search_live_browser",
        "description": (
            "Search Live's own browser (factory packs, user library: presets, instruments, kits) for presets "
            "matching a text query. Prefer English terms ('accordion', 'warm pad', 'wurlitzer'); Live preset "
            "names are English. Returns up to 15 items with name, path, uri, category and relevance score. "
            "Pass the best item's `uri` as preset_uri to create_sound to load that preset. Requires Live to be "
            "connected. The browser index fills in gradually after Live starts, so results may be partial."
        ),
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search words (English works best)."},
            "categories": {"type": "array", "items": {"type": "string", "enum": [
                "sounds", "instruments", "drums", "audio_effects", "midi_effects", "samples", "packs",
                "user_library", "clips", "plugins", "max_for_live"]},
                "description": "Optional filter. For playable sounds use ['sounds', 'instruments', 'drums']."},
        }, "required": ["query"], "additionalProperties": False},
    },
    {
        "name": "create_sound",
        "description": (
            "Create a sound in Live: makes a new MIDI track (or re-uses `track_index`), loads the instrument "
            "from a library recipe or a Live preset, applies parameters and effects, names the track and "
            "adds a demo clip. This is the main action for requests like 'I want an accordion sound'. "
            "Give `description` (the user's request) and usually a `recipe_id` from search_sound_library. "
            "strategy: 'auto' (default: recipe, then browser preset, then synthesis), 'recipe' (force "
            "synthesis from the recipe), 'preset' (force a browser preset; give preset_uri from "
            "search_live_browser). The result lists track_index, devices, demo_clip_slot, warnings and "
            "`unmatched_parameters` (parameters the engine could not map): if that list is non-empty, call "
            "get_device_parameters for that device and fix the values with set_device_parameters. Do not call "
            "this twice for the same request unless the first call failed."
        ),
        "input_schema": {"type": "object", "properties": {
            "description": {"type": "string", "description": "The user's request in their words, e.g. 'звук баяна'."},
            "recipe_id": {"type": "string", "description": "Recipe id from search_sound_library."},
            "preset_uri": {"type": "string", "description": "Browser item uri from search_live_browser."},
            "strategy": {"type": "string", "enum": ["auto", "preset", "recipe"], "description": "Default 'auto'."},
            "track_name": {"type": "string", "description": "Override the track name (default comes from the recipe)."},
            "add_demo_clip": {"type": "boolean", "description": "Add a demo clip to audition the sound (default true)."},
            "track_index": {"type": "integer", "description": (
                "Replace the instrument of this existing MIDI track instead of creating a new track. "
                "Omit to create a new track.")},
        }, "required": ["description"], "additionalProperties": False},
    },
    {
        "name": "design_custom_sound",
        "description": CUSTOM_RECIPE_DESCRIPTION,
        "input_schema": {"type": "object", "properties": {
            "description": {"type": "string", "description": "The user's request in their words."},
            "recipe": {"type": "object", "description": "The custom recipe object described above.",
                       "properties": {
                           "name": {"type": "object"},
                           "category": {"type": "string"},
                           "instrument": {"type": "object", "properties": {
                               "device": {"type": "string"},
                               "fallback_devices": {"type": "array", "items": {"type": "string"}},
                               "parameters": {"type": "object"},
                               "fallback_parameters": {"type": "object"}},
                               "required": ["device"]},
                           "effects": {"type": "array", "items": {"type": "object", "properties": {
                               "device": {"type": "string"}, "parameters": {"type": "object"}},
                               "required": ["device"]}},
                           "track": {"type": "object"},
                           "preset_search": {"type": "array", "items": {"type": "string"}},
                           "demo": {"type": "object"},
                           "sound_design_notes": {"type": "string"}},
                       "required": ["instrument"]},
        }, "required": ["description", "recipe"], "additionalProperties": False},
    },
    {
        "name": "get_device_parameters",
        "description": (
            "Read the REAL parameters of one device: name, current value, min, max, display text (e.g. "
            "'2.5 kHz') and, for dropdown/quantized parameters, the list of allowed items. Parameter names "
            "and ranges differ between Live versions and devices, so always call this before editing a "
            "device you did not just configure, and to resolve `unmatched_parameters` from create_sound. "
            "Long lists are truncated to the first 120 parameters."
        ),
        "input_schema": {"type": "object", "properties": {"track_index": _TRACK_INDEX, "device_index": _DEVICE_INDEX},
                         "required": ["track_index", "device_index"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "set_device_parameters",
        "description": (
            "Set one or more parameters of a device in one call. `values` maps a parameter name (or its "
            "numeric index) to: a number (raw value, clamped to the parameter's range), a string (an item "
            "of a dropdown parameter, e.g. 'Saw D'), or {\"norm\": 0..1} (position within the range, best for "
            "'a bit brighter'-style edits). Names are matched case-insensitively. A parameter that doesn't "
            "exist is reported in `failed` without stopping the others: re-read the real names with "
            "get_device_parameters. Never guess parameter names from memory when editing an existing device."
        ),
        "input_schema": {"type": "object", "properties": {
            "track_index": _TRACK_INDEX, "device_index": _DEVICE_INDEX,
            "values": {"type": "object", "description": (
                "e.g. {\"Filter Freq\": {\"norm\": 0.7}, \"Osc-A Wave\": \"Saw D\", \"Dry/Wet\": 0.25}"),
                "additionalProperties": True},
        }, "required": ["track_index", "device_index", "values"], "additionalProperties": False},
    },
    {
        "name": "load_device",
        "description": (
            "Add a native Live device (native Live devices only - no VST/AU/M4L) to a track by its name as shown "
            "in Live's browser: instruments ('Operator', 'Wavetable', 'Analog', 'Drift', 'Drum Rack', "
            "'Simpler'), audio effects ('Reverb', 'Delay', 'Echo', 'EQ Eight', 'Compressor', 'Saturator', "
            "'Chorus-Ensemble', 'Auto Filter', 'Phaser-Flanger', 'Utility', 'Limiter') or MIDI effects "
            "('Arpeggiator', 'Chord', 'Scale'). Loading an instrument on a MIDI track replaces the existing "
            "instrument. Returns the new device's index; follow up with get_device_parameters and "
            "set_device_parameters to configure it."
        ),
        "input_schema": {"type": "object", "properties": {
            "track_index": _TRACK_INDEX,
            "device_name": {"type": "string", "description": "Exact native device name, e.g. 'Reverb'."},
        }, "required": ["track_index", "device_name"], "additionalProperties": False},
    },
    {
        "name": "create_midi_clip",
        "description": (
            "Create a MIDI clip with notes on a MIDI track (melody, chords, bass line, drum pattern). Times "
            "are in beats (quarter notes): a 4/4 bar = 4 beats. Pitch is MIDI 0..127 (60 = C3 in Live; "
            "36 = C1 kick on a Drum Rack, 38 snare, 42 closed hat). `length` is the clip length in beats "
            "(e.g. 8 = two bars). By default the first free clip slot is used; pass slot_index to choose. "
            "Fails with code 'conflict' if the slot already holds a clip: pick another slot (see "
            "get_track_details). It never overwrites existing clips. Set fire=true to launch the clip so "
            "the user hears it immediately."
        ),
        "input_schema": {"type": "object", "properties": {
            "track_index": _TRACK_INDEX,
            "notes": {"type": "array", "description": "Notes of the clip.", "items": {
                "type": "object", "properties": {
                    "pitch": {"type": "integer", "minimum": 0, "maximum": 127},
                    "start": {"type": "number", "minimum": 0, "description": "Start in beats from clip start."},
                    "duration": {"type": "number", "description": "Length in beats (> 0)."},
                    "velocity": {"type": "integer", "minimum": 1, "maximum": 127, "description": "Default 100."}},
                "required": ["pitch", "start", "duration"], "additionalProperties": False}},
            "length": {"type": "number", "description": "Clip length in beats, e.g. 8."},
            "slot_index": {"type": "integer", "description": "Clip slot (0-based). Default: first empty slot."},
            "name": {"type": "string", "description": "Clip name."},
            "fire": {"type": "boolean", "description": "Launch the clip after creating it (default false)."},
        }, "required": ["track_index", "notes", "length"], "additionalProperties": False},
    },
    {
        "name": "transport",
        "description": (
            "Control Live's transport: action 'play' starts playback, 'stop' stops it, 'set_tempo' sets the "
            "tempo in BPM (20..999; give `tempo`). Use only when the user asks, or to let them hear what "
            "you just made."
        ),
        "input_schema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["play", "stop", "set_tempo"]},
            "tempo": {"type": "number", "description": "BPM, required for set_tempo."},
        }, "required": ["action"], "additionalProperties": False},
    },
    {
        "name": "undo_last_action",
        "description": (
            "Undo the single most recent undoable action in Live (like Ctrl/Cmd+Z). Use when the user asks "
            "to undo, or to revert your own clear mistake. Call it once per step to go back further. No inputs."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "search_ableton_help",
        "description": (
            "Search the built-in Ableton Live knowledge base (how-to articles in Russian/English: warping, "
            "recording, routing, clips, devices, shortcuts, Live 11/12 differences). Use it FIRST for any "
            "'how do I do X in Ableton' question and ground the answer in the returned sections. Returns up "
            "to 4 sections with title, section heading and text. Works without a Live connection."
        ),
        "input_schema": {"type": "object", "properties": {"query": {
            "type": "string", "description": "The question or key terms, e.g. 'как сделать варп лупа'."}},
            "required": ["query"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "rename_track",
        "description": "Rename a track. Use for requests like 'rename this track to Lead'.",
        "input_schema": {"type": "object", "properties": {"track_index": _TRACK_INDEX, "name": {
            "type": "string", "description": "New track name."}},
            "required": ["track_index", "name"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "delete_track",
        "description": (
            "Delete a track from the Set (destructive; can be reverted with undo_last_action). Only delete a "
            "track that YOU created in this conversation, or when the user explicitly asks to delete a "
            "specific track. Never delete tracks on your own initiative. Track indices shift after deletion."
        ),
        "input_schema": {"type": "object", "properties": {"track_index": _TRACK_INDEX},
                         "required": ["track_index"], "additionalProperties": False},
        "strict": True,
    },
]

_SCHEMA_BY_NAME = {t["name"]: t["input_schema"] for t in TOOL_SCHEMAS}
TOOL_NAMES = [t["name"] for t in TOOL_SCHEMAS]


def get_tools(strict: bool = True) -> list[dict[str, Any]]:
    """Tool definitions for the API (static, deterministic order: cache-friendly)."""
    tools = copy.deepcopy(TOOL_SCHEMAS)
    if not strict:
        for t in tools:
            t.pop("strict", None)
    return tools


# --------------------------------------------------------------------------- validation
_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def validate_input(schema: dict[str, Any], value: Any, path: str = "input") -> list[str]:
    """Light JSON-schema validator (type, required, enum, bounds, items, additionalProperties)."""
    errors: list[str] = []
    t = schema.get("type")
    if t and not _TYPE_CHECKS[t](value):
        return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
    if t in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")
    if t == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        addl = schema.get("additionalProperties", True)
        for key, sub in value.items():
            if key in props:
                errors.extend(validate_input(props[key], sub, f"{path}.{key}"))
            elif addl is False:
                errors.append(f"{path}: unexpected property '{key}'")
            elif isinstance(addl, dict):
                errors.extend(validate_input(addl, sub, f"{path}.{key}"))
    if t == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "items" in schema:
            for i, sub in enumerate(value):
                errors.extend(validate_input(schema["items"], sub, f"{path}[{i}]"))
                if len(errors) > 12:
                    break
    return errors[:12]


# --------------------------------------------------------------------------- results
@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    code: str | None = None  # error code for the UI/model (bridge_offline, invalid_input, ...)

    def model_content(self) -> str:
        """Compact JSON string for the tool_result block."""
        payload = self.data if self.ok else {"error": self.summary_for_model(), "code": self.code, **self.data}
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = json.dumps({"truncated": True, "partial_json": text[: MAX_RESULT_CHARS - 200]},
                              ensure_ascii=False)
        return text

    def summary_for_model(self) -> str:
        return self.data.get("message") or self.summary

    def ui_data(self) -> dict[str, Any]:
        return self.data if self.ok else {"error": self.summary, "code": self.code, **self.data}


def _ok(data: dict[str, Any], summary: str) -> ToolResult:
    return ToolResult(True, data, summary)


def _fail(message: str, code: str = "error", **extra: Any) -> ToolResult:
    return ToolResult(False, dict(extra), message, code)


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return dict(vars(obj))


def _cap(items: list, limit: int) -> tuple[list, dict[str, Any]]:
    if len(items) <= limit:
        return items, {}
    return items[:limit], {"truncated": True, "total": len(items)}


def _num(v: Any) -> Any:
    return round(v, 4) if isinstance(v, float) else v


@dataclass
class _FallbackSoundRequest:
    description: str
    recipe_id: str | None = None
    recipe: dict | None = None
    preset_uri: str | None = None
    strategy: str = "auto"
    track_name: str | None = None
    add_demo_clip: bool = True
    track_index: int | None = None


def _sound_request_cls() -> Any:
    try:
        from ..sound import SoundRequest  # type: ignore

        return SoundRequest
    except ImportError:
        return _FallbackSoundRequest


def _default_recipe_validator(recipe: dict) -> list[str]:
    try:
        from ..sound import validate_recipe  # type: ignore

        try:
            return validate_recipe(recipe, custom=True)  # LLM recipes may omit id/aliases/name
        except TypeError:  # older signature: validate_recipe(recipe)
            return validate_recipe(recipe)
    except ImportError:
        errors = []
        inst = recipe.get("instrument") if isinstance(recipe, dict) else None
        if not isinstance(inst, dict) or not isinstance(inst.get("device"), str) or not inst["device"].strip():
            errors.append("instrument.device is required")
        return errors


# --------------------------------------------------------------------------- executor
class ToolExecutor:
    def __init__(self, bridge: Any, engine: Any, knowledge: Any,
                 recipe_validator: Callable[[dict], list[str]] | None = None):
        self.bridge = bridge
        self.engine = engine
        self.knowledge = knowledge
        self.recipe_validator = recipe_validator or _default_recipe_validator

    def execute(self, name: str, tool_input: Any) -> ToolResult:
        handler = getattr(self, f"_t_{name}", None)
        schema = _SCHEMA_BY_NAME.get(name)
        if handler is None or schema is None:
            return _fail(f"Неизвестный инструмент: {name}", "unknown_tool")
        errors = validate_input(schema, tool_input)
        if errors:
            return _fail("Неверные параметры инструмента: " + "; ".join(errors), "invalid_input",
                         validation_errors=errors)
        try:
            return handler(**tool_input)
        except BridgeConnectionError as e:
            log.info("bridge offline during %s: %s", name, e)
            return _fail(BRIDGE_OFFLINE_MESSAGE, "bridge_offline", detail=str(e))
        except BridgeCommandError as e:
            return _fail(f"Live ответил ошибкой ({e.code}): {e.message}", e.code, message_en=e.message)
        except Exception as e:  # never crash the agent loop
            log.exception("tool %s crashed", name)
            return _fail(f"Внутренняя ошибка инструмента {name}: {e}", "internal")

    # ---- helpers
    def _call(self, command: str, params: dict | None = None, timeout: float | None = None) -> dict:
        return self.bridge.call(command, params or {}, timeout)

    def _need_engine(self) -> ToolResult | None:
        return None if self.engine is not None else _fail(ENGINE_MISSING_MESSAGE, "engine_missing")

    # ---- session / tracks
    def _t_get_session_overview(self) -> ToolResult:
        info = self._call("get_session_info")
        tracks = []
        for t in info.get("tracks", []):
            row: dict[str, Any] = {"index": t.get("index"), "name": t.get("name"), "type": t.get("type"),
                                   "devices": [{"index": d.get("index"), "name": d.get("name")}
                                               for d in t.get("devices", [])]}
            for flag in ("mute", "solo", "arm", "is_selected"):
                if t.get(flag):
                    row[flag] = True
            tracks.append(row)
        tracks, extra = _cap(tracks, MAX_TRACKS)
        data = {"tempo": info.get("tempo"), "signature": info.get("signature"),
                "is_playing": info.get("is_playing"), "track_count": info.get("track_count", len(tracks)),
                "return_track_count": info.get("return_track_count"),
                "selected_track_index": info.get("selected_track_index"), "tracks": tracks, **extra}
        return _ok(data, f"Сет: {data['track_count']} дорожек, темп {_num(info.get('tempo'))}")

    def _t_get_track_details(self, track_index: int) -> ToolResult:
        info = self._call("get_track_info", {"track_index": track_index})
        slots = info.get("clip_slots", [])
        filled = [s for s in slots if s.get("has_clip")]
        data = {k: info.get(k) for k in ("index", "name", "type", "mute", "solo", "arm") if k in info}
        data["devices"] = info.get("devices", [])
        data["clips"] = filled
        data["slot_count"] = len(slots)
        data["free_slots"] = [s.get("index") for s in slots if not s.get("has_clip")][:8]
        return _ok(data, f"Дорожка «{info.get('name')}»: устройств {len(data['devices'])}, клипов {len(filled)}")

    def _t_rename_track(self, track_index: int, name: str) -> ToolResult:
        res = self._call("set_track_name", {"track_index": track_index, "name": name})
        return _ok({"name": res.get("name", name), "track_index": track_index}, f"Дорожка переименована: «{name}»")

    def _t_delete_track(self, track_index: int) -> ToolResult:
        name = None
        try:
            name = self._call("get_track_info", {"track_index": track_index}).get("name")
        except BridgeCommandError:
            pass
        self._call("delete_track", {"track_index": track_index})
        label = f"«{name}»" if name else f"№{track_index}"
        return _ok({"deleted": True, "name": name, "note": "Track indices after this one shifted down by one."},
                   f"Удалена дорожка {label}")

    # ---- sound
    def _t_search_sound_library(self, query: str) -> ToolResult:
        if (r := self._need_engine()):
            return r
        matches = [_as_dict(m) for m in self.engine.find_recipes(query, 6)]
        matches = [{k: _num(v) for k, v in m.items()} for m in matches]
        data: dict[str, Any] = {"matches": matches}
        if not matches:
            data["hint"] = "No recipe matched. Try an English synonym, or use design_custom_sound."
        return _ok(data, f"В библиотеке найдено рецептов: {len(matches)}")

    def _t_search_live_browser(self, query: str, categories: list[str] | None = None) -> ToolResult:
        if (r := self._need_engine()):
            return r
        items = self.engine.search_presets(query, None, 30 if categories else MAX_BROWSER_ITEMS)
        items = [_as_dict(i) for i in items]
        if categories:
            items = [i for i in items if i.get("category") in categories]
        total = len(items)
        items = items[:MAX_BROWSER_ITEMS]
        slim = [{k: _num(i[k]) for k in ("name", "path", "uri", "category", "score") if k in i} for i in items]
        data: dict[str, Any] = {"items": slim}
        if total > MAX_BROWSER_ITEMS:
            data.update(truncated=True, total=total)
        if not slim:
            data["hint"] = "Nothing found (the browser index may still be building). Try other words."
        return _ok(data, f"В браузере Live найдено пресетов: {len(slim)}")

    def _create(self, **req_kwargs: Any) -> ToolResult:
        if (r := self._need_engine()):
            return r
        request = _sound_request_cls()(**req_kwargs)
        result = _as_dict(self.engine.create_sound(request))
        data = dict(result)
        data["devices"], extra_d = _cap(list(data.get("devices") or []), 12)
        data["unmatched_parameters"], extra_u = _cap(list(data.get("unmatched_parameters") or []), 30)
        data["warnings"] = list(data.get("warnings") or [])[:10]
        if extra_d or extra_u:
            data["truncated"] = True
        if isinstance(data.get("preset"), dict):
            data["preset"] = {k: v for k, v in data["preset"].items() if k in ("name", "path", "uri")}
        name = data.get("track_name")
        if not data.get("ok", False):
            msg = data.get("message") or "Не удалось создать звук."
            return ToolResult(False, data, msg, "create_failed")
        if req_kwargs.get("track_index") is None:
            summary = f"Создана дорожка «{name}»"
        else:
            summary = f"Звук обновлён на дорожке «{name}»"
        n_un = len(result.get("unmatched_parameters") or [])
        if n_un:
            summary += f" (параметров не применено: {n_un})"
        return _ok(data, summary)

    def _t_create_sound(self, description: str, recipe_id: str | None = None, preset_uri: str | None = None,
                        strategy: str = "auto", track_name: str | None = None,
                        add_demo_clip: bool = True, track_index: int | None = None) -> ToolResult:
        return self._create(description=description, recipe_id=recipe_id, preset_uri=preset_uri,
                            strategy=strategy, track_name=track_name, add_demo_clip=add_demo_clip,
                            track_index=track_index)

    def _t_design_custom_sound(self, description: str, recipe: dict) -> ToolResult:
        errors = self.recipe_validator(recipe)
        if errors:
            return _fail("Рецепт не прошёл проверку: " + "; ".join(errors[:10]), "invalid_recipe",
                         validation_errors=errors[:20])
        return self._create(description=description, recipe=recipe, strategy="recipe")

    # ---- devices
    def _t_get_device_parameters(self, track_index: int, device_index: int) -> ToolResult:
        res = self._call("get_device_parameters", {"track_index": track_index, "device_index": device_index})
        params = []
        for p in res.get("parameters", []):
            row = {"index": p.get("index"), "name": p.get("name"), "value": _num(p.get("value")),
                   "min": _num(p.get("min")), "max": _num(p.get("max")), "display": p.get("display")}
            if p.get("is_quantized") and p.get("value_items"):
                row["items"] = list(p["value_items"])[:30]
            params.append(row)
        params, extra = _cap(params, MAX_PARAMS)
        device = res.get("device", {})
        data = {"device": device, "parameters": params, **extra}
        return _ok(data, f"Параметры «{device.get('name', '?')}»: {len(params)}")

    def _t_set_device_parameters(self, track_index: int, device_index: int, values: dict) -> ToolResult:
        if not values:
            return _fail("Пустой словарь values: нечего менять.", "invalid_input")
        bad = [k for k, v in values.items() if not self._valid_value(v)]
        if bad:
            return _fail("Недопустимые значения для: " + ", ".join(map(str, bad[:10]))
                         + ". Допустимо: число, строка или {\"norm\": 0..1}.", "invalid_input")
        res = self._call("set_device_parameters",
                         {"track_index": track_index, "device_index": device_index, "values": values})
        applied = [{"name": p.get("name"), "value": _num(p.get("value")), "display": p.get("display")}
                   for p in res.get("applied", [])]
        failed = res.get("failed", [])
        data = {"applied": applied, "failed": failed[:30]}
        summary = f"Изменено параметров: {len(applied)}"
        if failed:
            summary += f", не найдено: {len(failed)}"
        if not applied:
            return ToolResult(False, data, summary, "no_parameters_applied")
        return _ok(data, summary)

    @staticmethod
    def _valid_value(v: Any) -> bool:
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float, str)):
            return True
        return isinstance(v, dict) and set(v) == {"norm"} and isinstance(v["norm"], (int, float)) \
            and not isinstance(v["norm"], bool) and 0 <= v["norm"] <= 1

    def _t_load_device(self, track_index: int, device_name: str) -> ToolResult:
        res = self._call("load_device", {"track_index": track_index, "device_name": device_name},
                         timeout=LONG_TIMEOUT)
        return _ok(res, f"Добавлено устройство «{res.get('name', device_name)}» на дорожку {track_index}")

    # ---- clips / transport
    def _t_create_midi_clip(self, track_index: int, notes: list, length: float, slot_index: int | None = None,
                            name: str | None = None, fire: bool = False) -> ToolResult:
        if length <= 0:
            return _fail("length должна быть > 0.", "invalid_input")
        if not notes:
            return _fail("notes пуст: добавьте хотя бы одну ноту.", "invalid_input")
        if len(notes) > MAX_NOTES:
            return _fail(f"Слишком много нот ({len(notes)} > {MAX_NOTES}).", "invalid_input")
        for i, n in enumerate(notes):
            if n["duration"] <= 0:
                return _fail(f"notes[{i}].duration должна быть > 0.", "invalid_input")
        params: dict[str, Any] = {"track_index": track_index, "length": float(length), "overwrite": False}
        if slot_index is not None:
            params["slot_index"] = slot_index
        if name:
            params["name"] = name
        clip = self._call("create_clip", params)
        slot = clip.get("slot_index", slot_index)
        added = self._call("add_notes", {"track_index": track_index, "slot_index": slot, "notes": notes})
        fired = False
        if fire:
            self._call("fire_clip", {"track_index": track_index, "slot_index": slot})
            fired = True
        data = {"track_index": track_index, "slot_index": slot, "length": clip.get("length", length),
                "notes_added": added.get("added", len(notes)), "fired": fired}
        return _ok(data, f"Создан MIDI-клип: нот {data['notes_added']}, слот {slot}")

    def _t_transport(self, action: str, tempo: float | None = None) -> ToolResult:
        if action == "play":
            res = self._call("start_playback")
            return _ok(res, "Воспроизведение запущено")
        if action == "stop":
            res = self._call("stop_playback")
            return _ok(res, "Воспроизведение остановлено")
        if tempo is None or not 20 <= tempo <= 999:
            return _fail("Для set_tempo нужен tempo в диапазоне 20..999.", "invalid_input")
        res = self._call("set_tempo", {"tempo": float(tempo)})
        return _ok(res, f"Темп: {_num(res.get('tempo', tempo))} BPM")

    def _t_undo_last_action(self) -> ToolResult:
        res = self._call("undo")
        if res.get("done"):
            return _ok(res, "Последнее действие отменено")
        return _ok({"done": False, "message": "Nothing to undo."}, "Отменять нечего")

    # ---- help
    def _t_search_ableton_help(self, query: str) -> ToolResult:
        hits = self.knowledge.search(query, limit=4) if self.knowledge is not None else []
        out = []
        for h in hits:
            text = h.get("text", "")
            if len(text) > MAX_HELP_CHARS:
                text = text[:MAX_HELP_CHARS].rstrip() + " …"
            out.append({"file": h.get("file"), "title": h.get("title"), "section": h.get("section"),
                        "text": text, "score": _num(h.get("score"))})
        data: dict[str, Any] = {"results": out}
        if not out:
            data["hint"] = "No relevant sections in the built-in docs. Say so if you answer from general knowledge."
        return _ok(data, f"В справке найдено разделов: {len(out)}")

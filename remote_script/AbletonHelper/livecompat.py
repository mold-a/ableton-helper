"""Small defensive helpers around Live API objects (no Live imports)."""

DEVICE_TYPE_BY_INT = {1: "instrument", 2: "audio_effect", 4: "midi_effect"}

_INSTRUMENT_CLASSES = frozenset([
    "OriginalSimpler", "MultiSampler", "Operator", "UltraAnalog", "InstrumentVector",
    "DrumGroupDevice", "InstrumentGroupDevice", "LoungeLizard", "StringStudio", "Collision",
    "InstrumentImpulse", "Drift", "Meld", "Wavetable", "MxDeviceInstrument",
])


def safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def same(a, b):
    """Identity or equality of two Live objects, never raising."""
    if a is b:
        return True
    try:
        return bool(a == b)
    except Exception:
        return False


def device_type(device):
    """'instrument' | 'audio_effect' | 'midi_effect' | 'unknown' (int enum first, then class_name)."""
    raw = safe_get(device, "type", None)
    try:
        number = int(raw)
    except Exception:
        number = 0
    if number in DEVICE_TYPE_BY_INT:
        return DEVICE_TYPE_BY_INT[number]
    cls = str(safe_get(device, "class_name", "") or "")
    if cls in _INSTRUMENT_CLASSES:
        return "instrument"
    if cls.startswith("Midi") or cls == "MxDeviceMidiEffect":
        return "midi_effect"
    if cls in ("AudioEffectGroupDevice", "MxDeviceAudioEffect"):
        return "audio_effect"
    return "unknown"


def device_summary(index, device):
    return {
        "index": index,
        "name": str(safe_get(device, "name", "")),
        "class_name": str(safe_get(device, "class_name", "")),
        "type": device_type(device),
    }


def track_type(track):
    if safe_get(track, "is_foldable", False):
        return "group"
    if safe_get(track, "has_midi_input", False):
        return "midi"
    return "audio"


def has_midi_input(track):
    return bool(safe_get(track, "has_midi_input", False)) and not safe_get(track, "is_foldable", False)


def get_arm(track):
    """track.arm raises on group tracks (ableton-mcp #126): guard it."""
    try:
        if not safe_get(track, "can_be_armed", False):
            return False
        return bool(track.arm)
    except Exception:
        return False


def device_list(track):
    return list(safe_get(track, "devices", []) or [])


def devices_summary(track):
    return [device_summary(i, d) for i, d in enumerate(device_list(track))]


def param_display(param):
    try:
        return str(param.str_for_value(param.value))
    except Exception:
        pass
    try:
        return "%.4g" % float(param.value)
    except Exception:
        return ""


def param_to_dict(index, param):
    quantized = bool(safe_get(param, "is_quantized", False))
    items = []
    if quantized:
        try:
            items = [str(x) for x in param.value_items]
        except Exception:
            items = []
    value = safe_get(param, "value", 0.0)
    default = safe_get(param, "default_value", None)
    return {
        "index": index,
        "name": str(safe_get(param, "name", "")),
        "value": value,
        "min": safe_get(param, "min", 0.0),
        "max": safe_get(param, "max", 1.0),
        "default": default if default is not None else value,
        "display": param_display(param),
        "is_quantized": quantized,
        "value_items": items,
    }

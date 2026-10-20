"""Device and device-parameter commands."""

import re

from ..browser_index import category_root, get_children
from ..dispatcher import (BAD_REQUEST, INTERNAL, NOT_FOUND, UNSUPPORTED, CommandError,
                          get_bool, get_dict, get_int, get_str)
from ..livecompat import (device_list, device_summary, param_to_dict, safe_get, same)
from .common import resolve_device, resolve_track, select_track

DEVICE_CATEGORIES = ("instruments", "audio_effects", "midi_effects")
MAX_DEVICE_SEARCH_DEPTH = 3
MAX_DEVICE_SEARCH_VISITS = 20000


# ---------------------------------------------------------------- finding the new device

def find_new_device_index(before, after, hint=None):
    """Index in `after` of the device that appeared (insertion or replacement); None if unchanged."""
    if hint is not None:
        for i, device in enumerate(after):
            if same(device, hint):
                return i
    for i in range(min(len(before), len(after))):
        if not same(before[i], after[i]):
            return i
    if len(after) > len(before):
        return len(before)
    return None


def find_device_item(ctx, name):
    """Browser item for a native device by (case-insensitive) name -> (item, category) or (None, None)."""
    lowered = name.lower()
    index = ctx.browser_index
    if index is not None:
        entry = index.find_device(name, DEVICE_CATEGORIES)
        if entry is not None:
            return entry["ref"], entry["category"]
    browser = safe_get(ctx.application, "browser", None)
    if browser is None:
        return None, None
    visited = 0
    for category in DEVICE_CATEGORIES:
        root = category_root(browser, category)
        if root is None:
            continue
        level = get_children(root)
        depth = 1
        while level and depth <= MAX_DEVICE_SEARCH_DEPTH:
            following = []
            for item in level:
                visited += 1
                if visited > MAX_DEVICE_SEARCH_VISITS:
                    break
                if safe_get(item, "is_device", False) and \
                        str(safe_get(item, "name", "")).lower() == lowered:
                    return item, category
                if depth < MAX_DEVICE_SEARCH_DEPTH:
                    following.extend(get_children(item))
            level = following
            depth += 1
    return None, None


def load_via_browser(ctx, track, name):
    item, category = find_device_item(ctx, name)
    if item is None:
        raise CommandError(NOT_FOUND, "Device '%s' not found in browser" % name)
    if category in ("instruments", "midi_effects") and not safe_get(track, "has_midi_input", False):
        raise CommandError(BAD_REQUEST, "Cannot load %s '%s' on a track without MIDI input" % (
            "an instrument" if category == "instruments" else "a MIDI effect", name))
    browser = safe_get(ctx.application, "browser", None)
    if browser is None or not hasattr(browser, "load_item"):
        raise CommandError(UNSUPPORTED, "Browser API is not available")
    select_track(ctx, track)
    browser.load_item(item)


def load_device(ctx, params):
    _track_index, track = resolve_track(ctx, params)
    name = get_str(params, "device_name")
    position = get_int(params, "position", -1, minimum=-1)
    before = device_list(track)
    hint = None
    inserted = False
    if hasattr(track, "insert_device"):   # Live 12.3+
        try:
            try:
                if position == -1:
                    hint = track.insert_device(name)
                else:
                    hint = track.insert_device(name, position)
            except TypeError:
                if position != -1:
                    raise
                hint = track.insert_device(name, len(before))
            inserted = True
        except Exception as exc:
            ctx.log("insert_device('%s') failed (%s), falling back to the browser" % (name, exc))
            hint = None
    if not inserted:
        load_via_browser(ctx, track, name)
    after = device_list(track)
    new_index = find_new_device_index(before, after, hint if hint is not None and hasattr(hint, "name") else None)
    if new_index is None:
        raise CommandError(INTERNAL, "Live did not add the device '%s' (incompatible with this track?)" % name)
    summary = device_summary(new_index, after[new_index])
    return {"device_index": new_index, "name": summary["name"], "class_name": summary["class_name"]}


def delete_device(ctx, params):
    _ti, track, device_index, _device = resolve_device(ctx, params)
    track.delete_device(device_index)
    return {"deleted": True}


# ---------------------------------------------------------------- parameters

def _norm(text):
    return re.sub(r"[\s\-_.]+", "", str(text).lower())


def find_parameter(device, key):
    params = list(safe_get(device, "parameters", []) or [])
    if isinstance(key, bool):
        raise CommandError(BAD_REQUEST, "parameter must be int or str")
    if isinstance(key, int):
        if 0 <= key < len(params):
            return key, params[key]
        raise CommandError(NOT_FOUND, "Parameter index %s out of range" % key)
    if not isinstance(key, str):
        raise CommandError(BAD_REQUEST, "parameter must be int or str")
    for attr in ("name", "original_name"):
        matchers = (lambda s: s == key, lambda s: s.lower() == key.lower(), lambda s: _norm(s) == _norm(key))
        for matcher in matchers:
            for i, p in enumerate(params):
                if matcher(str(safe_get(p, attr, "") or "")):
                    return i, p
    raise CommandError(NOT_FOUND, "Parameter '%s' not found on %s" % (key, safe_get(device, "name", "device")))


def coerce_value(param, value):
    """Protocol value coercion -> float within [min, max], rounded for quantized params."""
    pmin = float(safe_get(param, "min", 0.0))
    pmax = float(safe_get(param, "max", 1.0))
    quantized = bool(safe_get(param, "is_quantized", False))
    name = safe_get(param, "name", "")
    if isinstance(value, dict):
        if "norm" not in value:
            raise CommandError(BAD_REQUEST, "Object value must be {\"norm\": number}")
        norm = value["norm"]
        if isinstance(norm, bool) or not isinstance(norm, (int, float)):
            raise CommandError(BAD_REQUEST, "'norm' must be a number")
        result = pmin + float(norm) * (pmax - pmin)
    elif isinstance(value, str):
        if not quantized:
            raise CommandError(BAD_REQUEST, "Parameter '%s' is not quantized; string value not allowed" % name)
        items = [str(x).lower() for x in safe_get(param, "value_items", [])]
        if value.lower() not in items:
            raise CommandError(BAD_REQUEST, "'%s' is not one of %s" % (value, list(items)))
        result = float(items.index(value.lower()))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
    else:
        raise CommandError(BAD_REQUEST, "Unsupported value %r" % (value,))
    if result != result:   # NaN
        raise CommandError(BAD_REQUEST, "Value must be a finite number")
    result = max(pmin, min(pmax, result))
    if quantized:
        result = float(round(result))
    return result


def apply_parameter(device, key, value):
    """Set one parameter; returns the Parameter dict read back after the change."""
    index, param = find_parameter(device, key)
    if safe_get(param, "is_enabled", True) is False:
        raise CommandError(BAD_REQUEST, "Parameter '%s' is disabled (automated or not controllable)" % safe_get(param, "name", index))
    param.value = coerce_value(param, value)
    return param_to_dict(index, param)


def get_device_parameters(ctx, params):
    _ti, _track, device_index, device = resolve_device(ctx, params)
    plist = list(safe_get(device, "parameters", []) or [])
    summary = device_summary(device_index, device)
    return {
        "device": {"name": summary["name"], "class_name": summary["class_name"], "type": summary["type"]},
        "parameters": [param_to_dict(i, p) for i, p in enumerate(plist)],
    }


def set_device_parameter(ctx, params):
    _ti, _track, _di, device = resolve_device(ctx, params)
    if "parameter" not in params or params["parameter"] is None:
        raise CommandError(BAD_REQUEST, "Missing required parameter 'parameter'")
    if "value" not in params:
        raise CommandError(BAD_REQUEST, "Missing required parameter 'value'")
    return apply_parameter(device, params["parameter"], params["value"])


def set_device_parameters(ctx, params):
    _ti, _track, _di, device = resolve_device(ctx, params)
    values = get_dict(params, "values")
    applied, failed = [], []
    for key, value in values.items():
        k = int(key) if isinstance(key, str) and key.isdigit() else key
        try:
            applied.append(apply_parameter(device, k, value))
        except CommandError as err:
            failed.append({"parameter": key, "code": err.code, "message": err.message})
        except Exception as exc:
            ctx.log("set_device_parameters: %r failed: %s" % (key, exc))
            failed.append({"parameter": key, "code": INTERNAL, "message": str(exc) or exc.__class__.__name__})
    return {"applied": applied, "failed": failed}


def set_device_enabled(ctx, params):
    _ti, _track, _di, device = resolve_device(ctx, params)
    enabled = get_bool(params, "enabled")
    plist = list(safe_get(device, "parameters", []) or [])
    if not plist:
        raise CommandError(UNSUPPORTED, "Device has no 'Device On' parameter")
    target = plist[0]
    for p in plist:
        if str(safe_get(p, "name", "")) == "Device On":
            target = p
            break
    pmax = float(safe_get(target, "max", 1.0))
    pmin = float(safe_get(target, "min", 0.0))
    target.value = pmax if enabled else pmin
    return {"enabled": float(target.value) > (pmin + pmax) / 2.0}


COMMANDS = {
    "load_device": load_device,
    "delete_device": delete_device,
    "get_device_parameters": get_device_parameters,
    "set_device_parameter": set_device_parameter,
    "set_device_parameters": set_device_parameters,
    "set_device_enabled": set_device_enabled,
}

"""Service commands: ping, get_capabilities, batch."""

from ..constants import SCRIPT_VERSION
from ..dispatcher import BAD_REQUEST, CommandError, get_bool, get_list
from ..livecompat import safe_get


def live_version(application):
    try:
        return "%s.%s.%s" % (application.get_major_version(), application.get_minor_version(),
                             application.get_bugfix_version())
    except Exception:
        return "unknown"


def ping(ctx, params):
    return {"pong": True, "script_version": SCRIPT_VERSION, "live_version": live_version(ctx.application)}


def _live_class_has(ctx, module_name, class_name, attr):
    live = ctx.get_live()
    if live is None:
        return None
    try:
        cls = getattr(getattr(live, module_name), class_name)
        return hasattr(cls, attr)
    except Exception:
        return None


def get_capabilities(ctx, params):
    tracks = list(safe_get(ctx.song, "tracks", []) or [])

    # insert_device: on a Track instance, or on the Live.Track.Track class.
    insert_device = None
    if tracks:
        insert_device = hasattr(tracks[0], "insert_device")
    if insert_device is None:
        insert_device = _live_class_has(ctx, "Track", "Track", "insert_device")

    # create_audio_clip: on a ClipSlot instance, or the Live.Clip.ClipSlot class.
    audio_clip = None
    for track in tracks:
        slots = list(safe_get(track, "clip_slots", []) or [])
        if slots:
            audio_clip = hasattr(slots[0], "create_audio_clip")
            break
    if audio_clip is None:
        audio_clip = _live_class_has(ctx, "Clip", "ClipSlot", "create_audio_clip")

    # add_new_notes: on an existing clip, or on the Live.Clip.Clip class.
    add_new_notes = None
    for track in tracks:
        for slot in list(safe_get(track, "clip_slots", []) or []):
            if safe_get(slot, "has_clip", False):
                add_new_notes = hasattr(slot.clip, "add_new_notes")
                break
        if add_new_notes is not None:
            break
    if add_new_notes is None:
        add_new_notes = _live_class_has(ctx, "Clip", "Clip", "add_new_notes")

    browser = safe_get(ctx.application, "browser", None)
    return {
        "insert_device": bool(insert_device),
        "create_audio_clip": bool(audio_clip),
        "add_new_notes": bool(add_new_notes),
        "browser": browser is not None and hasattr(browser, "load_item"),
    }


def batch(ctx, params):
    commands = get_list(params, "commands")
    stop_on_error = get_bool(params, "stop_on_error", True)
    results = []
    for entry in commands:
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
            envelope = {"ok": False, "error": {"code": BAD_REQUEST, "message": "Invalid batch entry"}}
        elif entry["command"] == "batch":
            envelope = {"ok": False, "error": {"code": BAD_REQUEST, "message": "Nested batch is not allowed"}}
        else:
            envelope = ctx.dispatcher.execute_envelope(entry["command"], entry.get("params"))
        results.append(envelope)
        if stop_on_error and not envelope["ok"]:
            break
    return {"results": results}


COMMANDS = {
    "ping": ping,
    "get_capabilities": get_capabilities,
    "batch": batch,
}

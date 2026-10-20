"""Lookup helpers shared by handler modules."""

from ..dispatcher import NOT_FOUND, CommandError, get_int
from ..livecompat import device_list, devices_summary, get_arm, safe_get, same, track_type


def resolve_track(ctx, params, key="track_index"):
    raw = get_int(params, key)
    tracks = list(ctx.song.tracks)
    index = len(tracks) - 1 if raw == -1 else raw
    if not 0 <= index < len(tracks):
        raise CommandError(NOT_FOUND, "Track %s does not exist" % raw)
    return index, tracks[index]


def resolve_device(ctx, params):
    track_index, track = resolve_track(ctx, params)
    device_index = get_int(params, "device_index")
    devices = device_list(track)
    if not 0 <= device_index < len(devices):
        raise CommandError(NOT_FOUND, "Device %s does not exist on track %s" % (device_index, track_index))
    return track_index, track, device_index, devices[device_index]


def resolve_slot(track, params, key="slot_index"):
    slot_index = get_int(params, key)
    slots = list(safe_get(track, "clip_slots", []) or [])
    if not 0 <= slot_index < len(slots):
        raise CommandError(NOT_FOUND, "Clip slot %s does not exist" % slot_index)
    return slot_index, slots[slot_index]


def resolve_clip(ctx, params):
    track_index, track = resolve_track(ctx, params)
    slot_index, slot = resolve_slot(track, params)
    if not safe_get(slot, "has_clip", False):
        raise CommandError(NOT_FOUND, "No clip in slot %s" % slot_index)
    return track_index, track, slot_index, slot, slot.clip


def selected_track_index(ctx):
    try:
        selected = ctx.song.view.selected_track
    except Exception:
        return None
    for i, track in enumerate(list(ctx.song.tracks)):
        if same(track, selected):
            return i
    return None


def track_summary(ctx, index, track, selected_index=None):
    if selected_index is None:
        selected_index = selected_track_index(ctx)
    return {
        "index": index,
        "name": str(safe_get(track, "name", "")),
        "type": track_type(track),
        "color_index": safe_get(track, "color_index", 0),
        "is_selected": selected_index == index,
        "mute": bool(safe_get(track, "mute", False)),
        "solo": bool(safe_get(track, "solo", False)),
        "arm": get_arm(track),
        "devices": devices_summary(track),
    }


def select_track(ctx, track):
    ctx.song.view.selected_track = track

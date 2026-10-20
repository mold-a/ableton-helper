"""Track commands."""

from ..dispatcher import (BAD_REQUEST, INTERNAL, CommandError, get_bool, get_int,
                          get_number, get_str)
from ..livecompat import get_arm, safe_get
from .common import resolve_track, select_track, track_summary


def _slot_infos(track):
    infos = []
    for i, slot in enumerate(list(safe_get(track, "clip_slots", []) or [])):
        has_clip = bool(safe_get(slot, "has_clip", False))
        clip = safe_get(slot, "clip", None) if has_clip else None
        infos.append({
            "index": i,
            "has_clip": has_clip,
            "clip_name": str(safe_get(clip, "name", "")) if clip is not None else None,
            "clip_length": safe_get(clip, "length", None) if clip is not None else None,
            "is_playing": bool(safe_get(clip, "is_playing", False)) if clip is not None else False,
        })
    return infos


def get_track_info(ctx, params):
    index, track = resolve_track(ctx, params)
    info = track_summary(ctx, index, track)
    info["clip_slots"] = _slot_infos(track)
    return info


def _create_track(ctx, params, kind):
    index = get_int(params, "index", -1)
    name = get_str(params, "name", None, allow_empty=True)
    color = get_int(params, "color_index", None, minimum=0, maximum=69)
    song = ctx.song
    count = len(list(song.tracks))
    position = count if index == -1 or index >= count else max(0, index)
    live_index = -1 if position == count else position
    if kind == "midi":
        song.create_midi_track(live_index)
    else:
        song.create_audio_track(live_index)
    tracks = list(song.tracks)
    if len(tracks) != count + 1:
        raise CommandError(INTERNAL, "Live did not create the track")
    track = tracks[position]
    if name is not None:
        track.name = name
    if color is not None:
        track.color_index = color
    select_track(ctx, track)
    return {"track_index": position}


def create_midi_track(ctx, params):
    return _create_track(ctx, params, "midi")


def create_audio_track(ctx, params):
    return _create_track(ctx, params, "audio")


def delete_track(ctx, params):
    index, _track = resolve_track(ctx, params)
    ctx.song.delete_track(index)
    return {"deleted": True}


def set_track_name(ctx, params):
    _index, track = resolve_track(ctx, params)
    name = get_str(params, "name", allow_empty=True)
    track.name = name
    return {"name": str(track.name)}


def set_track_color(ctx, params):
    _index, track = resolve_track(ctx, params)
    color = get_int(params, "color_index", minimum=0, maximum=69)
    track.color_index = color
    return {"color_index": track.color_index}


def select_track_cmd(ctx, params):
    _index, track = resolve_track(ctx, params)
    select_track(ctx, track)
    return {"selected": True}


def set_track_mixer(ctx, params):
    _index, track = resolve_track(ctx, params)
    volume = get_number(params, "volume", None)
    pan = get_number(params, "pan", None)
    mute = get_bool(params, "mute", None)
    solo = get_bool(params, "solo", None)
    arm = get_bool(params, "arm", None)
    mixer = track.mixer_device
    if volume is not None:
        mixer.volume.value = max(0.0, min(1.0, volume))
    if pan is not None:
        mixer.panning.value = max(-1.0, min(1.0, pan))
    if mute is not None:
        track.mute = mute
    if solo is not None:
        track.solo = solo
    if arm is not None:
        if not safe_get(track, "can_be_armed", False):
            raise CommandError(BAD_REQUEST, "This track cannot be armed")
        track.arm = arm
    # read back after mutating
    return {
        "volume": float(mixer.volume.value),
        "pan": float(mixer.panning.value),
        "mute": bool(track.mute),
        "solo": bool(track.solo),
        "arm": get_arm(track),
    }


COMMANDS = {
    "get_track_info": get_track_info,
    "create_midi_track": create_midi_track,
    "create_audio_track": create_audio_track,
    "delete_track": delete_track,
    "set_track_name": set_track_name,
    "set_track_color": set_track_color,
    "select_track": select_track_cmd,
    "set_track_mixer": set_track_mixer,
}

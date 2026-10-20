"""Clip commands."""

import os

from ..dispatcher import (BAD_REQUEST, CONFLICT, NOT_FOUND, UNSUPPORTED, CommandError,
                          get_bool, get_int, get_list, get_number, get_str)
from ..livecompat import has_midi_input, safe_get
from .common import resolve_clip, resolve_slot, resolve_track


def _first_empty_slot(ctx, track):
    slots = list(safe_get(track, "clip_slots", []) or [])
    for i, slot in enumerate(slots):
        if not safe_get(slot, "has_clip", False):
            return i
    # no free slot: add a scene (adds a slot to every track)
    song = ctx.song
    if hasattr(song, "create_scene"):
        song.create_scene(len(list(safe_get(song, "scenes", []) or [])))
        return len(slots)
    raise CommandError(CONFLICT, "No empty clip slot and scenes cannot be created")


def create_clip(ctx, params):
    _ti, track = resolve_track(ctx, params)
    if not has_midi_input(track):
        raise CommandError(BAD_REQUEST, "create_clip requires a MIDI track")
    length = get_number(params, "length", 4.0)
    if length <= 0:
        raise CommandError(BAD_REQUEST, "length must be > 0")
    name = get_str(params, "name", None, allow_empty=True)
    overwrite = get_bool(params, "overwrite", False)
    slot_index = get_int(params, "slot_index", None)
    if slot_index is None:
        slot_index = _first_empty_slot(ctx, track)
    else:
        slot_index, _slot = resolve_slot(track, params)
    slot = list(track.clip_slots)[slot_index]
    if safe_get(slot, "has_clip", False):
        if not overwrite:
            raise CommandError(CONFLICT, "Slot %s already has a clip" % slot_index)
        slot.delete_clip()
    slot.create_clip(length)
    clip = slot.clip
    if name is not None:
        clip.name = name
    return {"slot_index": slot_index, "length": float(clip.length)}


def parse_notes(raw):
    notes = []
    for n in raw:
        if not isinstance(n, dict):
            raise CommandError(BAD_REQUEST, "Invalid note: %r" % (n,))
        try:
            pitch_raw = n["pitch"]
            if isinstance(pitch_raw, bool):
                raise TypeError("bool")
            pitch = int(pitch_raw)
            start = float(n["start"])
            duration = float(n["duration"])
            velocity = int(n.get("velocity", 100))
        except (KeyError, TypeError, ValueError):
            raise CommandError(BAD_REQUEST, "Invalid note: %r" % (n,))
        if not 0 <= pitch <= 127 or duration <= 0 or start < 0 or start != start or duration != duration:
            raise CommandError(BAD_REQUEST, "Invalid note: %r" % (n,))
        notes.append({"pitch": pitch, "start": start, "duration": duration,
                      "velocity": max(1, min(127, velocity)), "mute": bool(n.get("mute", False))})
    return notes


def _remove_all_notes(clip):
    length = float(clip.length)
    if hasattr(clip, "remove_notes_extended"):
        clip.remove_notes_extended(from_pitch=0, pitch_span=128, from_time=0.0, time_span=length)
    else:
        clip.remove_notes(0.0, 0, length, 128)


def _add_notes_to_clip(ctx, clip, notes):
    spec_cls = None
    live = ctx.get_live()
    if live is not None and hasattr(clip, "add_new_notes"):
        try:
            spec_cls = live.Clip.MidiNoteSpecification
        except Exception:
            spec_cls = None
    if spec_cls is not None:
        specs = tuple(spec_cls(pitch=n["pitch"], start_time=n["start"], duration=n["duration"],
                               velocity=n["velocity"], mute=n["mute"]) for n in notes)
        clip.add_new_notes(specs)
    elif hasattr(clip, "set_notes"):
        clip.set_notes(tuple((n["pitch"], n["start"], n["duration"], n["velocity"], n["mute"]) for n in notes))
    else:
        raise CommandError(UNSUPPORTED, "Neither add_new_notes nor set_notes is available")


def add_notes(ctx, params):
    _ti, track, _si, _slot, clip = resolve_clip(ctx, params)
    notes = parse_notes(get_list(params, "notes"))
    replace = get_bool(params, "replace", False)
    if not safe_get(clip, "is_midi_clip", True):
        raise CommandError(BAD_REQUEST, "Clip is not a MIDI clip")
    if replace:
        _remove_all_notes(clip)
    if notes:
        _add_notes_to_clip(ctx, clip, notes)
    return {"added": len(notes)}


def read_notes(clip):
    length = float(clip.length)
    notes = []
    if hasattr(clip, "get_notes_extended"):
        for n in clip.get_notes_extended(0, 128, 0.0, length):
            notes.append({"pitch": int(n.pitch), "start": float(n.start_time), "duration": float(n.duration),
                          "velocity": int(n.velocity), "mute": bool(n.mute)})
    else:
        for n in clip.get_notes(0.0, 0, length, 128):
            notes.append({"pitch": int(n[0]), "start": float(n[1]), "duration": float(n[2]),
                          "velocity": int(n[3]), "mute": bool(n[4])})
    notes.sort(key=lambda x: (x["start"], x["pitch"]))
    return notes


def get_clip_notes(ctx, params):
    _ti, _track, _si, _slot, clip = resolve_clip(ctx, params)
    return {"notes": read_notes(clip), "length": float(clip.length)}


def set_clip_name(ctx, params):
    _ti, _track, _si, _slot, clip = resolve_clip(ctx, params)
    clip.name = get_str(params, "name", allow_empty=True)
    return {"name": str(clip.name)}


def fire_clip(ctx, params):
    _ti, _track, _si, slot, clip = resolve_clip(ctx, params)
    if hasattr(clip, "fire"):
        clip.fire()
    else:
        slot.fire()
    return {"ok": True}


def stop_clip(ctx, params):
    _ti, _track, _si, slot, clip = resolve_clip(ctx, params)
    if hasattr(clip, "stop"):
        clip.stop()
    else:
        slot.stop()
    return {"ok": True}


def delete_clip(ctx, params):
    _ti, _track, _si, slot, _clip = resolve_clip(ctx, params)
    slot.delete_clip()
    return {"deleted": True}


def create_audio_clip(ctx, params):
    _ti, track = resolve_track(ctx, params)
    slot_index, slot = resolve_slot(track, params)
    file_path = get_str(params, "file_path")
    if not hasattr(slot, "create_audio_clip"):
        raise CommandError(UNSUPPORTED, "ClipSlot.create_audio_clip is not available in this Live version")
    if has_midi_input(track) or safe_get(track, "is_foldable", False):
        raise CommandError(BAD_REQUEST, "create_audio_clip requires an audio track")
    if not os.path.isabs(file_path):
        raise CommandError(BAD_REQUEST, "file_path must be an absolute path")
    if not os.path.isfile(file_path):
        raise CommandError(NOT_FOUND, "File does not exist: %s" % file_path)
    if safe_get(slot, "has_clip", False):
        raise CommandError(CONFLICT, "Slot %s already has a clip" % slot_index)
    try:
        slot.create_audio_clip(file_path)
    except Exception as exc:
        # Live throws on non-audio / frozen tracks and unsupported files.
        raise CommandError(BAD_REQUEST, "Live refused to create the audio clip: %s" % (str(exc) or exc.__class__.__name__))
    return {"slot_index": slot_index}


COMMANDS = {
    "create_clip": create_clip,
    "add_notes": add_notes,
    "get_clip_notes": get_clip_notes,
    "set_clip_name": set_clip_name,
    "fire_clip": fire_clip,
    "stop_clip": stop_clip,
    "delete_clip": delete_clip,
    "create_audio_clip": create_audio_clip,
}

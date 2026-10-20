"""Song-level commands."""

from ..dispatcher import get_number
from .common import selected_track_index, track_summary


def get_session_info(ctx, params):
    song = ctx.song
    tracks = list(song.tracks)
    selected = selected_track_index(ctx)
    return {
        "tempo": float(song.tempo),
        "signature": [int(song.signature_numerator), int(song.signature_denominator)],
        "is_playing": bool(song.is_playing),
        "track_count": len(tracks),
        "return_track_count": len(list(song.return_tracks)),
        "selected_track_index": selected,
        "tracks": [track_summary(ctx, i, t, selected) for i, t in enumerate(tracks)],
    }


def set_tempo(ctx, params):
    tempo = get_number(params, "tempo", minimum=20.0, maximum=999.0)
    ctx.song.tempo = tempo
    return {"tempo": float(ctx.song.tempo)}


def start_playback(ctx, params):
    ctx.song.start_playing()
    return {"is_playing": True}


def stop_playback(ctx, params):
    ctx.song.stop_playing()
    return {"is_playing": False}


def undo(ctx, params):
    if getattr(ctx.song, "can_undo", False):
        ctx.song.undo()
        return {"done": True}
    return {"done": False}


def redo(ctx, params):
    if getattr(ctx.song, "can_redo", False):
        ctx.song.redo()
        return {"done": True}
    return {"done": False}


COMMANDS = {
    "get_session_info": get_session_info,
    "set_tempo": set_tempo,
    "start_playback": start_playback,
    "stop_playback": stop_playback,
    "undo": undo,
    "redo": redo,
}

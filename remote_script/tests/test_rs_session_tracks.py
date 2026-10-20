import pytest

from rs_fakes import FakeDevice, FakeTrack, call, error, make_dispatcher, make_world, result


def fresh(**kw):
    song, app = make_world(**kw)
    return song, make_dispatcher(song, app)


def test_session_info():
    song, d = fresh(midi_tracks=2, audio_tracks=1)
    song.tracks[0].devices.append(FakeDevice("Operator", "Operator", 1))
    song.view.selected_track = song.tracks[1]
    info = result(d, "get_session_info")
    assert info["tempo"] == 120.0 and info["signature"] == [4, 4]
    assert info["track_count"] == 3 and info["return_track_count"] == 1
    assert info["selected_track_index"] == 1
    assert [t["type"] for t in info["tracks"]] == ["midi", "midi", "audio"]
    assert info["tracks"][1]["is_selected"] is True
    assert info["tracks"][0]["devices"] == [{"index": 0, "name": "Operator", "class_name": "Operator", "type": "instrument"}]


def test_group_track_arm_does_not_raise():
    song, d = fresh()
    song.tracks.append(FakeTrack("Group", midi=False, foldable=True))
    info = result(d, "get_session_info")
    group = info["tracks"][1]
    assert group["type"] == "group" and group["arm"] is False
    assert error(d, "set_track_mixer", track_index=1, arm=True) == "bad_request"


def test_tempo_and_transport_and_undo():
    song, d = fresh()
    assert result(d, "set_tempo", tempo=140) == {"tempo": 140.0}
    assert song.tempo == 140.0
    assert result(d, "start_playback") == {"is_playing": True} and song.is_playing
    assert result(d, "stop_playback") == {"is_playing": False} and not song.is_playing
    assert result(d, "undo") == {"done": False}
    song.can_undo = True
    assert result(d, "undo") == {"done": True} and song.undone == 1
    assert result(d, "redo") == {"done": False}
    song.can_redo = True
    assert result(d, "redo") == {"done": True}


def test_create_tracks_and_selection():
    song, d = fresh(midi_tracks=1)
    assert result(d, "create_midi_track", name="Баян", color_index=12) == {"track_index": 1}
    t = song.tracks[1]
    assert t.name == "Баян" and t.color_index == 12 and song.view.selected_track is t
    # insert in the middle
    assert result(d, "create_audio_track", index=0, name="Aud") == {"track_index": 0}
    assert song.tracks[0].name == "Aud" and song.tracks[0].has_midi_input is False
    assert song.view.selected_track is song.tracks[0]
    # index beyond the end appends
    assert result(d, "create_midi_track", index=99) == {"track_index": 3}
    assert error(d, "create_midi_track", color_index=70) == "bad_request"
    assert error(d, "create_midi_track", name=5) == "bad_request"


def test_track_info_clip_slots():
    song, d = fresh()
    result(d, "create_clip", track_index=0, slot_index=1, length=8, name="Riff")
    info = result(d, "get_track_info", track_index=-1)
    assert info["index"] == 0
    assert len(info["clip_slots"]) == 4
    assert info["clip_slots"][1] == {"index": 1, "has_clip": True, "clip_name": "Riff", "clip_length": 8.0, "is_playing": False}
    assert info["clip_slots"][0]["has_clip"] is False and info["clip_slots"][0]["clip_name"] is None


def test_delete_rename_color_select():
    song, d = fresh(midi_tracks=3)
    assert result(d, "set_track_name", track_index=2, name="X") == {"name": "X"}
    assert result(d, "set_track_color", track_index=2, color_index=5) == {"color_index": 5}
    assert error(d, "set_track_color", track_index=2, color_index=99) == "bad_request"
    assert result(d, "select_track", track_index=-1) == {"selected": True}
    assert song.view.selected_track is song.tracks[2]
    assert result(d, "delete_track", track_index=1) == {"deleted": True}
    assert [t.name for t in song.tracks][-1] == "X" and len(song.tracks) == 2
    assert error(d, "delete_track", track_index=5) == "not_found"


def test_mixer():
    song, d = fresh()
    out = result(d, "set_track_mixer", track_index=0, volume=1.5, pan=-0.5, mute=True, solo=True, arm=True)
    assert out == {"volume": 1.0, "pan": -0.5, "mute": True, "solo": True, "arm": True}
    t = song.tracks[0]
    assert t.mixer_device.volume.value == 1.0 and t.mixer_device.panning.value == -0.5
    assert result(d, "set_track_mixer", track_index=0)["mute"] is True
    assert error(d, "set_track_mixer", track_index=0, mute="yes") == "bad_request"

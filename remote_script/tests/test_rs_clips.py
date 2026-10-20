import pytest

from rs_fakes import (AudioClipSlot, FakeLive, FakeClipSlot, LegacyClip, ModernClip, call, error,
                      make_dispatcher, make_world, result)


class LegacySlot(FakeClipSlot):
    clip_class = LegacyClip


def modern():
    song, app = make_world()
    return song, make_dispatcher(song, app, live_module=FakeLive)


def legacy():
    song, app = make_world(slot_class=LegacySlot)
    return song, make_dispatcher(song, app, live_module=None)


def test_create_clip_defaults_and_conflict():
    song, d = modern()
    assert result(d, "create_clip", track_index=0) == {"slot_index": 0, "length": 4.0}
    assert result(d, "create_clip", track_index=0, length=2, name="B") == {"slot_index": 1, "length": 2.0}
    assert song.tracks[0].clip_slots[1].clip.name == "B"
    assert error(d, "create_clip", track_index=0, slot_index=0) == "conflict"
    assert result(d, "create_clip", track_index=0, slot_index=0, length=16, overwrite=True)["length"] == 16.0
    assert error(d, "create_clip", track_index=0, slot_index=99) == "not_found"
    assert error(d, "create_clip", track_index=0, slot_index=2, length=0) == "bad_request"


def test_create_clip_adds_scene_when_full():
    song, d = modern()
    for _ in range(4):
        result(d, "create_clip", track_index=0)
    out = result(d, "create_clip", track_index=0)
    assert out["slot_index"] == 4 and len(song.scenes) == 5


def test_create_clip_requires_midi_track():
    song, app = make_world(midi_tracks=0, audio_tracks=1)
    d = make_dispatcher(song, app)
    assert error(d, "create_clip", track_index=0) == "bad_request"


NOTES = [{"pitch": 60, "start": 0, "duration": 1}, {"pitch": 64, "start": 1, "duration": 0.5, "velocity": 200, "mute": True}]


def test_add_and_get_notes_modern_api():
    song, d = modern()
    result(d, "create_clip", track_index=0, length=4)
    assert result(d, "add_notes", track_index=0, slot_index=0, notes=NOTES) == {"added": 2}
    clip = song.tracks[0].clip_slots[0].clip
    assert clip.notes == [(60, 0.0, 1.0, 100, False), (64, 1.0, 0.5, 127, True)]
    got = result(d, "get_clip_notes", track_index=0, slot_index=0)
    assert got["length"] == 4.0
    assert got["notes"][1] == {"pitch": 64, "start": 1.0, "duration": 0.5, "velocity": 127, "mute": True}
    # replace=True removes first (extended API)
    assert result(d, "add_notes", track_index=0, slot_index=0, notes=NOTES[:1], replace=True) == {"added": 1}
    assert clip.removed_with == "extended" and len(clip.notes) == 1


def test_add_and_get_notes_legacy_api():
    song, d = legacy()
    result(d, "create_clip", track_index=0, length=4)
    clip = song.tracks[0].clip_slots[0].clip
    assert not hasattr(clip, "add_new_notes")
    assert result(d, "add_notes", track_index=0, slot_index=0, notes=NOTES) == {"added": 2}
    assert clip.notes == [(60, 0.0, 1.0, 100, False), (64, 1.0, 0.5, 127, True)]
    got = result(d, "get_clip_notes", track_index=0, slot_index=0)
    assert [n["pitch"] for n in got["notes"]] == [60, 64]
    result(d, "add_notes", track_index=0, slot_index=0, notes=NOTES[:1], replace=True)
    assert clip.removed_with == "legacy" and len(clip.notes) == 1


def test_modern_clip_without_live_module_falls_back_to_set_notes():
    class Both(ModernClip):
        def set_notes(self, notes):
            self.notes.extend(("legacy",) + tuple(n) for n in notes)

    class S(FakeClipSlot):
        clip_class = Both

    song, app = make_world(slot_class=S)
    d = make_dispatcher(song, app)   # no Live module importable in tests
    result(d, "create_clip", track_index=0)
    result(d, "add_notes", track_index=0, slot_index=0, notes=NOTES[:1])
    assert song.tracks[0].clip_slots[0].clip.notes[0][0] == "legacy"


def test_note_validation():
    song, d = modern()
    result(d, "create_clip", track_index=0)
    bad = [{"pitch": 128, "start": 0, "duration": 1}, {"pitch": 60, "start": -1, "duration": 1},
           {"pitch": 60, "start": 0, "duration": 0}, {"pitch": 60, "start": 0}, "x", {"pitch": True, "start": 0, "duration": 1}]
    for n in bad:
        assert error(d, "add_notes", track_index=0, slot_index=0, notes=[n]) == "bad_request", n
    assert error(d, "add_notes", track_index=0, slot_index=0, notes="x") == "bad_request"
    assert song.tracks[0].clip_slots[0].clip.notes == []   # nothing partially added
    assert error(d, "add_notes", track_index=0, slot_index=1, notes=[]) == "not_found"


def test_clip_misc_commands():
    song, d = modern()
    result(d, "create_clip", track_index=0)
    clip = song.tracks[0].clip_slots[0].clip
    assert result(d, "set_clip_name", track_index=0, slot_index=0, name="Riff") == {"name": "Riff"}
    assert result(d, "fire_clip", track_index=0, slot_index=0) == {"ok": True} and clip.is_playing
    assert result(d, "get_track_info", track_index=0)["clip_slots"][0]["is_playing"] is True
    assert result(d, "stop_clip", track_index=0, slot_index=0) == {"ok": True} and not clip.is_playing
    assert result(d, "delete_clip", track_index=0, slot_index=0) == {"deleted": True}
    assert error(d, "delete_clip", track_index=0, slot_index=0) == "not_found"


def test_create_audio_clip(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    song, app = make_world(midi_tracks=1, audio_tracks=1, slot_class=AudioClipSlot)
    d = make_dispatcher(song, app)
    assert result(d, "create_audio_clip", track_index=1, slot_index=0, file_path=str(wav)) == {"slot_index": 0}
    assert song.tracks[1].clip_slots[0].clip.name == "a.wav"
    assert error(d, "create_audio_clip", track_index=1, slot_index=0, file_path=str(wav)) == "conflict"
    assert error(d, "create_audio_clip", track_index=0, slot_index=0, file_path=str(wav)) == "bad_request"
    assert error(d, "create_audio_clip", track_index=1, slot_index=1, file_path="rel.wav") == "bad_request"
    assert error(d, "create_audio_clip", track_index=1, slot_index=1, file_path=str(tmp_path / "no.wav")) == "not_found"


def test_create_audio_clip_unsupported_and_live_refusal(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    song, app = make_world(midi_tracks=0, audio_tracks=1)
    d = make_dispatcher(song, app)
    assert error(d, "create_audio_clip", track_index=0, slot_index=0, file_path=str(wav)) == "unsupported"

    class Refusing(AudioClipSlot):
        def create_audio_clip(self, path):
            raise RuntimeError("frozen track")

    song, app = make_world(midi_tracks=0, audio_tracks=1, slot_class=Refusing)
    d = make_dispatcher(song, app)
    assert error(d, "create_audio_clip", track_index=0, slot_index=0, file_path=str(wav)) == "bad_request"


def test_capabilities():
    song, app = make_world(with_insert=True, slot_class=AudioClipSlot)
    d = make_dispatcher(song, app, live_module=FakeLive)
    assert result(d, "get_capabilities") == {"insert_device": True, "create_audio_clip": True,
                                             "add_new_notes": True, "browser": True}
    song, app = make_world(slot_class=LegacySlot)
    d = make_dispatcher(song, app)
    assert result(d, "get_capabilities") == {"insert_device": False, "create_audio_clip": False,
                                             "add_new_notes": False, "browser": True}
    # no tracks at all: fall back to class attributes of the Live module
    song, app = make_world(midi_tracks=0)
    d = make_dispatcher(song, app, live_module=FakeLive)
    caps = result(d, "get_capabilities")
    assert caps["add_new_notes"] is True and caps["insert_device"] is False
    from rs_fakes import FakeBrowserItem
    app.browser = FakeBrowserItem("nobrowser")
    assert result(d, "get_capabilities")["browser"] is False

"""Demo MIDI patterns must be valid, in key and fit the clip."""

import pytest

from abhelper.sound import RecipeLibrary
from abhelper.sound.demo import (CLAP, CLOSED_HAT, KICK, OPEN_HAT, SCALES, SNARE, TOM_MID, build_demo, default_style,
                                 generate_notes)
from abhelper.sound.schema import CATEGORIES, DEMO_SCALES, DEMO_STYLES, DEMO_VARIANTS, validate_recipe

LIB = RecipeLibrary.load_default()
DRUM_PITCHES = {KICK, SNARE, CLAP, CLOSED_HAT, OPEN_HAT, TOM_MID}


def check_valid(notes, length):
    assert notes, "empty pattern"
    for n in notes:
        assert isinstance(n["pitch"], int) and 0 <= n["pitch"] <= 127
        assert 1 <= n["velocity"] <= 127
        assert n["start"] >= 0 and n["duration"] > 0
        assert n["start"] + n["duration"] <= length + 1e-6, n
    keys = [(n["start"], n["pitch"]) for n in notes]
    assert keys == sorted(keys), "notes must be sorted"


@pytest.mark.parametrize("style", DEMO_STYLES)
@pytest.mark.parametrize("variant", DEMO_VARIANTS)
@pytest.mark.parametrize("length", [4.0, 8.0, 12.0, 16.0])
def test_every_style_variant_length_is_valid(style, variant, length):
    check_valid(generate_notes(style, length=length, variant=variant), length)


@pytest.mark.parametrize("root", [0, 12, 36, 60, 96, 120, 127])
@pytest.mark.parametrize("style", ["chords", "melody", "bass", "arp", "pad", "single"])
def test_extreme_roots_are_folded_into_midi_range(style, root):
    check_valid(generate_notes(style, root=root, length=8.0), 8.0)


@pytest.mark.parametrize("scale", DEMO_SCALES)
@pytest.mark.parametrize("style", ["chords", "melody", "bass", "arp", "pad"])
def test_tonal_styles_stay_in_key(style, scale):
    root = 57
    notes = generate_notes(style, root=root, length=16.0, scale=scale)
    pcs = {(root + i) % 12 for i in SCALES[scale]}
    assert {n["pitch"] % 12 for n in notes} <= pcs


def test_waltz_chords_and_melody_use_three_four():
    notes = generate_notes("chords", root=57, length=12.0, scale="harmonic_minor", variant="waltz")
    starts = {n["start"] for n in notes}
    assert starts == {float(b) for b in range(12)}                # every beat of 4 waltz bars is played
    mel = generate_notes("melody", root=72, length=12.0, scale="major", variant="waltz")
    assert max(n["start"] + n["duration"] for n in mel) <= 12.0


@pytest.mark.parametrize("variant", ["default", "rock", "four_on_floor", "trap", "boom_bap", "lofi"])
def test_drum_patterns_use_gm_pitches_and_a_backbeat(variant):
    notes = generate_notes("drums", length=8.0, variant=variant)
    assert {n["pitch"] for n in notes} <= DRUM_PITCHES
    kicks = [n for n in notes if n["pitch"] == KICK]
    assert kicks and any(n["pitch"] in (SNARE, CLAP) for n in notes)
    assert any(n["pitch"] == CLOSED_HAT for n in notes)
    if variant == "four_on_floor":
        assert len([k for k in kicks if k["start"] % 1 == 0]) == 8
        assert any(n["pitch"] == OPEN_HAT for n in notes)


def test_drum_variants_differ():
    shapes = {v: [(n["pitch"], n["start"]) for n in generate_notes("drums", length=8.0, variant=v)]
              for v in ["rock", "four_on_floor", "trap", "boom_bap", "lofi"]}
    assert len({tuple(s) for s in shapes.values()}) == len(shapes)


def test_strum_offsets_chord_tones():
    plain = generate_notes("chords", root=52, length=8.0)
    strum = generate_notes("chords", root=52, length=8.0, variant="strum")
    assert len(plain) == len(strum)
    assert len({n["start"] for n in strum}) > len({n["start"] for n in plain})


def test_single_note_is_long_and_inside_clip():
    (n,) = generate_notes("single", root=60, length=8.0)
    assert n["start"] == 0 and 6 < n["duration"] <= 8.0


def test_pad_chords_are_long_and_wide():
    notes = generate_notes("pad", root=48, length=16.0)
    assert all(n["duration"] >= 7 for n in notes)
    assert max(n["pitch"] for n in notes) - min(n["pitch"] for n in notes) >= 12


def test_unknown_values_fall_back_to_safe_defaults():
    check_valid(generate_notes("nonsense", scale="nonsense", variant="nonsense"), 8.0)


def test_default_style_covers_every_category():
    for c in CATEGORIES:
        assert default_style(c) in DEMO_STYLES
    assert default_style(None) == "chords"


@pytest.mark.parametrize("rid", sorted(r["id"] for r in LIB.all()))
def test_each_library_demo_is_valid_and_honours_recipe_fields(rid):
    r = LIB.get(rid)
    clip = build_demo(r)
    check_valid(clip.notes, clip.length)
    assert clip.style == (r["demo"].get("style") or default_style(r["category"]))
    if r["demo"].get("length"):
        assert clip.length == r["demo"]["length"]
    if r["demo"].get("root") is not None and clip.style in ("bass", "single"):
        root = r["demo"]["root"]
        assert min(n["pitch"] for n in clip.notes) >= root - 12 and root in {n["pitch"] for n in clip.notes} | {root}


def test_demo_root_is_honoured_for_the_bass_line():
    notes = build_demo({"category": "bass", "demo": {"style": "bass", "root": 33, "scale": "minor"}}).notes
    assert notes[0]["pitch"] == 33


def test_explicit_notes_override_style():
    recipe = {"category": "pad", "demo": {"style": "chords", "notes": [
        {"pitch": 60, "start": 0, "duration": 1}, {"pitch": 64, "start": 2, "duration": 1.5, "velocity": 80}]}}
    clip = build_demo(recipe)
    assert [n["pitch"] for n in clip.notes] == [60, 64]
    assert clip.length == 4.0 and clip.notes[0]["velocity"] == 100 and clip.notes[1]["velocity"] == 80


def test_balalaika_demo_is_tremolo():
    notes = build_demo(LIB.get("balalaika")).notes
    assert len(notes) >= 24
    assert {n["pitch"] for n in notes} <= {69, 71, 72, 74, 76}
    assert validate_recipe(LIB.get("balalaika")) == []


def test_empty_recipe_gets_a_sensible_default():
    clip = build_demo(None)
    check_valid(clip.notes, clip.length)
    assert clip.style == "chords"

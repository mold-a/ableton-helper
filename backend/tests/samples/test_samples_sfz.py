"""SFZ parsing: inheritance, note names (C4 = 60), tuning folding, skipped regions."""

import pytest

from abhelper.samples.sfz import SfzError, fold_tuning, note_to_midi, parse_sfz


@pytest.mark.parametrize("text,midi", [
    ("60", 60), ("c4", 60), ("C4", 60), ("c#4", 61), ("Db4", 61), ("db4", 61), ("b3", 59), ("c-1", 0),
    ("a0", 21), ("g9", 127), ("F#5", 78), ("  e2 ", 40),
])
def test_note_names_use_c4_equals_60(text, midi):
    assert note_to_midi(text) == midi


def test_bad_note_name():
    with pytest.raises(SfzError):
        note_to_midi("h4")


@pytest.mark.parametrize("root,cents,expected", [
    (60, 0, (60, 0)),
    (60, -34, (60, -34)),
    (60, 66, (59, -34)),            # +66 ct == +1 semitone -34 ct
    (60, -66, (61, 34)),
    (47, 150, (45, -50)),           # banker's rounding must not matter for |fine| <= 50
    (60, 25, (60, 25)),
])
def test_fold_tuning_keeps_fine_tune_within_half_a_semitone(root, cents, expected):
    r, t = fold_tuning(root, cents)
    assert (r, t) == expected
    # the sounding pitch for key K must not change: (K - root) * 100 + tune
    assert (60 - r) * 100 + t == (60 - root) * 100 + cents
    assert abs(t) <= 50


def test_inheritance_control_global_master_group_region():
    sfz = parse_sfz("""
    <control> default_path=Smp\\
    <global> ampeg_release=0.4 volume=-3 loop_mode=no_loop
    <master> lovel=10
    <group> loop_mode=loop_continuous hivel=100
    <region> sample=a.wav key=60
    <region> sample=b.wav lokey=62 hikey=64 pitch_keycenter=63 hivel=50 loop_mode=no_loop
    <group>
    <region> sample=c.wav key=c5
    """)
    a, b, c = sfz.regions
    assert a.sample == "Smp/a.wav"                              # default_path applied, backslashes normalised
    assert (a.lokey, a.hikey, a.root) == (60, 60, 60)
    assert a.loop_mode == "loop_continuous" and (a.lovel, a.hivel) == (10, 100)
    assert (b.lokey, b.hikey, b.root, b.hivel, b.loop_mode) == (62, 64, 63, 50, "no_loop")
    assert a.volume_db == -3.0
    assert c.loop_mode == "no_loop" and c.hivel == 127 and c.root == 72    # new <group> resets group opcodes
    assert sfz.envelope == {"ampeg_release": 0.4}


def test_global_resets_master_and_group():
    sfz = parse_sfz("<global> a=1 <master> lovel=20 <group> hivel=30 <global> ampeg_release=1 <region> sample=x.wav key=1")
    r = sfz.regions[0]
    assert (r.lovel, r.hivel) == (0, 127)


def test_sample_names_with_spaces_and_hash_and_following_opcodes():
    sfz = parse_sfz("<region> sample=rel/Button Accordion HN F#4.wav pitch_keycenter=54 lokey=54 hikey=54 tune=-23\n loop_start=46413 loop_end=79367")
    r = sfz.regions[0]
    assert r.sample == "rel/Button Accordion HN F#4.wav"
    assert (r.root, r.detune, r.loop_start, r.loop_end) == (54, -23, 46413, 79367)


def test_tune_and_transpose_fold_into_root_key():
    sfz = parse_sfz("<region> sample=a.wav pitch_keycenter=60 tune=66 <region> sample=b.wav pitch_keycenter=60 transpose=2 tune=-10")
    a, b = sfz.regions
    assert (a.root, a.detune) == (59, -34)
    assert (b.root, b.detune) == (58, -10)       # 190 ct == 2 semitones - 10 ct, root moves down 2


def test_key_opcode_sets_range_and_root():
    r = parse_sfz("<region> sample=a.wav key=g#4").regions[0]
    assert (r.lokey, r.hikey, r.root) == (68, 68, 68)
    r = parse_sfz("<region> sample=a.wav key=60 pitch_keycenter=62").regions[0]
    assert (r.lokey, r.hikey, r.root) == (60, 60, 62)


def test_defaults_when_nothing_is_given():
    r = parse_sfz("<region> sample=a.wav").regions[0]
    assert (r.lokey, r.hikey, r.root, r.lovel, r.hivel, r.loop_mode, r.offset) == (0, 127, 60, 0, 127, "", 0)
    assert r.loop_start is None and r.loop_end is None and r.end is None


def test_release_triggered_and_generator_regions_are_skipped():
    sfz = parse_sfz("""
    <group> trigger=release
    <region> sample=rel.wav key=60
    <group>
    <region> sample=*sine key=61
    <region> key=62
    <region> sample=ok.wav key=63 trigger=first
    <region> sample=rr2.wav key=64 seq_position=2
    <region> sample=rr3.wav key=65 lorand=0.5
    <region> sample=rr1.wav key=65 hirand=0.5
    """)
    assert [r.sample for r in sfz.regions] == ["ok.wav", "rr1.wav"]
    assert len(sfz.skipped) == 5
    assert any("trigger=release" in s for s in sfz.skipped)


def test_comments_and_defines():
    sfz = parse_sfz("""
    // header comment with sample=ignored.wav
    #define $KEY 61
    /* block
       <region> sample=ignored2.wav */
    <region> sample=a.wav key=$KEY // trailing
    """)
    assert [r.sample for r in sfz.regions] == ["a.wav"] and sfz.regions[0].root == 61


def test_loop_and_range_fields():
    r = parse_sfz("<region> sample=a.wav lovel=20 hivel=90 offset=50 end=1000 loop_mode=loop_sustain loop_start=10 "
                  "loop_end=900 loop_crossfade=0.01 volume=-6 pan=-50").regions[0]
    assert (r.lovel, r.hivel, r.offset, r.end) == (20, 90, 50, 1000)
    assert (r.loop_mode, r.loop_start, r.loop_end, r.loop_crossfade) == ("loop_sustain", 10, 900, 0.01)
    assert (r.volume_db, r.pan) == (-6.0, -50.0)


def test_unknown_loop_mode_is_ignored_and_bad_note_skips_the_region():
    sfz = parse_sfz("<region> sample=a.wav loop_mode=wobble <region> sample=b.wav key=zz9")
    assert sfz.regions[0].loop_mode == "" and len(sfz.regions) == 1 and sfz.skipped


def test_envelope_comes_from_the_first_played_region():
    sfz = parse_sfz("""
    <group> trigger=release ampeg_attack=9
    <region> sample=rel.wav key=60
    <group> ampeg_attack=0.06 ampeg_sustain=55 amp_veltrack=40
    <region> sample=a.wav key=60
    """)
    assert sfz.envelope == {"ampeg_attack": 0.06, "ampeg_sustain": 55.0, "amp_veltrack": 40.0}

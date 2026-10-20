"""Template extraction from a user's Live XML and generation of the Sampler preset."""

import gzip
import xml.etree.ElementTree as ET

import pytest
from samples_testkit import make_wav, synth_template_xml, write_template

from abhelper.samples.adv import (TEMPLATE_PRESET_NAME, TemplateError, apply_device_settings, build_preset_xml,
                                  describe_parts, find_template, load_template_file, midi_name, read_live_xml,
                                  region_to_part, template_from_xml, write_adv)
from abhelper.samples.audioinfo import AudioInfo, read_audio_info
from abhelper.samples.sfz import Region, parse_sfz


def parse_adv(path):
    with gzip.open(path, "rb") as fh:
        return ET.fromstring(fh.read())


def val(el, path):
    return el.find(path).get("Value")


def parts_for(tmp_path, sfz_text, files):
    sfz = parse_sfz(sfz_text)
    out = []
    for r in sfz.regions:
        wav = make_wav(tmp_path / r.sample, **files.get(r.sample, {}))
        out.append(region_to_part(r, read_audio_info(wav), wav, "Samples/AbletonHelper/x/" + r.sample))
    return sfz, out


# ------------------------------------------------------------------ template extraction
def test_template_from_xml_takes_device_part_and_root_attributes():
    t = template_from_xml(synth_template_xml())
    assert t.root_attrib["Creator"] == "Ableton Live 11.3.25" and t.root_attrib["MinorVersion"] == "11.0_11300"
    assert t.device.tag == "MultiSampler" and t.part.tag == "MultiSamplePart"
    assert t.device.find("Player/MultiSampleMap/SampleParts/MultiSamplePart") is not None


def test_template_found_inside_a_group_device_preset():
    xml = ("<Ableton MajorVersion='5'><GroupDevicePreset><Device><InstrumentGroupDevice><Branches><Branch>"
           "<DeviceChain>" + synth_template_xml().split("<Ableton", 1)[1].split(">", 1)[1].rsplit("</Ableton>", 1)[0]
           + "</DeviceChain></Branch></Branches></InstrumentGroupDevice></Device></GroupDevicePreset></Ableton>")
    t = template_from_xml(xml)
    assert t.device.tag == "MultiSampler" and t.root_attrib == {"MajorVersion": "5"}


def test_template_skips_samplers_without_parts():
    empty = "<Ableton><MultiSampler><Player><MultiSampleMap><SampleParts /></MultiSampleMap></Player></MultiSampler></Ableton>"
    with pytest.raises(TemplateError):
        template_from_xml(empty)
    with pytest.raises(TemplateError):
        template_from_xml("<Ableton><Operator /></Ableton>")
    with pytest.raises(TemplateError):
        template_from_xml("not xml at all")
    # an empty sampler first, a usable one second: the second wins
    t = template_from_xml("<Ableton><MultiSampler Id='1'><Player><MultiSampleMap><SampleParts /></MultiSampleMap>"
                          "</Player></MultiSampler><MultiSampler Id='2'><X><MultiSamplePart Id='0'/></X></MultiSampler></Ableton>")
    assert t.device.get("Id") == "2"


def test_read_live_xml_handles_gzip_plain_and_garbage(tmp_path):
    write_template(tmp_path / "a.adv")
    assert read_live_xml(tmp_path / "a.adv").startswith(b"<?xml")
    (tmp_path / "b.adv").write_text("<Ableton/>")
    assert read_live_xml(tmp_path / "b.adv") == b"<Ableton/>"
    (tmp_path / "c.adv").write_bytes(b"\x00\x01binary")
    assert read_live_xml(tmp_path / "c.adv") is None
    (tmp_path / "d.adv").write_bytes(b"\x1f\x8bbroken gzip")
    assert read_live_xml(tmp_path / "d.adv") is None
    assert read_live_xml(tmp_path / "missing.adv") is None


# ------------------------------------------------------------------ where the template comes from
def test_find_template_priority(tmp_path):
    lib = tmp_path / "User Library"
    res = tmp_path / "Live" / "Resources"
    core = res / "Core Library" / "Presets" / "Instruments"
    write_template(core / "Sampler" / "Big Sampler.adv", synth_template_xml().replace("<OtherDevice />", "") + "<!-- big -->")
    # nothing but the Core Library
    t = find_template(lib, [res])
    assert t.kind == "core" and t.source.endswith("Big Sampler.adv")
    # any Sampler preset in the User Library comes after the Core Library ...
    write_template(lib / "Presets" / "Instruments" / "Sampler" / "Mine.adv")
    assert find_template(lib, [res]).kind == "core"
    assert find_template(lib, []).kind == "user-sampler"
    # ... the preset saved as "AbletonHelper Template" comes before it ...
    write_template(lib / "Presets" / "Instruments" / "Sampler" / (TEMPLATE_PRESET_NAME + ".adv"))
    t = find_template(lib, [res])
    assert t.kind == "user" and TEMPLATE_PRESET_NAME in t.source
    # ... and an explicit file wins over everything
    explicit = write_template(tmp_path / "explicit.adv")
    t = find_template(lib, [res], explicit)
    assert t.kind == "explicit" and t.source == str(explicit)


def test_find_template_prefers_sampler_named_smallest_adv_and_skips_junk(tmp_path):
    res = tmp_path / "Resources"
    core = res / "Core Library"
    write_template(core / "Drums" / "Kit.adv", "<Ableton><DrumGroupDevice /></Ableton>")        # no sampler at all
    (core / "Broken.adv").write_bytes(b"\x1f\x8bnope")
    write_template(core / "Presets" / "Sampler" / "Large.adv", synth_template_xml() + "<!--" + "x" * 5000 + "-->")
    write_template(core / "Presets" / "Sampler" / "Small.adv")
    write_template(core / "Racks" / "Rack.adg")
    t = find_template(None, [res])
    assert t is not None and t.source.endswith("Small.adv") and t.kind == "core"


def test_find_template_returns_none_without_candidates(tmp_path):
    assert find_template(tmp_path / "lib", [tmp_path / "res"]) is None
    assert find_template(None, []) is None


def test_broken_explicit_template_is_an_error(tmp_path):
    bad = tmp_path / "bad.adv"
    bad.write_bytes(b"garbage")
    with pytest.raises(TemplateError):
        load_template_file(bad)
    write_template(bad, "<Ableton><Operator/></Ableton>")
    with pytest.raises(TemplateError):
        find_template(None, [], bad)


# ------------------------------------------------------------------ zones
def test_region_to_part_loops_from_sfz_and_wav(tmp_path):
    wav = make_wav(tmp_path / "a.wav", frames=3000, loops=[(200, 2500)])
    info = read_audio_info(wav)
    base = dict(sample="a.wav", lokey=40, hikey=50, root=45)
    sfz_loop = region_to_part(Region(**base, loop_mode="loop_continuous", loop_start=100, loop_end=2000), info, wav, "S/a.wav")
    assert (sfz_loop.loop_mode, sfz_loop.loop_start, sfz_loop.loop_end) == (1, 100, 2000)
    wav_loop = region_to_part(Region(**base, loop_mode="loop_continuous"), info, wav, "S/a.wav")
    assert (wav_loop.loop_mode, wav_loop.loop_start, wav_loop.loop_end) == (1, 200, 2500)         # from the smpl chunk
    no_mode = region_to_part(Region(**base), info, wav, "S/a.wav")
    assert no_mode.loop_mode == 1                                                                   # the file's own loop
    forced_off = region_to_part(Region(**base, loop_mode="no_loop", loop_start=100, loop_end=2000), info, wav, "S/a.wav")
    assert forced_off.loop_mode == 0 and forced_off.sample_end == 3000
    one_shot = region_to_part(Region(**base, loop_mode="one_shot"), info, wav, "S/a.wav")
    assert one_shot.loop_mode == 0


def test_region_to_part_rejects_bad_loops_and_clamps(tmp_path):
    wav = make_wav(tmp_path / "a.wav", frames=1000)
    info = read_audio_info(wav)
    bad = region_to_part(Region(sample="a.wav", loop_mode="loop_continuous", loop_start=900, loop_end=100), info, wav, "S/a.wav")
    assert bad.loop_mode == 0 and bad.warnings
    no_points = region_to_part(Region(sample="a.wav", loop_mode="loop_continuous"), info, wav, "S/a.wav")
    assert no_points.loop_mode == 0 and no_points.warnings
    clamped = region_to_part(Region(sample="a.wav", loop_mode="loop_continuous", loop_start=10, loop_end=99999,
                                    end=500000, offset=20, volume_db=-6.0, pan=50.0, lovel=0, hivel=0), info, wav, "S/a.wav")
    assert (clamped.loop_end, clamped.sample_end, clamped.sample_start) == (1000, 1000, 20)
    assert clamped.volume == pytest.approx(0.501187, abs=1e-5) and clamped.pan == 0.5
    assert (clamped.lovel, clamped.hivel) == (1, 1)


def test_loop_crossfade_in_frames_is_limited(tmp_path):
    wav = make_wav(tmp_path / "a.wav", frames=44100)
    info = read_audio_info(wav)
    p = region_to_part(Region(sample="a.wav", loop_mode="loop_continuous", loop_start=100, loop_end=300,
                              loop_crossfade=0.5), info, wav, "S/a.wav")
    assert p.loop_crossfade == 100                                   # at most half of the loop


# ------------------------------------------------------------------ the generated preset
def test_generated_preset_parses_back_with_correct_zones(tmp_path):
    sfz, parts = parts_for(tmp_path, """
        <global> ampeg_attack=0.06 ampeg_decay=18 ampeg_sustain=55 ampeg_release=0.13 amp_veltrack=40
        <region> sample=low.wav pitch_keycenter=47 lokey=0 hikey=49 tune=-34 loop_mode=loop_continuous loop_start=500 loop_end=1500
        <region> sample=mid.wav pitch_keycenter=c4 lokey=50 hikey=62 tune=66 lovel=1 hivel=90
        <region> sample=hi.wav key=g#5 loop_mode=no_loop
        """, {"low.wav": {"frames": 2000}, "mid.wav": {"frames": 1800, "channels": 2}, "hi.wav": {"frames": 3000, "rate": 48000}})
    xml = build_preset_xml(template_from_xml(synth_template_xml()), parts, "AbletonHelper Test", sfz.envelope)
    write_adv(tmp_path / "out" / "Test.adv", xml)
    root = parse_adv(tmp_path / "out" / "Test.adv")
    assert root.tag == "Ableton" and root.get("Creator") == "Ableton Live 11.3.25"
    dev = root.find("MultiSampler")
    assert dev.get("Id") == "0" and val(dev, "UserName") == "AbletonHelper Test" and val(dev, "Annotation") == ""
    zones = dev.findall("Player/MultiSampleMap/SampleParts/MultiSamplePart")
    assert [z.get("Id") for z in zones] == ["0", "1", "2"]
    low, mid, hi = zones
    assert (val(low, "KeyRange/Min"), val(low, "KeyRange/Max"), val(low, "KeyRange/CrossfadeMin"), val(low, "KeyRange/CrossfadeMax")) == ("0", "49", "0", "49")
    assert (val(low, "RootKey"), val(low, "Detune")) == ("47", "-34")
    assert (val(low, "SustainLoop/Start"), val(low, "SustainLoop/End"), val(low, "SustainLoop/Mode")) == ("500", "1500", "1")
    assert val(low, "ReleaseLoop/Mode") == "3" and val(low, "SampleEnd") == "2000" and val(low, "SampleStart") == "0"
    assert (val(mid, "RootKey"), val(mid, "Detune")) == ("59", "-34")                    # tune=66 folded: C4(60) + 66ct
    assert (val(mid, "VelocityRange/Min"), val(mid, "VelocityRange/Max")) == ("1", "90")
    assert val(mid, "SustainLoop/Mode") == "0"
    assert (val(hi, "RootKey"), val(hi, "KeyRange/Min"), val(hi, "SampleEnd"), val(hi, "SampleRef/DefaultSampleRate")) == ("80", "80", "3000", "48000")
    ref = low.find("SampleRef")
    assert val(ref, "FileRef/RelativePathType") == "6" and val(ref, "FileRef/Type") == "1"
    assert val(ref, "FileRef/RelativePath") == "Samples/AbletonHelper/x/low.wav"
    assert val(ref, "FileRef/Path") == str(tmp_path / "low.wav")
    assert val(ref, "FileRef/OriginalFileSize") == str((tmp_path / "low.wav").stat().st_size)
    assert val(ref, "DefaultDuration") == "2000" and val(ref, "DefaultSampleRate") == "44100"
    assert int(val(ref, "LastModDate")) > 0
    # stale data from the template's own sample must be gone
    assert val(low, "Name") == "low" and val(low, "Selection") == "true" and val(mid, "Selection") == "false"
    assert low.find("SampleWarpProperties/WarpMarkers") is not None and len(low.find("SampleWarpProperties/WarpMarkers")) == 0
    assert val(low, "SampleWarpProperties/IsWarped") == "false" and val(low, "SampleWarpProperties/WarpMode") == "0"
    assert len(low.find("SampleWarpProperties/Onsets/UserOnsets")) == 0
    assert len(low.find("SlicePoints")) == 1 and len(low.find("ManualSlicePoints")) == 0
    assert len(ref.find("SourceContext")) == 0
    assert dev.find("LastPresetRef/Value") is not None and len(dev.find("LastPresetRef/Value")) == 0
    assert len(dev.find("SourceContext/Value")) == 0


def test_adv_file_is_gzip_xml_utf8(tmp_path):
    xml = build_preset_xml(template_from_xml(synth_template_xml()), parts_for(tmp_path, "<region> sample=a.wav key=60", {})[1],
                           "AbletonHelper Баян")
    write_adv(tmp_path / "p.adv", xml)
    raw = (tmp_path / "p.adv").read_bytes()
    assert raw[:2] == b"\x1f\x8b"
    text = gzip.decompress(raw).decode("utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>') and "AbletonHelper Баян" in text
    assert not (tmp_path / "p.adv.tmp").exists()


def test_device_settings_are_neutralised_and_envelope_applied(tmp_path):
    sfz, parts = parts_for(tmp_path, "<global> ampeg_attack=0.06 ampeg_decay=18 ampeg_sustain=55 ampeg_release=0.13 amp_veltrack=40"
                                    "\n<region> sample=a.wav key=60", {})
    dev = parse_adv_text(build_preset_xml(template_from_xml(synth_template_xml()), parts, "N", sfz.envelope)).find("MultiSampler")
    assert val(dev, "Filter/IsOn/Manual") == "false" and val(dev, "Lfo/IsOn/Manual") == "false"
    assert val(dev, "Shaper/IsOn/Manual") == "0"                         # the template's 0/1 style is kept
    assert val(dev, "Pitch/Envelope/IsOn/Manual") == "false" and val(dev, "Player/Reverse/Manual") == "false"
    assert (val(dev, "Pitch/TransposeKey/Manual"), val(dev, "Pitch/TransposeFine/Manual")) == ("0", "0")
    assert val(dev, "Player/LoopModulators/SampleStart/Manual") == "0" and val(dev, "Player/LoopModulators/LoopLength/Manual") == "1"
    assert val(dev, "VelDst/ModConnections.0/Amount") == "0"
    env = "VolumeAndPan/Envelope/"
    assert float(val(dev, env + "AttackTime/Manual")) == 60 and float(val(dev, env + "DecayTime/Manual")) == 18000
    assert float(val(dev, env + "SustainLevel/Manual")) == pytest.approx(0.55) and float(val(dev, env + "ReleaseTime/Manual")) == 130
    assert float(val(dev, env + "DecayLevel/Manual")) == 1 and val(dev, env + "LoopMode/Manual") == "0"
    assert float(val(dev, "VolumeAndPan/VolumeVelScale/Manual")) == pytest.approx(0.4)
    assert val(dev, "VolumeAndPan/Volume/Manual") == "-6"                # unrelated settings untouched
    assert val(dev, "Globals/NumVoices") == "11"


def parse_adv_text(xml):
    return ET.fromstring(xml.encode("utf-8"))


def test_envelope_defaults_follow_sfz_semantics_and_clamping():
    dev = template_from_xml(synth_template_xml()).device
    apply_device_settings(dev, {"ampeg_release": 0.5})
    env = "VolumeAndPan/Envelope/"
    assert float(val(dev, env + "AttackTime/Manual")) == 0.1                # SFZ default 0 s, Live minimum 0.1 ms
    assert float(val(dev, env + "SustainLevel/Manual")) == 1 and float(val(dev, env + "ReleaseTime/Manual")) == 500
    dev2 = template_from_xml(synth_template_xml()).device
    apply_device_settings(dev2, None)                                       # no envelope info: envelope stays
    assert float(val(dev2, env + "AttackTime/Manual")) == 5


def test_empty_zone_list_is_refused():
    with pytest.raises(TemplateError):
        build_preset_xml(template_from_xml(synth_template_xml()), [], "x")


def test_template_without_sample_parts_container_is_refused(tmp_path):
    t = template_from_xml("<Ableton><MultiSampler><Other><MultiSamplePart Id='0'/></Other></MultiSampler></Ableton>")
    _sfz, parts = parts_for(tmp_path, "<region> sample=a.wav key=60", {})
    with pytest.raises(TemplateError):
        build_preset_xml(t, parts, "x")


def test_template_object_is_not_mutated_by_generation(tmp_path):
    t = template_from_xml(synth_template_xml())
    before = ET.tostring(t.device)
    _sfz, parts = parts_for(tmp_path, "<region> sample=a.wav key=60", {})
    build_preset_xml(t, parts, "x", {"ampeg_attack": 1.0})
    assert ET.tostring(t.device) == before


def test_midi_name_and_describe(tmp_path):
    assert midi_name(60) == "C3" and midi_name(0) == "C-2" and midi_name(127) == "G8"      # Ableton: C3 = 60
    _sfz, parts = parts_for(tmp_path, "<region> sample=a.wav key=c4 lovel=20 hivel=90 loop_mode=loop_continuous loop_start=1 loop_end=5", {})
    line = describe_parts(parts)[0]
    assert "root  60" in line and "vel 20-90" in line and "loop 1..5" in line

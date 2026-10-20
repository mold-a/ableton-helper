"""Installer: download (local file:// or patched), unpack, copy, generate, idempotency, uninstall."""

import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest
from samples_testkit import SFZ_BASIC, SFZ_FILES, make_pack_dir, synth_template_xml, write_template

from abhelper.samples import Pack
from abhelper.samples.installer import InstallError, Installer, rescan_browser


def build_archive(tmp_path, kind="zip"):
    src = make_pack_dir(tmp_path / "src", SFZ_BASIC, SFZ_FILES)
    arc = tmp_path / ("pack." + kind)
    if kind == "zip":
        with zipfile.ZipFile(arc, "w") as z:
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    z.write(f, "Test Pack 1.0/" + f.relative_to(src).as_posix())
    else:
        py7zr = pytest.importorskip("py7zr")
        with py7zr.SevenZipFile(arc, "w") as z:
            z.writeall(src, "Test Pack 1.0")
    return arc


def make_pack(arc, **over):
    data = arc.read_bytes()
    d = dict(id="test-pack", name="Test Pack", kind="accordion", license={"name": "CC0 1.0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"},
             url=arc.as_uri(), archive="zip" if arc.suffix == ".zip" else "7z", sfz="pack.sfz",
             preset_name="AbletonHelper Test Pack", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
             attribution="Tester", homepage="https://example.org", verified=True)
    d.update(over)
    return Pack(**d)


@pytest.fixture
def env(tmp_path):
    lib = tmp_path / "User Library"
    lib.mkdir()
    write_template(lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper Template.adv")
    logs = []
    inst = Installer(lib, [], cache_dir=tmp_path / "cache", log=logs.append)
    return lib, inst, logs


def read_preset(path):
    with gzip.open(path, "rb") as fh:
        return ET.fromstring(fh.read())


@pytest.mark.parametrize("kind", ["zip", "7z"])
def test_install_end_to_end(tmp_path, env, kind):
    lib, inst, logs = env
    pack = make_pack(build_archive(tmp_path, kind))
    assert inst.status(pack) == "absent"
    res = inst.install(pack)
    assert not res.already_installed and len(res.parts) == 3
    preset = lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper" / "AbletonHelper Test Pack.adv"
    samples = lib / "Samples" / "AbletonHelper" / "test-pack"
    assert res.preset_path == preset and res.samples_dir == samples and preset.is_file()
    # samples copied under their relative names, the unused release sample and the junk are not
    assert sorted(p.relative_to(samples).as_posix() for p in samples.rglob("*") if p.is_file()) == [
        "ATTRIBUTION.txt", "LICENSE.txt", "abhelper-pack.json", "samples/high.wav", "samples/low.wav", "samples/mid.wav"]
    assert "Tester" in (samples / "ATTRIBUTION.txt").read_text(encoding="utf-8")
    assert len(res.skipped) == 1 and "release" in res.skipped[0]
    # the preset: zones sorted by key, loops, paths relative to the User Library and absolute
    root = read_preset(preset)
    zones = root.findall("MultiSampler/Player/MultiSampleMap/SampleParts/MultiSamplePart")
    assert [z.find("KeyRange/Min").get("Value") for z in zones] == ["0", "50", "80"]
    assert [z.find("RootKey").get("Value") for z in zones] == ["47", "59", "80"]
    assert [z.find("SustainLoop/Mode").get("Value") for z in zones] == ["1", "1", "0"]
    ref = zones[0].find("SampleRef/FileRef")
    assert ref.find("RelativePath").get("Value") == "Samples/AbletonHelper/test-pack/samples/low.wav"
    assert ref.find("Path").get("Value") == str(samples / "samples" / "low.wav")
    assert (samples / "samples" / "low.wav").is_file()
    assert root.find("MultiSampler/UserName").get("Value") == "AbletonHelper Test Pack"
    env_ = root.find("MultiSampler/VolumeAndPan/Envelope/ReleaseTime/Manual")
    assert env_.get("Value") == "130"
    manifest = json.loads((samples / "abhelper-pack.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "test-pack" and "samples/low.wav" in manifest["files"]
    assert inst.status(pack) == "installed"
    assert any("Шаблон Sampler" in line for line in logs) and any("100%" in line for line in logs)
    assert not list((tmp_path / "cache").glob("extract-*"))                 # temp unpacking is cleaned up


def test_install_is_idempotent_and_force_regenerates(tmp_path, env):
    lib, inst, _ = env
    pack = make_pack(build_archive(tmp_path))
    inst.install(pack)
    stamp = inst.preset_path(pack).stat().st_mtime_ns
    again = inst.install(pack)
    assert again.already_installed and inst.preset_path(pack).stat().st_mtime_ns == stamp
    forced = inst.install(pack, force=True)
    assert not forced.already_installed and len(forced.parts) == 3 and inst.status(pack) == "installed"
    assert not list((lib / "Samples" / "AbletonHelper").glob("*.installing"))


def test_damaged_install_is_detected_and_repaired(tmp_path, env):
    lib, inst, _ = env
    pack = make_pack(build_archive(tmp_path))
    inst.install(pack)
    (inst.samples_dir(pack) / "samples" / "mid.wav").unlink()
    assert inst.status(pack) == "partial"
    inst.install(pack)
    assert inst.status(pack) == "installed" and (inst.samples_dir(pack) / "samples" / "mid.wav").is_file()
    inst.preset_path(pack).unlink()
    assert inst.status(pack) == "partial"


def test_uninstall_removes_exactly_our_files(tmp_path, env):
    lib, inst, _ = env
    pack = make_pack(build_archive(tmp_path))
    inst.install(pack)
    other = lib / "Presets" / "Instruments" / "Sampler" / "Mine.adv"
    write_template(other)
    removed = inst.uninstall(pack)
    assert {p.name for p in removed} == {"test-pack", "AbletonHelper Test Pack.adv"}
    assert inst.status(pack) == "absent" and other.is_file()
    assert not (lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper").exists()       # empty folders pruned
    assert not (lib / "Samples" / "AbletonHelper").exists()
    assert inst.uninstall(pack) == []                                                        # idempotent


def test_missing_template_gives_instructions_and_downloads_nothing(tmp_path):
    lib = tmp_path / "User Library"
    lib.mkdir()
    called = []
    inst = Installer(lib, [], cache_dir=tmp_path / "cache", downloader=lambda *a, **k: called.append(a), log=lambda s: None)
    with pytest.raises(InstallError) as exc:
        inst.install(make_pack(build_archive(tmp_path)))
    assert "AbletonHelper Template" in str(exc.value) and "Sampler" in str(exc.value) and called == []


def test_template_comes_from_the_live_core_library(tmp_path):
    lib = tmp_path / "User Library"
    lib.mkdir()
    res = tmp_path / "Live" / "Resources"
    write_template(res / "Core Library" / "Presets" / "Instruments" / "Sampler" / "Basic.adv")
    inst = Installer(lib, [res], cache_dir=tmp_path / "cache", log=lambda s: None)
    result = inst.install(make_pack(build_archive(tmp_path)))
    assert "Basic.adv" in result.template_source and "core" in result.template_source


def test_missing_user_library_is_reported(tmp_path):
    inst = Installer(tmp_path / "nope", [], cache_dir=tmp_path / "cache", log=lambda s: None)
    with pytest.raises(InstallError, match="User Library"):
        inst.install(make_pack(build_archive(tmp_path)))


def test_bad_checksum_aborts_before_touching_the_library(tmp_path, env):
    lib, inst, _ = env
    pack = make_pack(build_archive(tmp_path), sha256="0" * 64)
    with pytest.raises(InstallError, match="sha256"):
        inst.install(pack)
    assert not (lib / "Samples").exists() and not (lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper").exists()


def test_wrong_sfz_name_lists_what_is_there(tmp_path, env):
    _, inst, _ = env
    with pytest.raises(InstallError, match="pack.sfz"):
        inst.install(make_pack(build_archive(tmp_path), sfz="missing.sfz"))


def test_sfz_found_by_name_in_a_subfolder_and_case_insensitive_samples(tmp_path, env):
    lib, inst, _ = env
    src = tmp_path / "src2"
    make_pack_dir(src, "<region> sample=SMP/Note.WAV key=60", {"smp/Note.WAV": {"frames": 500}})
    arc = tmp_path / "p2.zip"
    with zipfile.ZipFile(arc, "w") as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, "top/inner/" + f.relative_to(src).as_posix())
    res = inst.install(make_pack(arc, id="case-pack", preset_name="AbletonHelper Case"))
    assert len(res.parts) == 1 and res.warnings == []


def test_missing_sample_files_become_warnings_and_all_missing_is_an_error(tmp_path, env):
    _, inst, _ = env
    src = tmp_path / "src3"
    make_pack_dir(src, "<region> sample=a.wav key=60\n<region> sample=gone.wav key=61", {"a.wav": {"frames": 100}})
    arc = tmp_path / "p3.zip"
    with zipfile.ZipFile(arc, "w") as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(src).as_posix())
    res = inst.install(make_pack(arc, id="p3", preset_name="AbletonHelper P3"))
    assert len(res.parts) == 1 and any("gone.wav" in w for w in res.warnings)
    src4 = tmp_path / "src4"
    make_pack_dir(src4, "<region> sample=zzz.wav key=60", {"a.wav": {"frames": 10}})
    arc4 = tmp_path / "p4.zip"
    with zipfile.ZipFile(arc4, "w") as z:
        z.write(src4 / "pack.sfz", "pack.sfz")
    with pytest.raises(InstallError, match="пригодной"):
        inst.install(make_pack(arc4, id="p4", preset_name="AbletonHelper P4"))
    assert not (inst.samples_dir(make_pack(arc4, id="p4")).exists())


def test_failed_generation_leaves_no_half_installed_files(tmp_path):
    lib = tmp_path / "User Library"
    lib.mkdir()
    write_template(lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper Template.adv",
                   "<Ableton><MultiSampler><Broken><MultiSamplePart Id='0'/></Broken></MultiSampler></Ableton>")
    inst = Installer(lib, [], cache_dir=tmp_path / "cache", log=lambda s: None)
    pack = make_pack(build_archive(tmp_path))
    with pytest.raises(InstallError, match="SampleParts"):
        inst.install(pack)
    assert inst.status(pack) == "absent"
    base = lib / "Samples" / "AbletonHelper"
    assert not base.exists() or not list(base.iterdir())


# ------------------------------------------------------------------ rescan
def test_rescan_browser_uses_the_bridge_and_survives_an_offline_live():
    from abhelper.bridge.base import BridgeConnectionError
    from abhelper.bridge.fake import FakeBridge

    bridge = FakeBridge()
    ok, msg = rescan_browser(bridge)
    assert ok and ("browser_rescan", {"categories": ["user_library"]}) in bridge.calls

    class Offline:
        def call(self, *a, **k):
            raise BridgeConnectionError("refused")

    ok, msg = rescan_browser(Offline())
    assert not ok and "Live" in msg

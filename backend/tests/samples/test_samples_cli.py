"""`abhelper samples ...` through the real argument parser; paths and downloads are redirected."""

import hashlib
import zipfile

import pytest
from samples_testkit import SFZ_BASIC, SFZ_FILES, make_pack_dir, write_template

from abhelper import livepaths
from abhelper.cli import build_parser, main
from abhelper.samples import Pack


@pytest.fixture
def world(tmp_path, monkeypatch):
    lib = tmp_path / "User Library"
    lib.mkdir()
    write_template(lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper Template.adv")
    monkeypatch.setenv("ABHELPER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ABHELPER_USER_LIBRARY", str(lib))
    monkeypatch.delenv("ABHELPER_LIVE_DIR", raising=False)
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "1")                       # nothing listens: "Live is not running"
    monkeypatch.setattr(livepaths, "common_resources_dirs", lambda platform=None: [])
    src = make_pack_dir(tmp_path / "src", SFZ_BASIC, SFZ_FILES)
    arc = tmp_path / "pack.zip"
    with zipfile.ZipFile(arc, "w") as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src).as_posix())
    data = arc.read_bytes()
    pack = Pack(id="test-pack", name="Test Pack", kind="accordion", license={"name": "CC0 1.0", "url": "https://x"},
                url=arc.as_uri(), archive="zip", sfz="pack.sfz", preset_name="AbletonHelper Test Pack",
                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), default=True, verified=True)
    unverified = Pack(id="shaky", name="Shaky", kind="x", license={"name": "CC0 1.0", "url": "https://x"}, url=arc.as_uri(),
                      archive="zip", sfz="pack.sfz", preset_name="AbletonHelper Shaky", default=False, verified=False)
    monkeypatch.setattr("abhelper.samples.cli.load_registry", lambda: [pack, unverified])
    return lib, pack


def test_parser_knows_the_samples_commands():
    p = build_parser()
    for argv in (["samples", "list"], ["samples", "install", "all"], ["samples", "install", "x", "--force", "--live-dir", "D:\\Ableton"],
                 ["samples", "uninstall", "x"], ["samples", "doctor", "--user-library", "/tmp/x"]):
        assert p.parse_args(argv).func


def test_list_shows_status_and_license(world, capsys):
    lib, _ = world
    assert main(["samples", "list"]) == 0
    out = capsys.readouterr().out
    assert "test-pack" in out and "не установлен" in out and "CC0" in out and "[не проверен]" in out and str(lib) in out


def test_install_all_installs_only_verified_defaults_and_list_updates(world, capsys):
    lib, pack = world
    assert main(["samples", "install", "all", "--no-rescan"]) == 0
    out = capsys.readouterr().out
    assert "Готово: 3 зон" in out and "AbletonHelper Test Pack" in out and "CC0 1.0" in out
    assert (lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper" / "AbletonHelper Test Pack.adv").is_file()
    assert not (lib / "Presets" / "Instruments" / "Sampler" / "AbletonHelper" / "AbletonHelper Shaky.adv").exists()
    assert main(["samples", "install", "test-pack", "--no-rescan"]) == 0
    assert "Уже установлен" in capsys.readouterr().out
    assert main(["samples", "list"]) == 0
    assert "установлен" in capsys.readouterr().out.replace("не установлен", "")


def test_install_prints_the_zone_map_with_long_flag(world, capsys):
    assert main(["samples", "install", "test-pack", "--no-rescan", "-l"]) == 0
    out = capsys.readouterr().out
    assert "root  47" in out and "loop 500..1500" in out


def test_install_unknown_pack_and_missing_template(world, capsys, tmp_path, monkeypatch):
    assert main(["samples", "install", "nope", "--no-rescan"]) == 1
    assert "Нет такого пака" in capsys.readouterr().out
    empty = tmp_path / "Empty Library"
    empty.mkdir()
    monkeypatch.setenv("ABHELPER_USER_LIBRARY", str(empty))
    assert main(["samples", "install", "test-pack", "--no-rescan"]) == 1
    assert "AbletonHelper Template" in capsys.readouterr().out


def test_install_rescans_the_browser_when_live_answers(world, capsys, monkeypatch):
    from abhelper.bridge.fake import FakeBridge
    bridge = FakeBridge()
    monkeypatch.setattr("abhelper.cli.make_bridge", lambda settings, fake: bridge)
    assert main(["samples", "install", "test-pack"]) == 0
    assert any(c[0] == "browser_rescan" for c in bridge.calls)
    assert "переиндексируется" in capsys.readouterr().out


def test_install_without_live_tells_how_to_refresh(world, capsys):
    assert main(["samples", "install", "test-pack"]) == 0
    assert "Refresh" in capsys.readouterr().out


def test_uninstall(world, capsys):
    lib, pack = world
    main(["samples", "install", "test-pack", "--no-rescan"])
    capsys.readouterr()
    assert main(["samples", "uninstall", "test-pack"]) == 0
    assert "Удалено" in capsys.readouterr().out and not (lib / "Samples" / "AbletonHelper").exists()
    assert main(["samples", "uninstall", "test-pack"]) == 0
    assert "не был установлен" in capsys.readouterr().out


def test_doctor_reports_paths_template_and_packs(world, capsys):
    lib, _ = world
    assert main(["samples", "doctor"]) == 0
    out = capsys.readouterr().out
    assert str(lib) in out and "Шаблон Sampler" in out
    assert "Live не отвечает" in out and "Установлено паков: 0 из 2" in out


def test_doctor_without_template_explains_how_to_make_one(world, capsys, tmp_path, monkeypatch):
    empty = tmp_path / "Lib2"
    empty.mkdir()
    monkeypatch.setenv("ABHELPER_USER_LIBRARY", str(empty))
    assert main(["samples", "doctor"]) == 1
    out = capsys.readouterr().out
    assert "Шаблон Sampler не найден" in out and "Save Preset" in out


def test_doctor_uses_the_script_path_from_ping(world, capsys, monkeypatch, tmp_path):
    from abhelper.bridge.fake import FakeBridge
    res = tmp_path / "Live" / "Resources"
    (res / "Core Library").mkdir(parents=True)
    (res / "MIDI Remote Scripts" / "AbletonHelper").mkdir(parents=True)
    bridge = FakeBridge()
    bridge.script_path = str(res / "MIDI Remote Scripts" / "AbletonHelper")
    monkeypatch.setattr("abhelper.cli.make_bridge", lambda settings, fake: bridge)
    assert main(["samples", "doctor"]) == 0
    out = capsys.readouterr().out
    assert "Live отвечает" in out and "папка скрипта" in out and "Папка Live (Resources): " + str(res) in out

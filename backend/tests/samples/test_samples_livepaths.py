"""Finding the User Library and Live's Resources folder."""

from abhelper import livepaths


def fake_live(tmp_path, name="Live 11.3.25"):
    res = tmp_path / "Ableton" / "Resources"
    (res / "Core Library").mkdir(parents=True)
    (res / "MIDI Remote Scripts" / "AbletonHelper").mkdir(parents=True)
    return res


def test_resources_from_live_dir_variants(tmp_path):
    res = fake_live(tmp_path)
    assert livepaths.resources_from_live_dir(tmp_path / "Ableton") == res
    assert livepaths.resources_from_live_dir(res) == res
    assert livepaths.resources_from_live_dir(tmp_path / "nowhere") is None
    assert livepaths.resources_from_live_dir(None) is None
    nested = tmp_path / "Root" / "Live 11 Suite" / "Resources"
    (nested / "Core Library").mkdir(parents=True)
    assert livepaths.resources_from_live_dir(tmp_path / "Root") == nested
    mac = tmp_path / "Ableton Live 11 Suite.app" / "Contents" / "App-Resources"
    (mac / "Core Library").mkdir(parents=True)
    assert livepaths.resources_from_live_dir(tmp_path / "Ableton Live 11 Suite.app") == mac


def test_resources_from_script_path(tmp_path):
    res = fake_live(tmp_path)
    script = res / "MIDI Remote Scripts" / "AbletonHelper"
    assert livepaths.resources_from_script_path(script) == res
    assert livepaths.resources_from_script_path(str(script)) == res
    assert livepaths.resources_from_script_path(tmp_path / "User Library" / "Remote Scripts" / "AbletonHelper") is None
    assert livepaths.resources_from_script_path(None) is None


def test_find_resources_dirs_priority_and_dedup(tmp_path, monkeypatch):
    res = fake_live(tmp_path)
    other = tmp_path / "Other" / "Resources"
    (other / "Core Library").mkdir(parents=True)
    monkeypatch.setattr(livepaths, "common_resources_dirs", lambda platform=None: [other, res])
    found = livepaths.find_resources_dirs(live_dir=tmp_path / "Ableton", script_path=res / "MIDI Remote Scripts" / "AbletonHelper")
    assert found == [res, other]
    assert livepaths.find_resources_dirs() == [other, res]


def test_user_library_from_library_cfg(tmp_path):
    lib = tmp_path / "D" / "User Library"
    lib.mkdir(parents=True)
    appdata = tmp_path / "AppData"
    prefs = appdata / "Ableton" / "Live 11.3.25" / "Preferences"
    prefs.mkdir(parents=True)
    (prefs / "Library.cfg").write_text(
        '<?xml version="1.0"?><Ableton><ContentLibrary><UserLibrary><LibraryProject><ProjectPath Value="%s" /></LibraryProject></UserLibrary></ContentLibrary></Ableton>' % lib,
        encoding="utf-8")
    assert livepaths.default_user_library("win32", tmp_path, appdata=str(appdata)) == lib
    assert livepaths.user_library_from_cfg(prefs / "Library.cfg") == lib
    assert livepaths.default_user_library("linux", tmp_path) is None

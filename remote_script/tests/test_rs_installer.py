import importlib.util
import os
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "install_remote_script.py")


@pytest.fixture(scope="module")
def inst():
    spec = importlib.util.spec_from_file_location("install_remote_script", os.path.abspath(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_paths(inst, tmp_path, monkeypatch):
    assert str(inst.default_remote_scripts_dir("darwin", tmp_path)).endswith(
        os.path.join("Music", "Ableton", "User Library", "Remote Scripts"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "winhome"))
    p = inst.default_remote_scripts_dir("win32", tmp_path)
    assert p == tmp_path / "winhome" / "Documents" / "Ableton" / "User Library" / "Remote Scripts"
    assert inst.default_remote_scripts_dir("linux", tmp_path) is None


def test_install_copies_clean_tree(inst, tmp_path):
    dest = tmp_path / "Remote Scripts"
    assert inst.main(["--dest", str(dest)]) == 0
    pkg = dest / "AbletonHelper"
    assert (pkg / "__init__.py").is_file()
    assert (pkg / "handlers" / "devices.py").is_file()
    assert not list(pkg.rglob("__pycache__")) and not list(pkg.rglob("*.pyc")) and not (pkg / "tests").exists()
    # re-install replaces
    (pkg / "stale.py").write_text("x")
    assert inst.main(["--dest", str(dest)]) == 0
    assert not (pkg / "stale.py").exists()


def test_dest_pointing_to_package_folder_is_normalised(inst, tmp_path):
    dest = tmp_path / "Remote Scripts" / "AbletonHelper"
    assert inst.main(["--dest", str(dest)]) == 0
    assert (tmp_path / "Remote Scripts" / "AbletonHelper" / "__init__.py").is_file()
    assert not (tmp_path / "Remote Scripts" / "AbletonHelper" / "AbletonHelper").exists()


def test_dry_run_and_uninstall(inst, tmp_path, capsys):
    dest = tmp_path / "RS"
    assert inst.main(["--dest", str(dest), "--dry-run"]) == 0
    assert not dest.exists()
    inst.main(["--dest", str(dest)])
    assert inst.main(["--dest", str(dest), "--uninstall", "--dry-run"]) == 0
    assert (dest / "AbletonHelper").exists()
    assert inst.main(["--dest", str(dest), "--uninstall"]) == 0
    assert not (dest / "AbletonHelper").exists()
    assert inst.main(["--dest", str(dest), "--uninstall"]) == 0   # idempotent


def test_refuses_to_clobber_foreign_folder(inst, tmp_path):
    dest = tmp_path / "RS"
    (dest / "AbletonHelper").mkdir(parents=True)
    (dest / "AbletonHelper" / "mine.txt").write_text("keep me")
    assert inst.main(["--dest", str(dest)]) == 1
    assert (dest / "AbletonHelper" / "mine.txt").exists()
    assert inst.main(["--dest", str(dest), "--uninstall"]) == 1


def test_next_steps_are_printed_in_russian(inst, tmp_path, capsys):
    inst.main(["--dest", str(tmp_path / "RS")])
    out = capsys.readouterr().out
    assert "перезапустите" in out.lower() and "Control Surface" in out and "MIDI Remote Scripts" in out

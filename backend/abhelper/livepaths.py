"""Where Ableton Live keeps things on this computer (User Library, installation folder).

Standard library only and written for Python 3.8+, because scripts/install_remote_script.py loads this
file by path (it must work without the package being installed).

* User Library: read from Live's own Library.cfg (most recently used Live version), otherwise the
  OS default (macOS ~/Music/Ableton/User Library, Windows <Documents>\\Ableton\\User Library).
* Live "Resources" folder (holds "Core Library" and "MIDI Remote Scripts"): an explicit --live-dir,
  or derived from the Remote Script's own folder, or one of the usual installation paths.
"""

from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

_USER_LIBRARY_BLOCK = re.compile(r"<UserLibrary>(.*?)</UserLibrary>", re.S)
_PROJECT_PATH = re.compile(r'<ProjectPath\s+Value="([^"]*)"')


# --------------------------------------------------------------------------- User Library
def live_preferences_dirs(platform=None, home=None, appdata=None):
    """Preferences folders of installed Live versions, most recently used first."""
    platform = platform or sys.platform
    home = Path(home) if home else Path.home()
    if platform == "darwin":
        pattern_root = home / "Library" / "Preferences" / "Ableton"
        dirs = list(pattern_root.glob("Live *")) if pattern_root.is_dir() else []
    elif platform.startswith("win"):
        root = Path(appdata or os.environ.get("APPDATA") or (home / "AppData" / "Roaming")) / "Ableton"
        dirs = [d / "Preferences" for d in root.glob("Live *")] if root.is_dir() else []
    else:
        return []
    dirs = [d for d in dirs if (d / "Library.cfg").is_file()]
    return sorted(dirs, key=lambda d: (d / "Library.cfg").stat().st_mtime, reverse=True)


def user_library_from_cfg(cfg_path):
    """User Library folder recorded in Live's Library.cfg, or None."""
    try:
        text = Path(cfg_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    block = _USER_LIBRARY_BLOCK.search(text)
    match = _PROJECT_PATH.search(block.group(1) if block else "")
    if not match or not match.group(1).strip():
        return None
    path = Path(match.group(1).strip())
    if path.name != "User Library" and (path / "User Library").is_dir():
        path = path / "User Library"
    return path if path.is_dir() else None


def windows_documents_dir():
    """The real Documents folder on Windows (it may be moved, e.g. to another drive or OneDrive)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
            return Path(buf.value)
    except Exception:
        pass
    return None


def default_user_library(platform=None, home=None, appdata=None, documents=None):
    """User Library folder for this OS (it may not exist yet), or None if the OS is not supported."""
    platform = platform or sys.platform
    home = Path(home) if home else Path.home()
    if not (platform == "darwin" or platform.startswith("win")):
        return None
    for prefs in live_preferences_dirs(platform, home, appdata):
        library = user_library_from_cfg(prefs / "Library.cfg")
        if library is not None:
            return library
    if platform == "darwin":
        return home / "Music" / "Ableton" / "User Library"
    if documents is None and platform == sys.platform:
        documents = windows_documents_dir()
    if documents is None:
        documents = Path(os.environ.get("USERPROFILE") or str(home)) / "Documents"
    return Path(documents) / "Ableton" / "User Library"


# --------------------------------------------------------------------------- Live installation
def is_resources_dir(path):
    """True if `path` looks like Live's Resources folder."""
    p = Path(path)
    return p.is_dir() and ((p / "Core Library").is_dir() or (p / "MIDI Remote Scripts").is_dir())


def resources_from_script_path(script_path):
    """<Live>/Resources for a Remote Script folder inside 'MIDI Remote Scripts', else None.

    Works with Windows paths reported by the Remote Script even when parsed on another OS.
    """
    if not script_path:
        return None
    parts = re.split(r"[\\/]+", str(script_path).rstrip("\\/"))
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower() == "midi remote scripts":
            head = parts[:i]
            sep = "\\" if "\\" in str(script_path) and "/" not in str(script_path) else "/"
            joined = sep.join(head) if head != [""] else sep
            cand = Path(joined)
            return cand if cand.is_dir() else None
    return None


def resources_from_live_dir(live_dir):
    """Accepts the Live folder (D:\\Ableton), its Resources folder, or a macOS .app bundle."""
    if not live_dir:
        return None
    p = Path(str(live_dir)).expanduser()
    for cand in (p, p / "Resources", p / "Contents" / "App-Resources"):
        if is_resources_dir(cand):
            return cand
    # D:\Ableton\Live 11 Suite\Resources and similar one-level-deeper layouts
    try:
        for sub in sorted(p.iterdir()):
            if sub.is_dir() and is_resources_dir(sub / "Resources"):
                return sub / "Resources"
    except OSError:
        pass
    return None


def common_resources_dirs(platform=None):
    """Usual places where Live keeps its Resources folder (only existing ones, newest version first)."""
    platform = platform or sys.platform
    patterns = []
    if platform.startswith("win"):
        for drive in "CDEFGH":
            patterns += [
                drive + ":\\ProgramData\\Ableton\\Live 1* *\\Resources",
                drive + ":\\Program Files\\Ableton\\Live 1* *\\Resources",
                drive + ":\\Ableton\\Resources",
                drive + ":\\Ableton\\Live 1* *\\Resources",
                drive + ":\\Ableton\\Program\\Resources",
            ]
    elif platform == "darwin":
        patterns = ["/Applications/Ableton Live 1* *.app/Contents/App-Resources",
                    "/Applications/Ableton Live 1*.app/Contents/App-Resources"]
    found = []
    for pat in patterns:
        for hit in sorted(glob.glob(pat), reverse=True):
            if is_resources_dir(hit) and Path(hit) not in found:
                found.append(Path(hit))
    return found


def find_resources_dirs(live_dir=None, script_path=None, platform=None):
    """Candidate Live Resources folders in priority order: --live-dir, Remote Script location, common paths."""
    out = []
    for cand in (resources_from_live_dir(live_dir), resources_from_script_path(script_path)):
        if cand is not None and cand not in out:
            out.append(cand)
    for cand in common_resources_dirs(platform):
        if cand not in out:
            out.append(cand)
    return out

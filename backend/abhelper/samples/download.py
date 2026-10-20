"""Downloading and unpacking sample archives: HTTPS, resumable, verified, safe extraction."""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
CHUNK = 256 * 1024
Progress = Callable[[int, int], None]          # (bytes_done, bytes_total or 0)


class DownloadError(Exception):
    pass


class ExtractError(Exception):
    pass


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_file(path, size_bytes: int | None = None, sha256: str | None = None) -> str | None:
    """None if the file matches the expected size / sha256, otherwise a Russian explanation."""
    p = Path(path)
    if not p.is_file():
        return "файл %s не найден" % p
    if size_bytes and p.stat().st_size != size_bytes:
        return "размер файла %d байт, ожидалось %d" % (p.stat().st_size, size_bytes)
    if sha256 and sha256_of(p).lower() != sha256.lower():
        return "контрольная сумма sha256 не совпала (файл повреждён или изменился на сервере)"
    return None


def download_file(url: str, dest, *, size_bytes: int | None = None, sha256: str | None = None,
                  progress: Progress | None = None, timeout: float = 60.0, opener=None) -> Path:
    """Download `url` to `dest` via a `.part` file (resumes with a Range request), then verify it.

    An already complete and valid `dest` is reused. `opener(request, timeout)` is injectable for tests.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and verify_file(dest, size_bytes, sha256) is None:
        if progress:
            progress(dest.stat().st_size, dest.stat().st_size)
        return dest
    part = dest.with_name(dest.name + ".part")
    opener = opener or (lambda req, t: urllib.request.urlopen(req, timeout=t))
    for attempt in range(2):
        have = part.stat().st_size if part.is_file() else 0
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if have:
            headers["Range"] = "bytes=%d-" % have
        try:
            resp = opener(urllib.request.Request(url, headers=headers), timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have:                    # the .part is already complete or stale
                if size_bytes and have == size_bytes:
                    break
                part.unlink()
                continue
            raise DownloadError("сервер ответил %s %s для %s" % (exc.code, exc.reason, url))
        except (urllib.error.URLError, OSError) as exc:
            raise DownloadError("нет соединения с %s: %s" % (url, getattr(exc, "reason", exc)))
        with resp:
            status = getattr(resp, "status", 200)
            total_header = int(resp.headers.get("Content-Length") or 0)
            if have and status == 206:
                mode, done, total = "ab", have, have + total_header
            else:                                           # no resume support: start over
                mode, done, total = "wb", 0, total_header
            if size_bytes:
                total = size_bytes
            try:
                with open(str(part), mode) as out:
                    while True:
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        out.write(block)
                        done += len(block)
                        if progress:
                            progress(done, total)
            except OSError as exc:
                raise DownloadError("обрыв загрузки (%s); повторите команду — загрузка продолжится" % exc)
        break
    problem = verify_file(part, size_bytes, sha256)
    if problem:
        # keep a short partial for resuming, drop a complete-but-wrong file
        if size_bytes is None or part.stat().st_size >= size_bytes:
            part.unlink()
        raise DownloadError("%s: %s" % (url, problem))
    os.replace(str(part), str(dest))
    return dest


# --------------------------------------------------------------------------- extraction
def _inside(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def extract_archive(archive, dest, kind: str | None = None) -> Path:
    """Unpack .7z (py7zr), .zip, .tar.gz/.tar.xz/.tar.bz2 into `dest` (created). Refuses paths that escape it."""
    archive, dest = Path(archive), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    kind = (kind or "").lower() or ("7z" if name.endswith(".7z") else "zip" if name.endswith(".zip") else
                                    "tar" if ".tar" in name or name.endswith((".tgz", ".txz")) else "")
    if kind == "7z":
        try:
            import py7zr
        except ImportError:
            raise ExtractError("для распаковки .7z нужен пакет py7zr: pip install py7zr")
        try:
            with py7zr.SevenZipFile(str(archive)) as z:
                for entry in z.getnames():
                    if not _inside(dest, dest / entry):
                        raise ExtractError("в архиве путь за пределами папки: %s" % entry)
                z.extractall(str(dest))
        except ExtractError:
            raise
        except Exception as exc:                            # py7zr raises many types
            raise ExtractError("не удалось распаковать %s: %s" % (archive.name, exc))
    elif kind == "zip":
        try:
            with zipfile.ZipFile(str(archive)) as z:
                for entry in z.namelist():
                    if not _inside(dest, dest / entry):
                        raise ExtractError("в архиве путь за пределами папки: %s" % entry)
                z.extractall(str(dest))
        except zipfile.BadZipFile as exc:
            raise ExtractError("не удалось распаковать %s: %s" % (archive.name, exc))
    elif kind in ("tar", "tar.gz", "tar.xz", "tar.bz2", "tgz"):
        try:
            with tarfile.open(str(archive)) as t:
                for member in t.getmembers():
                    if not _inside(dest, dest / member.name) or member.issym() or member.islnk():
                        raise ExtractError("в архиве недопустимый элемент: %s" % member.name)
                try:
                    t.extractall(str(dest), filter="data")
                except TypeError:                           # Python without extraction filters
                    t.extractall(str(dest))
        except tarfile.TarError as exc:
            raise ExtractError("не удалось распаковать %s: %s" % (archive.name, exc))
    else:
        raise ExtractError("неизвестный формат архива: %s" % archive.name)
    return dest


def clean_dir(path) -> None:
    shutil.rmtree(str(path), ignore_errors=True)

"""Downloading (resume, checksum) and safe extraction; no network."""

import hashlib
import io
import tarfile
import urllib.error
import zipfile

import pytest

from abhelper.samples.download import (DownloadError, ExtractError, download_file, extract_archive, sha256_of,
                                       verify_file)

PAYLOAD = bytes(range(256)) * 400            # ~100 KB


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self._buf = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeServer:
    """Serves PAYLOAD; supports Range requests when `ranges` is true; can drop the connection mid-way once."""

    def __init__(self, ranges=True, payload=PAYLOAD):
        self.ranges, self.payload, self.requests = ranges, payload, []

    def __call__(self, request, timeout):
        self.requests.append(dict(request.header_items()))
        rng = request.get_header("Range")
        if rng and self.ranges:
            start = int(rng.split("=")[1].rstrip("-"))
            return FakeResponse(self.payload[start:], status=206)
        return FakeResponse(self.payload)


def test_download_verifies_and_reports_progress(tmp_path):
    seen = []
    server = FakeServer()
    dest = download_file("https://x/pack.7z", tmp_path / "d" / "pack.7z", size_bytes=len(PAYLOAD),
                         sha256=hashlib.sha256(PAYLOAD).hexdigest(), progress=lambda d, t: seen.append((d, t)), opener=server)
    assert dest.read_bytes() == PAYLOAD and not (tmp_path / "d" / "pack.7z.part").exists()
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert "Mozilla" in server.requests[0]["User-agent"]                      # browser-like UA


def test_download_reuses_a_valid_file_without_requests(tmp_path):
    (tmp_path / "p.bin").write_bytes(PAYLOAD)
    server = FakeServer()
    download_file("https://x/p.bin", tmp_path / "p.bin", size_bytes=len(PAYLOAD), opener=server)
    assert server.requests == []


@pytest.mark.parametrize("ranges", [True, False])
def test_download_resumes_a_partial_file(tmp_path, ranges):
    (tmp_path / "p.bin.part").write_bytes(PAYLOAD[:30000])
    server = FakeServer(ranges=ranges)
    download_file("https://x/p.bin", tmp_path / "p.bin", size_bytes=len(PAYLOAD),
                  sha256=hashlib.sha256(PAYLOAD).hexdigest(), opener=server)
    assert (tmp_path / "p.bin").read_bytes() == PAYLOAD
    assert ("Range" in server.requests[0]) and server.requests[0]["Range"] == "bytes=30000-"


def test_download_rejects_wrong_checksum_and_removes_the_bad_file(tmp_path):
    with pytest.raises(DownloadError, match="sha256"):
        download_file("https://x/p.bin", tmp_path / "p.bin", size_bytes=len(PAYLOAD), sha256="0" * 64, opener=FakeServer())
    assert not (tmp_path / "p.bin").exists() and not (tmp_path / "p.bin.part").exists()


def test_download_rejects_wrong_size(tmp_path):
    with pytest.raises(DownloadError, match="размер"):
        download_file("https://x/p.bin", tmp_path / "p.bin", size_bytes=len(PAYLOAD) + 1, opener=FakeServer())


def test_download_http_and_network_errors(tmp_path):
    def http404(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    def offline(req, timeout):
        raise urllib.error.URLError("no route")

    with pytest.raises(DownloadError, match="404"):
        download_file("https://x/p.bin", tmp_path / "a.bin", opener=http404)
    with pytest.raises(DownloadError, match="нет соединения"):
        download_file("https://x/p.bin", tmp_path / "b.bin", opener=offline)


def test_download_from_file_url_with_the_real_opener(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(PAYLOAD)
    dest = download_file(src.as_uri(), tmp_path / "out" / "dst.bin", size_bytes=len(PAYLOAD))
    assert sha256_of(dest) == hashlib.sha256(PAYLOAD).hexdigest()


def test_verify_file(tmp_path):
    p = tmp_path / "a"
    p.write_bytes(b"abc")
    assert verify_file(p, 3, hashlib.sha256(b"abc").hexdigest().upper()) is None
    assert verify_file(p, 4) and verify_file(p, None, "0" * 64) and verify_file(tmp_path / "nope")


# ------------------------------------------------------------------ extraction
def test_extract_zip_and_tar(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("dir/file.txt", "hi")
    extract_archive(z, tmp_path / "ox", "zip")
    assert (tmp_path / "ox" / "dir" / "file.txt").read_text() == "hi"
    for ext, mode in (("tar.gz", "w:gz"), ("tar.xz", "w:xz"), ("tar.bz2", "w:bz2")):
        t = tmp_path / ("a." + ext)
        with tarfile.open(t, mode) as tf:
            info = tarfile.TarInfo("d/f.bin")
            info.size = 3
            tf.addfile(info, io.BytesIO(b"abc"))
        extract_archive(t, tmp_path / ("o" + ext), ext)
        assert (tmp_path / ("o" + ext) / "d" / "f.bin").read_bytes() == b"abc"


def test_extract_7z(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "f.txt").write_text("seven")
    arc = tmp_path / "a.7z"
    with py7zr.SevenZipFile(arc, "w") as z:
        z.writeall(src, "pack")
    extract_archive(arc, tmp_path / "out")                    # kind guessed from the extension
    assert (tmp_path / "out" / "pack" / "sub" / "f.txt").read_text() == "seven"


def test_extract_refuses_path_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escaped.txt", "x")
    with pytest.raises(ExtractError):
        extract_archive(z, tmp_path / "o1", "zip")
    assert not (tmp_path / "escaped.txt").exists()
    t = tmp_path / "evil.tar"
    with tarfile.open(t, "w") as tf:
        info = tarfile.TarInfo("../escaped2.txt")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ExtractError):
        extract_archive(t, tmp_path / "o2", "tar")
    assert not (tmp_path / "escaped2.txt").exists()


def test_extract_errors(tmp_path):
    (tmp_path / "x.zip").write_bytes(b"not a zip")
    with pytest.raises(ExtractError):
        extract_archive(tmp_path / "x.zip", tmp_path / "o")
    with pytest.raises(ExtractError):
        extract_archive(tmp_path / "x.rar", tmp_path / "o")

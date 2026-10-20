"""Frame count / sample rate of audio files without any third-party library (WAV, FLAC, AIFF)."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path


class AudioError(ValueError):
    pass


@dataclass
class AudioInfo:
    frames: int
    sample_rate: int
    channels: int
    bits: int
    format: str                                   # "wav" | "flac" | "aiff"
    loops: list[tuple[int, int]] = field(default_factory=list)   # (start, end) frames from a WAV 'smpl' chunk
    size_bytes: int = 0


def _read_wav(f, size: int) -> AudioInfo:
    head = f.read(12)
    if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
        raise AudioError("не WAV (нет заголовка RIFF/WAVE)")
    channels = rate = bits = 0
    block_align = 0
    data_bytes = None
    loops: list[tuple[int, int]] = []
    pos = 12
    while pos + 8 <= size:
        f.seek(pos)
        chunk = f.read(8)
        if len(chunk) < 8:
            break
        cid, csize = chunk[:4], struct.unpack("<I", chunk[4:])[0]
        body = pos + 8
        if cid == b"fmt ":
            fmt = f.read(min(csize, 40))
            if len(fmt) < 16:
                raise AudioError("повреждён блок fmt")
            tag, channels, rate, _byte_rate, block_align, bits = struct.unpack("<HHIIHH", fmt[:16])
            if tag == 0xFFFE and len(fmt) >= 26:                      # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack("<H", fmt[24:26])[0]
            if tag not in (1, 3):
                raise AudioError("формат WAV %#x не поддерживается (нужен PCM или float)" % tag)
        elif cid == b"data":
            data_bytes = min(csize, max(0, size - body))
        elif cid == b"smpl":
            smpl = f.read(min(csize, 36 + 24 * 16))
            if len(smpl) >= 36:
                n = struct.unpack("<I", smpl[28:32])[0]
                for i in range(min(n, 16)):
                    rec = smpl[36 + 24 * i:36 + 24 * (i + 1)]
                    if len(rec) == 24:
                        _id, _type, start, end = struct.unpack("<IIII", rec[:16])
                        loops.append((start, end))
        pos = body + csize + (csize & 1)
    if not (channels and rate and block_align and data_bytes is not None):
        raise AudioError("в WAV нет блока fmt или data")
    return AudioInfo(data_bytes // block_align, rate, channels, bits, "wav", loops, size)


def _read_flac(f, size: int) -> AudioInfo:
    if f.read(4) != b"fLaC":
        raise AudioError("не FLAC (нет метки fLaC)")
    while True:
        hdr = f.read(4)
        if len(hdr) < 4:
            raise AudioError("во FLAC нет блока STREAMINFO")
        last, kind, length = bool(hdr[0] & 0x80), hdr[0] & 0x7F, int.from_bytes(hdr[1:], "big")
        if kind == 0:
            info = f.read(length)
            if len(info) < 18:
                raise AudioError("повреждён STREAMINFO")
            packed = int.from_bytes(info[10:18], "big")          # 20 bits rate, 3 ch-1, 5 bps-1, 36 total samples
            rate = packed >> 44
            channels = ((packed >> 41) & 0x7) + 1
            bits = ((packed >> 36) & 0x1F) + 1
            total = packed & ((1 << 36) - 1)
            if not rate:
                raise AudioError("во FLAC нулевая частота")
            return AudioInfo(total, rate, channels, bits, "flac", [], size)
        if last:
            raise AudioError("во FLAC нет блока STREAMINFO")
        f.seek(length, 1)


def _read_aiff(f, size: int) -> AudioInfo:
    head = f.read(12)
    if len(head) < 12 or head[:4] != b"FORM" or head[8:12] not in (b"AIFF", b"AIFC"):
        raise AudioError("не AIFF")
    pos = 12
    while pos + 8 <= size:
        f.seek(pos)
        chunk = f.read(8)
        if len(chunk) < 8:
            break
        cid, csize = chunk[:4], struct.unpack(">I", chunk[4:])[0]
        if cid == b"COMM":
            comm = f.read(18)
            channels, frames, bits = struct.unpack(">hIh", comm[:8])
            exp = struct.unpack(">H", comm[8:10])[0]
            mant = int.from_bytes(comm[10:18], "big")
            rate = int(round(mant * 2.0 ** ((exp & 0x7FFF) - 16383 - 63)))
            return AudioInfo(frames, rate, channels, bits, "aiff", [], size)
        pos += 8 + csize + (csize & 1)
    raise AudioError("в AIFF нет блока COMM")


def read_audio_info(path) -> AudioInfo:
    p = Path(path)
    try:
        size = p.stat().st_size
        with open(str(p), "rb") as f:
            magic = f.read(4)
            f.seek(0)
            if magic in (b"RIFF", b"RF64"):
                return _read_wav(f, size)
            if magic == b"fLaC":
                return _read_flac(f, size)
            if magic == b"FORM":
                return _read_aiff(f, size)
    except OSError as exc:
        raise AudioError("не удалось прочитать %s: %s" % (p.name, exc))
    raise AudioError("%s: неизвестный формат аудио (поддерживаются WAV, FLAC, AIFF)" % p.name)

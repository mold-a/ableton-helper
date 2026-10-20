"""Frame count / rate from tiny WAV, WAVE_FORMAT_EXTENSIBLE and FLAC headers."""

import pytest
from samples_testkit import make_flac, make_wav, make_wav_extensible

from abhelper.samples.audioinfo import AudioError, read_audio_info


def test_plain_wav(tmp_path):
    info = read_audio_info(make_wav(tmp_path / "a.wav", frames=1234, rate=48000, channels=2))
    assert (info.frames, info.sample_rate, info.channels, info.bits, info.format) == (1234, 48000, 2, 16, "wav")
    assert info.loops == [] and info.size_bytes == (tmp_path / "a.wav").stat().st_size


def test_wav_smpl_loops(tmp_path):
    info = read_audio_info(make_wav(tmp_path / "a.wav", frames=5000, loops=[(100, 4000), (5, 6)]))
    assert info.loops == [(100, 4000), (5, 6)] and info.frames == 5000


def test_wav_extensible_with_extra_chunks(tmp_path):
    info = read_audio_info(make_wav_extensible(tmp_path / "e.wav", frames=777, rate=96000, channels=2, bits=24))
    assert (info.frames, info.sample_rate, info.channels, info.bits) == (777, 96000, 2, 24)


def test_flac_streaminfo(tmp_path):
    info = read_audio_info(make_flac(tmp_path / "a.flac", frames=123456, rate=48000, channels=2, bits=24))
    assert (info.frames, info.sample_rate, info.channels, info.bits, info.format) == (123456, 48000, 2, 24, "flac")
    big = read_audio_info(make_flac(tmp_path / "b.flac", frames=2 ** 35 + 5, rate=192000, channels=1, bits=16))
    assert big.frames == 2 ** 35 + 5 and big.sample_rate == 192000


def test_aiff(tmp_path):
    import struct
    # 80-bit extended float for 44100: exponent 16398, mantissa 44100 << 48
    mant = (44100 << 48).to_bytes(8, "big")
    comm = struct.pack(">hIh", 1, 321, 16) + struct.pack(">H", 16398) + mant
    body = b"AIFF" + b"COMM" + struct.pack(">I", 18) + comm + b"SSND" + struct.pack(">I", 8) + b"\0" * 8
    p = tmp_path / "a.aif"
    p.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)
    info = read_audio_info(p)
    assert (info.frames, info.sample_rate, info.channels, info.format) == (321, 44100, 1, "aiff")


def test_errors(tmp_path):
    (tmp_path / "x.wav").write_bytes(b"not audio at all")
    with pytest.raises(AudioError):
        read_audio_info(tmp_path / "x.wav")
    with pytest.raises(AudioError):
        read_audio_info(tmp_path / "missing.wav")
    (tmp_path / "bad.flac").write_bytes(b"fLaC")
    with pytest.raises(AudioError):
        read_audio_info(tmp_path / "bad.flac")
    # WAV with an unsupported codec tag (ADPCM = 2)
    import struct
    fmt = struct.pack("<HHIIHH", 2, 1, 8000, 8000, 1, 4)
    body = b"WAVEfmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", 0)
    (tmp_path / "adpcm.wav").write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    with pytest.raises(AudioError):
        read_audio_info(tmp_path / "adpcm.wav")

"""Helpers for the samples tests (plain module with a unique basename, like sound_testkit)."""

from __future__ import annotations

import gzip
import io
import struct
import wave
from pathlib import Path

# A tiny self-written stand-in for the Sampler XML Live writes. It only mimics the element names that the
# generator touches; it is NOT a copy of any real preset or of ConvertWithMoss templates.
SYNTH_PART = """
<MultiSamplePart Id="0" HasImportedSlicePoints="true" NeedsAnalysisData="false">
  <LomId Value="0" />
  <Name Value="template-sample" />
  <Selection Value="true" />
  <IsActive Value="true" />
  <Solo Value="false" />
  <KeyRange><Min Value="0" /><Max Value="127" /><CrossfadeMin Value="0" /><CrossfadeMax Value="127" /></KeyRange>
  <VelocityRange><Min Value="1" /><Max Value="127" /><CrossfadeMin Value="1" /><CrossfadeMax Value="127" /></VelocityRange>
  <SelectorRange><Min Value="0" /><Max Value="127" /><CrossfadeMin Value="0" /><CrossfadeMax Value="127" /></SelectorRange>
  <RootKey Value="60" />
  <Detune Value="0" />
  <TuneScale Value="100" />
  <Panorama Value="0" />
  <Volume Value="1" />
  <Link Value="false" />
  <SampleStart Value="0" />
  <SampleEnd Value="1000" />
  <SustainLoop><Start Value="0" /><End Value="1000" /><Mode Value="0" /><Crossfade Value="0" /><Detune Value="0" /></SustainLoop>
  <ReleaseLoop><Start Value="0" /><End Value="1000" /><Mode Value="3" /><Crossfade Value="0" /><Detune Value="0" /></ReleaseLoop>
  <SampleRef>
    <FileRef>
      <RelativePathType Value="3" />
      <RelativePath Value="old/template.wav" />
      <Path Value="/old/template.wav" />
      <Type Value="1" />
      <LivePackName Value="" />
      <LivePackId Value="" />
      <OriginalFileSize Value="123" />
    </FileRef>
    <LastModDate Value="1" />
    <SourceContext><SourceContext><OriginalFileRef /></SourceContext></SourceContext>
    <SampleUsageHint Value="0" />
    <DefaultDuration Value="1000" />
    <DefaultSampleRate Value="44100" />
  </SampleRef>
  <SampleWarpProperties>
    <WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0" /><WarpMarker Id="1" SecTime="1" BeatTime="2" /></WarpMarkers>
    <WarpMode Value="4" />
    <IsWarped Value="true" />
    <Onsets><UserOnsets><SomeOnset /></UserOnsets><HasUserOnsets Value="true" /></Onsets>
  </SampleWarpProperties>
  <SlicePoints>
    <SlicePoint TimeInSeconds="0.5" Rank="3" NormalizedEnergy="0.2" />
    <SlicePoint TimeInSeconds="0.7" Rank="4" NormalizedEnergy="0.3" />
  </SlicePoints>
  <ManualSlicePoints><SlicePoint TimeInSeconds="9" /></ManualSlicePoints>
  <BeatSlicePoints />
  <RegionSlicePoints />
</MultiSamplePart>
"""


def _param(name: str, value) -> str:
    return '<%s><LomId Value="0" /><Manual Value="%s" /><AutomationTarget Id="1"><LockEnvelope Value="0" /></AutomationTarget></%s>' % (
        name, value, name)


def synth_template_xml(extra_device: bool = False) -> str:
    env = "".join(_param(n, v) for n, v in (
        ("AttackTime", 5), ("AttackLevel", 0.5), ("DecayTime", 600), ("DecayLevel", 0.9), ("SustainLevel", 0.3),
        ("ReleaseTime", 50), ("ReleaseLevel", 0.2), ("LoopMode", 2)))
    body = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="11.0_11300" SchemaChangeCount="3" Creator="Ableton Live 11.3.25" Revision="abc">
  <MultiSampler Id="7">
    <LomId Value="0" />
    <UserName Value="Some Factory Preset" />
    <Annotation Value="factory text" />
    <LastPresetRef><Value><FilePresetRef Id="0"><FileRef><Path Value="/factory.adv" /></FileRef></FilePresetRef></Value></LastPresetRef>
    <SourceContext><Value><BranchSourceContext Id="0" /></Value></SourceContext>
    <Player>
      <MultiSampleMap>
        <SampleParts>%(part)s</SampleParts>
        <LoadInRam Value="false" />
        <SourceContext><Value><X /></Value></SourceContext>
      </MultiSampleMap>
      <LoopModulators>
        <SampleStart><Manual Value="0.3" /></SampleStart>
        <SampleLength><Manual Value="0.5" /></SampleLength>
        <LoopLength><Manual Value="0.2" /></LoopLength>
        <LoopFade><Manual Value="0.4" /></LoopFade>
      </LoopModulators>
      <Reverse><Manual Value="true" /></Reverse>
    </Player>
    <Pitch>
      <TransposeKey><Manual Value="5" /></TransposeKey>
      <TransposeFine><Manual Value="12" /></TransposeFine>
      <Envelope><IsOn><Manual Value="true" /></IsOn></Envelope>
    </Pitch>
    <Filter><IsOn><Manual Value="true" /></IsOn></Filter>
    <Shaper><IsOn><Manual Value="1" /></IsOn></Shaper>
    <VolumeAndPan>
      <Volume><Manual Value="-6" /></Volume>
      <VolumeVelScale><Manual Value="0.9" /></VolumeVelScale>
      <Envelope>%(env)s</Envelope>
    </VolumeAndPan>
    <Lfo><IsOn><Manual Value="true" /></IsOn></Lfo>
    <VelDst>
      <ModConnections.0><Amount Value="40" /><Connection Value="3" /></ModConnections.0>
    </VelDst>
    <Globals><NumVoices Value="11" /></Globals>
  </MultiSampler>
</Ableton>
""" % {"part": SYNTH_PART, "env": env}
    if extra_device:
        body = body.replace("</Ableton>", "  <OtherDevice />\n</Ableton>")
    return body


def synth_template_gz() -> bytes:
    return gzip.compress(synth_template_xml().encode("utf-8"))


def write_template(path: Path, xml: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress((xml or synth_template_xml()).encode("utf-8")))
    return path


# ------------------------------------------------------------------ audio
def make_wav(path: Path, frames: int = 2000, rate: int = 44100, channels: int = 1, loops=()) -> Path:
    """Write a small silent 16-bit WAV, optionally with a 'smpl' chunk holding loops [(start, end)]."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * frames)
    data = buf.getvalue()
    if loops:
        smpl = struct.pack("<9I", 0, 0, 0, 60, 0, 0, 0, len(loops), 0)
        for i, (s, e) in enumerate(loops):
            smpl += struct.pack("<6I", i, 0, s, e, 0, 0)
        data += b"smpl" + struct.pack("<I", len(smpl)) + smpl
        data = data[:4] + struct.pack("<I", len(data) - 8) + data[8:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def make_wav_extensible(path: Path, frames: int = 1234, rate: int = 48000, channels: int = 2, bits: int = 24) -> Path:
    block = channels * bits // 8
    sub = struct.pack("<H", 1) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"   # PCM sub-format GUID
    fmt = struct.pack("<HHIIHH", 0xFFFE, channels, rate, rate * block, block, bits)
    fmt += struct.pack("<HHI", 22, bits, 3) + sub
    data = b"\x00" * (frames * block)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"LIST" + struct.pack("<I", 5) + b"abcde\x00" \
        + b"data" + struct.pack("<I", len(data)) + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def make_flac(path: Path, frames: int = 5000, rate: int = 44100, channels: int = 1, bits: int = 16) -> Path:
    """A FLAC file that is only a valid fLaC marker + STREAMINFO block (enough for header parsing)."""
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | frames
    info = struct.pack(">HH", 4096, 4096) + b"\x00\x00\x00\x00\x00\x00" + packed.to_bytes(8, "big") + b"\x00" * 16
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(info).to_bytes(3, "big") + info)
    return path


# ------------------------------------------------------------------ archives / packs
def make_pack_dir(root: Path, sfz_text: str, files: dict[str, dict]) -> Path:
    """root/<files>.wav + root/pack.sfz; files: {relative name: {frames, rate, loops, channels}}."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, kw in files.items():
        make_wav(root / rel, **kw)
    (root / "pack.sfz").write_text(sfz_text, encoding="utf-8")
    (root / "LICENSE.txt").write_text("CC0 test license\n", encoding="utf-8")
    return root


SFZ_BASIC = """
// a tiny test instrument
<control> default_path=samples/
<global> ampeg_attack=0.06 ampeg_decay=18 ampeg_sustain=55 ampeg_release=0.13 amp_veltrack=40 loop_mode=loop_continuous
<group>
<region> sample=low.wav pitch_keycenter=47 lokey=0 hikey=49 tune=-34 loop_start=500 loop_end=1500
<region> sample=mid.wav pitch_keycenter=c4 lokey=50 hikey=62 tune=66 loop_start=400 loop_end=1900
<group> loop_mode=no_loop
<region> sample=high.wav key=g#5 lovel=1 hivel=90
<group> trigger=release
<region> sample=rel.wav key=60
"""
SFZ_FILES = {
    "samples/low.wav": {"frames": 2000},
    "samples/mid.wav": {"frames": 2000, "channels": 2},
    "samples/high.wav": {"frames": 3000, "rate": 48000},
    "samples/rel.wav": {"frames": 300},
}

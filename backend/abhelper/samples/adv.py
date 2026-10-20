"""Generating Ableton Sampler presets (.adv = gzip-compressed XML).

License-clean and version-exact: instead of shipping a template we take the Sampler (`<MultiSampler>`)
XML from the user's OWN Live installation (Core Library) or from a preset they saved themselves, and
only replace the sample zones (`<MultiSamplePart>`) and a few settings in a copy of it.

The XML paths used below (Player/MultiSampleMap/SampleParts, KeyRange, RootKey, SustainLoop,
SampleRef/FileRef, VolumeAndPan/Envelope ...) are the ones Live 11 writes itself.
"""

from __future__ import annotations

import copy
import gzip
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .audioinfo import AudioInfo
from .sfz import Region

TEMPLATE_PRESET_NAME = "AbletonHelper Template"
HOW_TO_MAKE_TEMPLATE = (
    "В Live: перетащите устройство Sampler на MIDI-дорожку, бросьте в него любой звук, затем «Save Preset» "
    "(кнопка-дискета в шапке устройства) под именем «%s» в папку User Library\\Presets\\Instruments\\Sampler. "
    "После этого повторите команду." % TEMPLATE_PRESET_NAME)

_MAX_CANDIDATE_BYTES = 3 * 1024 * 1024        # compressed size cap when scanning the Core Library
_MAX_SCAN_FILES = 6000
MIN_LEVEL = 0.0003162277571                    # Live's -70 dB floor for envelope levels


class TemplateError(Exception):
    pass


# --------------------------------------------------------------------------- reading templates
def read_live_xml(path) -> bytes | None:
    """Content of a .adv/.adg (gzip XML, or plain XML) as bytes, or None if unreadable."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except (OSError, EOFError):
            return None
    return raw if raw.lstrip()[:1] == b"<" else None


@dataclass
class Template:
    source: str
    kind: str                                  # "explicit" | "user" | "core" | "user-sampler" | "memory"
    root_attrib: dict
    device: ET.Element                         # the <MultiSampler> subtree
    part: ET.Element                           # its first <MultiSamplePart>


MIN_TEMPLATE_MAJOR = 11      # Live 11 switched FileRef to path strings; older presets use a binary <Data> ref


def live_major_version(root_attrib: dict) -> int | None:
    """Live version a document was saved with: Creator 'Ableton Live 11.3.22' or MinorVersion '11.0_11300'."""
    m = re.search(r"Live\s+(\d+)", root_attrib.get("Creator", ""))
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\.", root_attrib.get("MinorVersion", ""))
    return int(m.group(1)) if m else None


def template_from_xml(data: bytes | str, source: str = "memory", kind: str = "memory") -> Template:
    """Take the first `<MultiSampler>` that has at least one `<MultiSamplePart>` out of a Live XML document."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise TemplateError("%s: не XML (%s)" % (source, exc))
    major = live_major_version(dict(root.attrib))
    if major is not None and major < MIN_TEMPLATE_MAJOR:
        raise TemplateError("%s: сохранён в Live %d — нужен шаблон из Live %d+ (иначе Live отбрасывает зоны)"
                            % (source, major, MIN_TEMPLATE_MAJOR))
    for dev in root.iter("MultiSampler"):
        part = dev.find(".//MultiSamplePart")
        if part is not None:
            return Template(source, kind, dict(root.attrib), copy.deepcopy(dev), copy.deepcopy(part))
    raise TemplateError("%s: в файле нет Sampler с зонами сэмплов" % source)


def load_template_file(path, kind: str = "explicit") -> Template:
    data = read_live_xml(path)
    if data is None:
        raise TemplateError("%s: не удалось прочитать (ожидался .adv/.adg)" % path)
    return template_from_xml(data, str(path), kind)


def _iter_live_files(root: Path) -> list[Path]:
    out = []
    for dirpath, _dirs, files in os.walk(str(root)):
        for name in files:
            if name.lower().endswith((".adv", ".adg")):
                out.append(Path(dirpath) / name)
    return out


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 1 << 60


def _scan_for_template(files: Iterable[Path], kind: str, limit: int = _MAX_SCAN_FILES) -> Template | None:
    def priority(p: Path):
        low = str(p).lower()
        return (0 if "sampler" in low else 1, 0 if low.endswith(".adv") else 1, _file_size(p))

    for i, p in enumerate(sorted(files, key=priority)):
        if i >= limit:
            break
        if _file_size(p) > _MAX_CANDIDATE_BYTES:
            continue
        data = read_live_xml(p)
        if data is None or b"<MultiSampler" not in data or b"<MultiSamplePart" not in data:
            continue
        try:
            return template_from_xml(data, str(p), kind)
        except TemplateError:
            continue
    return None


def find_template(user_library: Path | None, resources_dirs: Iterable[Path] = (), explicit=None) -> Template | None:
    """Look for a Sampler template; priority: --template, 'AbletonHelper Template' saved by the user,
    Live's Core Library, any other Sampler preset in the User Library."""
    if explicit:
        return load_template_file(explicit, "explicit")
    if user_library is not None:
        sampler_dir = Path(user_library) / "Presets" / "Instruments" / "Sampler"
        for ext in (".adv", ".adg"):
            for cand in (sampler_dir / (TEMPLATE_PRESET_NAME + ext), Path(user_library) / (TEMPLATE_PRESET_NAME + ext)):
                if cand.is_file():
                    try:
                        return load_template_file(cand, "user")
                    except TemplateError:
                        pass
    for res in resources_dirs:
        core = Path(res) / "Core Library"
        if core.is_dir():
            found = _scan_for_template(_iter_live_files(core), "core")
            if found:
                return found
    if user_library is not None:
        sampler_dir = Path(user_library) / "Presets" / "Instruments" / "Sampler"
        if sampler_dir.is_dir():
            files = [p for p in _iter_live_files(sampler_dir) if "AbletonHelper" not in p.parts]
            found = _scan_for_template(files, "user-sampler", limit=300)
            if found:
                return found
    return None


# --------------------------------------------------------------------------- XML helpers
def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value == int(value) and abs(value) < 1e12 else format(value, ".10g")
    return str(value)


def _child(parent: ET.Element, name: str) -> ET.Element:
    el = parent.find(name)
    if el is None:
        el = ET.SubElement(parent, name)
    return el


def set_value(parent: ET.Element, path: str, value, create: bool = True) -> bool:
    """Set the `Value` attribute of the element at `path` ('A/B/C'); creates it if allowed."""
    el = parent
    for seg in path.split("/"):
        nxt = el.find(seg)
        if nxt is None:
            if not create:
                return False
            nxt = ET.SubElement(el, seg)
        el = nxt
    el.set("Value", _fmt(value))
    return True


def _set_flag(parent: ET.Element, path: str, on: bool) -> None:
    """Switch an existing on/off parameter, keeping the number style (0/1 or false/true) of the template."""
    el = parent.find(path)
    if el is None:
        return
    old = el.get("Value", "")
    el.set("Value", ("1" if on else "0") if old in ("0", "1") else ("true" if on else "false"))


def _clear(parent: ET.Element, path: str) -> None:
    el = parent.find(path)
    if el is not None:
        for ch in list(el):
            el.remove(ch)


# --------------------------------------------------------------------------- zones
@dataclass
class PartSpec:
    name: str
    lokey: int
    hikey: int
    lovel: int
    hivel: int
    root: int
    detune: float
    sample_start: int
    sample_end: int
    loop_mode: int                  # 0 none, 1 forward
    loop_start: int
    loop_end: int
    loop_crossfade: int
    volume: float                   # linear gain, 0..1
    pan: float                      # -1..1
    rel_path: str                   # relative to the User Library, '/' separators
    abs_path: str
    file_size: int
    mtime: int
    frames: int
    sample_rate: int
    warnings: list[str] = field(default_factory=list)

    @property
    def looped(self) -> bool:
        return self.loop_mode != 0


def region_to_part(region: Region, info: AudioInfo, abs_path: Path, rel_path: str) -> PartSpec:
    warnings: list[str] = []
    frames = info.frames
    end = region.end if region.end and region.end <= frames else frames
    start = region.offset if 0 <= region.offset < end else 0
    mode = region.loop_mode
    ls, le = region.loop_start, region.loop_end
    wanted = mode in ("loop_continuous", "loop_sustain")
    if mode not in ("no_loop", "one_shot") and (ls is None or le is None) and info.loops:
        ls, le = info.loops[0]                    # loop points stored inside the WAV
        wanted = True
    elif mode == "" and ls is not None and le is not None:
        wanted = True
    loop_mode = 0
    loop_start = loop_end = 0
    if wanted:
        if ls is None or le is None:
            warnings.append("%s: нужен цикл, но границы не заданы — играет без цикла" % abs_path.name)
        else:
            le = min(le, frames)
            if 0 <= ls < le:
                loop_mode, loop_start, loop_end = 1, ls, le
            else:
                warnings.append("%s: некорректный цикл %s..%s — играет без цикла" % (abs_path.name, ls, le))
    xfade = 0
    if loop_mode and region.loop_crossfade > 0:
        xfade = max(0, min(int(region.loop_crossfade * info.sample_rate), (loop_end - loop_start) // 2))
    gain = min(1.0, 10.0 ** (region.volume_db / 20.0)) if region.volume_db else 1.0
    try:
        mtime = int(abs_path.stat().st_mtime)
    except OSError:
        mtime = 0
    return PartSpec(
        name=abs_path.stem, lokey=region.lokey, hikey=region.hikey,
        lovel=max(1, region.lovel), hivel=max(1, region.hivel), root=region.root, detune=region.detune,
        sample_start=start, sample_end=end, loop_mode=loop_mode, loop_start=loop_start, loop_end=loop_end,
        loop_crossfade=xfade, volume=round(gain, 6), pan=max(-1.0, min(1.0, region.pan / 100.0)),
        rel_path=rel_path, abs_path=str(abs_path), file_size=info.size_bytes, mtime=mtime,
        frames=frames, sample_rate=info.sample_rate, warnings=warnings)


def _fill_part(part: ET.Element, index: int, spec: PartSpec) -> None:
    part.set("Id", str(index))
    set_value(part, "Name", Path(spec.abs_path).name or spec.name)   # Live stores the file name with extension
    set_value(part, "Selection", index == 0)
    set_value(part, "IsActive", True)
    set_value(part, "Solo", False)
    for tag, lo, hi in (("KeyRange", spec.lokey, spec.hikey), ("VelocityRange", spec.lovel, spec.hivel),
                        ("SelectorRange", 0, 127)):
        set_value(part, tag + "/Min", lo)
        set_value(part, tag + "/Max", hi)
        set_value(part, tag + "/CrossfadeMin", lo)
        set_value(part, tag + "/CrossfadeMax", hi)
    set_value(part, "RootKey", spec.root)
    set_value(part, "Detune", spec.detune)
    set_value(part, "TuneScale", 100)
    set_value(part, "Panorama", spec.pan)
    set_value(part, "Volume", spec.volume)
    set_value(part, "Link", False)
    set_value(part, "SampleStart", spec.sample_start)
    set_value(part, "SampleEnd", spec.sample_end)
    set_value(part, "SustainLoop/Start", spec.loop_start)
    set_value(part, "SustainLoop/End", spec.loop_end if spec.loop_mode else spec.sample_end)
    set_value(part, "SustainLoop/Mode", spec.loop_mode)
    set_value(part, "SustainLoop/Crossfade", spec.loop_crossfade)
    set_value(part, "SustainLoop/Detune", 0)
    set_value(part, "ReleaseLoop/Start", 0)
    set_value(part, "ReleaseLoop/End", spec.sample_end)
    set_value(part, "ReleaseLoop/Mode", 3)
    set_value(part, "ReleaseLoop/Crossfade", 0)
    set_value(part, "ReleaseLoop/Detune", 0)
    ref = _child(part, "SampleRef")
    fr = _child(ref, "FileRef")
    set_value(fr, "RelativePathType", 6)
    set_value(fr, "RelativePath", spec.rel_path)
    set_value(fr, "Path", spec.abs_path.replace("\\", "/"))           # Live writes forward slashes, also on Windows
    set_value(fr, "Type", 1)
    set_value(fr, "LivePackName", "")
    set_value(fr, "LivePackId", "")
    set_value(fr, "OriginalFileSize", spec.file_size)
    if fr.find("OriginalCrc") is not None:
        set_value(fr, "OriginalCrc", 0)
    set_value(ref, "LastModDate", spec.mtime)
    _clear(ref, "SourceContext")
    set_value(ref, "SampleUsageHint", 0)
    set_value(ref, "DefaultDuration", spec.frames)
    set_value(ref, "DefaultSampleRate", spec.sample_rate)
    # neutral slicing / warping: no analysis data carried over from the template's sample
    warp = _child(part, "SampleWarpProperties")
    _clear(warp, "WarpMarkers")
    set_value(warp, "WarpMode", 0)
    set_value(warp, "IsWarped", False)
    _clear(warp, "Onsets/UserOnsets")
    set_value(warp, "Onsets/HasUserOnsets", False)
    slice_points = part.find("SlicePoints")
    if slice_points is not None:
        for ch in list(slice_points):
            slice_points.remove(ch)
        ET.SubElement(slice_points, "SlicePoint", {"TimeInSeconds": "0", "Rank": "0", "NormalizedEnergy": "1"})
    for tag in ("ManualSlicePoints", "BeatSlicePoints", "RegionSlicePoints"):
        _clear(part, tag)


# --------------------------------------------------------------------------- device settings
_SWITCHES_OFF = ("Filter/IsOn/Manual", "Shaper/IsOn/Manual", "Lfo/IsOn/Manual", "AuxEnv/IsOn/Manual",
                 "AuxLfos.0/IsOn/Manual", "AuxLfos.1/IsOn/Manual", "Pitch/Envelope/IsOn/Manual",
                 "Player/SubOsc/IsOn/Manual", "Player/Reverse/Manual")
_NEUTRAL_NUMBERS = (
    ("Pitch/TransposeKey/Manual", 0), ("Pitch/TransposeFine/Manual", 0), ("Pitch/PitchLfoAmount/Manual", 0),
    ("VolumeAndPan/VolumeLfoAmount/Manual", 0), ("VolumeAndPan/VolumeKeyScale/Manual", 0),
    ("VolumeAndPan/Panorama/Manual", 0), ("VolumeAndPan/PanoramaKeyScale/Manual", 0),
    ("VolumeAndPan/PanoramaRnd/Manual", 0), ("VolumeAndPan/PanoramaLfoAmount/Manual", 0),
    ("Globals/SpreadAmount/Manual", 0), ("Globals/KeyZoneShift/Manual", 0),
    ("Player/LoopModulators/SampleStart/Manual", 0), ("Player/LoopModulators/SampleLength/Manual", 1),
    ("Player/LoopModulators/LoopLength/Manual", 1), ("Player/LoopModulators/LoopFade/Manual", 0),
    ("Player/SampleSelector/Manual", 0),
)
_MOD_GROUPS = ("KeyDst", "VelDst", "RelVelDst")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def apply_device_settings(dev: ET.Element, envelope: dict | None) -> None:
    """Neutralise settings the source preset may carry and set the amp envelope from SFZ `ampeg_*`."""
    for path in _SWITCHES_OFF:
        _set_flag(dev, path, False)
    for path, value in _NEUTRAL_NUMBERS:
        if dev.find(path) is not None:
            set_value(dev, path, value, create=False)
    for group in _MOD_GROUPS:
        for amount in dev.findall(group + "/*/Amount"):
            amount.set("Value", "0")
    if envelope is None:
        return
    env = "VolumeAndPan/Envelope/"
    attack = envelope.get("ampeg_attack", 0.0)
    decay = envelope.get("ampeg_decay", 0.0)
    sustain = envelope.get("ampeg_sustain", 100.0)
    release = envelope.get("ampeg_release", 0.0)
    values = (
        ("AttackTime", _clamp(attack * 1000.0, 0.1, 20000.0)),
        ("AttackLevel", MIN_LEVEL),
        ("DecayTime", _clamp(decay * 1000.0, 1.0, 60000.0)),
        ("DecayLevel", 1.0),
        ("SustainLevel", _clamp(sustain / 100.0, MIN_LEVEL, 1.0)),
        ("ReleaseTime", _clamp(release * 1000.0, 1.0, 60000.0)),
        ("ReleaseLevel", MIN_LEVEL),
        ("LoopMode", 0),
    )
    for name, value in values:
        if dev.find(env + name) is not None:
            set_value(dev, env + name + "/Manual", value, create=False)
    if "amp_veltrack" in envelope and dev.find("VolumeAndPan/VolumeVelScale/Manual") is not None:
        set_value(dev, "VolumeAndPan/VolumeVelScale/Manual", _clamp(envelope["amp_veltrack"] / 100.0, 0.0, 1.0),
                  create=False)


# --------------------------------------------------------------------------- the preset
def build_preset_xml(template: Template, parts: list[PartSpec], name: str, envelope: dict | None = None) -> str:
    if not parts:
        raise TemplateError("нет ни одной зоны сэмплов — пресет получился бы пустым")
    root = ET.Element("Ableton", dict(template.root_attrib))
    dev = copy.deepcopy(template.device)
    dev.attrib.pop("Id", None)          # a top-level preset device carries no Id (only devices inside racks do)
    root.append(dev)
    holder = dev.find("Player/MultiSampleMap/SampleParts")
    if holder is None:
        raise TemplateError("в шаблоне нет Player/MultiSampleMap/SampleParts (%s)" % template.source)
    for ch in list(holder):
        holder.remove(ch)
    for i, spec in enumerate(parts):
        part = copy.deepcopy(template.part)
        _fill_part(part, i, spec)
        holder.append(part)
    set_value(dev, "UserName", name)
    set_value(dev, "Annotation", "")
    _clear(dev, "LastPresetRef/Value")
    _clear(dev, "SourceContext/Value")
    _clear(dev, "Player/MultiSampleMap/SourceContext/Value")
    apply_device_settings(dev, envelope)
    ET.indent(root, space="\t")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_adv(path, xml_text: str) -> None:
    """Write gzip-compressed UTF-8 XML (what Live expects in a .adv)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(str(tmp), "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(xml_text.encode("utf-8"))
    os.replace(str(tmp), str(p))


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_name(n: int) -> str:
    """Ableton naming: MIDI 60 = C3."""
    return "%s%d" % (NOTE_NAMES[n % 12], n // 12 - 2)


def describe_parts(parts: list[PartSpec]) -> list[str]:
    """Human-readable region map, one line per zone."""
    lines = []
    for i, s in enumerate(parts):
        vel = "" if (s.lovel, s.hivel) == (1, 127) else " vel %d-%d" % (s.lovel, s.hivel)
        loop = "loop %d..%d" % (s.loop_start, s.loop_end) if s.loop_mode else "без цикла"
        lines.append("%2d  keys %3d-%-3d (%s..%s)  root %3d (%s)  detune %+6.1f ct%s  %s  [%s]" % (
            i, s.lokey, s.hikey, midi_name(s.lokey), midi_name(s.hikey), s.root, midi_name(s.root), s.detune, vel,
            loop, s.name))
    return lines

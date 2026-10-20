"""Minimal SFZ parser: just what is needed to turn an SFZ instrument into an Ableton Sampler preset.

Supported: <control> default_path, <global>/<master>/<group>/<region> inheritance, simple
``#define $NAME value``, key / lokey / hikey / pitch_keycenter (numbers and note names, SFZ convention
C4 = MIDI 60), tune / transpose (folded into root key + fine tune), lovel / hivel, offset / end,
loop_start / loop_end / loop_mode, trigger (release regions are skipped), volume, pan, ampeg_*.
Everything else is kept in ``Region.opcodes`` and otherwise ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LOOP_MODES = ("no_loop", "one_shot", "loop_continuous", "loop_sustain")
_NOTE_RE = re.compile(r"^([a-gA-G])([#bB]?)(-?\d+)$")
_NOTE_BASE = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
_HEADER_RE = re.compile(r"<(\w+)>")
_OPCODE_RE = re.compile(r"(?:(?<=\s)|^)([A-Za-z_][A-Za-z0-9_]*)=")
_DEFINE_RE = re.compile(r"^\s*#define\s+(\$\w+)\s+(.*?)\s*$", re.M)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"//.*$", re.M)
_PLAYABLE_TRIGGERS = ("attack", "first", "legato", "")


class SfzError(ValueError):
    pass


def note_to_midi(text) -> int:
    """'60', 'c4', 'F#3', 'Db5', 'c-1' -> MIDI number (SFZ convention: C4 = 60)."""
    s = str(text).strip()
    try:
        return int(s)
    except ValueError:
        pass
    m = _NOTE_RE.match(s)
    if not m:
        raise SfzError("не понимаю ноту «%s»" % s)
    letter, acc, octave = m.group(1).lower(), m.group(2), int(m.group(3))
    semitone = _NOTE_BASE[letter] + (1 if acc == "#" else -1 if acc in ("b", "B") else 0)
    return (octave + 1) * 12 + semitone


def fold_tuning(root: int, cents: float) -> tuple[int, float]:
    """Move whole semitones of `cents` into the root key, so the fine tune stays within +-50 cents.

    Playing key K with root R and tune T shifts the sample by (K - R) semitones + T cents; moving
    n semitones from T to R (R' = R - n, T' = T - 100 n) keeps the result identical.
    """
    n = int(round(cents / 100.0))
    return root - n, cents - 100.0 * n


@dataclass
class Region:
    sample: str                      # path relative to the SFZ file, '/' separators
    lokey: int = 0
    hikey: int = 127
    root: int = 60                   # pitch_keycenter after folding the tuning
    detune: float = 0.0              # cents, -50..50
    lovel: int = 0
    hivel: int = 127
    offset: int = 0
    end: int | None = None
    loop_start: int | None = None
    loop_end: int | None = None
    loop_mode: str = ""              # "" = not specified
    loop_crossfade: float = 0.0      # seconds
    volume_db: float = 0.0
    pan: float = 0.0                 # -100..100
    opcodes: dict[str, str] = field(default_factory=dict)


@dataclass
class SfzInstrument:
    regions: list[Region]
    envelope: dict[str, float]       # ampeg_attack/decay/sustain/release/..., amp_veltrack (first played region)
    skipped: list[str] = field(default_factory=list)   # human-readable reasons for ignored regions


def _num(ops: dict, key: str, default: float) -> float:
    try:
        return float(ops[key])
    except (KeyError, ValueError):
        return default


def _int(ops: dict, key: str, default: int) -> int:
    return int(round(_num(ops, key, default)))


def _parse_opcodes(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    matches = list(_OPCODE_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[m.group(1).lower()] = body[m.end():end].strip()
    return out


def _tokenize(text: str):
    """Yield (header, opcodes) for every <header> section."""
    parts = _HEADER_RE.split(text)
    for i in range(1, len(parts) - 1, 2):
        yield parts[i].lower(), _parse_opcodes(parts[i + 1])


def _clean_text(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub(" ", text)
    text = _LINE_COMMENT_RE.sub("", text)
    defines = dict(_DEFINE_RE.findall(text))
    text = _DEFINE_RE.sub("", text)
    for name in sorted(defines, key=len, reverse=True):
        text = text.replace(name, defines[name])
    return text


def parse_sfz(text: str) -> SfzInstrument:
    default_path = ""
    glob_ops: dict[str, str] = {}
    master_ops: dict[str, str] = {}
    group_ops: dict[str, str] = {}
    regions: list[Region] = []
    skipped: list[str] = []
    envelope: dict[str, float] = {}
    for header, ops in _tokenize(_clean_text(text)):
        if header == "control":
            default_path = ops.get("default_path", default_path).replace("\\", "/")
        elif header == "global":
            glob_ops, master_ops, group_ops = ops, {}, {}
        elif header == "master":
            master_ops, group_ops = ops, {}
        elif header == "group":
            group_ops = ops
        elif header == "region":
            merged = {**glob_ops, **master_ops, **group_ops, **ops}
            region = _make_region(merged, default_path, skipped)
            if region is not None:
                regions.append(region)
                if not envelope:
                    for k, v in merged.items():
                        if k.startswith("ampeg_") or k == "amp_veltrack":
                            try:
                                envelope[k] = float(v)
                            except ValueError:
                                pass
    return SfzInstrument(regions, envelope, skipped)


def _make_region(ops: dict[str, str], default_path: str, skipped: list[str]) -> Region | None:
    sample = ops.get("sample", "").strip()
    if not sample or sample.startswith("*"):
        skipped.append("регион без файла (генератор «%s»)" % sample if sample else "регион без sample=")
        return None
    sample = sample.replace("\\", "/")
    label = sample.rsplit("/", 1)[-1]
    trigger = ops.get("trigger", "").strip().lower()
    if trigger not in _PLAYABLE_TRIGGERS:
        skipped.append("%s: trigger=%s (Sampler не умеет играть по отпусканию клавиши)" % (label, trigger))
        return None
    if _num(ops, "lorand", 0.0) > 0 or _num(ops, "seq_position", 1.0) > 1:
        skipped.append("%s: round-robin вариант (берётся только первый)" % label)
        return None
    try:
        if "key" in ops:
            lokey = hikey = root = note_to_midi(ops["key"])
        else:
            lokey = note_to_midi(ops["lokey"]) if "lokey" in ops else 0
            hikey = note_to_midi(ops["hikey"]) if "hikey" in ops else 127
            root = note_to_midi(ops["pitch_keycenter"]) if "pitch_keycenter" in ops else 60
        if "pitch_keycenter" in ops and "key" in ops:
            root = note_to_midi(ops["pitch_keycenter"])
    except SfzError as exc:
        skipped.append("%s: %s" % (label, exc))
        return None
    if lokey > hikey:
        skipped.append("%s: lokey > hikey" % label)
        return None
    cents = _num(ops, "tune", 0.0) + 100.0 * _num(ops, "transpose", 0.0)
    root, detune = fold_tuning(root, cents)
    if not 0 <= root <= 127:
        skipped.append("%s: корневая нота %d вне диапазона MIDI" % (label, root))
        return None
    mode = ops.get("loop_mode", "").strip().lower()
    if mode and mode not in LOOP_MODES:
        mode = ""
    full = sample if not default_path else default_path.rstrip("/") + "/" + sample
    end = _int(ops, "end", -1)
    return Region(
        sample=full,
        lokey=max(0, lokey), hikey=min(127, hikey), root=root, detune=round(detune, 3),
        lovel=max(0, _int(ops, "lovel", 0)), hivel=min(127, _int(ops, "hivel", 127)),
        offset=max(0, _int(ops, "offset", 0)),
        end=end if end > 0 else None,
        loop_start=_int(ops, "loop_start", -1) if "loop_start" in ops else None,
        loop_end=_int(ops, "loop_end", -1) if "loop_end" in ops else None,
        loop_mode=mode,
        loop_crossfade=_num(ops, "loop_crossfade", 0.0),
        volume_db=_num(ops, "volume", 0.0),
        pan=_num(ops, "pan", 0.0),
        opcodes=dict(ops),
    )


def parse_sfz_file(path) -> SfzInstrument:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return parse_sfz(data.decode(enc))
        except UnicodeDecodeError:
            continue
    return parse_sfz(data.decode("latin-1"))

"""Demo MIDI patterns: a short, musical, in-key clip to audition a new sound.

Styles: chords, melody, bass, arp, drums, pad, single. Everything is deterministic
(no randomness) so the result is reproducible and testable. Drums use a General-MIDI-ish
Drum Rack layout: kick 36, snare 38, clap 39, closed hat 42, open hat 46.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KICK, SNARE, CLAP, CLOSED_HAT, OPEN_HAT, TOM_LOW, TOM_MID, CRASH = 36, 38, 39, 42, 46, 45, 48, 49

SCALES: dict[str, list[int]] = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
}

# Chord roots as scale degrees (0 = tonic). Triads are stacked diatonically.
PROGRESSIONS: dict[str, list[int]] = {
    "minor": [0, 5, 2, 6],            # i  VI  III VII
    "major": [0, 4, 5, 3],            # I  V   vi  IV
    "dorian": [0, 3, 6, 3],           # i  IV  bVII IV
    "phrygian": [0, 1, 0, 6],         # i  bII i   bVII
    "mixolydian": [0, 6, 3, 0],       # I  bVII IV I
    "harmonic_minor": [0, 5, 3, 4],   # i  VI  iv  V
}
WALTZ_PROGRESSION = [0, 3, 4, 0]      # i  iv  V  i (harmonic minor) / I IV V I

_STYLE_BY_CATEGORY = {
    "keys": "chords", "piano": "chords", "organ": "chords", "strings": "chords", "brass": "chords",
    "woodwind": "melody", "reed": "melody", "plucked": "melody", "guitar": "chords",
    "bass": "bass", "lead": "melody", "pad": "pad", "bell": "melody", "mallet": "melody",
    "choir": "pad", "fx": "single", "drums": "drums", "percussion": "drums", "ethnic": "melody",
    "synth": "arp",
}
_ROOT_BY_STYLE = {"chords": 60, "melody": 60, "bass": 36, "arp": 60, "drums": 36, "pad": 48, "single": 60}
_LENGTH_BY_STYLE = {"chords": 8.0, "melody": 8.0, "bass": 8.0, "arp": 8.0, "drums": 8.0, "pad": 16.0, "single": 4.0}


@dataclass
class DemoClip:
    notes: list[dict]
    length: float
    style: str


def default_style(category: str | None) -> str:
    return _STYLE_BY_CATEGORY.get(category or "", "chords")


# ------------------------------------------------------------------ helpers
def _scale_pitch(root: int, scale: list[int], degree: int) -> int:
    octave, idx = divmod(degree, 7)
    return root + 12 * octave + scale[idx]


def _note(pitch: int, start: float, duration: float, velocity: int = 96) -> dict:
    return {"pitch": int(pitch), "start": round(float(start), 4),
            "duration": round(float(duration), 4), "velocity": int(max(1, min(127, velocity)))}


def _triad(root: int, scale: list[int], degree: int, prev_mean: float) -> list[int]:
    """Diatonic triad on `degree`, inversion chosen for smooth voice-leading."""
    base = [_scale_pitch(root, scale, degree + off) for off in (0, 2, 4)]
    best, best_d = base, 1e9
    for inv in range(3):
        voiced = sorted(p + 12 if i < inv else p for i, p in enumerate(base))
        for shift in (-12, 0, 12):
            cand = [p + shift for p in voiced]
            d = abs(sum(cand) / 3.0 - prev_mean)
            if d < best_d:
                best, best_d = cand, d
    return best


def _fit_range(notes: list[dict], length: float) -> list[dict]:
    """Clamp pitches into 0..127 (octave folding), trim to the clip, sort."""
    out = []
    for n in notes:
        if n["start"] >= length - 1e-9:
            continue
        p = n["pitch"]
        while p > 127:
            p -= 12
        while p < 0:
            p += 12
        dur = min(n["duration"], length - n["start"])
        if dur <= 0:
            continue
        out.append({**n, "pitch": p, "duration": round(dur, 4)})
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    return out


# ------------------------------------------------------------------ generators
def _chords(root: int, scale_name: str, length: float, variant: str) -> list[dict]:
    scale = SCALES[scale_name]
    notes: list[dict] = []
    prev_mean = root + 4.0
    if variant == "waltz":
        progression = WALTZ_PROGRESSION
        bars = int(math.ceil(length / 3.0))
        for b in range(bars):
            deg = progression[b % len(progression)]
            chord = _triad(root, scale, deg, prev_mean)
            prev_mean = sum(chord) / 3.0
            t = b * 3.0
            notes.append(_note(_scale_pitch(root, scale, deg) - 12, t, 0.9, 100))  # "oom"
            for beat in (1.0, 2.0):                                                 # "pah pah"
                for i, p in enumerate(chord):
                    notes.append(_note(p, t + beat, 0.85, 82 - 4 * i))
        return _fit_range(notes, length)

    progression = PROGRESSIONS[scale_name]
    chord_len = 2.0 if length <= 8 else 4.0
    count = int(math.ceil(length / chord_len))
    for c in range(count):
        deg = progression[c % len(progression)]
        chord = _triad(root, scale, deg, prev_mean)
        prev_mean = sum(chord) / 3.0
        for i, p in enumerate(chord):
            notes.append(_note(p, c * chord_len, chord_len * 0.94, 96 - 6 * i))
        notes.append(_note(_scale_pitch(root, scale, deg) - 12, c * chord_len, chord_len * 0.94, 84))
    return _fit_range(notes, length)


_MOTIF_44 = [(0, 0, 1), (2, 1, 0.5), (4, 1.5, 0.5), (5, 2, 1), (4, 3, 0.5), (2, 3.5, 0.5),
             (3, 4, 1), (2, 5, 0.5), (1, 5.5, 0.5), (0, 6, 2)]
_MOTIF_34 = [(4, 0, 1.5), (2, 1.5, 0.5), (4, 2, 1), (5, 3, 1.5), (4, 4.5, 0.5), (2, 5, 1),
             (3, 6, 1.5), (2, 7.5, 0.5), (1, 8, 1), (2, 9, 1), (0, 10, 2)]


def _melody(root: int, scale_name: str, length: float, variant: str) -> list[dict]:
    scale = SCALES[scale_name]
    motif, period = (_MOTIF_34, 12.0) if variant == "waltz" else (_MOTIF_44, 8.0)
    notes = []
    reps = int(math.ceil(length / period))
    for r in range(reps):
        for k, (deg, start, dur) in enumerate(motif):
            vel = 100 if start == int(start) else 88
            notes.append(_note(_scale_pitch(root, scale, deg), r * period + start, dur * 0.92, vel))
    return _fit_range(notes, length)


def _bass(root: int, scale_name: str, length: float, variant: str) -> list[dict]:
    scale = SCALES[scale_name]
    if variant == "trap":
        pattern = [(0, 0, 1.5), (1.75, 0, 0.25), (2.5, 0, 1.0), (3.75, 7, 0.25)]
    elif variant == "four_on_floor":  # offbeat techno/house bass
        pattern = [(0.5, 0, 0.4), (1.5, 0, 0.4), (2.5, 0, 0.4), (3.5, 0, 0.4)]
    else:
        pattern = [(0, 0, 0.75), (1, 0, 0.5), (2, 0, 0.75), (3, 7, 0.5), (3.5, 5, 0.5)]
    progression = PROGRESSIONS[scale_name]
    notes = []
    bars = int(math.ceil(length / 4.0))
    for b in range(bars):
        deg = progression[b % len(progression)]
        r = _scale_pitch(root, scale, deg)
        for beat, interval, dur in pattern:
            notes.append(_note(r + interval, b * 4.0 + beat, dur * 0.95, 112 if beat == 0 else 96))
    return _fit_range(notes, length)


def _arp(root: int, scale_name: str, length: float, variant: str) -> list[dict]:
    scale = SCALES[scale_name]
    progression = PROGRESSIONS[scale_name]
    chord_len = 2.0
    notes = []
    prev_mean = root + 4.0
    order = [0, 1, 2, 3, 2, 1, 2, 1]
    for c in range(int(math.ceil(length / chord_len))):
        deg = progression[c % len(progression)]
        chord = _triad(root, scale, deg, prev_mean)
        prev_mean = sum(chord) / 3.0
        tones = chord + [chord[0] + 12]
        for i, idx in enumerate(order):
            notes.append(_note(tones[idx], c * chord_len + i * 0.25, 0.22, 100 if i % 4 == 0 else 80))
    return _fit_range(notes, length)


def _drums(length: float, variant: str) -> list[dict]:
    notes: list[dict] = []
    bars = int(math.ceil(length / 4.0))

    def add(pitch: int, t: float, vel: int, dur: float = 0.25) -> None:
        notes.append(_note(pitch, t, dur, vel))

    for b in range(bars):
        t0 = b * 4.0
        last = b % 2 == 1
        if variant == "four_on_floor":
            for beat in range(4):
                add(KICK, t0 + beat, 118)
            for beat in (1, 3):
                add(CLAP, t0 + beat, 104)
            for i in range(16):
                if i % 4 == 2:                       # off-beat open hat
                    add(OPEN_HAT, t0 + i * 0.25, 84, 0.25)
                elif i % 2 == 1:                     # quiet 16th ticks
                    add(CLOSED_HAT, t0 + i * 0.25, 60 + 8 * (i % 4 == 3), 0.1)
        elif variant == "trap":
            add(KICK, t0, 120)
            add(KICK, t0 + 1.75, 104)
            add(KICK, t0 + 2.5, 112)
            add(SNARE, t0 + 2.0, 112)
            add(CLAP, t0 + 2.0, 100)
            for i in range(8):
                add(CLOSED_HAT, t0 + i * 0.5, 84 if i % 2 == 0 else 62, 0.1)
            if last:
                for k in range(4):                      # hat roll into the next bar
                    add(CLOSED_HAT, t0 + 3.0 + k * 0.25, 70 + 8 * k, 0.1)
                add(OPEN_HAT, t0 + 3.5, 90)
        elif variant in ("boom_bap", "lofi"):
            swing = 0.09 if variant == "lofi" else 0.0
            soft = 0.8 if variant == "lofi" else 1.0
            add(KICK, t0, int(118 * soft))
            add(KICK, t0 + 1.5 + (0.0 if not last else 0.25), int(100 * soft))
            add(KICK, t0 + 2.5, int(108 * soft))
            for beat in (1, 3):
                add(SNARE, t0 + beat + swing * 0.5, int(112 * soft))
            if variant == "lofi":
                add(SNARE, t0 + 3.75, 38)               # ghost note
            for i in range(8):
                off = swing if i % 2 == 1 else 0.0
                add(CLOSED_HAT, t0 + i * 0.5 + off, int((88 if i % 2 == 0 else 62) * soft), 0.1)
            if last:
                add(OPEN_HAT, t0 + 3.5 + swing, int(80 * soft))
        else:  # default / rock
            add(KICK, t0, 118)
            add(KICK, t0 + 2.0, 108)
            if last:
                add(KICK, t0 + 2.5, 100)
                add(KICK, t0 + 3.5, 92)
            else:
                add(KICK, t0 + 0.5 + 2.0, 90)
            for beat in (1, 3):
                add(SNARE, t0 + beat, 112)
            for i in range(8):
                add(CLOSED_HAT, t0 + i * 0.5, 90 if i % 2 == 0 else 66, 0.1)
            if last:
                add(OPEN_HAT, t0 + 3.5, 84)
    return _fit_range(notes, length)


def _pad(root: int, scale_name: str, length: float, variant: str) -> list[dict]:
    scale = SCALES[scale_name]
    progression = PROGRESSIONS[scale_name]
    chord_len = length / 2.0 if length >= 8 else length
    count = int(round(length / chord_len))
    notes = []
    prev_mean = root + 6.0
    for c in range(count):
        deg = progression[c % len(progression)]
        chord = _triad(root + 12, scale, deg, prev_mean)
        prev_mean = sum(chord) / 3.0
        pitches = [_scale_pitch(root, scale, deg)] + chord
        for i, p in enumerate(pitches):
            notes.append(_note(p, c * chord_len, chord_len * 0.98, 78 - 4 * i))
    return _fit_range(notes, length)


def _single(root: int, length: float) -> list[dict]:
    return _fit_range([_note(root, 0.0, length * 0.9, 100)], length)


def generate_notes(style: str, root: int | None = None, length: float | None = None,
                   scale: str = "minor", variant: str = "default") -> list[dict]:
    """Generate demo notes for a style. Unknown values fall back to safe defaults."""
    if style not in _ROOT_BY_STYLE:
        style = "chords"
    root = _ROOT_BY_STYLE[style] if root is None else int(root)
    length = _LENGTH_BY_STYLE[style] if length is None else float(length)
    if scale not in SCALES:
        scale = "minor"
    if variant == "waltz":
        length = max(3.0, length)
    if style == "chords":
        return _chords(root, scale, length, variant)
    if style == "melody":
        return _melody(root, scale, length, variant)
    if style == "bass":
        return _bass(root, scale, length, variant)
    if style == "arp":
        return _arp(root, scale, length, variant)
    if style == "drums":
        return _drums(length, variant)
    if style == "pad":
        return _pad(root, scale, length, variant)
    return _single(root, length)


def build_demo(recipe: dict | None, style: str | None = None) -> DemoClip:
    """Demo clip for a recipe (explicit `demo.notes` win over `demo.style`)."""
    recipe = recipe or {}
    demo = recipe.get("demo") or {}
    st = style or demo.get("style") or default_style(recipe.get("category"))
    length = demo.get("length")
    explicit = demo.get("notes")
    if explicit:
        notes = [_note(n["pitch"], n["start"], n["duration"], n.get("velocity", 100)) for n in explicit]
        if length is None:
            end = max(n["start"] + n["duration"] for n in notes)
            length = float(math.ceil(end / 4.0) * 4.0)
        return DemoClip(_fit_range(notes, float(length)), float(length), st)
    length = float(length) if length is not None else _LENGTH_BY_STYLE.get(st, 8.0)
    if demo.get("variant") == "waltz":
        length = max(3.0, length)
    notes = generate_notes(st, demo.get("root"), length, demo.get("scale", "minor"),
                           demo.get("variant", "default"))
    return DemoClip(notes, length, st)

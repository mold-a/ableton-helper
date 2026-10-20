"""Deterministic "macro tweaks" of an existing sound: adjust_sound("brighter" / "ярче" / "more reverb" ...).

Why: free-form parameter editing by the model proved unreliable ("make it brighter" -> wrong or no
parameters). Here an adjective is mapped to *roles* (cutoff, attack, wet ...), roles to the exact
parameter names of every device on the track (data/device_roles.json), and the new value is computed in
DISPLAY space (what Live shows: Hz, ms, dB, %), parsed/formatted with bridge.displayval and written with
``{"display": "5.4 kHz"}``. Parameters whose display is not usable fall back to relative {"norm"} steps
(or to the next item for dropdowns).
"""

from __future__ import annotations

import itertools
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..bridge.base import BridgeCommandError
from ..bridge.displayval import DisplayError, format_display, parse_display
from ..knowledge.search import stem
from .roles import DeviceRoles, RoleBook, load_roles

log = logging.getLogger(__name__)

AMOUNTS = ("small", "medium", "large")
LOAD_TIMEOUT = 30.0
MAX_CHANGES_IN_RESULT = 40
NORM_STEPS = (0.06, 0.12, 0.2)  # relative {"norm"} fallback, by amount


# --------------------------------------------------------------------------- operations
def _mul(role, factors, *, devices=None, bounds=None, min_step=None, kinds=None, wake=False):
    return {"kind": "mul", "role": role, "factors": tuple(factors), "devices": devices, "bounds": bounds or {},
            "min_step": min_step or {}, "kinds": kinds, "wake": wake}


def _add(role, deltas, *, devices=None, bounds=None, kinds=None, wake=False, norm=None):
    """deltas: {dimension: (small, medium, large)}; dimension = what the parameter displays (percent/level/...)."""
    return {"kind": "add", "role": role, "deltas": {k: tuple(v) for k, v in deltas.items()}, "devices": devices,
            "bounds": bounds or {}, "kinds": kinds, "wake": wake, "norm": norm}


def _enable(role, *, kinds=None):
    return {"kind": "enable", "role": role, "devices": None, "kinds": kinds}


def _neg(t):
    return tuple(-x for x in t)


_PCT = (8, 15, 25)
_DB = (1.5, 3.0, 6.0)
_WET = (8, 15, 25)
_WIDTH = (15, 30, 50)
_FREQ = {"freq": (40.0, 18000.0)}
_TIME_ATTACK = {"time": (0.0, 5000.0)}

# request name -> definition: ops, optional autoload, Russian title
REQUESTS: dict[str, dict[str, Any]] = {
    "brighter": {"ru": "ярче", "ops": [
        _mul("cutoff", (1.35, 1.8, 2.6), bounds=_FREQ),
        _add("tone", {"percent": _PCT}, bounds={"percent": (0, 100)}),
    ]},
    "darker": {"ru": "темнее", "ops": [
        _mul("cutoff", (0.75, 0.55, 0.35), bounds=_FREQ),
        _add("tone", {"percent": _neg(_PCT)}, bounds={"percent": (0, 100)}),
    ]},
    "warmer": {"ru": "теплее", "ops": [
        _mul("cutoff", (0.9, 0.75, 0.6), bounds=_FREQ),
        _add("drive", {"level": (1.5, 3.0, 5.0)}, devices=["Saturator"], bounds={"level": (-36, 36)}),
        _add("warmth", {"percent": (10, 20, 30)}, bounds={"percent": (0, 100)}),
    ]},
    "harsher": {"ru": "жёстче", "ops": [
        _mul("cutoff", (1.2, 1.5, 2.0), bounds=_FREQ),
        _add("resonance", {"percent": (6, 12, 20)}, bounds={"percent": (0, 90)}),
        _add("drive", {"level": (1.0, 3.0, 6.0), "percent": (6, 12, 20)}, bounds={"level": (-36, 36), "percent": (0, 100)}),
    ]},
    "softer": {"ru": "мягче", "ops": [
        _mul("cutoff", (0.85, 0.7, 0.5), bounds=_FREQ),
        _add("resonance", {"percent": (-5, -10, -20)}, bounds={"percent": (0, 90)}),
        _add("drive", {"level": (-1.0, -3.0, -6.0), "percent": (-6, -12, -20)}, bounds={"level": (0, 36), "percent": (0, 100)}),
    ]},
    "softer_attack": {"ru": "мягче атака", "ops": [
        _mul("attack", (2.0, 2.5, 4.0), bounds=_TIME_ATTACK, min_step={"time": (3.0, 8.0, 20.0)}),
    ]},
    "punchier": {"ru": "резче атака, больше панча", "ops": [
        _mul("attack", (0.6, 0.4, 0.2), bounds={"time": (0.1, 5000.0)}),
        _mul("decay", (0.85, 0.7, 0.5), bounds={"time": (5.0, 20000.0)}),
        _add("filter_env_amount", {"percent": (8, 15, 25)}, bounds={"percent": (-100, 100)}),
        _add("transients", {"percent": (15, 25, 40)}, bounds={"percent": (-100, 100)}),
    ]},
    "longer_release": {"ru": "дольше релиз", "ops": [
        _mul("release", (1.6, 2.5, 4.0), bounds={"time": (0.0, 20000.0)}, min_step={"time": (40.0, 100.0, 300.0)}),
    ]},
    "shorter_release": {"ru": "короче релиз", "ops": [
        _mul("release", (0.7, 0.5, 0.3), bounds={"time": (5.0, 20000.0)}),
    ]},
    "more_reverb": {"ru": "больше реверба", "ops": [
        _add("wet", {"percent": _WET}, devices=["Reverb"], bounds={"percent": (0, 100)}, wake=True),
    ], "autoload": {"device": "Reverb", "unless": ["Reverb"], "init": {"Dry/Wet": ("15 %", "25 %", "40 %")}}},
    "less_reverb": {"ru": "меньше реверба", "ops": [
        _add("wet", {"percent": _neg(_WET)}, devices=["Reverb"], bounds={"percent": (0, 100)}),
    ]},
    "longer_tail": {"ru": "длиннее хвост", "ops": [
        _mul("decay_time", (1.4, 2.0, 3.0), devices=["Reverb"], bounds={"time": (200.0, 30000.0)}),
        _mul("release", (1.4, 1.8, 2.5), bounds={"time": (0.0, 20000.0)}, min_step={"time": (30.0, 80.0, 200.0)}),
    ]},
    "shorter_tail": {"ru": "короче хвост", "ops": [
        _mul("decay_time", (0.75, 0.5, 0.3), devices=["Reverb"], bounds={"time": (200.0, 30000.0)}),
        _mul("release", (0.75, 0.55, 0.35), bounds={"time": (5.0, 20000.0)}),
    ]},
    "more_delay": {"ru": "больше эха", "ops": [
        _add("wet", {"percent": _WET}, devices=["Delay"], bounds={"percent": (0, 100)}, wake=True),
    ], "autoload": {"device": "Delay", "unless": ["Delay"], "init": {"Dry/Wet": ("15 %", "25 %", "40 %")}}},
    "less_delay": {"ru": "меньше эха", "ops": [
        _add("wet", {"percent": _neg(_WET)}, devices=["Delay"], bounds={"percent": (0, 100)}),
    ]},
    "more_chorus": {"ru": "больше хоруса", "ops": [
        _add("wet", {"percent": (10, 20, 30)}, devices=["Chorus-Ensemble"], bounds={"percent": (0, 100)}, wake=True),
    ], "autoload": {"device": "Chorus-Ensemble", "unless": ["Chorus-Ensemble"],
                    "init": {"Dry/Wet": ("25 %", "40 %", "60 %")}}},
    "less_chorus": {"ru": "меньше хоруса", "ops": [
        _add("wet", {"percent": (-10, -20, -30)}, devices=["Chorus-Ensemble"], bounds={"percent": (0, 100)}),
    ]},
    "wider": {"ru": "шире", "ops": [
        _add("width", {"percent": _WIDTH}, bounds={"percent": (0, 200)}, wake=True),
    ], "autoload": {"device": "Utility", "unless": ["Utility"], "if_untouched": True,
                 "init": {"Stereo Width": ("130 %", "150 %", "180 %")}}},
    "narrower": {"ru": "уже", "ops": [
        _add("width", {"percent": _neg(_WIDTH)}, bounds={"percent": (0, 200)}),
    ]},
    "more_drive": {"ru": "больше драйва", "ops": [
        _add("drive", {"level": _DB, "percent": _PCT}, bounds={"level": (-36, 36), "percent": (0, 100)}, wake=True),
    ], "autoload": {"device": "Saturator", "unless": ["Saturator", "Overdrive", "Drum Buss"],
                    "init": {"Drive": ("3 dB", "6 dB", "10 dB")}}},
    "cleaner": {"ru": "чище", "ops": [
        _add("drive", {"level": _neg(_DB), "percent": _neg(_PCT)}, bounds={"level": (0, 36), "percent": (0, 100)}),
    ]},
    "more_resonance": {"ru": "больше резонанса", "ops": [
        _add("resonance", {"percent": _PCT}, bounds={"percent": (0, 90)}),
    ]},
    "less_resonance": {"ru": "меньше резонанса", "ops": [
        _add("resonance", {"percent": _neg(_PCT)}, bounds={"percent": (0, 90)}),
    ]},
    "louder": {"ru": "громче", "ops": [
        _add(["volume", "output_gain"], {"level": _DB}, bounds={"level": (-60, 6)}),
    ]},
    "quieter": {"ru": "тише", "ops": [
        _add(["volume", "output_gain"], {"level": _neg(_DB)}, bounds={"level": (-60, 6)}),
    ]},
    "more_vibrato": {"ru": "больше вибрато", "ops": [
        _enable("vibrato_enable"),
        _add("vibrato_amount", {"percent": (10, 20, 35)}, bounds={"percent": (0, 100)}),
    ]},
    "less_vibrato": {"ru": "меньше вибрато", "ops": [
        _add("vibrato_amount", {"percent": (-10, -20, -35)}, bounds={"percent": (0, 100)}),
    ]},
    "fatter": {"ru": "жирнее", "ops": [
        _enable("unison_enable"),
        _enable("sub_enable"),
        _add("unison", {"percent": (10, 20, 35)}, bounds={"percent": (0, 100)}),
        _add("detune", {"percent": (10, 20, 35)}, bounds={"percent": (0, 100)}),
        _add("sub_level", {"percent": (8, 15, 25)}, bounds={"percent": (0, 100)}),
    ]},
    "thinner": {"ru": "тоньше", "ops": [
        _add("unison", {"percent": (-10, -20, -35)}, bounds={"percent": (0, 100)}),
        _add("detune", {"percent": (-10, -20, -35)}, bounds={"percent": (0, 100)}),
        _add("sub_level", {"percent": (-8, -15, -25)}, bounds={"percent": (0, 100)}),
    ]},
}

# --------------------------------------------------------------------------- vocabulary (RU / EN)
_MORE = ["больше", "побольше", "добавь", "добавить", "добавим", "еще", "ещё", "усиль", "усилить", "увеличь",
         "увеличить", "повысь", "поднимай", "more", "add", "increase", "boost", "extra"]
_LESS = ["меньше", "поменьше", "менее", "убери", "убрать", "убавь", "убавить", "уменьши", "уменьшить", "снизь",
         "less", "reduce", "remove", "decrease", "lower", "fewer"]

_NOUNS = {
    "reverb": ["реверб", "реверба", "реверберация", "реверберации", "ревер", "reverb", "reverberation"],
    "space": ["пространства", "пространство", "space", "room", "простора"],
    "delay": ["эхо", "эха", "эху", "дилей", "делей", "дилея", "делея", "delay", "echo"],
    "chorus": ["хорус", "хоруса", "chorus"],
    "drive": ["драйв", "драйва", "дисторшн", "искажения", "искажений", "перегруз", "перегруза", "овердрайв",
              "сатурации", "сатурация", "drive", "distortion", "overdrive", "saturation", "grit", "crunch"],
    "resonance": ["резонанс", "резонанса", "resonance", "reso"],
    "vibrato": ["вибрато", "vibrato"],
    "volume": ["громкость", "громкости", "уровень", "уровня", "volume", "level", "gain"],
    "width": ["стерео", "ширина", "ширины", "stereo", "width"],
    "release": ["релиз", "релиза", "release", "затухание", "затухания"],
    "tail": ["хвост", "хвоста", "tail"],
    "bright": ["яркости", "яркость", "brightness", "верхов", "верха", "высоких", "highs", "treble", "срез", "cutoff"],
    "warmth": ["тепла", "тепло", "теплоты", "warmth"],
    "fat": ["унисон", "унисона", "unison", "жирности", "толщины"],
}

# (more-request, less-request) per noun group
_PAIRS = {
    "reverb": ("more_reverb", "less_reverb"), "space": ("more_reverb", "less_reverb"),
    "delay": ("more_delay", "less_delay"), "chorus": ("more_chorus", "less_chorus"),
    "drive": ("more_drive", "cleaner"), "resonance": ("more_resonance", "less_resonance"),
    "vibrato": ("more_vibrato", "less_vibrato"), "volume": ("louder", "quieter"),
    "width": ("wider", "narrower"), "release": ("longer_release", "shorter_release"),
    "tail": ("longer_tail", "shorter_tail"), "bright": ("brighter", "darker"),
    "warmth": ("warmer", None), "fat": ("fatter", "thinner"),
}

_DIRECT: dict[str, list[str]] = {
    "brighter": ["ярче", "ярко", "яркий", "яркая", "яркое", "яркость", "светлее", "звонче", "блестящее", "brighter",
                 "bright", "brightness", "brighten", "airy", "открой фильтр", "открыть фильтр", "open filter",
                 "open the filter", "больше верхов", "больше верха", "more highs", "more treble", "sparkle"],
    "darker": ["темнее", "темный", "тёмный", "тусклее", "глуше", "приглуши", "приглушить", "приглушённее", "darker",
               "dark", "dull", "duller", "muffled", "закрой фильтр", "закрыть фильтр", "close filter",
               "close the filter", "меньше верхов", "less highs", "less treble", "менее яркий", "less bright",
               "less brightness", "убери верха"],
    "warmer": ["теплее", "теплый", "тёплый", "тепло", "теплота", "ламповее", "warmer", "warm", "warmth"],
    "harsher": ["жестче", "жёстче", "грубее", "резче", "агрессивнее", "агрессивный", "злее", "острее", "harsher",
                "harsh", "aggressive", "grittier", "gritty", "edgy", "edgier", "rougher"],
    "softer": ["мягче", "помягче", "мягкий", "нежнее", "смягчи", "смягчить", "полегче", "softer", "soft", "smoother",
               "smooth", "gentler", "gentle", "less harsh", "менее резкий"],
    "punchier": ["панч", "панчевее", "пробивной", "пробивнее", "ударнее", "собраннее", "punchier", "punchy", "punch",
                 "snappier", "snappy", "tighter", "tight"],
    "longer_release": ["дольше затухает"],
    "shorter_release": ["отрывистее", "отрывистый", "стаккато", "staccato", "более отрывистый"],
    "more_reverb": ["просторнее", "spacious"],
    "less_reverb": ["суше", "посуше", "сухой", "сухо", "drier", "dryer", "dry"],
    "wider": ["шире", "широкий", "широко", "расширь", "расширить", "wider", "widen", "wide"],
    "narrower": ["сузь", "сузить", "более узкий", "narrower", "narrow"],
    "more_drive": ["грязнее", "dirtier", "saturate", "насыщеннее"],
    "cleaner": ["чище", "чистый", "чистее", "cleaner", "clean"],
    "louder": ["громче", "погромче", "louder", "make louder", "volume up"],
    "quieter": ["тише", "потише", "quieter", "volume down"],
    "fatter": ["жирнее", "жирный", "толще", "толстый", "полнее", "мощнее", "массивнее", "богаче", "fatter", "fat",
               "thicker", "thick", "fuller", "bigger", "beefier"],
    "thinner": ["тоньше", "тонкий", "худее", "thinner", "thin", "leaner"],
}

# bare nouns ("reverb!", "и реверб"): matched on the words left over after the phrases above
_WEAK: dict[str, list[str]] = {
    "more_reverb": ["реверб", "реверба", "реверберация", "ревер", "reverb"],
    "more_delay": ["эхо", "эха", "дилей", "делей", "delay", "echo"],
    "more_chorus": ["хорус", "chorus"],
    "more_drive": ["дисторшн", "перегруз", "овердрайв", "драйв", "distortion", "overdrive", "drive"],
    "more_resonance": ["резонанс", "resonance", "reso"],
    "more_vibrato": ["вибрато", "vibrato"],
    "fatter": ["унисон", "unison"],
}

_ATTACK = ["атака", "атаку", "атаки", "атаке", "attack"]
_SOFT_ATTACK_ADJ = ["мягче", "помягче", "плавнее", "медленнее", "длиннее", "дольше", "softer", "smoother", "slower",
                    "longer", "gentler", "slow", "soft"]
_PUNCH_ATTACK_ADJ = ["резче", "быстрее", "короче", "жестче", "жёстче", "faster", "shorter", "snappier", "harder",
                     "quicker", "sharper", "tighter", "fast", "short"]

_SMALL_WORDS = ["чуть", "чуть-чуть", "чуток", "немного", "слегка", "капельку", "чуточку", "незначительно", "маленько",
                "bit", "slightly", "slight", "little", "touch", "tad", "subtle", "subtly", "tiny"]
_LARGE_WORDS = ["сильно", "намного", "гораздо", "значительно", "очень", "максимально", "радикально", "много",
                "much", "lot", "way", "very", "significantly", "heavily", "drastically", "hugely", "extremely",
                "strongly", "massively"]

_WORD_RE = re.compile(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("ё", "е"))


def _stem_set(phrase: str) -> frozenset[str]:
    return frozenset(stem(w) for w in _words(phrase))


def _build_specs(weak: bool = False) -> list[tuple[frozenset[str], str, int]]:
    specs: dict[tuple[frozenset[str], str], int] = {}
    prio = itertools.count()

    def add(spec: frozenset[str], req: str) -> None:
        if spec:
            specs.setdefault((spec, req), next(prio))

    if weak:
        for req, phrases in _WEAK.items():
            for ph in phrases:
                add(_stem_set(ph), req)
        return sorted(((s, r, p) for (s, r), p in specs.items()), key=lambda x: (-len(x[0]), x[2]))
    for req, phrases in _DIRECT.items():
        for ph in phrases:
            add(_stem_set(ph), req)
    for group, (more_req, less_req) in _PAIRS.items():
        for noun in _NOUNS[group]:
            for verb in _MORE:
                add(_stem_set(f"{verb} {noun}"), more_req)
            if less_req:
                for verb in _LESS:
                    add(_stem_set(f"{verb} {noun}"), less_req)
    for adj in _SOFT_ATTACK_ADJ:
        for noun in _ATTACK:
            add(_stem_set(f"{adj} {noun}"), "softer_attack")
    for adj in _PUNCH_ATTACK_ADJ:
        for noun in _ATTACK:
            add(_stem_set(f"{adj} {noun}"), "punchier")
    # "longer/shorter" + the thing
    for adj, req in (("длиннее", "longer_tail"), ("дольше", "longer_tail"), ("longer", "longer_tail"),
                     ("long", "longer_tail"), ("длинный", "longer_tail"),
                     ("короче", "shorter_tail"), ("shorter", "shorter_tail"), ("short", "shorter_tail")):
        for noun in _NOUNS["tail"] + ["реверб", "реверба", "reverb", "decay", "затухание"]:
            add(_stem_set(f"{adj} {noun}"), req)
    for adj, req in (("длиннее", "longer_tail"), ("дольше", "longer_tail"), ("longer", "longer_tail"),
                     ("long", "longer_tail"), ("длинный", "longer_tail"),
                     ("короче", "shorter_tail"), ("shorter", "shorter_tail"), ("short", "shorter_tail")):
        for rv in _NOUNS["reverb"]:
            for tail in _NOUNS["tail"] + ["decay", "затухание", "затухания"]:
                add(_stem_set(f"{adj} {rv} {tail}"), req)
    for adj, req in (("длиннее", "longer_release"), ("дольше", "longer_release"), ("longer", "longer_release"),
                     ("короче", "shorter_release"), ("shorter", "shorter_release")):
        for noun in _NOUNS["release"]:
            add(_stem_set(f"{adj} {noun}"), req)
    return sorted(((s, r, p) for (s, r), p in specs.items()), key=lambda x: (-len(x[0]), x[2]))


_SPECS = _build_specs()
_WEAK_SPECS = _build_specs(weak=True)
_AMOUNT_SMALL = frozenset(stem(w) for w in _words(" ".join(_SMALL_WORDS)))
_AMOUNT_LARGE = frozenset(stem(w) for w in _words(" ".join(_LARGE_WORDS)))


def supported_requests() -> list[str]:
    return list(REQUESTS)


def resolve_requests(text: str) -> list[str]:
    """Names of the REQUESTS mentioned in free text (RU/EN), in the order they appear. Canonical names pass through."""
    t = (text or "").strip().lower().replace("ё", "е")
    if not t:
        return []
    if t.replace(" ", "_") in REQUESTS:
        return [t.replace(" ", "_")]
    # position of every word; a clause break (comma, semicolon, period...) pushes the next words far away
    stems: dict[int, str] = {}
    pos = 0
    for m in re.finditer(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*|[,;.!?]+", t):
        tok = m.group(0)
        if tok[0] in ",;.!?":
            pos += 10
        else:
            stems[pos] = stem(tok)
            pos += 1
    free = dict(stems)
    found: list[tuple[int, str]] = []

    def match(specs: list) -> None:
        for spec, req, _prio in specs:
            if any(req == r for _, r in found):
                continue
            per_stem = [[i for i, v in sorted(free.items()) if v == st] for st in spec]
            if not all(per_stem):
                continue
            best = None
            for combo in itertools.product(*per_stem):
                if len(set(combo)) < len(combo):
                    continue
                span = max(combo) - min(combo)
                if span <= len(spec) and (best is None or span < best[0]):
                    best = (span, combo)
            if best is None:
                continue
            for p in best[1]:
                free.pop(p, None)
            found.append((min(best[1]), req))

    match(_SPECS)
    match(_WEAK_SPECS)  # bare nouns only use words not consumed by a more specific phrase
    found.sort()
    return [r for _, r in found]


def detect_amount(text: str) -> str | None:
    stems = {stem(w) for w in _words(text or "")}
    if stems & _AMOUNT_LARGE:
        return "large"
    if stems & _AMOUNT_SMALL:
        return "small"
    return None


# --------------------------------------------------------------------------- planning one parameter
@dataclass
class _Plan:
    value: Any  # what to send to set_device_parameters
    mode: str  # "display" | "norm" | "item"
    expected: str | None = None


class _Skip(Exception):
    pass


def _is_on(p: dict) -> bool:
    disp = str(p.get("display", "")).strip().lower()
    if disp in ("on", "true"):
        return True
    if disp in ("off", "false"):
        return False
    try:
        return float(p.get("value", 0)) >= 0.5
    except (TypeError, ValueError):
        return False


def _item_index(p: dict, wanted: str) -> int | None:
    items = [str(x).lower() for x in p.get("value_items") or []]
    return items.index(wanted.lower()) if wanted.lower() in items else None


def _clamp(v: float, lo: float | None, hi: float | None) -> float:
    if lo is not None:
        v = max(v, lo)
    if hi is not None:
        v = min(v, hi)
    return v


def _plan(op: dict, p: dict, ai: int) -> _Plan:
    """Compute the write for parameter row ``p`` (dict from get_device_parameters). Raises _Skip(reason)."""
    kind = op["kind"]
    quantized = bool(p.get("is_quantized")) and bool(p.get("value_items"))

    if kind == "enable":
        if _is_on(p):
            raise _Skip("уже включено")
        idx = _item_index(p, "On")
        if idx is None:
            raise _Skip("нет значения On")
        return _Plan("On", "item", "On")

    if kind == "mul":
        factor = op["factors"][ai]
        sign = 1 if factor > 1 else -1
    else:
        delta_by_dim = op["deltas"]
        sign = 1 if next(iter(delta_by_dim.values()))[ai] > 0 else -1

    if quantized:  # dropdown: move to the neighbouring item
        items = list(p["value_items"])
        cur = int(round(float(p.get("value", 0))))
        new = int(_clamp(cur + sign, float(p.get("min", 0)), float(p.get("max", len(items) - 1))))
        if new == cur or not 0 <= new < len(items):
            raise _Skip("уже на пределе")
        return _Plan(items[new], "item", items[new])

    display = p.get("display")
    parsed: tuple[float, str] | None = None
    try:
        parsed = parse_display(str(display))
    except (DisplayError, ValueError):
        parsed = None
    raw = float(p.get("value", 0.0))
    if parsed is not None and parsed[1] == "number" and abs(parsed[0] - raw) < 0.006 + 0.005 * abs(raw):
        parsed = None  # display just echoes the raw number: no unit information, use norm steps
    if parsed is not None and math.isinf(parsed[0]):
        parsed = (-70.0 if parsed[0] < 0 else 1e6, parsed[1])

    if parsed is not None:
        old, dim = parsed
        new: float | None = None
        if kind == "mul" and dim in ("freq", "time", "number"):
            new = old * op["factors"][ai]
            step = op["min_step"].get(dim)
            if step and op["factors"][ai] > 1:
                new = max(new, old + step[ai])
            lo_hi = op["bounds"].get(dim)
            if lo_hi:
                if op["factors"][ai] < 1 and old <= lo_hi[0] * 1.001:
                    raise _Skip("уже на пределе")
                if op["factors"][ai] > 1 and old >= lo_hi[1] * 0.999:
                    raise _Skip("уже на пределе")
                new = _clamp(new, lo_hi[0], lo_hi[1])
        elif kind == "add" and dim in op["deltas"]:
            new = old + op["deltas"][dim][ai]
            lo_hi = op["bounds"].get(dim)
            if lo_hi:
                if op["deltas"][dim][ai] < 0 and old <= lo_hi[0] + 1e-9:
                    raise _Skip("уже на пределе")
                if op["deltas"][dim][ai] > 0 and old >= lo_hi[1] - 1e-9:
                    raise _Skip("уже на пределе")
                new = _clamp(new, lo_hi[0], lo_hi[1])
        if new is not None:
            if abs(new - old) <= 1e-6 * max(1.0, abs(old)):
                raise _Skip("уже на пределе")
            text = format_display(new, dim)
            return _Plan({"display": text}, "display", text)

    # fallback: relative step in normalised units
    lo, hi = float(p.get("min", 0.0)), float(p.get("max", 1.0))
    if hi <= lo:
        raise _Skip("диапазон параметра вырожден")
    step = (op.get("norm") or NORM_STEPS)[ai] if kind == "add" else NORM_STEPS[ai]
    n = (raw - lo) / (hi - lo)
    n2 = min(1.0, max(0.0, n + sign * step))
    if abs(n2 - n) < 1e-6:
        raise _Skip("уже на пределе")
    return _Plan({"norm": round(n2, 4)}, "norm")


# --------------------------------------------------------------------------- the tweaker
@dataclass
class _Dev:
    index: int
    name: str
    roles: DeviceRoles
    params: dict[str, dict] | None = None
    pending: dict[str, Any] = field(default_factory=dict)  # parameter name -> value to write
    plans: dict[str, tuple[str, str, _Plan]] = field(default_factory=dict)  # name -> (role, before, plan)


class Tweaker:
    def __init__(self, bridge: Any, track_index: int, roles: RoleBook | None = None):
        self.bridge = bridge
        self.track_index = track_index
        self.book = roles or load_roles()
        self.devs: list[_Dev] = []
        self.changes: list[dict] = []
        self.skipped: list[dict] = []
        self.added: list[dict] = []
        self.warnings: list[str] = []

    # ---- bridge helpers
    def _read_params(self, dev: _Dev) -> dict[str, dict]:
        if dev.params is None:
            res = self.bridge.call("get_device_parameters",
                                   {"track_index": self.track_index, "device_index": dev.index})
            dev.params = {p["name"]: p for p in res.get("parameters", [])}
        return dev.params

    def _scan_track(self) -> None:
        info = self.bridge.call("get_track_info", {"track_index": self.track_index})
        self.track_name = info.get("name")
        self.devs = []
        for d in info.get("devices", []):
            roles = self.book.get(d.get("name"), d.get("class_name"))
            if roles is not None:
                self.devs.append(_Dev(index=d.get("index", len(self.devs)), name=d.get("name") or roles.name,
                                      roles=roles))

    def _dev_label(self, dev: _Dev) -> str:
        same = [d for d in self.devs if d.name == dev.name]
        return dev.name if len(same) <= 1 else f"{dev.name} №{dev.index}"

    # ---- planning
    def _gate_ok(self, dev: _Dev, when: str | None) -> bool:
        if not when:
            return True
        if when in dev.pending:
            return str(dev.pending[when]).lower() == "on"
        p = (dev.params or {}).get(when)
        return p is None or _is_on(p)

    def _candidates(self, req: dict, op: dict, roles: list[str]) -> list[tuple[_Dev, str]]:
        for role in roles:
            out = []
            for dev in self.devs:
                if op.get("devices") and dev.roles.name not in op["devices"]:
                    continue
                if op.get("kinds") and dev.roles.kind not in op["kinds"]:
                    continue
                if dev.roles.params(role):
                    out.append((dev, role))
            if out:
                return out
        return []

    def _apply_op(self, req_name: str, op: dict, ai: int) -> bool:
        roles = op["role"] if isinstance(op["role"], list) else [op["role"]]
        cands = self._candidates(REQUESTS[req_name], op, roles)
        touched = False
        for dev, role in cands:
            params = self._read_params(dev)
            if op.get("wake") and "Device On" in params and not _is_on(params["Device On"]):
                self._queue(dev, "Device On", "device_on", _Plan("On", "item", "On"))
            rps = dev.roles.params(role)
            for rp in rps:
                p = params.get(rp.name)
                if p is None:
                    self.skipped.append({"device": self._dev_label(dev), "parameter": rp.name,
                                         "reason": "параметра нет в этой версии Live"})
                    continue
                if not self._gate_ok(dev, rp.when):
                    self.skipped.append({"device": self._dev_label(dev), "parameter": rp.name,
                                         "reason": f"не слышно: «{rp.when}» выключен"})
                    continue
                try:
                    plan = _plan(op, p, ai)
                except _Skip as s:
                    self.skipped.append({"device": self._dev_label(dev), "parameter": rp.name, "reason": str(s)})
                    continue
                self._queue(dev, rp.name, role, plan)
                touched = True
        return touched

    def _queue(self, dev: _Dev, name: str, role: str, plan: _Plan) -> None:
        p = (dev.params or {}).get(name, {})
        dev.plans[name] = (role, str(p.get("display", "")), plan)
        dev.pending[name] = plan.value

    # ---- flushing
    def _flush(self) -> None:
        for dev in self.devs:
            if not dev.pending:
                continue
            res = self.bridge.call("set_device_parameters", {
                "track_index": self.track_index, "device_index": dev.index, "values": dict(dev.pending)})
            applied = {a.get("name"): a for a in res.get("applied", [])}
            failed = {f.get("parameter"): f for f in res.get("failed", [])}
            label = self._dev_label(dev)
            for name, (role, before, plan) in dev.plans.items():
                if name in failed:
                    self.skipped.append({"device": label, "parameter": name,
                                         "reason": f"Live отклонил: {failed[name].get('message', '')}"[:120]})
                    continue
                a = applied.get(name)
                after = str(a.get("display")) if a and a.get("display") is not None else (plan.expected or "")
                if a is not None and dev.params is not None and name in dev.params:
                    dev.params[name] = {**dev.params[name], **{k: a[k] for k in ("value", "display") if k in a}}
                if role == "device_on":
                    self.changes.append({"device": label, "device_index": dev.index, "parameter": name,
                                         "role": role, "before": before, "after": after or "On"})
                    continue
                if before and after == before:
                    self.skipped.append({"device": label, "parameter": name, "reason": "значение не изменилось"})
                    continue
                self.changes.append({"device": label, "device_index": dev.index, "parameter": name, "role": role,
                                     "before": before, "after": after})
            dev.pending.clear()
            dev.plans.clear()

    # ---- autoload
    def _autoload(self, req_name: str, ai: int) -> None:
        spec = REQUESTS[req_name].get("autoload")
        if not spec:
            return
        present = {d.roles.name for d in self.devs}
        if present & set(spec.get("unless", [])):
            return
        name = spec["device"]
        try:
            res = self.bridge.call("load_device", {"track_index": self.track_index, "device_name": name},
                                   LOAD_TIMEOUT)
        except BridgeCommandError as e:
            self.warnings.append(f"Не удалось добавить {name}: {e.message}")
            return
        roles = self.book.get(name)
        if roles is None:
            return
        dev = _Dev(index=int(res.get("device_index", len(self.devs))), name=res.get("name", name), roles=roles)
        self.devs.append(dev)
        self.added.append({"device": dev.name, "device_index": dev.index})
        params = self._read_params(dev)
        for pname, values in spec.get("init", {}).items():
            p = params.get(pname)
            if p is None:
                continue
            text = values[ai]
            self._queue(dev, pname, self._role_of(roles, pname), _Plan({"display": text}, "display", text))

    @staticmethod
    def _role_of(roles: DeviceRoles, pname: str) -> str:
        found = roles.roles_of(pname)
        return found[0] if found else "init"

    # ---- main
    def run(self, request: str, amount: str | None = None) -> dict:
        names = resolve_requests(request)
        if not names:
            return {"ok": False, "code": "unknown_request", "request": request,
                    "message": ("Не понял, как изменить звук по запросу «%s». Поддерживаются: %s. "
                                "Для остального используйте get_device_parameters и set_device_parameters."
                                % (request, ", ".join(REQUESTS))),
                    "supported": supported_requests()}
        amount = amount if amount in AMOUNTS else (detect_amount(request) or "medium")
        ai = AMOUNTS.index(amount)
        self._scan_track()
        if not self.devs:
            return {"ok": False, "code": "no_devices", "request": request, "interpreted": names, "amount": amount,
                    "message": "На дорожке нет устройств, параметры которых я умею подстраивать "
                               "(нужен Operator/Analog/Wavetable/Drift/Simpler или эффект).",
                    "changes": [], "skipped": []}
        for req_name in names:
            touched = False
            for op in REQUESTS[req_name]["ops"]:
                touched = self._apply_op(req_name, op, ai) or touched
            spec = REQUESTS[req_name].get("autoload")
            if spec and not (spec.get("if_untouched") and touched):
                self._autoload(req_name, ai)
            self._flush()
        return self._result(request, names, amount)

    def _result(self, request: str, names: list[str], amount: str) -> dict:
        lines = []
        groups: dict[tuple, list[dict]] = {}
        for c in self.changes:  # identical moves of sibling parameters (Operator's B/C/D attacks) read as one line
            groups.setdefault((c["device_index"], c["role"], c["before"], c["after"]), []).append(c)
        for cs in groups.values():
            label = self._ru_label(cs[0], [c["parameter"] for c in cs])
            lines.append(f"{label}: {cs[0]['before']} → {cs[0]['after']}" if cs[0]["before"] else
                         f"{label}: {cs[0]['after']}")
        for a in self.added:
            lines.insert(0, f"Добавлен {a['device']} (устройство №{a['device_index']})")
        ok = bool(self.changes or self.added)
        ru_titles = ", ".join(REQUESTS[n]["ru"] for n in names)
        if ok:
            step = {"small": "малый", "medium": "средний", "large": "большой"}[amount]
            msg = f"Подстроено ({ru_titles}; шаг: {step}): " + "; ".join(lines)
        else:
            reasons = "; ".join(f"{s['device']} {s['parameter']}: {s['reason']}" for s in self.skipped[:6])
            msg = (f"Ничего не изменено ({ru_titles}). "
                   + (f"Причины: {reasons}. " if reasons else "На дорожке нет подходящих параметров. ")
                   + "Можно попробовать вручную через get_device_parameters и set_device_parameters.")
        data: dict[str, Any] = {
            "ok": ok, "request": request, "interpreted": names, "amount": amount,
            "track_index": self.track_index,
            "changes": self.changes[:MAX_CHANGES_IN_RESULT], "message": msg,
        }
        if len(self.changes) > MAX_CHANGES_IN_RESULT:
            data["truncated"] = True
            data["total_changes"] = len(self.changes)
        if self.added:
            data["added_devices"] = self.added
        if self.skipped:
            data["skipped"] = self.skipped[:15]
        if self.warnings:
            data["warnings"] = self.warnings
        if not ok:
            data["code"] = "nothing_changed"
        return data

    def _ru_label(self, c: dict, params: list[str] | None = None) -> str:
        role = c["role"]
        if role == "device_on":
            return f"Включён {c['device']}"
        label = f"{self.book.label(role, 'ru')} {c['device']}"
        dev = next((d for d in self.devs if d.index == c["device_index"]), None)
        if dev is not None and len(dev.roles.params(role)) > 1:
            label += f" ({', '.join(params or [c['parameter']])})"
        return label


def adjust_sound(bridge: Any, track_index: int, request: str, amount: str | None = None,
                 roles: RoleBook | None = None) -> dict:
    """Apply an adjective/effect request to every suitable device on the track. Returns a result dict (see Tweaker)."""
    return Tweaker(bridge, track_index, roles).run(request, amount)

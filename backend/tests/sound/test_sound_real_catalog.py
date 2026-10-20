"""Recipes against the REAL Live 11.3.25 catalog: parameter names, value forms, display units and mix hygiene.

The catalog (abhelper/sound/data/device_catalog.json) is the user's own calibration dump, so these tests catch
exactly the failure of the first real-world run: right names but wrong values (Hz/ms assumed on 0..1 curves).
"""

import math
import re

import pytest

from abhelper.bridge.displayval import parse_display
from abhelper.bridge.fake import FakeBridge
from abhelper.sound import RecipeLibrary, SoundEngine, SoundRequest, validate_recipe
from abhelper.sound.calibration import load_catalog

LIB = RecipeLibrary.load_default()
CAT = load_catalog()["devices"]
IDS = sorted(r["id"] for r in LIB.all())

# Recipes known to be mid-redesign can be listed here with a reason: they are then reported as xfail, not failed.
XFAIL_REASONS: dict[str, str] = {}


def _ids():
    for rid in IDS:
        if rid in XFAIL_REASONS:
            yield pytest.param(rid, marks=pytest.mark.xfail(reason=XFAIL_REASONS[rid], strict=False))
        else:
            yield rid


def iter_params(recipe):
    """(where, device, {name: value}) for the instrument, each fallback device and every effect."""
    inst = recipe["instrument"]
    yield "instrument", inst["device"], inst.get("parameters", {})
    for dev, params in (inst.get("fallback_parameters") or {}).items():
        yield f"fallback:{dev}", dev, params
    for i, fx in enumerate(recipe.get("effects", [])):
        yield f"effects[{i}]", fx["device"], fx.get("parameters", {})


def iter_values(recipe):
    for where, dev, params in iter_params(recipe):
        for name, value in params.items():
            yield where, dev, name, value


# ------------------------------------------------------------------ unit heuristics (by parameter name)
FREQ_WORDS = {"freq", "frequency", "cutoff", "rate", "speed"}
TIME_WORDS = {"attack", "decay", "release", "rel", "time", "predelay", "delay"}
LEVEL_WORDS = {"gain", "volume", "level", "output", "threshold"}
PERCENT_WORDS = {"dry", "wet", "amount", "amt", "mix", "width", "warmth", "feedback"}

# name -> allowed dimensions, for display values that legitimately break the heuristic (none needed so far).
DISPLAY_EXCEPTIONS: dict[str, set] = {}
# Parameters with a unit-like name that may still carry {"norm"}: the display unit is not known for sure in Live 11.
NORM_EXCEPTIONS = {
    "Vib Amount": "Analog vibrato depth: shown in a unit we could not verify (%, ct or st), so a 0..1 macro is safest",
}

LFO_WORDS = {"rate", "speed", "lfo", "mod", "vib"}
LFO_DEVICES = {"Auto Pan", "Chorus-Ensemble", "Phaser-Flanger"}   # their Frequency / Rate is an LFO
RANGES = {  # canonical units: Hz, ms, %, dB   (frequencies: audio filters >= 20 Hz, LFO / modulation rates >= 0.01 Hz)
    "freq": (20.0, 22050.0),
    "time": (0.1, 120_000.0),
    "percent": (0.0, 200.0),
    "level": (-60.0, 12.0),
}


def words(name: str) -> set[str]:
    return set(re.findall(r"[a-z]+", name.lower()))


def expected_dims(name: str) -> set[str]:
    w = words(name)
    dims: set[str] = set()
    if w & FREQ_WORDS:
        dims.add("freq")
    if w & TIME_WORDS:
        dims.add("time")
    if w & LEVEL_WORDS:
        dims |= {"level", "percent"}
    if w & PERCENT_WORDS:
        dims.add("percent")
    return dims


# ------------------------------------------------------------------ (b) names and values resolve on the real catalog
@pytest.mark.parametrize("rid", list(_ids()))
def test_every_recipe_validates_and_uses_only_known_devices(rid):
    r = LIB.get(rid)
    assert validate_recipe(r) == []
    for _where, dev, _params in iter_params(r):
        assert dev in CAT, f"{rid}: device {dev!r} is not in the real catalog"
    inst = r["instrument"]
    assert set(inst.get("fallback_parameters") or {}) <= set(inst.get("fallback_devices") or [])


@pytest.mark.parametrize("rid", list(_ids()))
def test_recipe_uses_exact_real_parameter_names_and_items(rid):
    """Zero unmatched on the real catalog, and the recipe spells names / dropdown items exactly like Live does."""
    errors = []
    for where, dev, name, value in iter_values(LIB.get(rid)):
        params = {p["name"]: p for p in CAT[dev]["parameters"]}
        p = params.get(name)
        if p is None:
            errors.append(f"{where} {dev}: no parameter {name!r}")
            continue
        if isinstance(value, str):
            if value not in p["value_items"]:
                errors.append(f"{where} {dev}.{name}: {value!r} is not one of {p['value_items']}")
        elif isinstance(value, bool):
            errors.append(f"{where} {dev}.{name}: use 'On'/'Off', not a bool")
        elif isinstance(value, (int, float)):
            if not p["min"] - 1e-9 <= value <= p["max"] + 1e-9:
                errors.append(f"{where} {dev}.{name}: raw {value} is outside {p['min']}..{p['max']}")
            if p["is_quantized"] and int(value) != value:
                errors.append(f"{where} {dev}.{name}: quantized parameter needs an integer, got {value}")
        elif isinstance(value, dict) and "display" in value and p["is_quantized"]:
            errors.append(f"{where} {dev}.{name}: 'display' on a quantized parameter, use the item name")
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("rid", list(_ids()))
def test_recipe_applies_to_a_fake_live_built_from_the_real_catalog(rid):
    recipe = LIB.get(rid)
    bridge = FakeBridge(device_catalog=CAT, browser_items=[])
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest(description=rid, recipe_id=rid, strategy="recipe"))
    assert res.ok, res.message
    assert res.unmatched_parameters == [], res.unmatched_parameters
    assert [d["name"] for d in res.devices] == [recipe["instrument"]["device"]] + [fx["device"] for fx in recipe.get("effects", [])]
    assert all(w.startswith("Drum Rack") for w in res.warnings), res.warnings


# ------------------------------------------------------------------ (c) display values: plausible dimension and range
@pytest.mark.parametrize("rid", list(_ids()))
def test_display_values_have_a_plausible_unit_for_the_parameter(rid):
    errors = []
    for where, dev, name, value in iter_values(LIB.get(rid)):
        if not (isinstance(value, dict) and "display" in value):
            continue
        number, dim = parse_display(value["display"])
        want = DISPLAY_EXCEPTIONS.get(name, expected_dims(name))
        if want and dim not in want:
            errors.append(f"{where} {dev}.{name}: {value['display']!r} is {dim}, expected one of {sorted(want)}")
        if dim in RANGES and not math.isinf(number):
            lo, hi = RANGES[dim]
            if dim == "freq" and (words(name) & LFO_WORDS or dev in LFO_DEVICES):
                lo = 0.01
            if not lo <= number <= hi:
                errors.append(f"{where} {dev}.{name}: {value['display']!r} ({number:g}) is outside {lo:g}..{hi:g}")
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("rid", list(_ids()))
def test_display_units_match_catalog_display_samples_when_present(rid):
    """Once the catalog carries display_samples (newer calibration), recipes must use the unit Live shows."""
    errors = []
    for where, dev, name, value in iter_values(LIB.get(rid)):
        if not (isinstance(value, dict) and "display" in value):
            continue
        p = next((q for q in CAT[dev]["parameters"] if q["name"] == name), None)
        samples = (p or {}).get("display_samples") or []
        if not samples:
            continue
        shown = {parse_display(text)[1] for _raw, text in samples} - {"number"}
        want = parse_display(value["display"])[1]
        if shown and want != "number" and want not in shown:
            errors.append(f"{where} {dev}.{name}: Live shows {sorted(shown)}, recipe asks for {value['display']!r}")
    assert not errors, "\n".join(errors)


def test_the_unit_heuristics_themselves():
    assert expected_dims("Filter Freq") == {"freq"}
    assert expected_dims("AEG1 Rel") == {"time"}
    assert expected_dims("Dry/Wet") == {"percent"}
    assert expected_dims("Osc-A Level") == {"level", "percent"}
    assert expected_dims("Resonance") == set()
    assert expected_dims("Sample Rate") == {"freq"}


# ------------------------------------------------------------------ (d) {"norm"} only for unitless macros
@pytest.mark.parametrize("rid", list(_ids()))
def test_no_norm_on_parameters_that_have_a_unit(rid):
    errors = []
    for where, dev, name, value in iter_values(LIB.get(rid)):
        if isinstance(value, dict) and "norm" in value and expected_dims(name) and name not in NORM_EXCEPTIONS:
            errors.append(f"{where} {dev}.{name}: {value} - this parameter has a unit, use {{\"display\": ...}}")
    assert not errors, "\n".join(errors)


def test_most_unit_parameters_use_display_forms():
    """The point of the redesign: frequencies/times/levels are set by what Live displays."""
    shown = norm = 0
    for rid in IDS:
        for _where, _dev, name, value in iter_values(LIB.get(rid)):
            if expected_dims(name) and isinstance(value, dict):
                shown += "display" in value
                norm += "norm" in value
    assert shown > 400 and norm <= len(NORM_EXCEPTIONS) * len(IDS)


# ------------------------------------------------------------------ sound design hygiene
ACOUSTIC_CATEGORIES = {"piano", "strings", "brass", "woodwind", "reed", "guitar", "plucked", "keys", "ethnic", "mallet"}
# Chorus-Ensemble adds pitch wobble / multiple voices. Fine for ensembles, pads, e-pianos and synth plucks, wrong for solo
# acoustic instruments. Organ / lo-fi keys use it only in Vibrato mode (Leslie / tape wow).
CHORUS_ALLOWED = {"electric_piano", "strings_ensemble", "choir_aah", "church_organ", "organ_drawbar", "pluck_synth",
                  "warm_analog_pad", "ambient_pad", "noise_sweep_wind", "vinyl_lofi_keys"}


def _effects(recipe, device):
    return [fx.get("parameters", {}) for fx in recipe.get("effects", []) if fx["device"] == device]


def _display_number(value):
    return parse_display(value["display"])[0]


@pytest.mark.parametrize("rid", list(_ids()))
def test_chorus_is_never_classic_and_only_where_musically_justified(rid):
    r = LIB.get(rid)
    for p in _effects(r, "Chorus-Ensemble"):
        assert rid in CHORUS_ALLOWED, f"{rid}: Chorus-Ensemble on a (solo) acoustic/other sound; add to CHORUS_ALLOWED only if justified"
        assert p.get("Mode") in ("Ensemble", "Vibrato"), f"{rid}: Classic chorus makes instruments sound like cheap synths"
        if p.get("Mode") == "Vibrato":
            assert _display_number(p["Dry/Wet"]) == 100.0, f"{rid}: vibrato needs a fully wet signal (a dry mix is just a chorus)"
    # the same applies to the fallback-free Analog/Operator Chorus device name aliases
    assert not _effects(r, "Chorus")


@pytest.mark.parametrize("rid", list(_ids()))
def test_acoustic_reverbs_are_rooms_and_halls_not_washes(rid):
    r = LIB.get(rid)
    if r["category"] not in ACOUSTIC_CATEGORIES:
        pytest.skip("not an acoustic category")
    for p in _effects(r, "Reverb"):
        assert _display_number(p["Dry/Wet"]) <= 25.0, f"{rid}: reverb too wet for an acoustic sound"
        assert _display_number(p["Decay Time"]) <= 2600.0, f"{rid}: decay longer than 2.6 s"


@pytest.mark.parametrize("rid", list(_ids()))
def test_levels_leave_headroom_and_effects_do_not_boost(rid):
    r = LIB.get(rid)
    vol = r["instrument"].get("parameters", {}).get("Volume")
    if isinstance(vol, dict) and "display" in vol:
        assert -14.0 <= _display_number(vol) <= -3.0, f"{rid}: instrument Volume {vol['display']}"
    for fb_dev, params in (r["instrument"].get("fallback_parameters") or {}).items():
        v = params.get("Volume")
        if isinstance(v, dict) and "display" in v:
            assert -14.0 <= _display_number(v) <= -3.0, f"{rid}/{fb_dev}: Volume {v['display']}"
    for p in _effects(r, "Utility"):
        if "Gain" in p:
            assert _display_number(p["Gain"]) <= 0.0
    for p in _effects(r, "Saturator"):
        assert p.get("Output", 0) <= 0
    for p in _effects(r, "Compressor"):
        assert p.get("Output Gain", 0) <= 0
    for p in _effects(r, "EQ Eight"):
        for name, v in p.items():
            if name.endswith("Gain A"):
                assert -9.0 <= v <= 7.0, f"{rid}: EQ {name} = {v} dB"


@pytest.mark.parametrize("rid", list(_ids()))
def test_envelopes_are_realistic_for_the_category(rid):
    """Bowed/blown sounds need a soft attack; plucks and mallets an instant one and no sustain."""
    r = LIB.get(rid)
    if r["instrument"]["device"] != "Analog":
        pytest.skip("envelope times are compared on Analog patches")
    p = r["instrument"]["parameters"]
    attack = _display_number(p["AEG1 Attack"]) if "AEG1 Attack" in p else None
    sustain = p.get("AEG1 Sustain", {}).get("norm") if isinstance(p.get("AEG1 Sustain"), dict) else None
    if attack is None or not p.get("OSC1 On/Off") == "On":
        pytest.skip("noise-only patch")
    if r["category"] in ("strings", "brass", "woodwind"):
        assert 20.0 <= attack <= 700.0, f"{rid}: attack {attack} ms"
        assert sustain is not None and sustain >= 0.8, f"{rid}: bowed/blown notes sustain"
    if r["category"] == "plucked":
        assert attack <= 5.0 and sustain == 0.0, f"{rid}: plucks start instantly and decay to nothing"

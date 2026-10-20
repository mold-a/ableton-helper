"""Recipe library: schema validity, coverage and consistency with the device catalog / FakeBridge."""

import json
from pathlib import Path

import pytest
from sound_testkit import ScriptedBridge, missing_devices

from abhelper.bridge.fake import FakeBridge
from abhelper.sound import RecipeLibrary, SoundEngine, SoundRequest, validate_recipe
from abhelper.sound.calibration import load_catalog, recipe_device_names
from abhelper.sound.params import AliasTable
from abhelper.sound.schema import CATEGORIES

LIB = RecipeLibrary.load_default()
IDS = sorted(r["id"] for r in LIB.all())
SOUND_DIR = Path(__file__).resolve().parents[2] / "abhelper" / "sound"

REQUIRED_IDS = {
    "bayan", "grand_piano", "electric_piano", "wurlitzer", "organ_drawbar", "church_organ", "harmonium", "strings_ensemble",
    "solo_violin", "solo_cello", "pizzicato_strings", "brass_section", "trumpet", "flute", "clarinet", "choir_aah",
    "warm_analog_pad", "ambient_pad", "supersaw_lead", "chiptune_lead", "pluck_synth", "glockenspiel", "marimba", "kalimba",
    "harp", "acoustic_guitar", "balalaika", "sitar", "steel_drum", "sub_bass", "reese_bass", "acid_bass", "bass_808",
    "wobble_bass", "techno_rumble", "drum_kit_808", "drum_kit_acoustic", "lofi_drums", "riser_fx", "noise_sweep_wind",
    "vinyl_lofi_keys", "music_box",
}


def _has_cyrillic(s: str) -> bool:
    return any("а" <= ch.lower() <= "я" or ch in "ёЁ" for ch in s)


def test_library_is_large_enough():
    assert len(LIB) >= 40
    assert REQUIRED_IDS <= set(IDS)


def test_every_recipe_file_loaded_and_named_after_its_id():
    files = sorted(p.stem for p in (SOUND_DIR / "recipes").glob("*.json"))
    assert files == IDS


@pytest.mark.parametrize("rid", IDS)
def test_recipe_validates(rid):
    assert validate_recipe(LIB.get(rid)) == []


@pytest.mark.parametrize("rid", IDS)
def test_recipe_has_ru_and_en_aliases_and_english_preset_terms(rid):
    r = LIB.get(rid)
    assert any(_has_cyrillic(a) for a in r["aliases"]), "needs a Russian alias"
    assert any(a.isascii() for a in r["aliases"]), "needs an English alias"
    assert r["preset_search"] and all(t.isascii() for t in r["preset_search"])
    assert r["name"].get("ru") and r["name"].get("en")
    assert r["sound_design_notes"] and len(r["sound_design_notes"]) > 80
    assert r["category"] in CATEGORIES


def test_category_coverage():
    cats = {r["category"] for r in LIB.all()}
    assert {"keys", "piano", "organ", "strings", "brass", "woodwind", "reed", "plucked", "guitar", "bass", "lead", "pad",
            "bell", "mallet", "choir", "fx", "drums", "ethnic"} <= cats


def test_aliases_are_unique_enough():
    """The same alias must not select two different recipes with equal weight."""
    seen: dict[str, str] = {}
    for r in LIB.all():
        for a in r["aliases"]:
            key = a.lower().replace("ё", "е")
            assert key not in seen or seen[key] == r["id"], f"alias '{a}' used by {seen.get(key)} and {r['id']}"
            seen[key] = r["id"]


# ------------------------------------------------------------------ consistency with the catalog
def test_catalog_is_the_verified_live_dump_and_covers_every_device():
    cat = load_catalog()
    assert cat["_meta"]["verified"] is True and cat["_meta"]["live_version"] == "11.3.25"
    assert "note" in cat["_meta"]
    missing = set(recipe_device_names(LIB)) - set(cat["devices"])
    assert not missing, f"devices used by recipes but absent from catalog: {missing}"
    for name, spec in cat["devices"].items():
        assert spec["type"] in ("instrument", "audio_effect", "midi_effect"), name
        for p in spec["parameters"]:
            assert p["min"] <= p["default"] <= p["max"], (name, p["name"])
    # Erosion failed to load during the user's calibration: the old hand-written entry is kept, flagged per device
    assert "UNVERIFIED" in cat["devices"]["Erosion"]["note"]
    assert "Erosion" in cat["_meta"].get("failed", {})


def test_param_aliases_file_is_wellformed():
    data = json.loads((SOUND_DIR / "data" / "param_aliases.json").read_text(encoding="utf-8"))
    assert data["parameters"] and data["devices"]
    for group in data["parameters"] + data["devices"] + data["values"]:
        assert isinstance(group, list) and len(group) >= 2 and all(isinstance(x, str) for x in group)
    table = AliasTable.from_file()
    assert "Filter Frequency" in table.parameter_variants("Filter Freq")
    assert "Chorus" in table.device_variants("Chorus-Ensemble")


# ------------------------------------------------------------------ applying against FakeBridge
@pytest.mark.parametrize("rid", IDS)
def test_recipe_applies_with_zero_unmatched_parameters(rid):
    r = LIB.get(rid)
    bridge = FakeBridge(browser_items=[])
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest(description=rid, recipe_id=rid, strategy="recipe"))
    assert res.ok, res.message
    assert res.unmatched_parameters == [], res.unmatched_parameters
    assert res.source == "recipe" and res.recipe_id == rid and res.preset is None
    names = [d["name"] for d in res.devices]
    assert names == [r["instrument"]["device"]] + [fx["device"] for fx in r.get("effects", [])]
    allowed_warnings = ("Drum Rack",)
    assert all(w.startswith(allowed_warnings) for w in res.warnings), res.warnings

    track = bridge.tracks[res.track_index]
    assert track.name == r["track"]["name"] and track.color_index == r["track"]["color_index"]
    clip = track.slots[res.demo_clip_slot]
    assert clip is not None and clip.notes and clip.name.startswith("Демо — ")
    assert all(n["start"] + n["duration"] <= clip.length + 1e-6 for n in clip.notes)


def _fallback_cases():
    for rid in IDS:
        for dev in LIB.get(rid)["instrument"].get("fallback_parameters", {}):
            yield rid, dev


@pytest.mark.parametrize("rid,device", list(_fallback_cases()))
def test_fallback_parameters_apply_with_zero_unmatched(rid, device):
    inst = LIB.get(rid)["instrument"]
    chain = [inst["device"]] + inst["fallback_devices"]
    unavailable = chain[: chain.index(device)]
    bridge = ScriptedBridge(browser_items=[], fail={"load_device": missing_devices(*unavailable)})
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest(description=rid, recipe_id=rid, strategy="recipe"))
    assert res.ok, res.message
    assert res.devices[0]["name"] == device
    assert res.unmatched_parameters == [], res.unmatched_parameters
    assert any("недоступен" in w for w in res.warnings)


@pytest.mark.parametrize("rid", [i for i in IDS if LIB.get(i)["instrument"].get("fallback_devices")])
def test_every_fallback_device_can_actually_load(rid):
    """Even without fallback_parameters the chain must stay usable (warning, not failure)."""
    inst = LIB.get(rid)["instrument"]
    bridge = ScriptedBridge(browser_items=[], fail={"load_device": missing_devices(inst["device"])})
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest(description=rid, recipe_id=rid, strategy="recipe"))
    assert res.ok, res.message
    assert res.devices[0]["name"] == inst["fallback_devices"][0]


# ------------------------------------------------------------------ schema negatives
def _good():
    return json.loads(json.dumps(LIB.get("bayan")))


def test_validate_rejects_bad_recipes():
    assert validate_recipe("nope")
    r = _good(); r["id"] = "Bad Id"
    assert any(e.startswith("id") for e in validate_recipe(r))
    r = _good(); del r["aliases"]
    assert any("aliases" in e for e in validate_recipe(r))
    r = _good(); r["category"] = "weird"
    assert any("category" in e for e in validate_recipe(r))
    r = _good(); r["instrument"] = {}
    assert any("instrument.device" in e for e in validate_recipe(r))
    r = _good(); r["instrument"]["parameters"]["X"] = {"norm": 3}
    assert any("outside 0..1" in e for e in validate_recipe(r))
    r = _good(); r["instrument"]["parameters"]["X"] = [1]
    assert any("unsupported value" in e for e in validate_recipe(r))
    r = _good(); r["effects"] = [{"parameters": {}}]
    assert any("effects[0].device" in e for e in validate_recipe(r))
    r = _good(); r["demo"] = {"style": "dubstep"}
    assert any("demo.style" in e for e in validate_recipe(r))
    r = _good(); r["demo"] = {"notes": [{"pitch": 200, "start": 0, "duration": 1}]}
    assert any("pitch" in e for e in validate_recipe(r))
    r = _good(); r["track"] = {"color_index": 99}
    assert any("color_index" in e for e in validate_recipe(r))


def test_validate_accepts_display_values_and_rejects_malformed_ones():
    for ok in ("1.3 kHz", "80 Hz", "-6 dB", "18 %", "1,2 s", "-inf dB", "0.9", "4 : 1", "250 ms"):
        r = _good(); r["instrument"]["parameters"]["X"] = {"display": ok}
        assert validate_recipe(r) == [], ok
    for bad in ("", "  ", "loud", "kHz", 5, None):
        r = _good(); r["instrument"]["parameters"]["X"] = {"display": bad}
        assert any("display" in e for e in validate_recipe(r)), bad
    r = _good(); r["instrument"]["parameters"]["X"] = {"display": "1 kHz", "norm": 0.5}
    assert any("exactly" in e for e in validate_recipe(r))


def test_custom_recipes_may_omit_id_aliases_name_and_category():
    minimal = {"instrument": {"device": "Operator", "parameters": {"Algorithm": 2}}}
    assert validate_recipe(minimal) != []
    assert validate_recipe(minimal, custom=True) == []
    assert validate_recipe({"instrument": {}}, custom=True)

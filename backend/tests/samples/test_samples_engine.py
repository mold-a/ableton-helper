"""Engine integration: `preset_parameters` after a preset load and the AbletonHelper ranking boost."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sound"))      # sound_testkit lives next to the sound tests
from sound_testkit import ScriptedBridge  # noqa: E402

from abhelper.bridge.fake import FakeBridge
from abhelper.sound import RecipeLibrary, SoundEngine, SoundRequest
from abhelper.sound.presets import PresetSearcher, is_helper_item, score_item
from abhelper.sound.schema import validate_recipe

LIB = RecipeLibrary.load_default()
HELPER_PATH = "user_library/Presets/Instruments/Sampler/AbletonHelper/AbletonHelper Accordion HN.adv"

SAMPLER_SPEC = {"type": "instrument", "class_name": "MultiSampler", "parameters": [
    {"name": "Ve Attack", "min": 0.0, "max": 1.0, "default": 0.0},
    {"name": "Ve Release", "min": 0.0, "max": 1.0, "default": 0.1},
    {"name": "Volume", "min": 0.0, "max": 1.0, "default": 0.7},
]}


def catalog():
    cat = FakeBridge._load_default_catalog()
    cat = copy.deepcopy(cat)
    cat["Sampler"] = SAMPLER_SPEC
    return cat


def bridge_with_helper_preset(cls=FakeBridge, extra=()):
    items = [{"path": HELPER_PATH, "loads": ["Sampler"]},
             {"path": "sounds/Reed/Accordion Musette.adg", "loads": ["Instrument Rack"]}, *extra]
    return cls(browser_items=items, device_catalog=catalog())


def recipe_with_preset_parameters(**over):
    r = {
        "name": {"ru": "Баян из сэмплов", "en": "Sampled bayan"}, "category": "reed",
        "instrument": {"device": "Operator", "parameters": {}},
        "preset_search": ["accordion"],
        "preset_parameters": {"Ve Release": {"norm": 0.5}, "Volume": {"norm": 0.25}, "No Such Knob": 1},
    }
    r.update(over)
    return r


# ------------------------------------------------------------------ preset_parameters
def test_schema_accepts_and_checks_preset_parameters():
    ok = recipe_with_preset_parameters()
    assert validate_recipe(ok, custom=True) == []
    bad = recipe_with_preset_parameters(preset_parameters={"Ve Release": [1]})
    assert any("preset_parameters" in e for e in validate_recipe(bad, custom=True))
    assert any("preset_parameters" in e for e in validate_recipe(recipe_with_preset_parameters(preset_parameters=5), custom=True))


def test_preset_parameters_applied_to_the_loaded_presets_instrument():
    bridge = bridge_with_helper_preset()
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest("sampled accordion", recipe=recipe_with_preset_parameters()))
    assert res.ok and res.source == "preset" and res.preset["path"] == HELPER_PATH
    sampler = next(d for d in bridge.tracks[0].devices if d.name == "Sampler")
    params = {p.name: p.value for p in sampler.parameters}
    assert params["Ve Release"] == pytest.approx(0.5) and params["Volume"] == pytest.approx(0.25)
    assert params["Ve Attack"] == 0.0                                          # untouched
    # the unknown knob is reported like in the synthesis path
    assert [u["parameter"] for u in res.unmatched_parameters] == ["No Such Knob"]
    assert res.unmatched_parameters[0]["device"] == "Sampler"
    assert any(c[0] == "set_device_parameters" for c in bridge.calls)


def test_preset_parameters_use_fuzzy_names_and_display_values():
    recipe = recipe_with_preset_parameters(preset_parameters={"ve release": {"norm": 0.4}, "volume": 0.3})
    bridge = bridge_with_helper_preset()
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest("sampled accordion", recipe=recipe))
    sampler = next(d for d in bridge.tracks[0].devices if d.name == "Sampler")
    params = {p.name: p.value for p in sampler.parameters}
    assert res.unmatched_parameters == [] and params["Ve Release"] == pytest.approx(0.4) and params["Volume"] == pytest.approx(0.3)


def test_no_preset_parameters_means_no_extra_calls():
    recipe = recipe_with_preset_parameters()
    del recipe["preset_parameters"]
    bridge = bridge_with_helper_preset()
    SoundEngine(bridge, LIB).create_sound(SoundRequest("sampled accordion", recipe=recipe))
    assert not any(c[0] == "set_device_parameters" for c in bridge.calls)


def test_preset_parameters_are_not_applied_when_the_recipe_is_synthesised():
    bridge = bridge_with_helper_preset()
    recipe = recipe_with_preset_parameters()
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest("sampled accordion", recipe=recipe, strategy="recipe"))
    assert res.ok and res.source == "custom_recipe"
    assert res.unmatched_parameters == []                                      # preset_parameters were not tried on Operator


def test_preset_without_instrument_warns():
    bridge = FakeBridge(browser_items=[{"path": "user_library/AbletonHelper Only Reverb.adv", "loads": ["Reverb"]}],
                        device_catalog=catalog())
    recipe = recipe_with_preset_parameters(preset_search=["reverb"])
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest("reverb sound", recipe=recipe, strategy="preset"))
    assert res.ok and any("нет инструмента" in w for w in res.warnings)


def test_failure_applying_preset_parameters_is_a_warning_not_a_crash():
    from abhelper.bridge.base import BridgeCommandError
    bridge = bridge_with_helper_preset(ScriptedBridge)
    bridge.fail["get_device_parameters"] = BridgeCommandError("internal", "boom")
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest("sampled accordion", recipe=recipe_with_preset_parameters()))
    assert res.ok and any("не применены" in w for w in res.warnings)


# ------------------------------------------------------------------ ranking boost
def item(path, category="user_library", name=None, **kw):
    return {"name": name or path.rsplit("/", 1)[-1], "path": path, "category": category, "uri": "u:" + path,
            "is_loadable": True, "is_device": False, "is_folder": False, **kw}


WEIGHTS = {"sounds": 1.0, "instruments": 0.95, "user_library": 0.85, "samples": 0.35}


def test_is_helper_item():
    assert is_helper_item(item(HELPER_PATH)) and is_helper_item(item("x/Abletonhelper Foo.adv"))
    assert is_helper_item({"name": "Ableton Helper x", "path": ""})                  # spaces do not matter
    assert not is_helper_item(item("sounds/Ableton Pad.adg"))
    assert not is_helper_item(item("sounds/Reed/Accordion.adg"))


def test_helper_preset_beats_an_exact_factory_match():
    helper = item(HELPER_PATH)
    factory = item("sounds/Reed/Accordion.adg", category="sounds")
    assert score_item(factory, "accordion", WEIGHTS) == pytest.approx(1.0)
    assert score_item(helper, "accordion", WEIGHTS) >= score_item(factory, "accordion", WEIGHTS) >= 0.99
    # even for a later search term and in a low-weight category
    assert score_item(item(HELPER_PATH, category="samples"), "accordion", WEIGHTS, term_rank=3) >= 0.99
    # without the boost the same name would score much lower than the helper
    plain = item("user_library/Presets/Instruments/Sampler/Mine/Studio Accordion HN.adv")
    assert score_item(plain, "accordion", WEIGHTS) < 0.7 < score_item(helper, "accordion", WEIGHTS)


def test_helper_boost_needs_a_real_match_and_keeps_family_conflicts():
    helper = item("user_library/AbletonHelper/AbletonHelper Concert Harp.adv")
    assert score_item(helper, "accordion", WEIGHTS) == 0.0
    bass = item("user_library/AbletonHelper/AbletonHelper Accordion Bass.adv")
    assert score_item(bass, "accordion", WEIGHTS, allowed=set()) < score_item(bass, "accordion", WEIGHTS) <= 1.0


def test_installed_sample_instrument_beats_synthesis_in_auto_strategy():
    """Russian request 'хочу звук баяна' with bayan.json's own preset_search terms plus the installed pack."""
    recipe = LIB.get("bayan")
    terms = recipe.get("preset_search") or []
    assert terms, "bayan recipe must have preset_search"
    bridge = FakeBridge(browser_items=[{"path": "user_library/Presets/Instruments/Sampler/AbletonHelper/AbletonHelper "
                                               + terms[0].title() + " HN.adv", "loads": ["Sampler"]}], device_catalog=catalog())
    res = SoundEngine(bridge, LIB).create_sound(SoundRequest("хочу звук баяна"))
    assert res.ok and res.source == "preset" and "AbletonHelper" in res.preset["name"]
    assert [d["name"] for d in res.devices][0] == "Sampler"


def test_searcher_ranks_helper_first_and_ties_go_to_helper():
    bridge = FakeBridge(browser_items=[
        {"path": "sounds/Reed/Accordion.adg", "loads": ["Instrument Rack"]},
        {"path": HELPER_PATH, "loads": ["Sampler"]},
    ])
    ranked = PresetSearcher(bridge).search(["accordion"], recipe_category="reed")
    assert ranked[0]["path"] == HELPER_PATH and ranked[0]["score"] == ranked[1]["score"] == 1.0

"""SoundEngine behaviour against FakeBridge."""

import json

import pytest
from sound_testkit import FakeClock, ScriptedBridge, SlowIndexBridge, missing_devices, offline

from abhelper.bridge.base import BridgeCommandError
from abhelper.bridge.fake import FakeBridge
from abhelper.sound import RecipeLibrary, SoundEngine, SoundRequest, SoundResult

LIB = RecipeLibrary.load_default()


def engine(bridge, **kw):
    return SoundEngine(bridge, LIB, **kw)


def custom_recipe(**over):
    r = {
        "name": {"ru": "Жужжалка", "en": "Buzzer"},
        "category": "lead",
        "instrument": {"device": "Analog", "parameters": {"OSC1 Shape": "Rectangle", "F1 Freq": {"norm": 0.4}}},
        "effects": [{"device": "Reverb", "parameters": {"Dry/Wet": {"norm": 0.2}}}],
        "demo": {"style": "melody", "root": 64, "length": 8},
    }
    r.update(over)
    return r


# ------------------------------------------------------------------ recipe path (the main scenario)
def test_bayan_request_builds_a_track_from_the_recipe():
    """Selection by a Russian description + plumbing; assertions derive from the recipe (it gets redesigned often)."""
    recipe = LIB.get("bayan")
    chain = [recipe["instrument"]["device"]] + [fx["device"] for fx in recipe.get("effects", [])]
    bridge = FakeBridge(browser_items=[])
    res = engine(bridge).create_sound(SoundRequest("хочу звук баяна"))
    assert isinstance(res, SoundResult) and res.ok
    assert res.source == "recipe" and res.recipe_id == "bayan" and res.preset is None
    assert res.track_name == "Баян" and res.track_index == 0
    assert [d["name"] for d in res.devices] == chain
    assert res.demo_clip_slot == 0 and res.unmatched_parameters == [] and res.warnings == []
    assert res.message == f"Создана дорожка «Баян» ({' + '.join(chain)}), демо-клип в слоте 1."
    track = bridge.tracks[0]
    assert track.type == "midi" and track.color_index == recipe["track"]["color_index"]
    inst = next(d for d in track.devices if d.name == recipe["instrument"]["device"])
    params = {p.name: p for p in inst.parameters}
    for name, value in recipe["instrument"]["parameters"].items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and name in params:
            assert params[name].value == pytest.approx(value, abs=1e-6), name     # raw numbers go through verbatim
        elif isinstance(value, str) and name in params and params[name].value_items:
            assert params[name].value_items[int(params[name].value)] == value, name   # dropdown items by name
    assert track.slots[0].name == "Демо — Баян" and len(track.slots[0].notes) > 8


def test_result_is_json_serialisable():
    res = engine(FakeBridge(browser_items=[])).create_sound(SoundRequest("рояль", strategy="recipe"))
    data = res.to_dict()
    json.dumps(data, ensure_ascii=False)
    assert set(data) == {"ok", "track_index", "track_name", "source", "recipe_id", "preset", "devices",
                         "unmatched_parameters", "demo_clip_slot", "warnings", "message"}


def test_track_name_override_and_no_demo_clip():
    bridge = FakeBridge(browser_items=[])
    res = engine(bridge).create_sound(SoundRequest("рояль", track_name="Мой рояль", add_demo_clip=False))
    assert res.ok and res.track_name == "Мой рояль" and bridge.tracks[0].name == "Мой рояль"
    assert res.demo_clip_slot is None and all(s is None for s in bridge.tracks[0].slots)
    assert "демо-клип" not in res.message


def test_explicit_recipe_id_wins_over_description():
    res = engine(FakeBridge(browser_items=[])).create_sound(SoundRequest("что-нибудь", recipe_id="flute", strategy="recipe"))
    assert res.ok and res.recipe_id == "flute"


def test_unknown_recipe_id_fails_cleanly():
    bridge = FakeBridge()
    res = engine(bridge).create_sound(SoundRequest("x", recipe_id="flutee"))
    assert not res.ok and "flutee" in res.message and bridge.tracks == []
    assert any("flute" in w for w in res.warnings)


def test_invalid_strategy():
    res = engine(FakeBridge()).create_sound(SoundRequest("рояль", strategy="magic"))
    assert not res.ok and "magic" in res.message


# ------------------------------------------------------------------ preset path
def test_strong_browser_match_prefers_the_preset():
    bridge = FakeBridge()      # default browser has "Grand Piano.adg"
    res = engine(bridge).create_sound(SoundRequest("рояль"))
    assert res.ok and res.source == "preset" and res.recipe_id == "grand_piano"
    assert res.preset["name"] == "Grand Piano.adg" and res.preset["uri"].startswith("fake:")
    assert res.preset["score"] >= 0.9
    assert [d["name"] for d in res.devices] == ["Instrument Rack"]
    assert not any(c == "load_device" for c, _ in bridge.calls)
    assert "пресет «Grand Piano»" in res.message and "демо-клип" in res.message
    assert bridge.tracks[0].slots[res.demo_clip_slot] is not None


def test_custom_browser_items_drive_the_choice():
    items = [{"path": "sounds/Reed & Organ/Musette Accordion.adv", "loads": ["Analog"]}]
    bridge = FakeBridge(browser_items=items)
    res = engine(bridge).create_sound(SoundRequest("хочу звук баяна"))
    assert res.source == "preset" and res.recipe_id == "bayan"
    assert res.preset["name"] == "Musette Accordion.adv"
    assert [d["name"] for d in res.devices] == ["Analog"]


def test_weak_or_sample_matches_do_not_beat_the_recipe():
    # default browser only has an accordion *sample* -> synthesis from the recipe
    res = engine(FakeBridge()).create_sound(SoundRequest("баян"))
    assert res.ok and res.source == "recipe" and res.preset is None
    assert res.devices[0]["name"] == "Operator"


def test_unrelated_preset_names_are_ignored():
    items = [{"path": "sounds/Bass/Pianoforte Bass.adv"}, {"path": "sounds/Pad/Grand Canyon Pad.adv"}]
    res = engine(FakeBridge(browser_items=items)).create_sound(SoundRequest("рояль"))
    assert res.source == "recipe"


def test_strategy_recipe_ignores_available_presets():
    bridge = FakeBridge()
    res = engine(bridge).create_sound(SoundRequest("рояль", strategy="recipe"))
    assert res.source == "recipe"
    assert not any(c in ("browser_search", "load_browser_item") for c, _ in bridge.calls)


def test_strategy_preset_fails_without_a_preset_and_creates_nothing():
    bridge = FakeBridge(browser_items=[])
    res = engine(bridge).create_sound(SoundRequest("рояль", strategy="preset"))
    assert not res.ok and "пресет" in res.message and bridge.tracks == []


def test_strategy_preset_loads_when_found():
    res = engine(FakeBridge()).create_sound(SoundRequest("рояль", strategy="preset"))
    assert res.ok and res.source == "preset"


def test_explicit_preset_uri():
    bridge = FakeBridge()
    uri = next(i["uri"] for i in bridge.browser if i["name"].startswith("Warm Strings"))
    res = engine(bridge).create_sound(SoundRequest("что-то мягкое", preset_uri=uri))
    assert res.ok and res.source == "preset" and res.preset["uri"] == uri
    assert res.track_name == "Warm Strings Ensemble"
    assert bridge.tracks[0].slots[res.demo_clip_slot] is not None


def test_preset_search_terms_come_from_the_recipe_for_russian_queries():
    bridge = FakeBridge()
    eng = engine(bridge)
    found = eng.search_presets("скрипка")        # recipe terms: violin..., browser has nothing -> empty
    assert found == []
    found = eng.search_presets("струнные")
    assert found and found[0]["name"] == "Warm Strings Ensemble.adg" and found[0]["score"] >= 0.6


def test_failed_preset_load_in_auto_falls_back_to_the_recipe():
    bridge = ScriptedBridge(fail={"load_browser_item": BridgeCommandError("internal", "boom")})
    res = engine(bridge).create_sound(SoundRequest("рояль"))
    assert res.ok and res.source == "recipe" and res.preset is None
    assert any("не загрузился" in w for w in res.warnings)
    assert len(bridge.tracks) == 1


def test_failed_preset_load_in_strict_mode_is_a_clean_failure():
    bridge = ScriptedBridge(fail={"load_browser_item": BridgeCommandError("internal", "boom")})
    res = engine(bridge).create_sound(SoundRequest("рояль", strategy="preset"))
    assert not res.ok and "boom" in res.message
    assert res.track_index == 0 and len(bridge.tracks) == 1 and "оставлена в сете" in res.message


# ------------------------------------------------------------------ samples for Simpler recipes
def test_simpler_recipe_loads_a_sample_from_the_browser():
    recipe = custom_recipe(preset_search=["accordion"], instrument={"device": "Simpler", "parameters": {"Ve Attack": {"norm": 0.2}}})
    bridge = FakeBridge()        # has samples/One Shots/Accordion C3.wav
    res = engine(bridge).create_sound(SoundRequest("sample accordion", recipe=recipe, strategy="recipe"))
    assert res.ok and res.preset and res.preset["name"] == "Accordion C3.wav"
    assert res.devices[0]["name"] == "Simpler"
    assert res.unmatched_parameters == []


def test_simpler_without_a_sample_warns():
    recipe = custom_recipe(instrument={"device": "Simpler", "parameters": {}}, preset_search=["nonexistent"])
    res = engine(FakeBridge(browser_items=[])).create_sound(SoundRequest("x", recipe=recipe, strategy="recipe"))
    assert res.ok and any("без сэмпла" in w for w in res.warnings)


# ------------------------------------------------------------------ drum kits
def test_drum_kit_uses_a_preset_when_available():
    res = engine(FakeBridge()).create_sound(SoundRequest("ударные 808"))
    assert res.source == "preset" and res.preset["name"] == "808 Core Kit.adg"
    assert res.recipe_id == "drum_kit_808"


def test_drum_kit_without_preset_gives_an_empty_rack_with_a_warning():
    bridge = FakeBridge(browser_items=[])
    res = engine(bridge).create_sound(SoundRequest("ударные 808"))
    assert res.ok and res.source == "recipe" and res.devices[0]["name"] == "Drum Rack"
    assert any("Drum Rack" in w for w in res.warnings)
    notes = bridge.tracks[0].slots[res.demo_clip_slot].notes
    assert {n["pitch"] for n in notes} <= {36, 38, 39, 42, 46}


# ------------------------------------------------------------------ nothing found / custom recipes
def test_no_recipe_and_no_preset_asks_the_agent_to_design_one():
    bridge = FakeBridge(browser_items=[])
    res = engine(bridge).create_sound(SoundRequest("звук работающего пылесоса"))
    assert not res.ok and bridge.tracks == []
    assert "собственный рецепт" in res.message and "design_custom_sound" in res.message
    assert res.track_index is None


def test_low_scoring_candidates_are_listed_in_warnings():
    res = engine(FakeBridge(browser_items=[])).create_sound(SoundRequest("мягкий бас с воздухом"))
    assert not res.ok or res.source in ("recipe", "preset")
    if not res.ok:
        assert res.warnings and "Ближайшие рецепты" in res.warnings[0]


def test_the_users_own_english_words_are_searched_in_the_browser_too():
    items = [{"path": "sounds/Synth Keys/Vacuum Tube Keys.adv"}]
    res = engine(FakeBridge(browser_items=items)).create_sound(SoundRequest("vacuum tube keys"))
    assert res.ok and res.source == "preset"
    assert res.preset["name"] == "Vacuum Tube Keys.adv" and res.preset["score"] >= 0.9
    assert res.track_name == LIB.get(res.recipe_id)["track"]["name"]


def test_preset_without_any_recipe_uses_the_preset_name_for_the_track():
    items = [{"path": "sounds/Synth Keys/Quartz Shimmer.adv", "loads": ["Wavetable"]}]
    bridge = FakeBridge(browser_items=items)
    res = engine(bridge).create_sound(SoundRequest("quartz shimmer"))
    assert res.ok and res.source == "preset" and res.recipe_id is None
    assert res.track_name == "Quartz Shimmer" and bridge.tracks[0].name == "Quartz Shimmer"
    assert bridge.tracks[0].slots[res.demo_clip_slot] is not None


def test_custom_recipe_is_applied_and_gets_an_id():
    bridge = FakeBridge(browser_items=[])
    eng = engine(bridge)
    res = eng.create_sound(SoundRequest("жужжащий лид", recipe=custom_recipe()))
    assert res.ok and res.source == "custom_recipe" and res.recipe_id == "custom_1"
    assert res.track_name == "Жужжалка"
    assert [d["name"] for d in res.devices] == ["Analog", "Reverb"]
    assert res.unmatched_parameters == []
    res2 = eng.create_sound(SoundRequest("ещё", recipe=custom_recipe(id="my_buzz")))
    assert res2.recipe_id == "my_buzz"
    res3 = eng.create_sound(SoundRequest("ещё", recipe=custom_recipe()))
    assert res3.recipe_id == "custom_2"
    clip = bridge.tracks[0].slots[res.demo_clip_slot]
    assert clip.length == 8 and min(n["pitch"] for n in clip.notes) >= 64


def test_custom_recipe_beats_library_match_and_skips_preset_search_by_default():
    bridge = FakeBridge()        # a grand-piano preset exists
    res = engine(bridge).create_sound(SoundRequest("рояль", recipe=custom_recipe()))
    assert res.source == "custom_recipe" and res.preset is None
    assert not any(c == "browser_search" for c, _ in bridge.calls)


def test_custom_recipe_with_preset_search_may_use_a_preset():
    res = engine(FakeBridge()).create_sound(SoundRequest("рояль", recipe=custom_recipe(preset_search=["grand piano"])))
    assert res.ok and res.source == "preset" and res.recipe_id == "custom_1"


def test_invalid_custom_recipe_is_rejected_without_touching_live():
    bridge = FakeBridge()
    res = engine(bridge).create_sound(SoundRequest("x", recipe={"instrument": {}, "category": "nope"}))
    assert not res.ok and "не прошёл проверку" in res.message and res.warnings
    assert bridge.tracks == [] and not bridge.calls


def test_custom_recipe_unknown_parameters_are_reported_not_fatal():
    recipe = custom_recipe(instrument={"device": "Analog", "parameters": {
        "OSC1 Shape": "Banana", "Nonexistent Knob": 3, "F1 Freq": {"norm": 0.3}}})
    res = engine(FakeBridge(browser_items=[])).create_sound(SoundRequest("x", recipe=recipe))
    assert res.ok
    reasons = {u["parameter"]: u for u in res.unmatched_parameters}
    assert set(reasons) == {"OSC1 Shape", "Nonexistent Knob"}
    assert reasons["OSC1 Shape"]["device"] == "Analog" and "Banana" in reasons["OSC1 Shape"]["reason"]
    assert "параметр не найден" in reasons["Nonexistent Knob"]["reason"]
    assert "Замечаний" not in res.message and "Не удалось применить параметров: 2" in res.message


def test_failing_effects_are_warnings_and_do_not_stop_the_build():
    recipe = custom_recipe(effects=[{"device": "Flux Capacitor"}, {"device": "Reverb", "parameters": {"Dry/Wet": {"norm": 0.3}}}])
    res = engine(FakeBridge(browser_items=[])).create_sound(SoundRequest("x", recipe=recipe))
    assert res.ok and [d["name"] for d in res.devices] == ["Analog", "Reverb"]
    assert any("Flux Capacitor" in w for w in res.warnings)


def test_effect_name_alternatives_are_tried():
    # an older Live names the effect "Chorus"; FakeBridge only knows it when the catalog has it
    catalog = {"Operator": {"class_name": "Operator", "type": "instrument", "parameters": []},
               "Chorus": {"class_name": "Chorus", "type": "audio_effect", "parameters": []}}
    bridge = ScriptedBridge(device_catalog=catalog, browser_items=[],
                            fail={"load_device": missing_devices("Chorus-Ensemble")})
    recipe = custom_recipe(instrument={"device": "Operator"}, effects=[{"device": "Chorus-Ensemble"}])
    res = engine(bridge).create_sound(SoundRequest("x", recipe=recipe))
    assert res.ok and [d["name"] for d in res.devices] == ["Operator", "Chorus"]


# ------------------------------------------------------------------ fallback devices
def test_primary_instrument_missing_uses_the_fallback_with_its_parameters():
    inst = LIB.get("bayan")["instrument"]
    primary, fallback = inst["device"], inst["fallback_devices"][0]
    assert fallback in inst["fallback_parameters"], "the first fallback of 'bayan' must carry its own parameters"
    bridge = ScriptedBridge(browser_items=[], fail={"load_device": missing_devices(primary)})
    res = engine(bridge).create_sound(SoundRequest("баян"))
    assert res.ok and res.devices[0]["name"] == fallback
    assert any(f"{primary} недоступен" in w and fallback in w for w in res.warnings)
    assert res.unmatched_parameters == []
    dev = bridge.tracks[0].devices[0]
    values = {p.name: p.value for p in dev.parameters}
    checked = 0
    for name, value in inst["fallback_parameters"][fallback].items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and name in values:
            assert values[name] == pytest.approx(value, abs=1e-6), name
            checked += 1
    assert checked, "fallback parameters should reach the fallback device"


def test_fallback_without_parameters_warns():
    bridge = ScriptedBridge(browser_items=[], fail={"load_device": missing_devices("Analog")})
    res = engine(bridge).create_sound(SoundRequest("x", recipe=custom_recipe(
        instrument={"device": "Analog", "fallback_devices": ["Operator"], "parameters": {"F1 Freq": {"norm": 0.5}}})))
    assert res.ok and res.devices[0]["name"] == "Operator"
    assert any("не применены" in w for w in res.warnings)


def test_all_instruments_missing_keeps_the_track_and_reports():
    inst = LIB.get("bayan")["instrument"]
    chain = [inst["device"]] + inst["fallback_devices"]
    bridge = ScriptedBridge(browser_items=[], fail={"load_device": missing_devices(*chain)})
    res = engine(bridge).create_sound(SoundRequest("баян"))
    assert not res.ok and inst["device"] in res.message and "оставлена в сете" in res.message
    assert res.track_index == 0 and len(bridge.tracks) == 1 and res.demo_clip_slot is None


# ------------------------------------------------------------------ existing track
def test_existing_midi_track_is_reused():
    bridge = FakeBridge(browser_items=[], tracks=2)
    bridge.call("load_device", {"track_index": 1, "device_name": "Wavetable"})
    bridge.call("load_device", {"track_index": 1, "device_name": "Reverb"})
    res = engine(bridge).create_sound(SoundRequest("баян", track_index=1))
    assert res.ok and res.track_index == 1 and len(bridge.tracks) == 2
    assert not any(c == "create_midi_track" for c, _ in bridge.calls)
    names = [d.name for d in bridge.tracks[1].devices]
    assert names[0] == "Operator" and "Wavetable" not in names
    assert names.count("Reverb") == 1            # existing effect re-used, not duplicated
    assert res.message.startswith("Обновлена дорожка")
    assert res.track_name == "2-MIDI"            # name untouched unless requested
    assert bridge.tracks[1].slots[res.demo_clip_slot] is not None


def test_existing_track_can_be_renamed():
    bridge = FakeBridge(browser_items=[], tracks=1)
    res = engine(bridge).create_sound(SoundRequest("рояль", track_index=0, track_name="Клавиши"))
    assert bridge.tracks[0].name == "Клавиши" and res.track_name == "Клавиши"


def test_existing_track_must_be_midi_and_exist():
    bridge = FakeBridge(browser_items=[])
    bridge.call("create_audio_track", {})
    res = engine(bridge).create_sound(SoundRequest("рояль", track_index=0))
    assert not res.ok and "не MIDI" in res.message
    res = engine(bridge).create_sound(SoundRequest("рояль", track_index=9))
    assert not res.ok and "does not exist" in res.message


def test_existing_track_with_preset():
    bridge = FakeBridge(tracks=1)
    res = engine(bridge).create_sound(SoundRequest("рояль", track_index=0))
    assert res.ok and res.source == "preset" and len(bridge.tracks) == 1


# ------------------------------------------------------------------ bridge errors never raise
def test_connection_error_becomes_a_result():
    bridge = ScriptedBridge(fail={"create_midi_track": offline()})
    res = engine(bridge).create_sound(SoundRequest("рояль", strategy="recipe"))
    assert not res.ok and "Нет связи" in res.message and res.track_index is None


def test_connection_lost_mid_way_reports_progress():
    bridge = ScriptedBridge(browser_items=[], fail={"load_device": lambda p: offline() if p["device_name"] == "Reverb" else None})
    res = engine(bridge).create_sound(SoundRequest("баян"))
    assert not res.ok and "Нет связи" in res.message
    assert "оставлена в сете" in res.message and "создана дорожка «Баян»" in res.message
    assert len(bridge.tracks) == 1


@pytest.mark.parametrize("command", ["create_midi_track", "get_device_parameters", "set_device_parameters", "load_device",
                                     "create_clip", "add_notes", "get_track_info", "browser_search", "browser_status"])
@pytest.mark.parametrize("exc", [BridgeCommandError("internal", "kaboom"), offline()])
def test_any_failing_command_yields_a_result_without_raising(command, exc):
    bridge = ScriptedBridge(fail={command: exc})
    res = engine(bridge).create_sound(SoundRequest("баян"))
    assert isinstance(res, SoundResult)
    assert isinstance(res.message, str) and res.message
    if not res.ok:
        assert res.message


def test_demo_clip_failure_is_only_a_warning():
    bridge = ScriptedBridge(browser_items=[], fail={"add_notes": BridgeCommandError("internal", "no notes")})
    res = engine(bridge).create_sound(SoundRequest("баян"))
    assert res.ok and any("Демо-клип не создан" in w for w in res.warnings)


def test_rejected_parameters_from_the_bridge_are_unmatched():
    class Rejecting(FakeBridge):
        def _cmd_set_device_parameters(self, track_index, device_index, values):
            out = super()._cmd_set_device_parameters(track_index, device_index, values)
            if "Algorithm" in values:
                out["failed"].append({"parameter": "Algorithm", "code": "bad_request", "message": "nope"})
            return out

    res = engine(Rejecting(browser_items=[])).create_sound(SoundRequest("баян"))
    assert res.ok and any(u["parameter"] == "Algorithm" and "nope" in u["reason"] for u in res.unmatched_parameters)


# ------------------------------------------------------------------ browser index warm-up
def test_incomplete_index_is_retried_briefly_with_injectable_sleep():
    clock = FakeClock()
    bridge = SlowIndexBridge(incomplete_polls=3)
    res = engine(bridge, sleep=clock.sleep, clock=clock.clock).create_sound(SoundRequest("рояль"))
    assert res.source == "preset"                       # found once the index completed
    assert clock.sleeps and sum(clock.sleeps) <= 3.0 + 0.5


def test_index_that_never_completes_gives_up_after_three_seconds():
    clock = FakeClock()
    bridge = SlowIndexBridge(incomplete_polls=10_000)
    res = engine(bridge, sleep=clock.sleep, clock=clock.clock).create_sound(SoundRequest("рояль"))
    assert res.ok and res.source == "recipe"            # fell back to synthesis
    assert 2.5 <= sum(clock.sleeps) <= 3.0 + 0.5


def test_complete_index_does_not_sleep():
    clock = FakeClock()
    engine(FakeBridge(), sleep=clock.sleep, clock=clock.clock).create_sound(SoundRequest("рояль"))
    assert clock.sleeps == []


# ------------------------------------------------------------------ apply_parameters / fuzzy names
def _op_track():
    bridge = FakeBridge()
    bridge.call("create_midi_track", {})
    bridge.call("load_device", {"track_index": 0, "device_name": "Operator"})
    return bridge


def _value(bridge, name, device=0):
    return next(p for p in bridge.tracks[0].devices[device].parameters if p.name == name)


def test_apply_parameters_fuzzy_names_and_aliases():
    bridge = _op_track()
    unmatched = engine(bridge).apply_parameters(0, 0, {
        "Filter Freq": {"norm": 0.25},            # exact
        "filter res": {"norm": 0.4},              # case-insensitive
        "OscALevel": {"norm": 0.4},               # normalised against "Osc-A Level"
        "A Wave": "Square D",                     # alias group + string item
        "Cutoff Nonsense": 1,                     # nothing
    })
    assert [u["parameter"] for u in unmatched] == ["Cutoff Nonsense"]
    assert _value(bridge, "Filter Freq").value == pytest.approx(0.25)
    assert _value(bridge, "Filter Res").value == pytest.approx(0.5)     # Operator "Filter Res" is 0..1.25
    assert _value(bridge, "Osc-A Level").value == pytest.approx(0.4)
    wave = _value(bridge, "Osc-A Wave")
    assert wave.value_items[int(wave.value)] == "Square D"
    sets = [p for c, p in bridge.calls if c == "set_device_parameters"]
    assert len(sets) == 1, "all matched values go out in one call"


def test_apply_parameters_alias_for_filter_frequency():
    bridge = FakeBridge()
    bridge.call("create_midi_track", {})
    bridge.call("load_device", {"track_index": 0, "device_name": "Wavetable"})
    unmatched = engine(bridge).apply_parameters(0, 0, {"Cutoff": {"norm": 0.3}, "Resonance": {"norm": 0.2}})
    assert unmatched == []
    assert _value(bridge, "Filter 1 Freq").value == pytest.approx(0.3)


def test_string_values_are_resolved_loosely_and_failures_explained():
    bridge = _op_track()
    unmatched = engine(bridge).apply_parameters(0, 0, {"Osc-B Wave": "saw d", "Filter Type": "low pass", "Osc-C Wave": "Kazoo"})
    assert [u["parameter"] for u in unmatched] == ["Osc-C Wave"]
    assert "Kazoo" in unmatched[0]["reason"] and "Sine" in unmatched[0]["reason"]
    ft = _value(bridge, "Filter Type")
    assert ft.value_items[int(ft.value)] == "Lowpass"


def test_unmatched_entries_suggest_close_names():
    bridge = _op_track()
    (u,) = engine(bridge).apply_parameters(0, 0, {"Filter Frequncy": 1})
    assert u["parameter"] == "Filter Frequncy" and u["device"] == "Operator"
    assert "Filter Freq" in u.get("suggestions", [])


def test_two_keys_for_one_parameter_do_not_overwrite_each_other_silently():
    bridge = _op_track()
    unmatched = engine(bridge).apply_parameters(0, 0, {"Filter Freq": {"norm": 0.2}, "Cutoff": {"norm": 0.9}})
    assert len(unmatched) == 1 and "дубль" in unmatched[0]["reason"]
    assert _value(bridge, "Filter Freq").value == pytest.approx(0.2)


def test_raw_numbers_and_booleans_pass_through():
    bridge = _op_track()
    assert engine(bridge).apply_parameters(0, 0, {"Algorithm": 4, "Osc-B On": True, "Transpose": -12}) == []
    assert _value(bridge, "Algorithm").value == 4 and _value(bridge, "Osc-B On").value == 1
    assert _value(bridge, "Transpose").value == -12


def test_apply_parameters_with_nothing_to_set_makes_no_set_call():
    bridge = _op_track()
    assert engine(bridge).apply_parameters(0, 0, {}) == []
    assert not any(c == "set_device_parameters" for c, _ in bridge.calls)


# ------------------------------------------------------------------ library helpers on the engine
def test_find_recipes_and_search_presets_delegate():
    eng = engine(FakeBridge())
    assert eng.find_recipes("рояль", 3)[0].recipe_id == "grand_piano"
    presets = eng.search_presets("piano", terms=["piano", "electric piano"], limit=5)
    names = [p["name"] for p in presets]
    assert "Grand Piano.adg" in names and "Electric Piano Mk I.adg" in names
    assert all("score" in p for p in presets) and presets == sorted(presets, key=lambda p: -p["score"])


def test_search_presets_without_matches_is_empty():
    assert engine(FakeBridge()).search_presets("zzzxx") == []


def test_search_presets_survives_bridge_command_errors():
    bridge = ScriptedBridge(fail={"browser_search": BridgeCommandError("unsupported", "no browser")})
    assert engine(bridge).search_presets("piano") == []


def test_helper_sample_preset_found_without_browser_index():
    """On a big Suite library the index may not reach the User Library: the engine lists the known folder."""
    from abhelper.bridge.fake import FakeBridge
    from abhelper.sound import SoundEngine, SoundRequest

    path = "user_library/Presets/Instruments/Sampler/AbletonHelper/AbletonHelper Accordion HN.adv"
    b = FakeBridge(browser_items=[{"path": path, "loads": ["Sampler"]}])
    b._cmd_browser_search = lambda **kw: {"items": [], "index_complete": False}   # index never got there
    b._cmd_browser_status = lambda: {"indexed": 60000, "complete": True, "scanning": False, "truncated": True}
    res = SoundEngine(b, sleep=lambda s: None).create_sound(SoundRequest(description="хочу звук баяна"))
    assert res.ok and res.source == "preset", res.to_dict()
    assert res.preset["name"] == "AbletonHelper Accordion HN.adv"

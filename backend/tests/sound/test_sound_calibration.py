"""Calibration helpers: dump the device catalog from Live (FakeBridge here) and merge it."""

import json

import pytest
from sound_testkit import ScriptedBridge, offline

from abhelper.bridge.base import BridgeCommandError, BridgeConnectionError
from abhelper.bridge.fake import FakeBridge
from abhelper.sound import RecipeLibrary, SoundEngine, SoundRequest, dump_device_catalog, merge_catalog, recipe_device_names
from abhelper.sound.calibration import TEMP_TRACK_NAME, load_catalog, save_catalog


def test_dump_records_parameters_and_cleans_up():
    bridge = FakeBridge(tracks=1)
    cat = dump_device_catalog(bridge, ["Operator", "Reverb", "EQ Eight"])
    assert cat["_meta"]["verified"] is True and cat["_meta"]["live_version"] == "12.1.0 (fake)"
    assert set(cat["devices"]) == {"Operator", "Reverb", "EQ Eight"}
    op = cat["devices"]["Operator"]
    assert op["type"] == "instrument" and op["class_name"] == "Operator"
    wave = next(p for p in op["parameters"] if p["name"] == "Osc-A Wave")
    assert wave["is_quantized"] and "Saw D" in wave["value_items"] and set(wave) >= {"name", "min", "max", "default", "value_items"}
    assert any(p["name"] == "Dry/Wet" for p in cat["devices"]["Reverb"]["parameters"])
    # the user's own track is untouched, the temp track and devices are gone
    assert len(bridge.tracks) == 1 and bridge.tracks[0].devices == []
    assert all(t.name != TEMP_TRACK_NAME for t in bridge.tracks)
    json.dumps(cat)


def test_dump_records_display_samples_for_continuous_parameters_only():
    bridge = FakeBridge(tracks=1)
    cat = dump_device_catalog(bridge, ["Operator", "Reverb"])
    params = cat["devices"]["Reverb"]["parameters"]
    cont = [p for p in params if not p["is_quantized"]]
    assert cont and all(len(p["display_samples"]) == 9 for p in cont)
    first = cont[0]["display_samples"]
    assert first[0][0] == cont[0]["min"] and first[-1][0] == cont[0]["max"]
    assert all(isinstance(r, float) and isinstance(t, str) for r, t in first)
    assert all("display_samples" not in p for p in params if p["is_quantized"])
    asked = [p for c, p in bridge.calls if c == "get_parameter_displays"]
    assert asked and all(p["samples"] == 9 for p in asked)
    json.dumps(cat)


def test_old_remote_script_without_get_parameter_displays_still_calibrates():
    bridge = ScriptedBridge(fail={"get_parameter_displays": BridgeCommandError("unknown_command", "nope")})
    msgs = []
    cat = dump_device_catalog(bridge, ["Operator", "Reverb"], progress=msgs.append)
    assert set(cat["devices"]) == {"Operator", "Reverb"} and not cat["_meta"].get("failed")
    assert all("display_samples" not in p for d in cat["devices"].values() for p in d["parameters"])
    assert "get_parameter_displays" in cat["_meta"]["note"]
    assert [c for c, _ in bridge.calls].count("get_parameter_displays") == 1, "not retried for every device"
    assert bridge.tracks == []


def test_other_display_errors_are_reported_per_device():
    bridge = ScriptedBridge(fail={"get_parameter_displays": BridgeCommandError("internal", "boom")})
    cat = dump_device_catalog(bridge, ["Operator"])
    assert "internal" in cat["_meta"]["failed"]["Operator"] and bridge.tracks == []


def test_merge_keeps_display_samples():
    new = {"_meta": {"verified": True}, "devices": {"Reverb": {"parameters": [
        {"name": "Dry/Wet", "display_samples": [[0.0, "0 %"], [1.0, "100 %"]]}]}}}
    merged = merge_catalog({"_meta": {}, "devices": {}}, new)
    assert merged["devices"]["Reverb"]["parameters"][0]["display_samples"] == [[0.0, "0 %"], [1.0, "100 %"]]


def test_dump_creates_and_deletes_a_temporary_track_in_order():
    bridge = FakeBridge()
    dump_device_catalog(bridge, ["Operator", "Reverb"])
    cmds = [c for c, _ in bridge.calls]
    assert cmds[0] == "ping" and cmds[1] == "create_midi_track" and cmds[-1] == "delete_track"
    assert cmds.count("load_device") == 2 and cmds.count("delete_device") == 2
    assert bridge.tracks == []


def test_unknown_devices_are_reported_not_fatal():
    bridge = FakeBridge()
    cat = dump_device_catalog(bridge, ["Operator", "Imaginary Synth"])
    assert "Imaginary Synth" in cat["_meta"]["failed"] and "not_found" in cat["_meta"]["failed"]["Imaginary Synth"]
    assert list(cat["devices"]) == ["Operator"]
    assert bridge.tracks == []


def test_track_is_deleted_even_if_the_bridge_dies_mid_dump():
    bridge = ScriptedBridge(fail={"get_device_parameters": lambda p: offline()})
    with pytest.raises(BridgeConnectionError):
        dump_device_catalog(bridge, ["Operator"])
    assert bridge.tracks == [] , "temporary track must be removed in finally"


def test_track_is_deleted_if_progress_callback_explodes():
    bridge = FakeBridge()

    def boom(_msg):
        raise RuntimeError("ui crashed")

    with pytest.raises(RuntimeError):
        dump_device_catalog(bridge, ["Operator"], progress=boom)
    assert bridge.tracks == []


def test_device_is_removed_when_reading_parameters_fails():
    bridge = ScriptedBridge(fail={"get_device_parameters": BridgeCommandError("internal", "x")})
    cat = dump_device_catalog(bridge, ["Operator", "Reverb"])
    assert cat["devices"] == {} and set(cat["_meta"]["failed"]) == {"Operator", "Reverb"}
    assert bridge.tracks == []


def test_dumped_catalog_round_trips_into_a_fake_bridge():
    cat = dump_device_catalog(FakeBridge(), ["Operator", "Reverb"])
    bridge = FakeBridge(device_catalog=cat["devices"], browser_items=[])
    bridge.call("create_midi_track", {})
    out = bridge.call("load_device", {"track_index": 0, "device_name": "Operator"})
    assert out["name"] == "Operator"
    params = bridge.call("get_device_parameters", {"track_index": 0, "device_index": 0})["parameters"]
    assert [p["name"] for p in params][1:] == [p["name"] for p in cat["devices"]["Operator"]["parameters"] if p["name"] != "Device On"]


def test_merge_overrides_and_keeps_old_devices():
    old = {"_meta": {"verified": False, "note": "hand"}, "devices": {"Operator": {"parameters": [{"name": "old"}]}, "Delay": {"parameters": []}}}
    new = {"_meta": {"verified": True, "live_version": "12.1"}, "devices": {"Operator": {"parameters": [{"name": "new"}]}, "Reverb": {"parameters": []}}}
    merged = merge_catalog(old, new)
    assert set(merged["devices"]) == {"Operator", "Delay", "Reverb"}
    assert merged["devices"]["Operator"]["parameters"][0]["name"] == "new"
    assert merged["_meta"]["live_version"] == "12.1"
    assert merged["_meta"]["verified"] is False                 # Delay is still hand-written
    assert old["devices"]["Operator"]["parameters"][0]["name"] == "old", "inputs are not mutated"


def test_merge_fully_verified_and_failed_bookkeeping():
    old = {"_meta": {"verified": True, "failed": {"Meld": "not_found", "Reverb": "x"}}, "devices": {}}
    new = {"_meta": {"verified": True, "failed": {"Corpus": "not_found"}}, "devices": {"Reverb": {"parameters": []}}}
    merged = merge_catalog(old, new)
    assert merged["_meta"]["verified"] is True
    assert merged["_meta"]["failed"] == {"Meld": "not_found", "Corpus": "not_found"}
    assert merge_catalog({}, new)["devices"].keys() == {"Reverb"}
    assert "failed" not in merge_catalog(old, {"_meta": {"verified": True}, "devices": {"Meld": {}, "Reverb": {}}})["_meta"]


def test_recipe_device_names_cover_the_whole_library():
    lib = RecipeLibrary.load_default()
    names = recipe_device_names(lib)
    assert {"Operator", "Analog", "Wavetable", "Simpler", "Drum Rack", "Reverb", "EQ Eight", "Chorus-Ensemble", "Auto Filter"} <= set(names)
    cat = dump_device_catalog(FakeBridge(), names)
    assert not cat["_meta"].get("failed")


def test_a_dumped_catalog_still_drives_the_engine():
    """Calibrating with the (fake) 'real' Live and re-running recipes must not regress."""
    lib = RecipeLibrary.load_default()
    cat = dump_device_catalog(FakeBridge(), recipe_device_names(lib))
    bridge = FakeBridge(device_catalog=cat["devices"], browser_items=[])
    res = SoundEngine(bridge, lib).create_sound(SoundRequest("хочу звук баяна"))
    assert res.ok and res.unmatched_parameters == []


def test_catalog_file_save_and_load(tmp_path):
    cat = {"_meta": {"verified": True}, "devices": {"Операторный": {"parameters": []}}}
    path = tmp_path / "cat.json"
    save_catalog(cat, path)
    assert load_catalog(path) == cat

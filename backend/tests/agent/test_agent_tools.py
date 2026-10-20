import json

import pytest

from abhelper.agent.testing import StubEngine
from abhelper.agent.tools import TOOL_NAMES, TOOL_SCHEMAS, ToolExecutor, get_tools, validate_input
from abhelper.bridge.fake import FakeBridge
from abhelper.knowledge import KnowledgeBase

EXPECTED_TOOLS = ["get_session_overview", "get_track_details", "search_sound_library", "search_live_browser",
                  "create_sound", "design_custom_sound", "get_device_parameters", "set_device_parameters",
                  "load_device", "create_midi_clip", "transport", "undo_last_action", "search_ableton_help",
                  "rename_track", "delete_track"]


def make(bridge=None, **kw):
    bridge = bridge or FakeBridge()
    return ToolExecutor(bridge, StubEngine(bridge), KnowledgeBase("/nonexistent"), **kw), bridge


def test_tool_list_matches_contract_and_is_deterministic():
    assert sorted(TOOL_NAMES) == sorted(EXPECTED_TOOLS)
    assert get_tools() == get_tools()
    for t in get_tools():
        assert t["description"] and t["input_schema"]["type"] == "object"


def test_strict_tools_fit_strict_rules():
    strict = [t for t in TOOL_SCHEMAS if t.get("strict")]
    assert {t["name"] for t in strict} >= {"get_session_overview", "search_sound_library", "delete_track"}
    for t in strict:
        s = t["input_schema"]
        assert s["additionalProperties"] is False
        assert set(s["properties"]) == set(s["required"])
    for name in ("design_custom_sound", "create_sound", "set_device_parameters", "create_midi_clip"):
        assert not next(t for t in TOOL_SCHEMAS if t["name"] == name).get("strict")
    assert all("strict" not in t for t in get_tools(strict=False))


def test_descriptions_carry_key_guidance():
    d = {t["name"]: t["description"] for t in TOOL_SCHEMAS}
    assert "native Live devices only" in d["load_device"]
    assert "unmatched_parameters" in d["create_sound"]
    assert '"instrument"' in d["design_custom_sound"] and "Example" in d["design_custom_sound"]
    assert "created in this conversation" in d["delete_track"]


def test_validator():
    schema = {"type": "object", "properties": {"a": {"type": "integer", "minimum": 0}, "b": {"enum": ["x"]},
                                                 "c": {"type": "array", "items": {"type": "number"}}},
              "required": ["a"], "additionalProperties": False}
    assert validate_input(schema, {"a": 1, "c": [1, 2.5]}) == []
    assert validate_input(schema, {}) == ["input: missing required 'a'"]
    assert validate_input(schema, {"a": True})  # bool is not integer
    assert validate_input(schema, {"a": -1})
    assert validate_input(schema, {"a": 1, "z": 1})
    assert validate_input(schema, {"a": 1, "c": [1, "x"]})
    assert validate_input(schema, {"a": 1, "b": "y"})
    assert validate_input(schema, [])


def test_session_overview_and_track_details():
    ex, bridge = make()
    bridge.call("create_midi_track", {"name": "Лид"})
    bridge.call("load_device", {"track_index": 0, "device_name": "Operator"})
    r = ex.execute("get_session_overview", {})
    assert r.ok and r.data["tracks"][0]["name"] == "Лид" and r.data["tracks"][0]["devices"][0]["name"] == "Operator"
    d = ex.execute("get_track_details", {"track_index": 0})
    assert d.ok and d.data["clips"] == [] and d.data["free_slots"][0] == 0
    bad = ex.execute("get_track_details", {"track_index": 9})
    assert not bad.ok and bad.code == "not_found"


def test_device_parameters_truncated_and_set():
    cat = {"Operator": {"class_name": "Operator", "type": "instrument", "parameters": (
        [{"name": f"P{i}", "min": 0, "max": 1, "default": 0} for i in range(200)]
        + [{"name": "Osc-A Wave", "min": 0, "max": 2, "value_items": ["Sine", "Saw D", "Square D"]}])}}
    ex, bridge = make(FakeBridge(device_catalog=cat))
    bridge.call("create_midi_track")
    bridge.call("load_device", {"track_index": 0, "device_name": "Operator"})
    r = ex.execute("get_device_parameters", {"track_index": 0, "device_index": 0})
    assert r.ok and len(r.data["parameters"]) == 120 and r.data["truncated"] and r.data["total"] == 202
    s = ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0,
                                             "values": {"p3": {"norm": 0.5}, "Osc-A Wave": "Saw D", "Nope": 1}})
    assert s.ok and len(s.data["applied"]) == 2 and s.data["failed"][0]["parameter"] == "Nope"
    assert "не найдено: 1" in s.summary
    allbad = ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0, "values": {"Nope": 1}})
    assert not allbad.ok
    assert not ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0, "values": {}}).ok
    assert not ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0,
                                                    "values": {"P1": {"norm": 5}}}).ok
    assert not ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0,
                                                    "values": {"P1": None}}).ok


def test_set_device_parameters_accepts_display_values():
    ex, bridge = make()
    bridge.call("create_midi_track")
    bridge.call("load_device", {"track_index": 0, "device_name": "Reverb"})
    r = ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0,
                                             "values": {"Dry/Wet": {"display": "30 %"}}})
    assert r.ok and r.data["applied"][0]["name"] == "Dry/Wet"
    for bad in ({"display": ""}, {"display": 5}, {"display": "1 kHz", "norm": 1}):
        assert not ex.execute("set_device_parameters", {"track_index": 0, "device_index": 0,
                                                        "values": {"Dry/Wet": bad}}).ok


def test_tool_descriptions_teach_the_display_form():
    from abhelper.agent.tools import TOOL_SCHEMAS
    for name in ("set_device_parameters", "design_custom_sound"):
        text = next(t["description"] for t in TOOL_SCHEMAS if t["name"] == name)
        assert '{"display": "1.3 kHz"}' in text and "ALWAYS" in text and "norm" in text


def test_create_midi_clip_and_conflict():
    ex, bridge = make()
    bridge.call("create_midi_track")
    notes = [{"pitch": 60, "start": 0, "duration": 1}, {"pitch": 64, "start": 1, "duration": 1, "velocity": 90}]
    r = ex.execute("create_midi_clip", {"track_index": 0, "notes": notes, "length": 4, "name": "Idea", "fire": True})
    assert r.ok and r.data["notes_added"] == 2 and r.data["fired"]
    assert bridge.tracks[0].slots[0].is_playing
    c = ex.execute("create_midi_clip", {"track_index": 0, "notes": notes, "length": 4, "slot_index": 0})
    assert not c.ok and c.code == "conflict"
    assert not ex.execute("create_midi_clip", {"track_index": 0, "notes": [], "length": 4}).ok
    assert not ex.execute("create_midi_clip", {"track_index": 0, "length": 4}).ok
    assert not ex.execute("create_midi_clip", {"track_index": 0, "length": 4, "notes": [
        {"pitch": 200, "start": 0, "duration": 1}]}).ok


def test_transport_undo_rename_delete():
    ex, bridge = make()
    assert ex.execute("transport", {"action": "set_tempo", "tempo": 140}).ok and bridge.tempo == 140
    assert not ex.execute("transport", {"action": "set_tempo", "tempo": 5}).ok
    assert not ex.execute("transport", {"action": "dance"}).ok
    assert ex.execute("undo_last_action", {}).summary == "Отменять нечего"
    bridge.call("create_midi_track", {"name": "A"})
    assert ex.execute("rename_track", {"track_index": 0, "name": "Бас"}).ok and bridge.tracks[0].name == "Бас"
    d = ex.execute("delete_track", {"track_index": 0})
    assert d.ok and d.summary == "Удалена дорожка «Бас»" and bridge.tracks == []
    assert ex.execute("undo_last_action", {}).data["done"] is True and len(bridge.tracks) == 1


def test_load_device_uses_long_timeout():
    ex, bridge = make()
    seen = {}
    orig = bridge.call
    bridge.call = lambda c, p=None, timeout=None: (seen.__setitem__(c, timeout), orig(c, p, timeout))[1]
    bridge.tracks.append(__import__("abhelper.bridge.fake", fromlist=["FakeTrack"]).FakeTrack("t", "midi"))
    assert ex.execute("load_device", {"track_index": 0, "device_name": "Reverb"}).ok
    assert seen["load_device"] and seen["load_device"] >= 30


def test_design_custom_sound_validation_and_request():
    calls = []
    ex, bridge = make(recipe_validator=lambda r: [] if r.get("instrument", {}).get("device") != "Bad" else ["no good"])
    r = ex.execute("design_custom_sound", {"description": "x", "recipe": {"instrument": {"device": "Bad"}}})
    assert not r.ok and r.code == "invalid_recipe" and r.data["validation_errors"] == ["no good"]
    ok = ex.execute("design_custom_sound", {"description": "гармонь", "recipe": {
        "instrument": {"device": "Wavetable"}, "track": {"name": "Гармонь"}}})
    assert ok.ok and ok.summary == "Создана дорожка «Гармонь»"
    req = ex.engine.requests[-1]
    assert req.strategy == "recipe" and req.recipe["instrument"]["device"] == "Wavetable"
    assert bridge.tracks[0].devices[0].name == "Wavetable"
    # missing recipe key -> schema error
    assert not ex.execute("design_custom_sound", {"description": "x"}).ok


def test_search_live_browser_filters_categories():
    ex, _ = make()
    r = ex.execute("search_live_browser", {"query": "piano"})
    assert r.ok and r.data["items"][0]["name"].startswith("Grand Piano")
    none = ex.execute("search_live_browser", {"query": "piano", "categories": ["drums"]})
    assert none.ok and none.data["items"] == [] and "hint" in none.data
    assert not ex.execute("search_live_browser", {"query": "x", "categories": ["bogus"]}).ok


def test_engine_missing():
    bridge = FakeBridge()
    ex = ToolExecutor(bridge, None, KnowledgeBase("/nonexistent"))
    r = ex.execute("create_sound", {"description": "x"})
    assert not r.ok and r.code == "engine_missing"


def test_unexpected_exception_is_contained():
    class Boom(StubEngine):
        def find_recipes(self, *a, **k):
            raise RuntimeError("kaboom")

    bridge = FakeBridge()
    ex = ToolExecutor(bridge, Boom(bridge), KnowledgeBase("/nonexistent"))
    r = ex.execute("search_sound_library", {"query": "x"})
    assert not r.ok and r.code == "internal"
    assert json.loads(r.model_content())["code"] == "internal"

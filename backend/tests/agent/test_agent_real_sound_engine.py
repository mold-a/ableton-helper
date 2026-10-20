"""Integration with the real Sound Engine (skipped until abhelper.sound is importable)."""

import json

import pytest

sound = pytest.importorskip("abhelper.sound")

from abhelper.agent import AssistantAgent, Conversation  # noqa: E402
from abhelper.bridge.fake import FakeBridge  # noqa: E402
from abhelper.config import Settings  # noqa: E402
from abhelper.knowledge import KnowledgeBase  # noqa: E402
from abhelper.llm import ScriptedLLM, tool_use_block, turn  # noqa: E402


def make_agent(turns):
    bridge = FakeBridge()
    agent = AssistantAgent(bridge, sound.SoundEngine(bridge), KnowledgeBase("/nonexistent"),
                           ScriptedLLM(turns), Settings(api_key="k"))
    return agent, bridge


def test_library_flow_with_real_engine():
    lib = sound.RecipeLibrary.load_default()
    matches = lib.search("баян")
    if not matches:
        pytest.skip("recipe library has no 'баян' recipe yet")
    rid = matches[0].recipe_id
    agent, bridge = make_agent([
        turn(tool_use_block("search_sound_library", {"query": "баян"}, id="s")),
        turn(tool_use_block("create_sound", {"description": "я хочу звук баяна", "recipe_id": rid}, id="c")),
        turn("Готово."),
    ])
    conv = Conversation()
    events = list(agent.run_turn(conv, "я хочу звук баяна"))
    assert events[-1]["type"] == "done"
    results = [e for e in events if e["type"] == "tool_result"]
    assert json.loads(conv.messages[2]["content"][0]["content"])["matches"][0]["recipe_id"] == rid
    assert results[1]["ok"], results[1]
    assert results[1]["summary"].startswith("Создана дорожка")
    assert len(bridge.tracks) == 1 and bridge.tracks[0].devices


def test_custom_sound_flow_with_real_engine():
    recipe = {"name": {"ru": "Гармонь", "en": "Reed"}, "category": "reed",
              "instrument": {"device": "Operator", "parameters": {"Filter Freq": {"norm": 0.5}}},
              "effects": [{"device": "Reverb", "parameters": {"Dry/Wet": {"norm": 0.2}}}],
              "track": {"name": "Гармонь"}}
    agent, bridge = make_agent([
        turn(tool_use_block("design_custom_sound", {"description": "гармонь", "recipe": recipe}, id="d")),
        turn("Готово."),
    ])
    events = list(agent.run_turn(Conversation(), "гармонь"))
    res = [e for e in events if e["type"] == "tool_result"][0]
    assert res["ok"], res
    assert bridge.tracks[0].name == "Гармонь" and bridge.tracks[0].devices


def test_invalid_custom_recipe_rejected_with_real_validator():
    agent, _ = make_agent([])
    r = agent.executor.execute("design_custom_sound", {"description": "x", "recipe": {
        "instrument": {"device": "Operator"}, "category": "bogus"}})
    assert not r.ok and r.code == "invalid_recipe"
    ok = agent.executor.execute("design_custom_sound", {"description": "x", "recipe": {
        "instrument": {"device": "Operator"}}})
    assert ok.code != "invalid_recipe"

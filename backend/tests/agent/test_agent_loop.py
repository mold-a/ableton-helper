import json

import pytest

from abhelper.agent import AssistantAgent, Conversation, SYSTEM_PROMPT, get_tools
from abhelper.agent.testing import StubEngine
from abhelper.bridge import BridgeConnectionError
from abhelper.bridge.fake import FakeBridge
from abhelper.config import Settings
from abhelper.knowledge import KnowledgeBase
from abhelper.llm import LLMAuthError, LLMRateLimitError, ScriptedLLM, tool_use_block, turn
from abhelper.llm.base import LLMError


def make_agent(turns, bridge=None, engine=None, api_key="sk-test", kb=None, **engine_kw):
    bridge = bridge if bridge is not None else FakeBridge()
    engine = engine if engine is not None else StubEngine(bridge, **engine_kw)
    llm = ScriptedLLM(turns)
    agent = AssistantAgent(bridge, engine, kb or KnowledgeBase("/nonexistent"), llm, Settings(api_key=api_key))
    return agent, llm, bridge, engine


def run(agent, text="хочу звук баяна", conv=None):
    conv = conv or Conversation()
    return list(agent.run_turn(conv, text)), conv


def types(events):
    return [e["type"] for e in events]


def test_sound_request_happy_path():
    turns = [
        turn("Ищу в библиотеке.", tool_use_block("search_sound_library", {"query": "баян"}, id="t1")),
        turn(tool_use_block("create_sound", {"description": "звук баяна", "recipe_id": "bayan"}, id="t2")),
        turn("Готово: дорожка «Баян». Запустите демо-клип."),
    ]
    agent, llm, bridge, engine = make_agent(turns)
    events, conv = run(agent)

    assert types(events) == [
        "text_delta", "text_delta", "tool_start", "tool_result",
        "tool_start", "tool_result", "text_delta", "text_delta", "text_delta", "done"]
    start, res = events[2], events[3]
    assert start == {"type": "tool_start", "id": "t1", "name": "search_sound_library", "input": {"query": "баян"}}
    assert res["ok"] and res["name"] == "search_sound_library" and "1" in res["summary"]
    create_res = events[5]
    assert create_res["ok"] and create_res["summary"] == "Создана дорожка «Баян»"
    assert create_res["data"]["demo_clip_slot"] == 0
    done = events[-1]
    assert "Готово" in done["text"] and done["text"].startswith("Ищу в библиотеке.")
    assert done["usage"]["output_tokens"] == 15

    # world state
    assert bridge.tracks[0].name == "Баян" and bridge.tracks[0].devices[0].name == "Operator"
    assert engine.requests[0].recipe_id == "bayan"

    # history: user, assistant(tool_use), user(tool_result), assistant, user(tool_result), assistant
    roles = [m["role"] for m in conv.messages]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]
    tr = conv.messages[2]["content"]
    assert [b["type"] for b in tr] == ["tool_result"] and tr[0]["tool_use_id"] == "t1" and tr[0]["is_error"] is False
    payload = json.loads(tr[0]["content"])
    assert payload["matches"][0]["recipe_id"] == "bayan"

    # the second LLM request saw the tool_result; system prompt + static tools were passed
    assert llm.calls[1]["messages"][-1]["content"][0]["tool_use_id"] == "t1"
    assert llm.calls[0]["system"] == SYSTEM_PROMPT
    assert [t["name"] for t in llm.calls[0]["tools"]] == [t["name"] for t in get_tools()]


def test_parallel_tool_use_blocks_single_user_message():
    turns = [
        turn(tool_use_block("get_session_overview", {}, id="a"),
             tool_use_block("search_sound_library", {"query": "баян"}, id="b"),
             tool_use_block("transport", {"action": "play"}, id="c")),
        turn("ok"),
    ]
    agent, llm, bridge, _ = make_agent(turns)
    events, conv = run(agent)
    assert types(events).count("tool_start") == 3 and types(events).count("tool_result") == 3
    assert len(conv.messages) == 4  # user, assistant, ONE user with 3 results, assistant
    results = conv.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b", "c"]
    assert bridge.is_playing is True


def test_invalid_tool_input_is_error_result_and_loop_continues():
    turns = [
        turn(tool_use_block("get_track_details", {"track_index": "zero"}, id="x"),
             tool_use_block("no_such_tool", {}, id="y"),
             tool_use_block("transport", {"action": "set_tempo"}, id="z")),
        turn("Понял, исправлюсь."),
    ]
    agent, llm, _, _ = make_agent(turns)
    events, conv = run(agent)
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [False, False, False]
    assert results[0]["data"]["code"] == "invalid_input"
    blocks = conv.messages[2]["content"]
    assert all(b["is_error"] for b in blocks)
    assert "expected integer" in blocks[0]["content"]
    assert events[-1]["type"] == "done"


def test_bridge_offline_tool_result_and_help_still_works(tmp_path):
    (tmp_path / "a.md").write_text("# Варп\nkeywords: варп\n\n## Как включить\nВключите Warp в Clip View.\n", encoding="utf-8")

    class Offline(FakeBridge):
        def call(self, *a, **k):
            raise BridgeConnectionError("refused")

    turns = [
        turn(tool_use_block("get_session_overview", {}, id="1"),
             tool_use_block("search_ableton_help", {"query": "варп"}, id="2")),
        turn("Live не подключён, но по справке: включите Warp."),
    ]
    agent, llm, _, _ = make_agent(turns, bridge=Offline(), kb=KnowledgeBase(tmp_path))
    events, conv = run(agent, "как включить варп")
    r1, r2 = [e for e in events if e["type"] == "tool_result"]
    assert not r1["ok"] and r1["data"]["code"] == "bridge_offline"
    assert "AbletonHelper" in r1["summary"]
    assert r2["ok"] and json.loads(conv.messages[2]["content"][1]["content"])["results"][0]["section"] == "Как включить"
    assert conv.messages[2]["content"][0]["is_error"] is True
    assert events[-1]["type"] == "done"


def test_refusal_emits_error_and_keeps_history_valid():
    agent, llm, _, _ = make_agent([turn("", stop_reason="refusal")])
    conv = Conversation()
    events, _ = run(agent, conv=conv)
    assert events[-1]["type"] == "error" and events[-1]["code"] == "llm_error"
    assert conv.messages == []  # unanswered prompt rolled back


def test_pause_turn_continues():
    turns = [turn("Думаю…", stop_reason="pause_turn"), turn("Готово.")]
    agent, llm, _, _ = make_agent(turns)
    events, conv = run(agent)
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Думаю…\n\nГотово."
    assert [m["role"] for m in conv.messages] == ["user", "assistant", "assistant"]
    assert len(llm.calls) == 2


def test_max_tokens_with_pending_tool_use_is_not_executed():
    bridge = FakeBridge()
    turns = [turn(tool_use_block("transport", {"action": "play"}, id="p"), stop_reason="max_tokens")]
    agent, _, _, _ = make_agent(turns, bridge=bridge)
    events, conv = run(agent)
    assert events[-1]["type"] == "error"
    assert "tool_start" not in types(events)
    assert bridge.is_playing is False
    assert conv.messages == []


def test_missing_api_key():
    agent, llm, _, _ = make_agent([turn("x")], api_key="")
    events, conv = run(agent)
    assert events == [events[0]] and events[0]["type"] == "error" and events[0]["code"] == "llm_not_configured"
    assert "API" in events[0]["message"]
    assert llm.calls == [] and conv.messages == []


def test_llm_errors_map_to_codes():
    for exc, code in [(LLMAuthError("Проверьте API-ключ"), "llm_not_configured"),
                      (LLMRateLimitError("лимит"), "llm_error"), (LLMError("x"), "llm_error")]:
        agent, *_ = make_agent([exc])
        events, conv = run(agent)
        assert events[-1]["type"] == "error" and events[-1]["code"] == code
        assert conv.messages == []


def test_error_after_tool_results_keeps_pairs_intact_for_retry():
    turns = [turn(tool_use_block("transport", {"action": "play"}, id="p")), LLMError("boom"), turn("Ок")]
    agent, llm, _, _ = make_agent(turns)
    conv = Conversation()
    events, _ = run(agent, conv=conv)
    assert events[-1]["type"] == "error"
    assert [m["role"] for m in conv.messages] == ["user", "assistant", "user"]
    events2, _ = run(agent, "ещё раз", conv=conv)
    assert events2[-1]["type"] == "done"


def test_thinking_blocks_preserved_unchanged_in_history():
    thinking = {"type": "thinking", "thinking": "hmm", "signature": "sig=="}
    turns = [turn(thinking, tool_use_block("transport", {"action": "stop"}, id="s")), turn("ok")]
    agent, llm, _, _ = make_agent(turns)
    events, conv = run(agent)
    assert conv.messages[1]["content"][0] == thinking
    assert llm.calls[1]["messages"][1]["content"][0] == thinking


def test_iteration_cap():
    turns = [turn(tool_use_block("transport", {"action": "stop"}, id=f"s{i}")) for i in range(30)]
    agent, llm, _, _ = make_agent(turns)
    events, _ = run(agent)
    assert events[-1]["type"] == "error" and len(llm.calls) == 25


def test_busy_conversation_rejected():
    agent, *_ = make_agent([turn("a")])
    conv = Conversation()
    assert conv.try_begin()
    events, _ = run(agent, conv=conv)
    assert events[0]["type"] == "error" and events[0]["code"] == "busy"
    conv.end()
    events, _ = run(agent, conv=conv)
    assert events[-1]["type"] == "done"


def test_unmatched_parameters_flow():
    unmatched = [{"device": "Operator", "parameter": "Osc-A Wave", "value": "Saw D", "reason": "not found"}]
    turns = [
        turn(tool_use_block("create_sound", {"description": "баян", "recipe_id": "bayan"}, id="c")),
        turn(tool_use_block("get_device_parameters", {"track_index": 0, "device_index": 0}, id="g")),
        turn("done"),
    ]
    agent, llm, bridge, _ = make_agent(turns, unmatched=unmatched)
    events, conv = run(agent)
    create = json.loads(conv.messages[2]["content"][0]["content"])
    assert create["unmatched_parameters"] == unmatched
    assert "(параметров не применено: 1)" in [e for e in events if e["type"] == "tool_result"][0]["summary"]
    assert events[-1]["type"] == "done"


def test_system_prompt_mentions_key_rules():
    p = SYSTEM_PROMPT
    for needle in ("unmatched_parameters", "get_device_parameters", "search_ableton_help", "delete_track",
                   "design_custom_sound", "user's language"):
        assert needle in p

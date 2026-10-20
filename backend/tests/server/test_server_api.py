import json

import pytest
from fastapi.testclient import TestClient

from abhelper.agent.testing import StubEngine
from abhelper.bridge.fake import FakeBridge
from abhelper.config import Settings
from abhelper.knowledge import KnowledgeBase
from abhelper.llm import LLMError, ScriptedLLM, tool_use_block, turn
from abhelper.server import create_app


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABHELPER_CONFIG", str(tmp_path / "cfg" / "config.json"))
    for var in ("ANTHROPIC_API_KEY", "ABHELPER_MODEL", "ABHELPER_EFFORT"):
        monkeypatch.delenv(var, raising=False)
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>Чат</title><script src=app.js></script>", encoding="utf-8")
    (ui / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("ABHELPER_UI_DIR", str(ui))
    return tmp_path


def make_client(turns=(), api_key="sk-secret-123", bridge=None):
    bridge = bridge if bridge is not None else FakeBridge()
    settings = Settings(api_key=api_key)
    llm = ScriptedLLM(list(turns))
    app = create_app(settings, bridge=bridge, engine=StubEngine(bridge), llm=llm, knowledge=KnowledgeBase("/nonexistent"))
    return TestClient(app), settings, bridge, llm


def parse_sse(resp):
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in resp.text.split("\n\n"):
        if block.strip():
            assert block.startswith("data: ")
            events.append(json.loads(block[len("data: "):]))
    return events


def test_status_with_fake_bridge():
    c, *_ = make_client()
    j = c.get("/api/status").json()
    assert j["bridge"]["connected"] is True and "fake" in j["bridge"]["live_version"]
    assert j["bridge"]["script_version"] == "0.2.0"
    assert j["llm"] == {"configured": True, "model": "claude-opus-5-5"}
    assert j["version"]


def test_status_bridge_offline():
    from abhelper.bridge.client import TcpBridge

    app = create_app(Settings(), bridge=TcpBridge(port=1, connect_timeout=0.2), engine=None, llm=ScriptedLLM([]))
    j = TestClient(app).get("/api/status").json()
    assert j["bridge"] == {"connected": False, "live_version": None, "script_version": None}
    assert j["llm"]["configured"] is False


def test_chat_sse_stream():
    turns = [
        turn("Ищу.", tool_use_block("search_sound_library", {"query": "баян"}, id="t1")),
        turn(tool_use_block("create_sound", {"description": "баян", "recipe_id": "bayan"}, id="t2")),
        turn("Готово!"),
    ]
    c, _, bridge, llm = make_client(turns)
    r = c.post("/api/chat", json={"message": "я хочу звук баяна"})
    assert r.status_code == 200
    ev = parse_sse(r)
    assert ev[0]["type"] == "conversation" and ev[0]["conversation_id"]
    kinds = [e["type"] for e in ev]
    assert kinds.count("tool_start") == 2 and kinds.count("tool_result") == 2 and kinds[-1] == "done"
    assert ev[-1]["text"].endswith("Готово!")
    assert bridge.tracks[0].name == "Баян"

    # same conversation continues with history
    llm.turns.append(turn("Ещё что-нибудь?"))
    cid = ev[0]["conversation_id"]
    ev2 = parse_sse(c.post("/api/chat", json={"message": "спасибо", "conversation_id": cid}))
    assert ev2[0]["conversation_id"] == cid and ev2[-1]["type"] == "done"
    assert len(llm.calls[-1]["messages"]) == 7  # history carried over

    # reset drops history
    assert c.post("/api/reset", json={"conversation_id": cid}).json() == {"ok": True}
    llm.turns.append(turn("Привет"))
    parse_sse(c.post("/api/chat", json={"message": "hi", "conversation_id": cid}))
    assert len(llm.calls[-1]["messages"]) == 1


def test_chat_errors_are_events_not_500():
    c, *_ = make_client([LLMError("упало")])
    ev = parse_sse(c.post("/api/chat", json={"message": "hi"}))
    assert ev[0]["type"] == "conversation" and ev[-1] == {"type": "error", "message": "упало", "code": "llm_error"}


def test_chat_without_key():
    c, *_ = make_client(api_key="")
    ev = parse_sse(c.post("/api/chat", json={"message": "hi"}))
    assert ev[-1]["code"] == "llm_not_configured"


def test_chat_validation():
    c, *_ = make_client()
    assert c.post("/api/chat", json={"message": "   "}).status_code == 400
    assert c.post("/api/chat", json={}).status_code == 422
    assert c.post("/api/chat", json={"message": "x" * 9000}).status_code == 413


def test_chat_invalid_conversation_id_gets_fresh_one():
    c, *_ = make_client([turn("a")])
    ev = parse_sse(c.post("/api/chat", json={"message": "hi", "conversation_id": "../../etc"}))
    assert ev[0]["conversation_id"] != "../../etc"


def test_config_get_post_never_echoes_key(isolated_env):
    c, settings, *_ = make_client(api_key="")
    cfg = c.get("/api/config").json()
    assert cfg == {"model": "claude-opus-5-5", "effort": "medium", "api_key_set": False,
                   "bridge_host": "127.0.0.1", "bridge_port": 9888}
    r = c.post("/api/config", json={"api_key": "sk-ant-TOPSECRET", "model": "claude-opus-5-5", "effort": "high"})
    assert r.status_code == 200
    assert "TOPSECRET" not in r.text and "TOPSECRET" not in c.get("/api/config").text
    assert r.json()["api_key_set"] is True and r.json()["effort"] == "high"
    assert settings.api_key == "sk-ant-TOPSECRET" and settings.effort == "high"  # live-applied
    saved = json.loads((isolated_env / "cfg" / "config.json").read_text(encoding="utf-8"))
    assert saved["api_key"] == "sk-ant-TOPSECRET" and saved["effort"] == "high"
    import os, stat
    if os.name == "posix":
        assert stat.S_IMODE((isolated_env / "cfg" / "config.json").stat().st_mode) == 0o600
    # status reflects it
    assert c.get("/api/status").json()["llm"]["configured"] is True


def test_config_validation():
    c, *_ = make_client()
    assert c.post("/api/config", json={"effort": "turbo"}).status_code == 400
    assert c.post("/api/config", json={"model": " "}).status_code == 400
    assert c.post("/api/config", json={"api_key": "has space"}).status_code == 400
    assert c.post("/api/config", json={}).status_code == 200


def test_config_env_override_reported(monkeypatch):
    c, settings, *_ = make_client()
    monkeypatch.setenv("ABHELPER_MODEL", "pinned-model")
    settings.model = "pinned-model"
    r = c.post("/api/config", json={"model": "other"}).json()
    assert r["env_overrides"] == ["model"] and r["model"] == "pinned-model"


def test_suggestions():
    c, *_ = make_client()
    items = c.get("/api/suggestions").json()["items"]
    assert len(items) >= 4 and any("баян" in s.lower() for s in items)


def test_static_ui_served():
    c, *_ = make_client()
    r = c.get("/")
    assert r.status_code == 200 and "<title>Чат</title>" in r.text
    assert c.get("/app.js").status_code == 200
    assert c.get("/ui/").status_code == 200 and c.get("/ui/app.js").status_code == 200
    assert c.get("/api/status").status_code == 200  # API not shadowed by the root mount


def test_missing_ui_dir_gives_hint(monkeypatch, tmp_path):
    monkeypatch.setenv("ABHELPER_UI_DIR", str(tmp_path / "missing"))
    c, *_ = make_client()
    r = c.get("/")
    assert r.status_code == 200 and "ABHELPER_UI_DIR" in r.text

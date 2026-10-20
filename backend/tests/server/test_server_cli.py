import io

import pytest

from abhelper import cli
from abhelper.bridge.fake import FakeBridge
from abhelper.config import Settings


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    for v in ("ANTHROPIC_API_KEY", "ABHELPER_MODEL", "ABHELPER_EFFORT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ABHELPER_CONFIG", str(tmp_path / "c.json"))
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("x")
    monkeypatch.setenv("ABHELPER_UI_DIR", str(ui))


def test_parser_subcommands():
    p = cli.build_parser()
    a = p.parse_args(["serve", "--fake", "--port", "9001"])
    assert a.fake and a.port == 9001 and a.func is cli.cmd_serve
    assert p.parse_args(["calibrate", "--devices", "Operator", "Reverb", "--out", "x.json"]).devices == ["Operator", "Reverb"]
    assert p.parse_args(["doctor"]).func is cli.cmd_doctor
    assert p.parse_args(["chat", "--fake"]).fake


def test_doctor_checklist_with_fake_bridge(capsys):
    rows = cli.run_doctor(Settings(api_key="k"), bridge=FakeBridge())
    text = "\n".join(f"{i} {t}" for i, t, _ in rows)
    assert "Мост к Live отвечает" in text and "Индекс браузера" in text and "Интерфейс чата" in text
    assert not any(i == cli.BAD and "API" in t for i, t, _ in rows)


def test_doctor_reports_missing_key_and_bridge(monkeypatch, capsys):
    from abhelper.bridge.client import TcpBridge

    rows = cli.run_doctor(Settings(api_key="", bridge_port=1), bridge=TcpBridge(port=1, connect_timeout=0.2))
    bad = [t for i, t, _ in rows if i == cli.BAD]
    assert any("API-ключ" in t for t in bad) and any("Мост" in t for t in bad)
    assert all(h for i, t, h in rows if i == cli.BAD and "Мост" in t)


def test_main_prints_help_without_command(capsys):
    assert cli.main([]) == 0
    assert "serve" in capsys.readouterr().out


def test_chat_repl_without_key(monkeypatch, capsys):
    inputs = iter(["привет", "/reset", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    assert cli.main(["chat", "--fake"]) == 0
    out = capsys.readouterr().out
    assert "API-ключ" in out


def test_chat_repl_with_scripted_llm(monkeypatch, capsys):
    from abhelper.agent import factory
    from abhelper.llm import ScriptedLLM, tool_use_block, turn

    llm = ScriptedLLM([turn(tool_use_block("get_session_overview", {}, id="1")), turn("Пустой сет.")])
    real = factory.build_agent
    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls, *a, **k: Settings(api_key="k")))
    monkeypatch.setattr(factory, "build_agent", lambda s, b, **kw: real(s, b, llm=llm, **kw))
    inputs = iter(["что в проекте?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    assert cli.main(["chat", "--fake"]) == 0
    out = capsys.readouterr().out
    assert "get_session_overview" in out and "Пустой сет." in out

import json
import os
import stat

import pytest

from abhelper.config import Settings, config_path, read_config_file


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for v in ("ANTHROPIC_API_KEY", "ABHELPER_MODEL", "ABHELPER_EFFORT", "ABHELPER_BRIDGE_HOST",
              "ABHELPER_BRIDGE_PORT", "ABHELPER_HOST", "ABHELPER_PORT", "ABHELPER_FALLBACKS"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ABHELPER_CONFIG", str(tmp_path / "config.json"))
    return tmp_path / "config.json"


def test_defaults():
    s = Settings.load()
    assert (s.api_key, s.model, s.effort) == ("", "claude-opus-5-5", "medium")
    assert (s.bridge_host, s.bridge_port, s.http_host, s.http_port) == ("127.0.0.1", 9888, "127.0.0.1", 8765)
    assert s.use_fallbacks is True


def test_file_over_defaults_env_over_file(clean_env, monkeypatch):
    clean_env.write_text(json.dumps({"api_key": "file-key", "model": "file-model", "effort": "low",
                                     "http_port": 9000}), encoding="utf-8")
    s = Settings.load()
    assert (s.api_key, s.model, s.effort, s.http_port) == ("file-key", "file-model", "low", 9000)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("ABHELPER_MODEL", "env-model")
    monkeypatch.setenv("ABHELPER_EFFORT", "max")
    monkeypatch.setenv("ABHELPER_PORT", "9100")
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "1234")
    monkeypatch.setenv("ABHELPER_FALLBACKS", "0")
    s = Settings.load()
    assert (s.api_key, s.model, s.effort, s.http_port, s.bridge_port) == ("env-key", "env-model", "max", 9100, 1234)
    assert s.use_fallbacks is False


def test_invalid_values_fall_back(clean_env, monkeypatch):
    monkeypatch.setenv("ABHELPER_EFFORT", "turbo")
    monkeypatch.setenv("ABHELPER_PORT", "abc")
    monkeypatch.setenv("ABHELPER_BRIDGE_PORT", "99999")
    s = Settings.load()
    assert s.effort == "medium" and s.http_port == 8765 and s.bridge_port == 9888


def test_corrupt_file_ignored(clean_env):
    clean_env.write_text("{not json", encoding="utf-8")
    assert Settings.load().model == "claude-opus-5-5"
    clean_env.write_text("[1,2]", encoding="utf-8")
    assert read_config_file() == {}


def test_save_roundtrip_chmod_and_merge(clean_env):
    clean_env.write_text(json.dumps({"http_port": 9000}), encoding="utf-8")
    s = Settings(api_key="k1", model="m1", effort="xhigh")
    path = s.save()
    assert path == config_path() == clean_env
    data = json.loads(clean_env.read_text(encoding="utf-8"))
    assert data == {"http_port": 9000, "api_key": "k1", "model": "m1", "effort": "xhigh"}
    if os.name == "posix":
        assert stat.S_IMODE(clean_env.stat().st_mode) == 0o600
    loaded = Settings.load()
    assert (loaded.api_key, loaded.model, loaded.effort, loaded.http_port) == ("k1", "m1", "xhigh", 9000)
    Settings(api_key="").save()
    assert "api_key" not in json.loads(clean_env.read_text(encoding="utf-8"))


def test_repr_hides_key():
    assert "sk-ant-secret" not in repr(Settings(api_key="sk-ant-secret"))
    assert "sk-ant-secret" not in str(Settings(api_key="sk-ant-secret").public_dict())

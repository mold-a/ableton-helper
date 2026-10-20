import os

from abhelper.config import Settings, load_dotenv, parse_dotenv


def test_parse_dotenv_formats():
    text = """
# comment
ANTHROPIC_API_KEY=sk-ant-123
export ABHELPER_MODEL="claude-sonnet-5-5"
ABHELPER_EFFORT='high'
ABHELPER_PORT=9000 # inline comment
EMPTY=
not a line
"""
    assert parse_dotenv(text) == {
        "ANTHROPIC_API_KEY": "sk-ant-123", "ABHELPER_MODEL": "claude-sonnet-5-5",
        "ABHELPER_EFFORT": "high", "ABHELPER_PORT": "9000", "EMPTY": "",
    }


def test_load_dotenv_fills_settings_but_real_env_wins(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-dotenv\nABHELPER_EFFORT=high\nABHELPER_MODEL=\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ABHELPER_EFFORT", "low")
    monkeypatch.setenv("ABHELPER_MODEL", "")
    monkeypatch.setenv("ABHELPER_CONFIG", str(tmp_path / "cfg.json"))
    # register for restoration: load_dotenv writes os.environ directly
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    assert load_dotenv([env_file]) == [env_file]
    s = Settings.load()
    assert s.api_key == "from-dotenv"
    assert s.effort == "low"            # real environment wins over .env
    assert s.model == "claude-opus-5-5"  # empty .env value is ignored


def test_missing_dotenv_is_fine(tmp_path):
    assert load_dotenv([tmp_path / "nope.env"]) == []


def test_tests_never_see_real_dotenv():
    assert os.environ["ABHELPER_ENV_FILE"].endswith("no-such.env")

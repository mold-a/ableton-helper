import pytest


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch, tmp_path):
    """Never let tests read the developer's real .env (it may hold an API key)."""
    monkeypatch.setenv("ABHELPER_ENV_FILE", str(tmp_path / "no-such.env"))

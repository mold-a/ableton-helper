"""Runtime settings: environment > .env file > config file > defaults.

The config file lives at ``~/.ableton-helper/config.json`` (move the whole folder with
``ABHELPER_HOME``, or just the file with ``ABHELPER_CONFIG``). It is created with mode 600 on POSIX because it may hold the
API key. The key is never logged or echoed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# field -> environment variable
ENV_VARS: dict[str, str] = {
    "api_key": "ANTHROPIC_API_KEY",
    "model": "ABHELPER_MODEL",
    "effort": "ABHELPER_EFFORT",
    "bridge_host": "ABHELPER_BRIDGE_HOST",
    "bridge_port": "ABHELPER_BRIDGE_PORT",
    "http_host": "ABHELPER_HOST",
    "http_port": "ABHELPER_PORT",
    "use_fallbacks": "ABHELPER_FALLBACKS",
    "strict_tools": "ABHELPER_STRICT_TOOLS",
}

# Fields written by Settings.save() by default.
DEFAULT_SAVED_FIELDS = ("api_key", "model", "effort")


def data_dir() -> Path:
    """Folder for files the app writes (config, calibration): ABHELPER_HOME or ~/.ableton-helper."""
    override = os.environ.get("ABHELPER_HOME")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return Path.home() / ".ableton-helper"


def config_path() -> Path:
    override = os.environ.get("ABHELPER_CONFIG")
    if override:
        return Path(override).expanduser()
    return data_dir() / "config.json"


def dotenv_paths() -> list[Path]:
    """Candidate .env files: ABHELPER_ENV_FILE, else ./.env and the repository root's .env."""
    override = os.environ.get("ABHELPER_ENV_FILE")
    if override:
        return [Path(override).expanduser()]
    repo_root = Path(__file__).resolve().parents[2]
    paths = [Path.cwd() / ".env", repo_root / ".env"]
    return list(dict.fromkeys(p.resolve() for p in paths))


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; supports comments, `export KEY=...` and single/double quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


def load_dotenv(paths: Iterable[Path] | None = None) -> list[Path]:
    """Copy variables from .env files into os.environ without overriding variables that are
    already set (the real environment wins). Empty values are skipped. Returns files read."""
    loaded = []
    for path in paths if paths is not None else dotenv_paths():
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        for key, value in parse_dotenv(text).items():
            if value and not (os.environ.get(key) or "").strip():
                os.environ[key] = value
        loaded.append(Path(path))
    return loaded


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return default


def _to_port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def read_config_file(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed config file, or {} if missing/corrupt."""
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config_file(data: dict[str, Any], path: Path | None = None) -> Path:
    """Atomically write the config file (chmod 600 on POSIX)."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


@dataclass
class Settings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 9888
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    use_fallbacks: bool = True
    strict_tools: bool = True

    def __repr__(self) -> str:  # never leak the key
        return (
            f"Settings(api_key={'<set>' if self.api_key else '<empty>'}, model={self.model!r}, "
            f"effort={self.effort!r}, bridge={self.bridge_host}:{self.bridge_port}, "
            f"http={self.http_host}:{self.http_port}, use_fallbacks={self.use_fallbacks})"
        )

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, env: dict[str, str] | None = None, path: Path | None = None) -> "Settings":
        env = os.environ if env is None else env
        if path is None and env.get("ABHELPER_CONFIG"):
            path = Path(env["ABHELPER_CONFIG"]).expanduser()
        file_data = read_config_file(path)

        def pick(field: str) -> Any:
            raw = env.get(ENV_VARS[field])
            if raw is not None and str(raw).strip() != "":
                return raw
            return file_data.get(field)

        s = cls()
        key = pick("api_key")
        if isinstance(key, str):
            s.api_key = key.strip()
        model = pick("model")
        if isinstance(model, str) and model.strip():
            s.model = model.strip()
        effort = pick("effort")
        if isinstance(effort, str) and effort.strip().lower() in EFFORTS:
            s.effort = effort.strip().lower()
        for f in ("bridge_host", "http_host"):
            v = pick(f)
            if isinstance(v, str) and v.strip():
                setattr(s, f, v.strip())
        for f in ("bridge_port", "http_port"):
            setattr(s, f, _to_port(pick(f), getattr(s, f)))
        for f in ("use_fallbacks", "strict_tools"):
            setattr(s, f, _to_bool(pick(f), getattr(s, f)))
        return s

    # ------------------------------------------------------------------ saving
    def save(self, fields: Iterable[str] = DEFAULT_SAVED_FIELDS, path: Path | None = None) -> Path:
        """Merge the given fields into the config file (other keys are preserved)."""
        data = read_config_file(path)
        for f in fields:
            if f not in ENV_VARS:
                raise ValueError(f"Unknown setting: {f}")
            value = getattr(self, f)
            if f == "api_key" and not value:
                data.pop("api_key", None)
            else:
                data[f] = value
        return write_config_file(data, path)

    def public_dict(self) -> dict[str, Any]:
        """Settings safe to expose over HTTP (no key)."""
        return {
            "model": self.model,
            "effort": self.effort,
            "api_key_set": bool(self.api_key),
            "bridge_host": self.bridge_host,
            "bridge_port": self.bridge_port,
        }

    def env_overrides(self, fields: Iterable[str]) -> list[str]:
        """Which of ``fields`` are currently pinned by an environment variable."""
        return [f for f in fields if (os.environ.get(ENV_VARS.get(f, ""), "") or "").strip()]

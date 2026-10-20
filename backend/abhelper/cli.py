"""Command line: abhelper serve | chat | doctor | calibrate."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .bridge.base import BridgeError
from .bridge.client import SerializedBridge, TcpBridge
from .config import Settings, config_path, data_dir, load_dotenv

OK = "✅"
BAD = "❌"
WARN = "⚠️"


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def make_bridge(settings: Settings, fake: bool) -> Any:
    if fake:
        from .bridge.fake import FakeBridge

        return SerializedBridge(FakeBridge())
    return TcpBridge(settings.bridge_host, settings.bridge_port)


# --------------------------------------------------------------------------- serve
def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    settings = Settings.load()
    if args.host:
        settings.http_host = args.host
    if args.port:
        settings.http_port = args.port
    bridge = make_bridge(settings, args.fake)
    app = create_app(settings, bridge=bridge)
    url = f"http://{settings.http_host}:{settings.http_port}"
    print(f"Ableton Helper {__version__} -> {url}" + ("  [режим --fake: Live не нужен]" if args.fake else ""))
    if not settings.api_key:
        print(f"{WARN} API-ключ не задан: впишите ANTHROPIC_API_KEY в файл .env (см. .env.example) или введите ключ в настройках чата.")
    uvicorn.run(app, host=settings.http_host, port=settings.http_port, log_level="warning")
    return 0


# --------------------------------------------------------------------------- chat
def cmd_chat(args: argparse.Namespace) -> int:
    from .agent.conversation import Conversation
    from .agent.factory import build_agent

    settings = Settings.load()
    bridge = make_bridge(settings, args.fake)
    agent = build_agent(settings, bridge)
    conv = Conversation()
    if not settings.api_key:
        print(f"{WARN} Нет API-ключа: впишите ANTHROPIC_API_KEY в файл .env (см. .env.example).")
    print("Ableton Helper: чат в терминале. /reset — очистить диалог, /exit — выход.")
    while True:
        try:
            line = input("\nВы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/reset":
            conv = Conversation()
            print("(диалог очищен)")
            continue
        print("Helper> ", end="", flush=True)
        for ev in agent.run_turn(conv, line):
            t = ev["type"]
            if t == "text_delta":
                print(ev["text"], end="", flush=True)
            elif t == "tool_start":
                args_s = json.dumps(ev["input"], ensure_ascii=False)
                print(f"\n  🔧 {ev['name']}({args_s[:120]})", flush=True)
            elif t == "tool_result":
                print(f"  {'→' if ev['ok'] else '✗'} {ev['summary']}", flush=True)
            elif t == "error":
                print(f"\n{BAD} {ev['message']}")
            elif t == "done":
                print()
    return 0  # pragma: no cover


# --------------------------------------------------------------------------- doctor
def run_doctor(settings: Settings, bridge: Any = None, ui_dir: Path | None = None) -> list[tuple[str, str, str]]:
    """Return [(icon, title, hint)] checks."""
    from .knowledge import KnowledgeBase
    from .server.app import resolve_ui_dir

    rows: list[tuple[str, str, str]] = []
    v = sys.version_info
    rows.append((OK if v >= (3, 10) else BAD, f"Python {v.major}.{v.minor}.{v.micro}",
                 "" if v >= (3, 10) else "Нужен Python 3.10 или новее."))
    try:
        import anthropic

        rows.append((OK, f"Библиотека anthropic {anthropic.__version__}", ""))
    except ImportError:
        rows.append((BAD, "Библиотека anthropic не установлена", "pip install anthropic"))
    rows.append((OK if settings.api_key else BAD,
                 "API-ключ Anthropic " + ("задан" if settings.api_key else "не задан"),
                 "" if settings.api_key else f"Впишите ANTHROPIC_API_KEY в файл .env в корне проекта (шаблон — .env.example) или введите ключ в настройках чата ({config_path()})."))
    rows.append((OK, f"Модель: {settings.model}, effort: {settings.effort}", ""))

    bridge = bridge or TcpBridge(settings.bridge_host, settings.bridge_port)
    try:
        info = bridge.probe() if hasattr(bridge, "probe") else bridge.call("ping")
    except BridgeError:
        info = None
    where = f"{settings.bridge_host}:{settings.bridge_port}"
    if info:
        rows.append((OK, f"Мост к Live отвечает ({where}); Live {info.get('live_version')}, "
                         f"скрипт {info.get('script_version')}", ""))
        try:
            st = bridge.call("browser_status")
            msg = f"Индекс браузера Live: {st.get('indexed')} элементов" + \
                  ("" if st.get("complete") else " (ещё строится)")
            rows.append((OK if st.get("indexed") else WARN, msg,
                         "" if st.get("complete") else "Подождите минуту после запуска Live: пресеты ищутся по неполному индексу."))
        except BridgeError as e:
            rows.append((WARN, "Состояние индекса браузера неизвестно", str(e)))
    else:
        rows.append((BAD, f"Мост к Live не отвечает ({where})",
                     "Запустите Live и выберите Control Surface «AbletonHelper» в Preferences → Link, Tempo & MIDI "
                     "(установка скрипта: scripts/install_remote_script.py). Без Live работает режим --fake."))
    ui = ui_dir or resolve_ui_dir()
    has_ui = (ui / "index.html").is_file()
    rows.append((OK if has_ui else BAD, f"Интерфейс чата: {ui}" + ("" if has_ui else " (index.html не найден)"),
                 "" if has_ui else "Задайте ABHELPER_UI_DIR или переустановите проект."))
    kb = KnowledgeBase()
    cols = kb.collections()
    detail = ", ".join(f"{name}: {n}" for name, n in cols.items())
    rows.append((OK if kb.sections else WARN,
                 f"База знаний: {len(kb.sections)} фрагментов" + (f" ({detail})" if detail else ""),
                 "" if kb.sections else "Папка knowledge/docs пуста: ответы будут из общих знаний модели."))
    missing = [c for c in ("help", "sound", "theory") if c not in cols]
    if kb.sections and missing:
        rows.append((WARN, "В базе знаний нет коллекций: " + ", ".join(missing),
                     "Папки knowledge/docs/<коллекция>/ пусты или не установлены."))
    try:
        import abhelper.sound  # noqa: F401

        rows.append((OK, "Звуковой движок загружен", ""))
    except ImportError as e:
        rows.append((BAD, "Звуковой движок (abhelper.sound) не загружается", str(e)))
    return rows


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = Settings.load()
    rows = run_doctor(settings, bridge=make_bridge(settings, args.fake) if args.fake else None)
    for icon, title, hint in rows:
        print(f"{icon} {title}")
        if hint:
            print(f"    → {hint}")
    bad = sum(1 for r in rows if r[0] == BAD)
    print("\n" + ("Всё готово к работе." if not bad else f"Проблем: {bad}. Исправьте пункты с {BAD}."))
    return 1 if bad else 0


# --------------------------------------------------------------------------- calibrate
def cmd_calibrate(args: argparse.Namespace) -> int:
    try:
        from .sound.calibration import dump_device_catalog, merge_catalog, recipe_device_names
    except ImportError as e:
        print(f"{BAD} Модуль калибровки недоступен: {e}")
        return 1
    settings = Settings.load()
    bridge = make_bridge(settings, args.fake)
    out = Path(args.out).expanduser() if args.out else data_dir() / "device_catalog.json"
    try:
        # Sampler/Simpler host the sample-based presets (abhelper samples), so calibrate them too.
        names = args.devices or sorted(set(recipe_device_names()) | {"Sampler", "Simpler"})
        if not names:
            print(f"{BAD} Нет устройств для калибровки: укажите --devices Operator Reverb ...")
            return 1
        print(f"Снимаю параметры устройств из Live: {len(names)} шт. Не трогайте Live до конца.")
        new = dump_device_catalog(bridge, names, progress=print)
    except BridgeError as e:
        print(f"{BAD} Нет связи с Live: {e}")
        return 1
    existing: dict = {}
    if out.is_file():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
    merged = merge_catalog(existing, new) if existing else new
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    devices = merged.get("devices", merged) if isinstance(merged, dict) else {}
    print(f"{OK} Каталог устройств сохранён: {out} ({len(devices)} устройств)")
    return 0


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abhelper", description="LLM-ассистент для Ableton Live")
    p.add_argument("--version", action="version", version=f"abhelper {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="подробные логи")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="запустить веб-сервер с чатом")
    s.add_argument("--fake", action="store_true", help="эмулятор Live вместо реального (Live не нужен)")
    s.add_argument("--port", type=int, help="HTTP-порт (по умолчанию 8765)")
    s.add_argument("--host", help="HTTP-хост (по умолчанию 127.0.0.1)")
    s.set_defaults(func=cmd_serve)

    c = sub.add_parser("chat", help="чат в терминале")
    c.add_argument("--fake", action="store_true")
    c.set_defaults(func=cmd_chat)

    d = sub.add_parser("doctor", help="проверить установку")
    d.add_argument("--fake", action="store_true")
    d.set_defaults(func=cmd_doctor)

    k = sub.add_parser("calibrate", help="снять каталог параметров устройств из запущенного Live")
    k.add_argument("--devices", nargs="*", help="имена устройств (по умолчанию — все из библиотеки рецептов)")
    k.add_argument("--out", help="куда писать JSON (по умолчанию <ABHELPER_HOME>/device_catalog.json, т. е. ~/.ableton-helper)")
    k.add_argument("--fake", action="store_true")
    k.set_defaults(func=cmd_calibrate)
    from .samples.cli import register as register_samples

    register_samples(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    for path in load_dotenv():
        logging.getLogger(__name__).info("loaded %s", path)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())

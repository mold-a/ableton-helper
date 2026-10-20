"""`abhelper samples list | install <id|all> | uninstall <id> | doctor`."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Callable

from abhelper import livepaths

from . import Pack, find_pack, load_registry
from .adv import HOW_TO_MAKE_TEMPLATE, describe_parts
from .installer import InstallError, Installer, rescan_browser

OK, BAD, WARN = "✅", "❌", "⚠️"


# --------------------------------------------------------------------------- environment
def _bridge(args: argparse.Namespace) -> tuple[Any | None, dict]:
    """(bridge, ping result) if Live answers `ping`, else (None, {}); never raises."""
    from abhelper.bridge.base import BridgeError
    from abhelper.cli import make_bridge
    from abhelper.config import Settings

    try:
        bridge = make_bridge(Settings.load(), bool(getattr(args, "fake", False)))
        info = bridge.call("ping")
    except (BridgeError, OSError, ValueError):
        return None, {}
    return bridge, info if isinstance(info, dict) else {}


def resolve_environment(args: argparse.Namespace, info: dict | None = None) -> dict:
    info = info or {}
    user_library = getattr(args, "user_library", None) or os.environ.get("ABHELPER_USER_LIBRARY")
    library = Path(user_library).expanduser() if user_library else livepaths.default_user_library()
    live_dir = getattr(args, "live_dir", None) or os.environ.get("ABHELPER_LIVE_DIR")
    resources = livepaths.find_resources_dirs(live_dir, info.get("script_path"))
    return {"user_library": library, "resources": resources, "info": info,
            "template": getattr(args, "template", None)}


def make_installer(env: dict, log: Callable[[str], None] = print) -> Installer | None:
    if env["user_library"] is None:
        return None
    return Installer(env["user_library"], env["resources"], template=env["template"], log=log)


def _need_library(env: dict) -> bool:
    if env["user_library"] is None:
        print("%s Не удалось определить User Library (поддерживаются Windows и macOS). Укажите --user-library." % BAD)
        return False
    return True


# --------------------------------------------------------------------------- commands
def cmd_list(args: argparse.Namespace) -> int:
    packs = load_registry()
    env = resolve_environment(args)
    inst = make_installer(env)
    labels = {"installed": "установлен", "partial": "повреждён (переустановите: install --force)", "absent": "не установлен"}
    for p in packs:
        status = labels[inst.status(p)] if inst else "—"
        size = "%.1f МБ" % (p.size_bytes / 1e6) if p.size_bytes else "?"
        flag = "" if p.verified else "  [не проверен]"
        print("%-26s %-34s %8s  %-8s %s%s" % (p.id, p.name, size, p.license.get("name", ""), status, flag))
        if args.verbose_list:
            print("    пресет: %s;  рецепты: %s;  синонимы: %s" % (
                p.preset_name, ", ".join(p.recipe_ids) or "—", ", ".join(p.aliases) or "—"))
    if inst:
        print("\nUser Library: %s" % env["user_library"])
    return 0


def _selected(packs: list[Pack], ident: str) -> list[Pack] | None:
    if ident == "all":
        return [p for p in packs if p.default and p.verified]
    pack = find_pack(packs, ident)
    if pack is None:
        print("%s Нет такого пака: «%s». Доступно: %s" % (BAD, ident, ", ".join(p.id for p in packs)))
        return None
    return [pack]


def cmd_install(args: argparse.Namespace) -> int:
    packs = load_registry()
    chosen = _selected(packs, args.pack)
    if chosen is None:
        return 1
    bridge, info = (None, {}) if args.no_rescan else _bridge(args)
    env = resolve_environment(args, info)
    if not _need_library(env):
        return 1
    inst = make_installer(env)
    failures, installed = 0, 0
    for pack in chosen:
        print("\n== %s (%s) ==" % (pack.name, pack.id))
        try:
            res = inst.install(pack, force=args.force)
        except InstallError as exc:
            print("%s %s" % (BAD, exc))
            failures += 1
            continue
        if res.already_installed:
            print("%s Уже установлен: %s  (чтобы переустановить — --force)" % (OK, res.preset_path))
            continue
        installed += 1
        print("%s Готово: %d зон(ы), пресет «%s»" % (OK, len(res.parts), pack.preset_name))
        print("    пресет:  %s" % res.preset_path)
        print("    сэмплы:  %s" % res.samples_dir)
        if args.verbose_list:
            for line in describe_parts(res.parts):
                print("    " + line)
        for w in res.warnings:
            print("    %s %s" % (WARN, w))
        if res.skipped:
            print("    пропущено регионов: %d (например: %s)" % (len(res.skipped), res.skipped[0]))
        print("    лицензия: %s — %s" % (pack.license.get("name"), pack.license.get("url")))
    if installed and bridge is not None:
        ok, msg = rescan_browser(bridge)
        print("\n%s %s" % (OK if ok else WARN, msg))
    elif installed:
        print("\nЕсли Live уже запущен: в браузере нажмите на User Library правой кнопкой → Refresh, "
              "или перезапустите Live. Пресеты: Presets → Instruments → Sampler → AbletonHelper.")
    return 1 if failures else 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    packs = load_registry()
    pack = find_pack(packs, args.pack)
    if pack is None:
        print("%s Нет такого пака: «%s»." % (BAD, args.pack))
        return 1
    env = resolve_environment(args)
    if not _need_library(env):
        return 1
    removed = make_installer(env).uninstall(pack)
    if removed:
        for p in removed:
            print("Удалено: %s" % p)
    else:
        print("%s %s не был установлен." % (OK, pack.id))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    bad = 0
    bridge, info = _bridge(args)
    env = resolve_environment(args, info)
    if bridge is not None:
        info = env["info"]
        print("%s Live отвечает: Live %s, скрипт %s" % (OK, info.get("live_version"), info.get("script_version")))
        if info.get("script_path"):
            print("    папка скрипта: %s" % info["script_path"])
        else:
            print("    %s Скрипт не сообщил свою папку (нужна версия 0.3.0+: переустановите Remote Script)." % WARN)
    else:
        print("%s Live не отвечает — установка сэмплов работает и без него (потом нажмите Refresh в браузере Live)." % WARN)
    lib = env["user_library"]
    if lib is None:
        print("%s User Library не определена (укажите --user-library)." % BAD)
        bad += 1
    else:
        print("%s User Library: %s%s" % (OK if lib.is_dir() else BAD, lib, "" if lib.is_dir() else "  (папки нет!)"))
        bad += 0 if lib.is_dir() else 1
    if env["resources"]:
        for r in env["resources"]:
            print("%s Папка Live (Resources): %s" % (OK, r))
    else:
        print("%s Папка установки Live не найдена — шаблон Sampler будет искаться только в User Library "
              "(можно указать --live-dir D:\\Ableton)." % WARN)
    inst = make_installer(env)
    if inst is not None:
        try:
            tpl = inst.find_template()
        except Exception as exc:                # a broken --template file
            print("%s Шаблон Sampler: %s" % (BAD, exc))
            bad += 1
            tpl = None
        else:
            if tpl is not None:
                from .adv import live_major_version
                ver = live_major_version(tpl.root_attrib) if hasattr(tpl, "root_attrib") else None
                print("%s Шаблон Sampler: %s (%s, сохранён в %s)" % (
                    OK, tpl.source, tpl.kind, tpl.root_attrib.get("Creator", "Live %s" % ver) if hasattr(tpl, "root_attrib") else "?"))
            else:
                print("%s Шаблон Sampler не найден." % BAD)
                print("    " + HOW_TO_MAKE_TEMPLATE)
                bad += 1
        packs = load_registry()
        done = [p.id for p in packs if inst.status(p) == "installed"]
        print("%s Установлено паков: %d из %d%s" % (OK if done else WARN, len(done), len(packs),
                                                    (" (" + ", ".join(done) + ")") if done else ""))
    return 1 if bad else 0


# --------------------------------------------------------------------------- registration
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--live-dir", help="папка установки Live (например D:\\Ableton) — оттуда берётся Resources\\Core Library")
    p.add_argument("--user-library", help="папка User Library (по умолчанию — как в настройках Live)")
    p.add_argument("--template", help="готовый .adv/.adg с Sampler в качестве шаблона (необязательно)")
    p.add_argument("--fake", action="store_true", help="эмулятор Live вместо реального")


def register(sub: Any) -> None:
    s = sub.add_parser("samples", help="бесплатные sample-библиотеки: скачать и сделать пресеты Sampler")
    ssub = s.add_subparsers(dest="samples_command")

    ls = ssub.add_parser("list", help="список паков и что уже установлено")
    _add_common(ls)
    ls.add_argument("-l", "--long", dest="verbose_list", action="store_true", help="подробнее")
    ls.set_defaults(func=cmd_list)

    ins = ssub.add_parser("install", help="скачать пак и создать пресет Sampler (all — все проверенные)")
    ins.add_argument("pack", help="идентификатор пака из `samples list` или all")
    _add_common(ins)
    ins.add_argument("--force", action="store_true", help="переустановить, даже если уже установлен")
    ins.add_argument("--no-rescan", action="store_true", help="не трогать запущенный Live")
    ins.add_argument("-l", "--long", dest="verbose_list", action="store_true", help="показать карту зон")
    ins.set_defaults(func=cmd_install)

    un = ssub.add_parser("uninstall", help="удалить пак (сэмплы и пресет)")
    un.add_argument("pack")
    _add_common(un)
    un.set_defaults(func=cmd_uninstall)

    dr = ssub.add_parser("doctor", help="проверить пути, шаблон Sampler и установленные паки")
    _add_common(dr)
    dr.set_defaults(func=cmd_doctor)

    s.set_defaults(func=lambda a: (s.print_help(), 0)[1])

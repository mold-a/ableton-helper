#!/usr/bin/env python3
"""Install / uninstall the AbletonHelper MIDI Remote Script into Ableton Live.

Copies remote_script/AbletonHelper into the "Remote Scripts" folder of the User Library:

  macOS    ~/Music/Ableton/User Library/Remote Scripts/AbletonHelper
  Windows  %USERPROFILE%\\Documents\\Ableton\\User Library\\Remote Scripts\\AbletonHelper

Usage:
  python scripts/install_remote_script.py                 # install
  python scripts/install_remote_script.py --dry-run       # show what would happen
  python scripts/install_remote_script.py --uninstall
  python scripts/install_remote_script.py --dest "/path/to/Remote Scripts"

--dest is the folder that CONTAINS the script folder (the "Remote Scripts" directory);
the package is copied to <dest>/AbletonHelper. Standard library only, Python 3.8+.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

PACKAGE_NAME = "AbletonHelper"
REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "remote_script" / PACKAGE_NAME
IGNORE_NAMES = {"__pycache__", "tests", ".pytest_cache", ".DS_Store"}
IGNORE_SUFFIXES = (".pyc", ".pyo")


def default_remote_scripts_dir(platform=None, home=None):
    """User Library 'Remote Scripts' folder for this OS, or None if the OS is not supported."""
    platform = platform or sys.platform
    home = Path(home) if home else Path.home()
    if platform == "darwin":
        return home / "Music" / "Ableton" / "User Library" / "Remote Scripts"
    if platform.startswith("win"):
        profile = Path(os.environ.get("USERPROFILE") or str(home))
        return profile / "Documents" / "Ableton" / "User Library" / "Remote Scripts"
    return None


def _ignore(_directory, names):
    return [n for n in names if n in IGNORE_NAMES or n.endswith(IGNORE_SUFFIXES)]


def verify_package(package_dir):
    """The classic pitfall: __init__.py must sit directly in <Remote Scripts>/AbletonHelper/."""
    init = Path(package_dir) / "__init__.py"
    if not init.is_file():
        return False, "нет файла %s (скрипт не появится в списке Control Surface)" % init
    text = init.read_text(encoding="utf-8")
    if "def create_instance" not in text:
        return False, "в %s нет функции create_instance" % init
    return True, str(init)


def install(remote_scripts_dir, dry_run=False, out=print):
    target = Path(remote_scripts_dir) / PACKAGE_NAME
    if not SOURCE.is_dir():
        out("Ошибка: не найден исходник %s" % SOURCE)
        return 1
    ok, msg = verify_package(SOURCE)
    if not ok:
        out("Ошибка в исходнике: " + msg)
        return 1
    out("Источник: %s" % SOURCE)
    out("Назначение: %s" % target)
    if dry_run:
        if target.exists():
            out("[dry-run] существующая папка будет заменена")
        out("[dry-run] будут скопированы файлы (без __pycache__ и tests):")
        for path in sorted(_walk_files(SOURCE)):
            out("  " + str(path.relative_to(SOURCE)))
        return 0
    Path(remote_scripts_dir).mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not (target / "__init__.py").is_file():
            out("Отказ: %s существует, но не похож на установленный скрипт. Удалите его вручную." % target)
            return 1
        shutil.rmtree(str(target))
        out("Старая версия удалена")
    shutil.copytree(str(SOURCE), str(target), ignore=_ignore)
    ok, msg = verify_package(target)
    if not ok:
        out("Ошибка установки: " + msg)
        return 1
    out("Скопировано. Проверено: %s" % msg)
    print_next_steps(target, out)
    return 0


def uninstall(remote_scripts_dir, dry_run=False, out=print):
    target = Path(remote_scripts_dir) / PACKAGE_NAME
    if not target.exists():
        out("Нечего удалять: %s не существует" % target)
        return 0
    if not (target / "__init__.py").is_file():
        out("Отказ: %s не похож на установленный скрипт. Удалите вручную." % target)
        return 1
    if dry_run:
        out("[dry-run] будет удалена папка %s" % target)
        return 0
    shutil.rmtree(str(target))
    out("Удалено: %s" % target)
    out("Перезапустите Live и выберите в Control Surface другой пункт (или None).")
    return 0


def _walk_files(root):
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_NAMES]
        for name in filenames:
            if name in IGNORE_NAMES or name.endswith(IGNORE_SUFFIXES):
                continue
            yield Path(dirpath) / name


def print_next_steps(target, out=print):
    out("")
    out("Готово. Дальше:")
    out("  1. Полностью перезапустите Ableton Live.")
    out("  2. Settings (Preferences) -> Link, Tempo & MIDI -> Control Surface -> выберите «AbletonHelper».")
    out("  3. Input и Output оставьте None.")
    out("  4. В строке состояния Live появится «AbletonHelper: listening on 9888».")
    out("  Установлено в: %s" % target)
    out("  Если AbletonHelper нет в списке: убедитесь, что файл __init__.py лежит прямо в этой папке")
    out("  (не на уровень глубже), либо поставьте скрипт внутрь приложения Live через --dest:")
    out("    macOS:   /Applications/Ableton Live 12 <Edition>.app/Contents/App-Resources/MIDI Remote Scripts")
    out("    Windows: C:\\ProgramData\\Ableton\\Live 12 <Edition>\\Resources\\MIDI Remote Scripts")
    out("  Логи Live: macOS ~/Library/Preferences/Ableton/Live <версия>/Log.txt,")
    out("             Windows %APPDATA%\\Ableton\\Live <версия>\\Preferences\\Log.txt")


def build_parser():
    parser = argparse.ArgumentParser(description="Установка Remote Script AbletonHelper в Ableton Live.")
    parser.add_argument("--dest", help="папка 'Remote Scripts', в которую будет помещена папка AbletonHelper "
                                       "(по умолчанию — User Library)")
    parser.add_argument("--uninstall", action="store_true", help="удалить установленный скрипт")
    parser.add_argument("--dry-run", action="store_true", help="ничего не менять, только показать план")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.dest:
        dest = Path(args.dest).expanduser()
        if dest.name == PACKAGE_NAME:
            print("Подсказка: --dest — это папка 'Remote Scripts', а не сама папка %s; использую %s" % (PACKAGE_NAME, dest.parent))
            dest = dest.parent
    else:
        dest = default_remote_scripts_dir()
        if dest is None:
            print("Эта ОС не поддерживается автоматически (Ableton Live есть только для macOS и Windows). "
                  "Укажите папку через --dest.")
            return 2
    if args.uninstall:
        return uninstall(dest, args.dry_run)
    return install(dest, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

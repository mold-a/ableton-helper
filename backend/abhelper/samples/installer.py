"""Installing a sample pack: download -> unpack -> copy used samples into the User Library -> write the preset.

Layout in the User Library (Live shows both in its browser):
  Samples/AbletonHelper/<pack id>/...                       the sample files (+ LICENSE / ATTRIBUTION)
  Presets/Instruments/Sampler/AbletonHelper/<preset>.adv    the generated Sampler preset
Everything is idempotent; `uninstall` removes exactly these two things.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from . import Pack
from .adv import (HOW_TO_MAKE_TEMPLATE, PartSpec, Template, TemplateError, build_preset_xml, describe_parts,
                  find_template, region_to_part, write_adv)
from .audioinfo import AudioError, read_audio_info
from .download import DownloadError, ExtractError, download_file, extract_archive
from .sfz import SfzError, parse_sfz_file

MANIFEST_NAME = "abhelper-pack.json"
SAMPLES_SUBDIR = ("Samples", "AbletonHelper")
PRESETS_SUBDIR = ("Presets", "Instruments", "Sampler", "AbletonHelper")
_NOTICE_NAMES = ("license", "licence", "copying", "readme", "attribution")


class InstallError(Exception):
    pass


@dataclass
class InstallResult:
    pack_id: str
    preset_path: Path
    samples_dir: Path
    already_installed: bool = False
    parts: list[PartSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    envelope: dict = field(default_factory=dict)
    template_source: str = ""


class Installer:
    def __init__(self, user_library, resources_dirs: Iterable[Path] = (), *, template=None,
                 cache_dir=None, downloader: Callable = download_file, log: Callable[[str], None] = print):
        self.user_library = Path(user_library)
        self.resources_dirs = [Path(p) for p in resources_dirs]
        self.template_path = template
        if cache_dir is None:
            from abhelper.config import data_dir
            cache_dir = data_dir() / "samples-cache"
        self.cache_dir = Path(cache_dir)
        self.downloader = downloader
        self.log = log

    # ------------------------------------------------------------------ locations
    def samples_dir(self, pack: Pack) -> Path:
        return self.user_library.joinpath(*SAMPLES_SUBDIR, pack.id)

    def preset_path(self, pack: Pack) -> Path:
        return self.user_library.joinpath(*PRESETS_SUBDIR, pack.preset_name + ".adv")

    def find_template(self) -> Template | None:
        return find_template(self.user_library, self.resources_dirs, self.template_path)

    # ------------------------------------------------------------------ status
    def status(self, pack: Pack) -> str:
        """'installed' | 'partial' | 'absent'."""
        manifest = self._read_manifest(pack)
        preset_ok = self.preset_path(pack).is_file()
        if manifest is None and not preset_ok:
            return "absent"
        if manifest is None or not preset_ok:
            return "partial"
        base = self.samples_dir(pack)
        if all((base / rel).is_file() for rel in manifest.get("files", [])):
            return "installed"
        return "partial"

    def _read_manifest(self, pack: Pack) -> dict | None:
        try:
            return json.loads((self.samples_dir(pack) / MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------ install
    def install(self, pack: Pack, force: bool = False) -> InstallResult:
        result = InstallResult(pack.id, self.preset_path(pack), self.samples_dir(pack))
        if not force and self.status(pack) == "installed":
            result.already_installed = True
            return result
        if not self.user_library.is_dir():
            raise InstallError("User Library не найдена: %s. Укажите её через --user-library "
                               "(путь смотрите в Live: Settings → Library)." % self.user_library)
        template = self.find_template()
        if template is None:
            raise InstallError("Не нашёл шаблон Sampler. " + HOW_TO_MAKE_TEMPLATE +
                               " Либо укажите папку Live через --live-dir (нужна Resources\\Core Library).")
        result.template_source = "%s (%s)" % (template.source, template.kind)
        self.log("Шаблон Sampler: %s" % result.template_source)

        archive = self._download(pack)
        work = Path(tempfile.mkdtemp(prefix="extract-%s-" % pack.id, dir=str(self._ensure(self.cache_dir))))
        try:
            self.log("Распаковываю %s ..." % archive.name)
            try:
                extract_archive(archive, work, pack.archive)
            except ExtractError as exc:
                raise InstallError(str(exc))
            sfz_path = self._locate_sfz(work, pack)
            self._build(pack, template, work, sfz_path, result)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        return result

    def _download(self, pack: Pack) -> Path:
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(pack.url).path)).name or (pack.id + ".bin")
        dest = self._ensure(self.cache_dir) / name
        state = {"last": -1}

        def progress(done: int, total: int) -> None:
            if total:
                pct = done * 100 // total
                if pct // 10 != state["last"] // 10 or pct == 100 and state["last"] != 100:
                    state["last"] = pct
                    self.log("  скачано %d%% (%.1f из %.1f МБ)" % (pct, done / 1e6, total / 1e6))

        self.log("Скачиваю %s (%s)" % (pack.name, "%.1f МБ" % (pack.size_bytes / 1e6) if pack.size_bytes else "размер неизвестен"))
        try:
            return self.downloader(pack.url, dest, size_bytes=pack.size_bytes, sha256=pack.sha256, progress=progress)
        except DownloadError as exc:
            raise InstallError("Не удалось скачать: %s" % exc)

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _locate_sfz(root: Path, pack: Pack) -> Path:
        direct = root / pack.sfz
        if direct.is_file():
            return direct
        name = PurePosixPath(pack.sfz.replace("\\", "/")).name.lower()
        for p in sorted(root.rglob("*.sfz")):
            if p.name.lower() == name:
                return p
        raise InstallError("В архиве нет файла %s (найдено: %s)" % (
            pack.sfz, ", ".join(p.name for p in root.rglob("*.sfz")) or "ни одного .sfz"))

    @staticmethod
    def _find_file(base: Path, rel: str) -> Path | None:
        """`base/rel`, tolerating different letter case (SFZ files are often written on Windows)."""
        p = base.joinpath(*PurePosixPath(rel).parts)
        if p.is_file():
            return p
        cur = base
        for part in PurePosixPath(rel).parts:
            nxt = cur / part
            if not nxt.exists():
                try:
                    match = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
                except OSError:
                    match = None
                if match is None:
                    return None
                nxt = match
            cur = nxt
        return cur if cur.is_file() else None

    def _build(self, pack: Pack, template: Template, work: Path, sfz_path: Path, result: InstallResult) -> None:
        try:
            inst = parse_sfz_file(sfz_path)
        except (OSError, SfzError) as exc:
            raise InstallError("Не удалось разобрать %s: %s" % (sfz_path.name, exc))
        result.skipped = list(inst.skipped)
        result.envelope = dict(inst.envelope)
        sfz_dir = sfz_path.parent

        # which files, under which relative names
        wanted: dict[str, Path] = {}
        regions = []
        for region in inst.regions:
            parts = [p for p in PurePosixPath(region.sample).parts if p not in ("..", ".", "/")]
            if not parts:
                continue
            src = self._find_file(sfz_dir, "/".join(parts))
            if src is None:
                result.warnings.append("файл сэмпла не найден в архиве: %s" % region.sample)
                continue
            rel = "/".join(parts)
            wanted[rel] = src
            regions.append((region, rel))
        if not regions:
            raise InstallError("В %s нет ни одной пригодной зоны сэмплов." % sfz_path.name)

        # stage the files next to the final folder, then swap
        final = self.samples_dir(pack)
        stage = final.with_name(final.name + ".installing")
        shutil.rmtree(str(stage), ignore_errors=True)
        try:
            for rel, src in wanted.items():
                dst = stage.joinpath(*rel.split("/"))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            self._write_notices(pack, work, sfz_dir, stage)
            parts_specs: list[PartSpec] = []
            rel_root = "/".join(SAMPLES_SUBDIR + (pack.id,))
            for region, rel in regions:
                staged = stage.joinpath(*rel.split("/"))
                try:
                    info = read_audio_info(staged)
                except AudioError as exc:
                    result.warnings.append(str(exc))
                    continue
                spec = region_to_part(region, info, final.joinpath(*rel.split("/")), "%s/%s" % (rel_root, rel))
                result.warnings.extend(spec.warnings)
                parts_specs.append(spec)
            if not parts_specs:
                raise InstallError("Ни один файл сэмпла не удалось прочитать.")
            parts_specs.sort(key=lambda s: (s.lokey, s.lovel, s.root, s.name))
            try:
                xml = build_preset_xml(template, parts_specs, pack.preset_name, inst.envelope or None)
            except TemplateError as exc:
                raise InstallError(str(exc))
            files = sorted(str(p.relative_to(stage)).replace("\\", "/") for p in stage.rglob("*") if p.is_file())
            (stage / MANIFEST_NAME).write_text(json.dumps({
                "id": pack.id, "name": pack.name, "preset": pack.preset_name + ".adv",
                "license": pack.license, "source_url": pack.url, "template": result.template_source,
                "files": [f for f in files if f != MANIFEST_NAME]}, ensure_ascii=False, indent=2), encoding="utf-8")
            shutil.rmtree(str(final), ignore_errors=True)
            stage.replace(final)
            write_adv(self.preset_path(pack), xml)
        except BaseException:
            shutil.rmtree(str(stage), ignore_errors=True)
            raise
        result.parts = parts_specs

    @staticmethod
    def _write_notices(pack: Pack, work: Path, sfz_dir: Path, stage: Path) -> None:
        """Keep the pack's own license / readme next to the samples, plus our ATTRIBUTION.txt."""
        for folder in dict.fromkeys([sfz_dir, work]):
            for p in sorted(folder.glob("*")):
                if p.is_file() and p.suffix.lower() in (".txt", ".md", "") and p.stem.lower().startswith(_NOTICE_NAMES):
                    shutil.copy2(str(p), str(stage / p.name))
        lic = pack.license
        (stage / "ATTRIBUTION.txt").write_text(
            "%s\nЛицензия: %s (%s)\nАвторы: %s\nИсточник: %s\nСтраница: %s\n\n"
            "Файлы скачаны и разложены программой Ableton Helper (abhelper samples install %s).\n" % (
                pack.name, lic.get("name", ""), lic.get("url", ""), pack.attribution, pack.url, pack.homepage, pack.id),
            encoding="utf-8")

    # ------------------------------------------------------------------ uninstall
    def uninstall(self, pack: Pack) -> list[Path]:
        removed: list[Path] = []
        samples = self.samples_dir(pack)
        if samples.exists():
            shutil.rmtree(str(samples), ignore_errors=True)
            removed.append(samples)
        preset = self.preset_path(pack)
        if preset.exists():
            preset.unlink()
            removed.append(preset)
        for folder in (preset.parent, samples.parent):
            try:
                folder.rmdir()                 # only if empty
            except OSError:
                pass
        return removed


def rescan_browser(bridge) -> tuple[bool, str]:
    """Ask Live to re-index its browser so the new preset shows up. Returns (ok, message)."""
    from abhelper.bridge.base import BridgeError
    try:
        bridge.call("browser_rescan", {"categories": ["user_library"]})
        return True, "Браузер Live переиндексируется — через несколько секунд пресет появится в User Library."
    except BridgeError as exc:
        return False, "Live недоступен (%s): пресет появится в браузере после перезапуска Live или обновления User Library." % exc

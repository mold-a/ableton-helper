"""Sample-library instruments for Ableton Live.

Synthesis cannot make a realistic bayan, so this package downloads free (CC0) sample libraries and turns
them into Ableton Sampler presets (`<User Library>/Presets/Instruments/Sampler/AbletonHelper/*.adv`).
Sound engine then finds them in the Live browser like any other preset.

Layout: registry.json (catalogue) / download.py / sfz.py / audioinfo.py / adv.py (preset generator) /
installer.py (install, uninstall, status) / cli.py (`abhelper samples ...`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.json"
ARCHIVE_FORMATS = ("7z", "zip", "tar.gz", "tar.xz", "tar.bz2")
PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HELPER_PREFIX = "AbletonHelper"


@dataclass
class Pack:
    id: str
    name: str
    kind: str
    license: dict
    url: str
    archive: str
    sfz: str
    preset_name: str
    size_bytes: int | None = None
    sha256: str | None = None
    attribution: str = ""
    homepage: str = ""
    aliases: list[str] = field(default_factory=list)
    recipe_ids: list[str] = field(default_factory=list)
    default: bool = True
    verified: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Pack":
        return cls(
            id=d["id"], name=d["name"], kind=d["kind"], license=dict(d["license"]), url=d["url"],
            archive=d["archive"], sfz=d["sfz"], preset_name=d["preset_name"], size_bytes=d.get("size_bytes"),
            sha256=d.get("sha256"), attribution=d.get("attribution", ""), homepage=d.get("homepage", ""),
            aliases=list(d.get("aliases") or []), recipe_ids=list(d.get("recipe_ids") or []),
            default=bool(d.get("default", True)), verified=bool(d.get("verified", False)), notes=d.get("notes", ""))


def validate_registry(data: Any, known_recipe_ids: set[str] | None = None) -> list[str]:
    """Human-readable problems of a registry document (empty list = valid)."""
    errors: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("packs"), list):
        return ["registry: нужен объект {\"packs\": [...]}"]
    seen_ids: set[str] = set()
    seen_presets: set[str] = set()
    for i, p in enumerate(data["packs"]):
        where = "packs[%d]" % i
        if not isinstance(p, dict):
            errors.append("%s: должен быть объектом" % where)
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not PACK_ID_RE.match(pid):
            errors.append("%s.id: нужен идентификатор [a-z0-9-]+" % where)
        elif pid in seen_ids:
            errors.append("%s.id: «%s» повторяется" % (where, pid))
        else:
            seen_ids.add(pid)
            where = "pack «%s»" % pid
        for key in ("name", "kind", "url", "sfz", "preset_name"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                errors.append("%s.%s: нужна непустая строка" % (where, key))
        if isinstance(p.get("url"), str) and not p["url"].startswith("https://"):
            errors.append("%s.url: только HTTPS" % where)
        if p.get("archive") not in ARCHIVE_FORMATS:
            errors.append("%s.archive: одно из %s" % (where, ", ".join(ARCHIVE_FORMATS)))
        preset = p.get("preset_name")
        if isinstance(preset, str):
            if not preset.startswith(HELPER_PREFIX):
                errors.append("%s.preset_name: имя должно начинаться с «%s» (по нему движок повышает рейтинг)"
                              % (where, HELPER_PREFIX))
            if re.search(r'[\\/:*?"<>|]', preset):
                errors.append("%s.preset_name: недопустимые символы для имени файла" % where)
            if preset in seen_presets:
                errors.append("%s.preset_name: «%s» повторяется" % (where, preset))
            seen_presets.add(preset)
        lic = p.get("license")
        if not isinstance(lic, dict) or not isinstance(lic.get("name"), str) or not str(lic.get("url", "")).startswith("https://"):
            errors.append("%s.license: нужен объект {name, url(https), spdx?}" % where)
        size = p.get("size_bytes")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size <= 0):
            errors.append("%s.size_bytes: положительное целое или null" % where)
        sha = p.get("sha256")
        if sha is not None and not (isinstance(sha, str) and SHA256_RE.match(sha)):
            errors.append("%s.sha256: 64 hex-символа нижнего регистра или null" % where)
        if p.get("verified") is True and (size is None or sha is None):
            errors.append("%s: verified=true требует size_bytes и sha256" % where)
        for key in ("aliases", "recipe_ids"):
            v = p.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                errors.append("%s.%s: список непустых строк" % (where, key))
        if known_recipe_ids is not None and isinstance(p.get("recipe_ids"), list):
            for rid in p["recipe_ids"]:
                if rid not in known_recipe_ids:
                    errors.append("%s.recipe_ids: рецепта «%s» нет в библиотеке" % (where, rid))
        if "default" in p and not isinstance(p["default"], bool):
            errors.append("%s.default: true/false" % where)
        if p.get("default") and not p.get("verified"):
            errors.append("%s: default=true допустим только для проверенных паков (verified=true)" % where)
    return errors


def load_registry(path: Path | str | None = None) -> list[Pack]:
    p = Path(path) if path else REGISTRY_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    errors = validate_registry(data)
    if errors:
        raise ValueError("registry.json: " + "; ".join(errors[:5]))
    return [Pack.from_dict(d) for d in data["packs"]]


def find_pack(packs: list[Pack], ident: str) -> Pack | None:
    key = ident.strip().lower()
    for p in packs:
        if p.id == key:
            return p
    return None

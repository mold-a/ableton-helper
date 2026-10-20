"""Device parameter roles: "what does this parameter do" for the native devices (data/device_roles.json).

A role ("cutoff", "attack", "wet", ...) maps to the exact parameter names of a device. Used to
  * prioritise the important parameters of big devices in the get_device_parameters tool (Operator has 195),
  * filter parameters by role/keyword (``query="filter"``),
  * drive the deterministic adjective tweaks of sound/tweaks.py (adjust_sound).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

ROLES_PATH = Path(__file__).resolve().parent / "data" / "device_roles.json"

# device-name aliases (how Live / users call them) -> canonical catalog name
_DEVICE_ALIASES = {
    "chorus": "Chorus-Ensemble", "chorus ensemble": "Chorus-Ensemble", "chorus2": "Chorus-Ensemble",
    "phaser": "Phaser-Flanger", "phaser flanger": "Phaser-Flanger", "phasernew": "Phaser-Flanger",
    "eq 8": "EQ Eight", "eq8": "EQ Eight", "eq-8": "EQ Eight",
    "vinyl": "Vinyl Distortion", "ultraanalog": "Analog", "instrumentvector": "Wavetable",
    "stereogain": "Utility", "originalsimpler": "Simpler", "multisampler": "Sampler", "drumgroupdevice": "Drum Rack",
}


def _norm(s: str) -> str:
    return re.sub(r"[\s_]+", " ", s.strip().lower())


@dataclass(frozen=True)
class RoleParam:
    name: str
    when: str | None = None  # name of an On/Off parameter that must be On for this one to matter


@dataclass
class DeviceRoles:
    name: str
    class_name: str
    kind: str  # "instrument" | "effect"
    roles: dict[str, list[RoleParam]] = field(default_factory=dict)

    def params(self, role: str) -> list[RoleParam]:
        return self.roles.get(role, [])

    def priority_names(self) -> list[str]:
        """Parameter names that carry a role, in role order, without duplicates (+ their `when` switches)."""
        seen: dict[str, None] = {}
        for plist in self.roles.values():
            for rp in plist:
                seen.setdefault(rp.name, None)
                if rp.when:
                    seen.setdefault(rp.when, None)
        return list(seen)

    def roles_of(self, param_name: str) -> list[str]:
        return [r for r, plist in self.roles.items() if any(rp.name == param_name for rp in plist)]


class RoleBook:
    def __init__(self, data: dict):
        self.labels: dict[str, dict[str, str]] = data.get("role_labels", {})
        self.groups: dict[str, list[str]] = data.get("role_groups", {})
        self.devices: dict[str, DeviceRoles] = {}
        self._lookup: dict[str, str] = {}
        for name, spec in data.get("devices", {}).items():
            roles: dict[str, list[RoleParam]] = {}
            for role, plist in spec.get("roles", {}).items():
                roles[role] = [RoleParam(e["param"], e.get("when")) if isinstance(e, dict) else RoleParam(e)
                               for e in plist]
            dev = DeviceRoles(name=name, class_name=spec.get("class_name", name), kind=spec.get("kind", "effect"),
                              roles=roles)
            self.devices[name] = dev
            self._lookup[_norm(name)] = name
            self._lookup[_norm(dev.class_name)] = name

    def get(self, name: str | None, class_name: str | None = None) -> DeviceRoles | None:
        for key in (name, class_name):
            if not key:
                continue
            k = _norm(key)
            canon = self._lookup.get(k) or _DEVICE_ALIASES.get(k)
            if canon and canon in self.devices:
                return self.devices[canon]
        return None

    def label(self, role: str, lang: str = "ru") -> str:
        return self.labels.get(role, {}).get(lang) or role.replace("_", " ")

    def roles_for_query(self, query: str) -> set[str]:
        """Role names a free-text query refers to: a role name, a role-group name ("filter", "envelope")."""
        q = _norm(query)
        if not q:
            return set()
        out: set[str] = set()
        known = set(self.labels)
        for dev in self.devices.values():
            known.update(dev.roles)
        for tok in [q] + q.split():
            tok_n = tok.replace(" ", "_")
            if tok_n in known:
                out.add(tok_n)
            if tok in self.groups:
                out.update(self.groups[tok])
        return out


@lru_cache(maxsize=1)
def load_roles(path: str | None = None) -> RoleBook:
    p = Path(path) if path else ROLES_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("device roles unavailable (%s): %s", p, e)
        data = {}
    return RoleBook(data)


def filter_parameters(book: RoleBook, device: DeviceRoles | None, rows: list[dict], query: str | None = None,
                      names: Iterable[str] | None = None) -> tuple[list[dict], list[str]]:
    """Select parameter rows (dicts with "name") by ``names`` (exact, case-insensitive) and/or ``query``.

    A query matches a parameter when every query word is a substring of the parameter name, or when the
    query is a role / role group of the device that the parameter has ("filter" -> cutoff, resonance...).
    Returns (rows, names_not_found).
    """
    selected = rows
    missing: list[str] = []
    if names:
        by_norm = {_norm(r["name"]): r for r in rows}
        picked: list[dict] = []
        for n in names:
            r = by_norm.get(_norm(str(n)))
            if r is None:
                missing.append(str(n))
            elif r not in picked:
                picked.append(r)
        selected = picked
    if query and query.strip():
        words = _norm(query).split()
        wanted_roles = book.roles_for_query(query)
        role_names: set[str] = set()
        if device is not None and wanted_roles:
            for role in wanted_roles:
                role_names.update(rp.name for rp in device.params(role))
        out = []
        for r in selected:
            n = _norm(r["name"])
            if all(w in n for w in words) or r["name"] in role_names:
                out.append(r)
        selected = out
    return selected, missing

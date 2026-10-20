"""Fuzzy mapping of recipe parameter names/values onto a device's real parameters.

Order of attempts for a recipe key (see docs/INTERFACES.md): exact name, case-insensitive,
normalised (alphanumerics only), then every alternative from data/param_aliases.json.
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ALIASES_PATH = Path(__file__).resolve().parent / "data" / "param_aliases.json"


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


class AliasTable:
    """Groups of interchangeable names for parameters, device names and quantized values."""

    def __init__(self, parameters: list[list[str]] | None = None, devices: list[list[str]] | None = None,
                 values: list[list[str]] | None = None):
        self._params = self._index(parameters or [])
        self._devices = self._index(devices or [])
        self._values = self._index(values or [])

    @staticmethod
    def _index(groups: list[list[str]]) -> dict[str, list[list[str]]]:
        idx: dict[str, list[list[str]]] = {}
        for g in groups:
            for name in g:
                idx.setdefault(norm_name(name), []).append(g)
        return idx

    @staticmethod
    def _variants(index: dict[str, list[list[str]]], name: str) -> list[str]:
        out = [name]
        for group in index.get(norm_name(name), []):
            for alt in group:
                if alt not in out:
                    out.append(alt)
        return out

    def parameter_variants(self, name: str) -> list[str]:
        return self._variants(self._params, name)

    def device_variants(self, name: str) -> list[str]:
        return self._variants(self._devices, name)

    def value_variants(self, name: str) -> list[str]:
        return self._variants(self._values, name)

    @classmethod
    def from_file(cls, path: Path | str = ALIASES_PATH) -> "AliasTable":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(data.get("parameters"), data.get("devices"), data.get("values"))


@lru_cache(maxsize=1)
def default_aliases() -> AliasTable:
    return AliasTable.from_file()


def resolve_parameter(key: str, live_params: list[dict], aliases: AliasTable | None = None) -> dict | None:
    """Find the live parameter for a recipe key, or None."""
    aliases = aliases or default_aliases()
    candidates = aliases.parameter_variants(key)
    steps = (
        lambda a, b: a == b,
        lambda a, b: a.lower() == b.lower(),
        lambda a, b: norm_name(a) == norm_name(b) and norm_name(a) != "",
    )
    for step in steps:
        for cand in candidates:
            for p in live_params:
                if step(p.get("name", ""), cand):
                    return p
    return None


def suggest_parameters(key: str, live_params: list[dict], n: int = 3) -> list[str]:
    names = [p.get("name", "") for p in live_params]
    by_norm = {norm_name(x): x for x in names}
    close = difflib.get_close_matches(norm_name(key), list(by_norm), n=n, cutoff=0.5)
    return [by_norm[c] for c in close]


def resolve_value(value: Any, param: dict, aliases: AliasTable | None = None) -> tuple[bool, Any, str]:
    """Convert a recipe value to something the bridge accepts for this parameter.

    Returns (ok, value_to_send, reason_if_not_ok).
    """
    aliases = aliases or default_aliases()
    if isinstance(value, bool):
        return True, int(value), ""
    if isinstance(value, (int, float)):
        return True, value, ""
    if isinstance(value, dict) and "norm" in value:
        try:
            x = max(0.0, min(1.0, float(value["norm"])))
        except (TypeError, ValueError):
            return False, None, "некорректное значение norm"
        return True, {"norm": x}, ""
    if isinstance(value, str):
        items = [str(i) for i in (param.get("value_items") or [])]
        if not items:
            try:
                return True, float(value), ""
            except ValueError:
                return False, None, "строковое значение для неквантованного параметра"
        wanted = aliases.value_variants(value)
        for step in (lambda a, b: a == b, lambda a, b: a.lower() == b.lower(),
                     lambda a, b: norm_name(a) == norm_name(b)):
            for w in wanted:
                for i, it in enumerate(items):
                    if step(it, w):
                        return True, i, ""
        nv = norm_name(value)
        starts = [i for i, it in enumerate(items) if nv and norm_name(it).startswith(nv)]
        if len(starts) == 1:
            return True, starts[0], ""
        contains = [i for i, it in enumerate(items) if nv and nv in norm_name(it)]
        if len(contains) == 1:
            return True, contains[0], ""
        shown = ", ".join(items[:14]) + ("…" if len(items) > 14 else "")
        return False, None, f"значение «{value}» не найдено среди [{shown}]"
    return False, None, f"неподдерживаемый тип значения: {type(value).__name__}"

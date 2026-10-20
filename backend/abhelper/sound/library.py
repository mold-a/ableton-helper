"""Recipe library: loading JSON recipes and RU/EN alias search."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .matching import build_entry, make_toks, score_entry
from .schema import validate_recipe

log = logging.getLogger(__name__)

RECIPES_DIR = Path(__file__).resolve().parent / "recipes"


@dataclass
class RecipeMatch:
    recipe_id: str
    name: str  # localised name (ru if present)
    score: float  # 0..1
    category: str

    def to_dict(self) -> dict:
        return asdict(self)


def recipe_display_name(recipe: dict) -> str:
    name = recipe.get("name") or {}
    if isinstance(name, str):
        return name
    return name.get("ru") or name.get("en") or recipe.get("id", "")


class RecipeLibrary:
    def __init__(self, recipes: list[dict] | None = None):
        self._recipes: dict[str, dict] = {}
        self._entries: dict[str, object] = {}
        for r in recipes or []:
            self.add(r)

    # ------------------------------------------------------------------ loading
    @classmethod
    def load_default(cls) -> "RecipeLibrary":
        return cls.load_dir(RECIPES_DIR)

    @classmethod
    def load_dir(cls, directory: Path | str) -> "RecipeLibrary":
        lib = cls()
        for path in sorted(Path(directory).glob("*.json")):
            try:
                recipe = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.warning("Skipping unreadable recipe %s: %s", path.name, exc)
                continue
            errors = validate_recipe(recipe)
            if errors:
                log.warning("Skipping invalid recipe %s: %s", path.name, "; ".join(errors))
                continue
            lib.add(recipe)
        return lib

    def add(self, recipe: dict) -> None:
        rid = recipe["id"]
        self._recipes[rid] = recipe
        self._entries[rid] = build_entry(recipe)

    # ------------------------------------------------------------------ access
    def get(self, recipe_id: str) -> dict | None:
        return self._recipes.get(recipe_id)

    def all(self) -> list[dict]:
        return list(self._recipes.values())

    def __len__(self) -> int:
        return len(self._recipes)

    def __contains__(self, recipe_id: object) -> bool:
        return recipe_id in self._recipes

    # ------------------------------------------------------------------ search
    def search(self, query: str, limit: int = 5) -> list[RecipeMatch]:
        q = make_toks(query or "")
        if not q:
            return []
        scored: list[tuple[float, str]] = []
        for rid, entry in self._entries.items():
            s = score_entry(q, entry)  # type: ignore[arg-type]
            if s > 0.05:
                scored.append((s, rid))
        scored.sort(key=lambda t: (-t[0], t[1]))
        out = []
        for s, rid in scored[: max(0, limit)]:
            r = self._recipes[rid]
            out.append(RecipeMatch(rid, recipe_display_name(r), round(s, 3), r.get("category", "")))
        return out

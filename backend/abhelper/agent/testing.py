"""Test doubles for the agent (kept in the package so every test directory can use them)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StubSoundResult:
    ok: bool
    track_index: int | None
    track_name: str | None
    source: str = "recipe"
    recipe_id: str | None = None
    preset: dict | None = None
    devices: list[dict] = field(default_factory=list)
    unmatched_parameters: list[dict] = field(default_factory=list)
    demo_clip_slot: int | None = None
    warnings: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class StubEngine:
    """Minimal stand-in for abhelper.sound.SoundEngine that really drives the bridge."""

    RECIPES = {"баян": ("bayan", "Баян", "reed"), "accordion": ("bayan", "Баян", "reed"),
               "бас": ("sub_bass", "Саб-бас", "bass")}

    def __init__(self, bridge: Any, unmatched: list[dict] | None = None):
        self.bridge = bridge
        self.unmatched = unmatched or []
        self.requests: list[Any] = []

    def find_recipes(self, query: str, limit: int = 5) -> list[dict]:
        q = query.lower()
        out = []
        for key, (rid, name, cat) in self.RECIPES.items():
            if key in q:
                out.append({"recipe_id": rid, "name": name, "score": 0.9, "category": cat})
        return out[:limit]

    def search_presets(self, query: str, terms: list[str] | None = None, limit: int = 10) -> list[dict]:
        res = self.bridge.call("browser_search", {"query": query, "limit": limit})
        return [dict(i, score=0.5) for i in res["items"]]

    def create_sound(self, request: Any) -> StubSoundResult:
        self.requests.append(request)
        name = request.track_name or (request.recipe or {}).get("track", {}).get("name") \
            or ("Баян" if request.recipe_id == "bayan" else "Sound")
        if request.track_index is None:
            t = self.bridge.call("create_midi_track", {"name": name})["track_index"]
        else:
            t = request.track_index
        device = (request.recipe or {}).get("instrument", {}).get("device", "Operator")
        d = self.bridge.call("load_device", {"track_index": t, "device_name": device})
        slot = None
        if request.add_demo_clip:
            slot = self.bridge.call("create_clip", {"track_index": t, "length": 8.0, "name": name})["slot_index"]
        return StubSoundResult(
            ok=True, track_index=t, track_name=name, recipe_id=request.recipe_id,
            devices=[{"index": d["device_index"], "name": d["name"], "class_name": d["class_name"]}],
            unmatched_parameters=list(self.unmatched), demo_clip_slot=slot,
            message=f"Создана дорожка «{name}».")

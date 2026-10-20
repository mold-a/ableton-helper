"""Searching Live's browser for ready-made presets and ranking the candidates."""

from __future__ import annotations

import re
import time
from typing import Callable

from abhelper.bridge.base import BridgeCommandError

from .matching import make_tok, token_match, tokenize

_EXT_RE = re.compile(r"\.(adv|adg|alp|amxd|aupreset|vstpreset|fxp|fxb|wav|aif|aiff|mp3|flac|ogg|mid|als|alc|agr|adm)$", re.I)

# How suitable a browser category is for "give me an instrument sound".
_CATEGORY_WEIGHT = {
    "sounds": 1.0, "instruments": 0.95, "drums": 0.55, "user_library": 0.85, "packs": 0.75,
    "current_project": 0.5, "user_folders": 0.5, "samples": 0.35, "clips": 0.3,
    "max_for_live": 0.4, "plugins": 0.3, "audio_effects": 0.0, "midi_effects": 0.0,
}
_DRUM_CATEGORY_WEIGHT = {**_CATEGORY_WEIGHT, "drums": 1.0, "sounds": 0.8, "instruments": 0.7}
_SAMPLE_CATEGORY_WEIGHT = {**_CATEGORY_WEIGHT, "samples": 1.0, "clips": 0.6, "sounds": 0.7}

DRUM_CATEGORIES = ("drums", "percussion")
SAMPLER_DEVICES = ("Simpler", "Sampler")


def clean_name(name: str) -> str:
    return _EXT_RE.sub("", name or "").strip()


def category_weights(recipe_category: str | None = None, instrument: str | None = None) -> dict[str, float]:
    if instrument in SAMPLER_DEVICES:
        return _SAMPLE_CATEGORY_WEIGHT
    if recipe_category in DRUM_CATEGORIES or instrument == "Drum Rack":
        return _DRUM_CATEGORY_WEIGHT
    return _CATEGORY_WEIGHT


def _matched(q_toks, pool) -> list[bool]:
    return [any(token_match(q, p) >= 0.85 for p in pool) for q in q_toks]


def score_item(item: dict, term: str, weights: dict[str, float], term_rank: int = 0) -> float:
    """Score one browser item for one search term, 0..1."""
    if item.get("is_device") or item.get("is_folder") or not item.get("is_loadable", True):
        return 0.0
    q = [make_tok(w) for w in tokenize(term)]
    if not q:
        return 0.0
    name_toks = [make_tok(w) for w in tokenize(clean_name(item.get("name", "")))]
    parts = (item.get("path") or "").split("/")
    folder_toks = [make_tok(w) for w in tokenize(" ".join(parts[1:-1]))]
    name_hits = _matched(q, name_toks)
    all_hits = _matched(q, name_toks + folder_toks)
    name_cov = sum(name_hits) / len(q)
    path_cov = sum(all_hits) / len(q)
    if path_cov == 0:
        return 0.0
    unmatched_name = sum(1 for p in name_toks if not any(token_match(qq, p) >= 0.85 for qq in q))
    exact = 1.0 if name_cov == 1.0 and unmatched_name == 0 else 0.0
    base = 0.65 * name_cov + 0.2 * path_cov + 0.15 * exact - min(0.1, 0.02 * unmatched_name)
    weight = weights.get(item.get("category", ""), 0.5)
    rank_factor = max(0.8, 1.0 - 0.04 * term_rank)
    return max(0.0, base * weight * rank_factor)


class PresetSearcher:
    """Runs browser searches through the bridge. `sleep`/`clock` are injectable for tests."""

    def __init__(self, bridge, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, wait_budget: float = 3.0,
                 poll_interval: float = 0.4):
        self.bridge = bridge
        self.sleep = sleep
        self.clock = clock
        self.wait_budget = wait_budget
        self.poll_interval = poll_interval
        self.last_error: str | None = None
        self.index_complete: bool = True

    def _wait_for_index(self, deadline: float) -> None:
        while True:
            try:
                status = self.bridge.call("browser_status")
            except BridgeCommandError:
                return
            self.index_complete = bool(status.get("complete", True))
            if self.index_complete or self.clock() >= deadline:
                return
            self.sleep(self.poll_interval)

    def _query(self, term: str, limit: int, deadline: float) -> list[dict]:
        while True:
            res = self.bridge.call("browser_search", {"query": term, "loadable_only": True, "limit": limit})
            items = res.get("items", []) or []
            complete = bool(res.get("index_complete", True))
            self.index_complete = complete
            if items or complete or self.clock() >= deadline:
                return items
            self.sleep(self.poll_interval)

    def search(self, terms: list[str], recipe_category: str | None = None,
               instrument: str | None = None, limit: int = 10, per_term: int = 25) -> list[dict]:
        self.last_error = None
        deadline = self.clock() + self.wait_budget
        weights = category_weights(recipe_category, instrument)
        seen_terms: list[str] = []
        for t in terms:
            t = (t or "").strip()
            if t and t.lower() not in [s.lower() for s in seen_terms]:
                seen_terms.append(t)
        try:
            self._wait_for_index(deadline)
            merged: dict[str, dict] = {}
            for rank, term in enumerate(seen_terms[:8]):
                queries = [term]
                items = self._query(term, per_term, deadline)
                if not items:
                    words = [w for w in tokenize(term) if len(w) >= 4]
                    if len(words) >= 2:
                        queries = words[:2]
                        items = []
                        for w in queries:
                            items.extend(self._query(w, per_term, deadline))
                for it in items:
                    s = score_item(it, term, weights, rank)
                    key = it.get("uri") or it.get("path") or it.get("name")
                    if s > 0 and (key not in merged or s > merged[key]["score"]):
                        merged[key] = {**it, "score": round(s, 3), "matched_term": term}
        except BridgeCommandError as exc:
            self.last_error = f"{exc.code}: {exc.message}"
            return []
        ranked = sorted(merged.values(), key=lambda i: (-i["score"], len(i.get("path", "")), i.get("name", "")))
        return ranked[: max(0, limit)]

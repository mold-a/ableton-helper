"""SoundEngine: turns "I want an accordion sound" into a configured MIDI track in Live.

Flow of `create_sound` (strategy "auto"):
  explicit preset_uri -> load it;
  otherwise resolve a recipe (custom dict > recipe_id > library search) ->
  look for a matching preset in Live's browser -> else build the sound from native devices
  (instrument + parameters + effect chain) -> add a short demo MIDI clip.

All bridge failures are converted to `SoundResult(ok=False, ...)`; if the track was already
created the result says what was done and the track is left in the set.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from abhelper.bridge.base import BridgeCommandError, BridgeConnectionError, BridgeError

from .demo import build_demo, default_style
from .library import RecipeLibrary, RecipeMatch, recipe_display_name
from .matching import STOPWORDS, tokenize
from .params import AliasTable, default_aliases, norm_name, resolve_parameter, resolve_value, suggest_parameters
from .presets import SAMPLER_DEVICES, PresetSearcher, clean_name
from .schema import validate_recipe

RECIPE_THRESHOLD = 0.5   # minimal library match score to pick a recipe automatically
PRESET_THRESHOLD = 0.6   # minimal ranked score to prefer a browser preset over synthesis

_CATEGORY_COLORS = {
    "keys": 12, "piano": 14, "organ": 17, "strings": 25, "brass": 8, "woodwind": 21, "reed": 3,
    "plucked": 5, "guitar": 6, "bass": 60, "lead": 56, "pad": 40, "bell": 36, "mallet": 38,
    "choir": 43, "fx": 49, "drums": 69, "percussion": 66, "ethnic": 10, "synth": 53,
}
_INFER_CATEGORY = {
    "bass": "bass", "sub": "bass", "pad": "pad", "lead": "lead", "pluck": "plucked", "drum": "drums",
    "kit": "drums", "kick": "drums", "piano": "piano", "keys": "keys", "organ": "organ",
    "string": "strings", "brass": "brass", "bell": "bell", "choir": "choir", "vocal": "choir",
    "guitar": "guitar", "flute": "woodwind", "fx": "fx", "riser": "fx", "arp": "synth",
    "percussion": "percussion", "mallet": "mallet", "marimba": "mallet",
}


@dataclass
class SoundRequest:
    description: str
    recipe_id: str | None = None
    recipe: dict | None = None
    preset_uri: str | None = None
    strategy: str = "auto"  # "auto" | "preset" | "recipe"
    track_name: str | None = None
    add_demo_clip: bool = True
    track_index: int | None = None  # None = new track, otherwise reuse this MIDI track


@dataclass
class SoundResult:
    ok: bool
    track_index: int | None
    track_name: str | None
    source: str  # "preset" | "recipe" | "custom_recipe"
    recipe_id: str | None
    preset: dict | None
    devices: list[dict]
    unmatched_parameters: list[dict]
    demo_clip_slot: int | None
    warnings: list[str]
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Run:
    """Mutable state of one create_sound call (so failures can report partial progress)."""
    request: SoundRequest
    result: SoundResult
    track_created: bool = False
    steps: list[str] = field(default_factory=list)


class _Abort(Exception):
    """Internal: stop with ok=False and a ready message."""


class SoundEngine:
    def __init__(self, bridge, library: RecipeLibrary | None = None, *,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 aliases: AliasTable | None = None):
        self.bridge = bridge
        self.library = library or RecipeLibrary.load_default()
        self.aliases = aliases or default_aliases()
        self.searcher = PresetSearcher(bridge, sleep=sleep, clock=clock)
        self._custom_counter = 0
        self.recipe_threshold = RECIPE_THRESHOLD
        self.preset_threshold = PRESET_THRESHOLD

    # ================================================================== public API
    def find_recipes(self, query: str, limit: int = 5) -> list[RecipeMatch]:
        return self.library.search(query, limit)

    def search_presets(self, query: str, terms: list[str] | None = None, limit: int = 10) -> list[dict]:
        """Search Live's browser; ranking prefers sounds/instruments/drums over samples/clips."""
        category = None
        if not terms:
            matches = self.library.search(query, 3)
            terms = []
            if query and query.isascii():
                terms.append(query)
            for m in matches:
                if m.score >= 0.4:
                    r = self.library.get(m.recipe_id) or {}
                    terms += list(r.get("preset_search") or [])[:3]
                    category = category or r.get("category")
            if not terms:
                terms = self._latin_terms(query)
        return self.searcher.search(terms, recipe_category=category, limit=limit)

    def apply_parameters(self, track_index: int, device_index: int, params: dict) -> list[dict]:
        """Fuzzy-apply {name: value} to a device; returns the list of unmatched parameters."""
        _, unmatched = self._apply(track_index, device_index, params or {})
        return unmatched

    def create_sound(self, request: SoundRequest) -> SoundResult:
        result = SoundResult(
            ok=False, track_index=request.track_index, track_name=None, source="recipe", recipe_id=None,
            preset=None, devices=[], unmatched_parameters=[], demo_clip_slot=None, warnings=[], message="",
        )
        run = _Run(request, result)
        try:
            self._create(run)
        except _Abort as exc:
            self._fail(run, str(exc))
        except BridgeConnectionError as exc:
            self._fail(run, f"Нет связи с Ableton Live ({exc}). Проверьте, что Live запущен и Remote Script "
                            "AbletonHelper включён в настройках.")
        except BridgeCommandError as exc:
            self._fail(run, f"Live отклонил команду: {exc.message} (код {exc.code}).")
        except BridgeError as exc:
            self._fail(run, f"Ошибка моста: {exc}.")
        return result

    # ================================================================== orchestration
    def _create(self, run: _Run) -> None:
        req, res = run.request, run.result
        if req.strategy not in ("auto", "preset", "recipe"):
            raise _Abort(f"Неизвестная стратегия «{req.strategy}» (допустимо: auto, preset, recipe).")

        recipe, is_custom, matches = self._resolve_recipe(run)
        if recipe is not None:
            res.recipe_id = recipe.get("id")
            res.source = "custom_recipe" if is_custom else "recipe"

        preset_item: dict | None = None
        if req.preset_uri:
            preset_item = {"uri": req.preset_uri}
        elif req.strategy in ("auto", "preset"):
            preset_item = self._pick_preset(run, recipe, is_custom, matches)

        if req.strategy == "preset" and preset_item is None:
            raise _Abort(f"В браузере Live не нашлось подходящего пресета для «{req.description}». "
                         "Попробуйте strategy=\"recipe\" или уточните запрос.")
        if preset_item is None and recipe is None:
            hints = [f"{m.recipe_id} ({m.name}, {m.score})" for m in matches[:3]]
            if hints:
                res.warnings.append("Ближайшие рецепты: " + "; ".join(hints))
            raise _Abort(
                f"Для «{req.description}» нет подходящего рецепта в библиотеке и пресета в браузере. "
                "Составьте собственный рецепт (design_custom_sound: инструмент, параметры, эффекты) "
                "по схеме рецепта и передайте его в create_sound.")

        track_index = self._prepare_track(run, recipe, preset_item)

        built = False
        if preset_item is not None:
            built = self._load_preset(run, track_index, preset_item, recipe, fallback_allowed=(
                req.strategy == "auto" and recipe is not None))
        if not built:
            assert recipe is not None
            res.source = "custom_recipe" if is_custom else "recipe"
            res.preset = None
            self._build_from_recipe(run, track_index, recipe)

        if req.add_demo_clip:
            self._add_demo(run, track_index, recipe, res.preset)
        self._refresh_devices(run, track_index)
        res.ok = True
        res.message = self._summary(run, recipe)

    # ------------------------------------------------------------------ recipe resolution
    def _resolve_recipe(self, run: _Run) -> tuple[dict | None, bool, list[RecipeMatch]]:
        req, res = run.request, run.result
        matches = self.library.search(req.description, 5) if req.description else []
        if req.recipe is not None:
            errors = validate_recipe(req.recipe, custom=True)
            if errors:
                res.warnings.extend(errors[:10])
                raise _Abort("Кастомный рецепт не прошёл проверку: " + "; ".join(errors[:5]))
            return self._normalize_custom(req.recipe, req.description), True, matches
        if req.recipe_id:
            recipe = self.library.get(req.recipe_id)
            if recipe is None:
                near = self.library.search(req.recipe_id, 3)
                if near:
                    res.warnings.append("Похожие рецепты: " + "; ".join(f"{m.recipe_id} ({m.name})" for m in near))
                raise _Abort(f"Рецепт «{req.recipe_id}» не найден в библиотеке.")
            return recipe, False, matches
        if req.preset_uri and req.strategy != "recipe":
            best = matches[0] if matches and matches[0].score >= self.recipe_threshold else None
            return (self.library.get(best.recipe_id) if best else None), False, matches
        if matches and matches[0].score >= self.recipe_threshold:
            return self.library.get(matches[0].recipe_id), False, matches
        return None, False, matches

    def _normalize_custom(self, recipe: dict, description: str) -> dict:
        r = copy.deepcopy(recipe)
        if not r.get("id"):
            self._custom_counter += 1
            r["id"] = f"custom_{self._custom_counter}"
        if not r.get("name"):
            r["name"] = {"ru": (description or r["id"]).strip()[:40], "en": (description or r["id"]).strip()[:40]}
        r.setdefault("category", "synth")
        r.setdefault("aliases", [])
        return r

    # ------------------------------------------------------------------ preset selection
    def _pick_preset(self, run: _Run, recipe: dict | None, is_custom: bool, matches: list[RecipeMatch]) -> dict | None:
        terms = self._preset_terms(run.request, recipe, is_custom, matches)
        if not terms:
            return None
        category = recipe.get("category") if recipe else None
        device = (recipe.get("instrument") or {}).get("device") if recipe else None
        candidates = self.searcher.search(terms, recipe_category=category, instrument=device, limit=5)
        if self.searcher.last_error:
            run.result.warnings.append(f"Поиск по браузеру Live недоступен ({self.searcher.last_error}).")
        if candidates and candidates[0]["score"] >= self.preset_threshold:
            return candidates[0]
        if candidates:
            top = candidates[0]
            run.result.warnings.append(
                f"Пресеты в браузере похожи слабо (лучший: «{clean_name(top['name'])}», {top['score']}) — "
                "использую синтез по рецепту." if recipe else
                f"Пресеты в браузере похожи слабо (лучший: «{clean_name(top['name'])}», {top['score']}).")
        return None

    def _preset_terms(self, req: SoundRequest, recipe: dict | None, is_custom: bool,
                      matches: list[RecipeMatch]) -> list[str]:
        terms: list[str] = []
        if recipe is not None:
            terms += list(recipe.get("preset_search") or [])
            if not terms and not is_custom:
                terms += [a for a in recipe.get("aliases", []) if a.isascii()][:4]
            if not terms and is_custom and req.strategy == "preset":
                terms += self._latin_terms(req.description)
        else:
            terms += self._latin_terms(req.description)
            for m in matches:
                if m.score >= 0.25:
                    r = self.library.get(m.recipe_id) or {}
                    terms += list(r.get("preset_search") or [])[:3]
        return terms

    @staticmethod
    def _latin_terms(text: str) -> list[str]:
        words = [w for w in tokenize(text or "") if w.isascii() and w not in STOPWORDS and len(w) > 2]
        if not words:
            return []
        out = [" ".join(words)] if len(words) > 1 else []
        out += words
        return out

    # ------------------------------------------------------------------ track handling
    def _prepare_track(self, run: _Run, recipe: dict | None, preset_item: dict | None) -> int:
        req, res = run.request, run.result
        name = self._track_name(req, recipe, preset_item)
        if req.track_index is not None:
            info = self.bridge.call("get_track_info", {"track_index": req.track_index})
            if info.get("type") != "midi":
                raise _Abort(f"Дорожка {req.track_index} не MIDI-дорожка — инструмент на неё не загрузить.")
            res.track_index = info.get("index", req.track_index)
            res.track_name = info.get("name")
            if req.track_name:
                self.bridge.call("set_track_name", {"track_index": res.track_index, "name": req.track_name})
                res.track_name = req.track_name
            return res.track_index
        params: dict = {"name": name}
        color = ((recipe or {}).get("track") or {}).get("color_index")
        if color is None:
            color = _CATEGORY_COLORS.get((recipe or {}).get("category") or self._infer_category(req, preset_item))
        if color is not None:
            params["color_index"] = color
        created = self.bridge.call("create_midi_track", params)
        run.track_created = True
        res.track_index = created["track_index"]
        res.track_name = name
        run.steps.append(f"создана дорожка «{name}»")
        return res.track_index

    def _track_name(self, req: SoundRequest, recipe: dict | None, preset_item: dict | None) -> str:
        if req.track_name:
            return req.track_name
        if recipe:
            tn = (recipe.get("track") or {}).get("name")
            if tn:
                return tn
            return recipe_display_name(recipe)
        if preset_item and preset_item.get("name"):
            return clean_name(preset_item["name"])
        return (req.description or "Звук").strip()[:40]

    def _infer_category(self, req: SoundRequest, preset_item: dict | None) -> str:
        text = " ".join([req.description or "", (preset_item or {}).get("path", "")])
        for tok in tokenize(text):
            for key, cat in _INFER_CATEGORY.items():
                if tok.startswith(key):
                    return cat
        return "synth"

    # ------------------------------------------------------------------ preset loading
    def _load_preset(self, run: _Run, ti: int, item: dict, recipe: dict | None, fallback_allowed: bool) -> bool:
        res = run.result
        try:
            loaded = self.bridge.call("load_browser_item", {"track_index": ti, "uri": item["uri"]})
        except BridgeCommandError as exc:
            if fallback_allowed:
                res.warnings.append(f"Пресет «{clean_name(item.get('name', item['uri']))}» не загрузился "
                                    f"({exc.message}) — строю звук по рецепту.")
                return False
            raise
        name = loaded.get("name") or item.get("name") or item["uri"]
        res.preset = {k: v for k, v in {**item, "name": name}.items() if not str(k).startswith("_")}
        res.source = "preset"
        res.devices = [self._dev_view(d) for d in loaded.get("devices", [])]
        run.steps.append(f"загружен пресет «{clean_name(name)}»")
        return True

    @staticmethod
    def _dev_view(d: dict) -> dict:
        return {"index": d.get("index"), "name": d.get("name"), "class_name": d.get("class_name")}

    # ------------------------------------------------------------------ synthesis from a recipe
    def _build_from_recipe(self, run: _Run, ti: int, recipe: dict) -> None:
        res = run.result
        inst = recipe["instrument"]
        reused = run.request.track_index is not None

        used_device, dev_index = self._load_instrument(run, ti, recipe)
        if used_device == "Drum Rack":
            res.warnings.append("Drum Rack из рецепта пустой (без сэмплов): для ударных нужен пресет-кит из браузера "
                                "Live — перетащите сэмплы на пэды или загрузите кит вручную.")
        elif used_device in SAMPLER_DEVICES and not res.preset:
            res.warnings.append(f"{used_device} загружен без сэмпла — перетащите аудио-файл на устройство.")

        if used_device == inst["device"]:
            params = inst.get("parameters") or {}
        else:
            params = (inst.get("fallback_parameters") or {}).get(used_device) or {}
            res.warnings.append(
                f"Основной инструмент {inst['device']} недоступен — загружен {used_device}"
                + ("." if params else ", параметры рецепта к нему не применены."))
        if params:
            applied, unmatched = self._apply(ti, dev_index, params)
            res.unmatched_parameters.extend(unmatched)
            run.steps.append(f"{used_device}: параметров применено {applied}")

        existing: dict[str, int] = {}
        if reused:
            existing = {d["name"]: d["index"] for d in self._track_devices(ti)}
        for fx in recipe.get("effects") or []:
            self._add_effect(run, ti, fx, existing)

    def _load_instrument(self, run: _Run, ti: int, recipe: dict) -> tuple[str, int]:
        inst = recipe["instrument"]
        res = run.result
        candidates = [inst["device"]] + [d for d in inst.get("fallback_devices") or [] if d != inst["device"]]
        last_err: BridgeCommandError | None = None
        for dev in candidates:
            if dev in SAMPLER_DEVICES:
                loaded = self._try_sample(run, ti, recipe, dev)
                if loaded is not None:
                    return dev, loaded
            for name in self.aliases.device_variants(dev):
                try:
                    out = self.bridge.call("load_device", {"track_index": ti, "device_name": name, "position": 0})
                except BridgeCommandError as exc:
                    last_err = exc
                    continue
                run.steps.append(f"инструмент {out.get('name', name)}")
                return dev, out["device_index"]
            res.warnings.append(f"Не удалось загрузить {dev}: {last_err.message if last_err else 'неизвестная ошибка'}.")
        raise _Abort(f"Не удалось загрузить инструмент ({', '.join(candidates)}): "
                     f"{last_err.message if last_err else 'устройство недоступно'}."
                     + (f" Дорожка «{res.track_name}» осталась в сете пустой." if run.track_created else ""))

    def _try_sample(self, run: _Run, ti: int, recipe: dict, device: str) -> int | None:
        """For Simpler/Sampler: try to load a matching sample from the browser first."""
        terms = list(recipe.get("preset_search") or [])
        if not terms:
            return None
        found = self.searcher.search(terms, recipe_category=recipe.get("category"), instrument=device, limit=3)
        if not found or found[0]["score"] < self.preset_threshold:
            return None
        try:
            loaded = self.bridge.call("load_browser_item", {"track_index": ti, "uri": found[0]["uri"]})
        except BridgeCommandError:
            return None
        run.result.preset = {k: v for k, v in found[0].items() if not k.startswith("_")}
        run.steps.append(f"сэмпл «{clean_name(found[0]['name'])}» в {device}")
        for d in loaded.get("devices", []):
            if d.get("type") == "instrument" or d.get("name") in SAMPLER_DEVICES:
                return d["index"]
        return 0

    def _add_effect(self, run: _Run, ti: int, fx: dict, existing: dict[str, int]) -> None:
        res = run.result
        wanted = fx["device"]
        dev_index: int | None = None
        for name in self.aliases.device_variants(wanted):
            if name in existing:
                dev_index = existing[name]
                break
        last_err: BridgeCommandError | None = None
        if dev_index is None:
            for name in self.aliases.device_variants(wanted):
                try:
                    out = self.bridge.call("load_device", {"track_index": ti, "device_name": name})
                except BridgeCommandError as exc:
                    last_err = exc
                    continue
                dev_index = out["device_index"]
                break
        if dev_index is None:
            res.warnings.append(f"Эффект {wanted} не загрузился: {last_err.message if last_err else 'недоступен'}.")
            return
        params = fx.get("parameters") or {}
        if params:
            try:
                applied, unmatched = self._apply(ti, dev_index, params)
            except BridgeCommandError as exc:
                res.warnings.append(f"Параметры эффекта {wanted} не применены: {exc.message}.")
                return
            res.unmatched_parameters.extend(unmatched)
            run.steps.append(f"{wanted}: параметров применено {applied}")

    # ------------------------------------------------------------------ parameters
    def _apply(self, track_index: int, device_index: int, params: dict) -> tuple[int, list[dict]]:
        data = self.bridge.call("get_device_parameters", {"track_index": track_index, "device_index": device_index})
        live = data.get("parameters", [])
        dev_name = (data.get("device") or {}).get("name", "")
        name_counts: dict[str, int] = {}
        for p in live:
            name_counts[p["name"]] = name_counts.get(p["name"], 0) + 1

        unmatched: list[dict] = []
        send: dict[str, object] = {}
        key_for: dict[str, str] = {}
        for key, value in params.items():
            p = resolve_parameter(key, live, self.aliases)
            if p is None:
                entry = {"device": dev_name, "parameter": key, "value": value, "reason": "параметр не найден на устройстве"}
                sug = suggest_parameters(key, live)
                if sug:
                    entry["suggestions"] = sug
                unmatched.append(entry)
                continue
            ok, to_send, reason = resolve_value(value, p, self.aliases)
            if not ok:
                unmatched.append({"device": dev_name, "parameter": key, "value": value, "reason": reason})
                continue
            wire_key = p["name"] if name_counts[p["name"]] == 1 else str(p["index"])
            if wire_key in send:
                unmatched.append({"device": dev_name, "parameter": key, "value": value,
                                  "reason": f"дубль: параметр «{p['name']}» уже задан другим ключом рецепта"})
                continue
            send[wire_key] = to_send
            key_for[wire_key] = key
        applied = 0
        if send:
            out = self.bridge.call("set_device_parameters",
                                   {"track_index": track_index, "device_index": device_index, "values": send})
            failed = out.get("failed", []) or []
            applied = len(send) - len(failed)
            for f in failed:
                k = str(f.get("parameter"))
                unmatched.append({"device": dev_name, "parameter": key_for.get(k, k), "value": params.get(key_for.get(k, k)),
                                  "reason": f"отклонено Live: {f.get('code', '')} {f.get('message', '')}".strip()})
        return applied, unmatched

    # ------------------------------------------------------------------ demo clip
    def _add_demo(self, run: _Run, ti: int, recipe: dict | None, preset: dict | None) -> None:
        res = run.result
        if recipe is not None:
            clip = build_demo(recipe)
            label = recipe_display_name(recipe)
        else:
            category = self._infer_category(run.request, preset)
            clip = build_demo({"category": category, "demo": {"style": default_style(category)}})
            label = res.track_name or run.request.description
        label = (res.track_name or label)
        try:
            made = self.bridge.call("create_clip", {"track_index": ti, "length": clip.length, "name": f"Демо — {label}"})
            slot = made["slot_index"]
            res.demo_clip_slot = slot
            self.bridge.call("add_notes", {"track_index": ti, "slot_index": slot, "notes": clip.notes})
            run.steps.append(f"демо-клип в слоте {slot + 1}")
        except BridgeCommandError as exc:
            res.warnings.append(f"Демо-клип не создан: {exc.message}.")

    # ------------------------------------------------------------------ final reporting
    def _track_devices(self, ti: int) -> list[dict]:
        info = self.bridge.call("get_track_info", {"track_index": ti})
        return [self._dev_view(d) for d in info.get("devices", [])]

    def _refresh_devices(self, run: _Run, ti: int) -> None:
        try:
            run.result.devices = self._track_devices(ti)
        except BridgeCommandError:
            pass

    def _summary(self, run: _Run, recipe: dict | None) -> str:
        res, req = run.result, run.request
        names = [d["name"] for d in res.devices if d.get("name")]
        chain = " + ".join(names)
        reused = req.track_index is not None
        head = "Обновлена дорожка" if reused else "Создана дорожка"
        if res.source == "preset" and res.preset:
            what = f"пресет «{clean_name(res.preset.get('name', ''))}»" + (f", {chain}" if chain else "")
        else:
            what = chain or "инструмент"
        parts = [f"{head} «{res.track_name}» ({what})"]
        text = parts[0]
        if res.demo_clip_slot is not None:
            text += f", демо-клип в слоте {res.demo_clip_slot + 1}"
        text += "."
        if res.unmatched_parameters:
            text += f" Не удалось применить параметров: {len(res.unmatched_parameters)}."
        if res.warnings:
            text += f" Замечаний: {len(res.warnings)}."
        return text

    def _fail(self, run: _Run, message: str) -> None:
        res = run.result
        res.ok = False
        if run.track_created and res.track_index is not None:
            done = "; ".join(run.steps) or "ничего не выполнено"
            message += f" Дорожка {res.track_index} («{res.track_name}») оставлена в сете. Выполнено: {done}."
            self._refresh_devices_safe(run)
        res.message = message

    def _refresh_devices_safe(self, run: _Run) -> None:
        try:
            if run.result.track_index is not None:
                run.result.devices = self._track_devices(run.result.track_index)
        except BridgeError:
            pass

# Интерфейсы между модулями

Этот файл — контракт. Если реализация требует изменить контракт, это делает оркестратор.

## 1. Bridge (`abhelper.bridge.base`)

```python
class Bridge(Protocol):
    def call(self, command: str, params: dict | None = None, timeout: float | None = None) -> dict
        # возвращает result; при ok=false бросает BridgeCommandError(code, message)
    def is_connected(self) -> bool
    def close(self) -> None

class BridgeError(Exception): ...                    # базовое
class BridgeConnectionError(BridgeError): ...        # нет соединения с Live
class BridgeCommandError(BridgeError):               # ok=false
    code: str; message: str
```

Реализации:
- `abhelper.bridge.client.TcpBridge(host="127.0.0.1", port=9888, timeout=15.0)` — реальная
  (агент Agent Core). Ленивое подключение, авто-переподключение один раз при обрыве,
  потокобезопасна (lock на запрос), id = инкрементный счётчик.
- `abhelper.bridge.fake.FakeBridge(device_catalog=None, browser_items=None)` — эмулятор Live
  в памяти для тестов (оркестратор). Реализует все команды `docs/PROTOCOL.md`.
  Состояние доступно напрямую: `fake.tracks`, `fake.calls` (лог вызовов).

## 2. SoundEngine (`abhelper.sound`)

Публичный API (импорт `from abhelper.sound import ...`):

```python
@dataclass
class RecipeMatch:
    recipe_id: str
    name: str              # локализованное имя (ru, если есть)
    score: float           # 0..1
    category: str

@dataclass
class SoundRequest:
    description: str                      # исходный текст пользователя («звук баяна»)
    recipe_id: str | None = None          # явный рецепт из библиотеки
    recipe: dict | None = None            # кастомный рецепт от LLM (схема ниже)
    preset_uri: str | None = None         # явный пресет из браузера
    strategy: str = "auto"                # "auto" | "preset" | "recipe"
    track_name: str | None = None
    add_demo_clip: bool = True
    track_index: int | None = None        # None = новая дорожка; иначе — заменить инструмент на существующей MIDI-дорожке

@dataclass
class SoundResult:
    ok: bool
    track_index: int | None
    track_name: str | None
    source: str                           # "preset" | "recipe" | "custom_recipe"
    recipe_id: str | None
    preset: dict | None                   # BrowserItem, если грузили пресет
    devices: list[dict]                   # [{index, name, class_name}]
    unmatched_parameters: list[dict]      # [{device, parameter, value, reason}]
    demo_clip_slot: int | None
    warnings: list[str]
    message: str                          # краткое человекочитаемое резюме (ru)
    def to_dict(self) -> dict

class RecipeLibrary:
    @classmethod
    def load_default(cls) -> "RecipeLibrary"     # все JSON из abhelper/sound/recipes/
    def get(self, recipe_id: str) -> dict | None
    def all(self) -> list[dict]
    def search(self, query: str, limit: int = 5) -> list[RecipeMatch]   # RU/EN алиасы, теги, fuzzy

def validate_recipe(recipe: dict) -> list[str]   # список ошибок, [] = валиден

class SoundEngine:
    def __init__(self, bridge: Bridge, library: RecipeLibrary | None = None)
    def find_recipes(self, query: str, limit: int = 5) -> list[RecipeMatch]
    def search_presets(self, query: str, terms: list[str] | None = None, limit: int = 10) -> list[dict]
        # BrowserItem + "score"; ранжирование, предпочтение sounds/instruments/drums
    def create_sound(self, request: SoundRequest) -> SoundResult
        # не бросает исключения моста — ошибки → ok=False, message, warnings
    def apply_parameters(self, track_index: int, device_index: int, params: dict) -> list[dict]
        # возвращает unmatched (нечёткое сопоставление имён, см. ниже)
```

### Нечёткое сопоставление параметров
Движок сначала читает `get_device_parameters`, затем для каждого ключа рецепта ищет
параметр: точное имя → без регистра → нормализованное → алиасы из
`abhelper/sound/data/param_aliases.json` (например `"Filter Freq" ↔ "Filter Frequency" ↔ "Frequency"`).
Найденные отправляет одним `set_device_parameters`, остальные — в `unmatched_parameters`.

## 3. Схема рецепта (`abhelper/sound/recipes/*.json`)

```json
{
  "id": "bayan",
  "version": 1,
  "name": {"ru": "Баян", "en": "Bayan (button accordion)"},
  "category": "keys",
  "aliases": ["баян", "аккордеон", "гармонь", "гармошка", "accordion", "bayan", "musette"],
  "tags": ["folk", "reed", "acoustic", "russian"],
  "description": {"ru": "...", "en": "..."},
  "preset_search": ["accordion", "musette", "harmonium", "reed organ"],
  "track": {"name": "Баян", "color_index": 12},
  "instrument": {
    "device": "Operator",
    "fallback_devices": ["Wavetable", "Analog"],
    "parameters": {"Algorithm": 10, "Osc-A Wave": "Saw D", "Filter Freq": {"norm": 0.55}}
  },
  "effects": [
    {"device": "Chorus-Ensemble", "parameters": {"Dry/Wet": {"norm": 0.3}}},
    {"device": "Reverb", "parameters": {"Dry/Wet": {"norm": 0.18}}}
  ],
  "demo": {"style": "chords", "root": 57, "length": 8.0, "notes": null},
  "sound_design_notes": "Два слегка расстроенных пилообразных голоса (мюзет) ..."
}
```

Поля:
- обязательные: `id` (`[a-z0-9_]+`), `name.en`, `category`, `aliases` (≥1), `instrument.device`.
- `category` ∈ `keys, piano, organ, strings, brass, woodwind, reed, plucked, guitar, bass, lead, pad, bell, mallet, choir, fx, drums, percussion, ethnic, synth`.
- значения параметров: число (сырое), строка (элемент `value_items`), `{"norm": 0..1}`.
- `instrument.fallback_devices`: если основное устройство не загрузилось — следующее
  (параметры тогда не применяются, только `fallback_parameters` если указаны:
  `"fallback_parameters": {"Wavetable": {...}}`).
- `demo.style` ∈ `chords, melody, bass, arp, drums, pad, single`; `demo.notes` — явные ноты
  (формат `add_notes`), если заданы — имеют приоритет над `style`.
- Для `drums` инструментом может быть `"Drum Rack"` с `preset_search` (пресет-кит) — синтез ударных
  через рецепт допустим упрощённый.

Кастомный рецепт от LLM — та же схема; `id` может отсутствовать (движок присвоит `custom_<n>`),
`aliases` необязательны.

## 4. Агент (`abhelper.agent`)

```python
class AssistantAgent:
    def __init__(self, bridge: Bridge, engine: SoundEngine, knowledge: KnowledgeBase,
                 llm: LLMClient, settings: Settings)
    def run_turn(self, conversation: Conversation, user_text: str) -> Iterator[AgentEvent]
```

`AgentEvent` (dict, сериализуется в SSE как `data: <json>\n\n`):
| type | поля |
|---|---|
| `text_delta` | `text` |
| `tool_start` | `id`, `name`, `input` |
| `tool_result` | `id`, `name`, `ok`, `summary` (короткая строка ru), `data` (dict, может быть урезан) |
| `done` | `text` (итоговый ответ целиком), `usage` |
| `error` | `message`, `code` (`llm_not_configured`, `bridge_offline`, `llm_error`, `internal`) |

Инструменты LLM (имена фиксированы — UI показывает их человеческие подписи):
`get_session_overview`, `get_track_details`, `search_sound_library`, `search_live_browser`,
`create_sound`, `design_custom_sound`, `get_device_parameters`, `set_device_parameters`,
`load_device`, `create_midi_clip`, `transport`, `undo_last_action`, `search_ableton_help`,
`rename_track`, `delete_track`.

## 5. HTTP API (`abhelper.server`)

| Метод | Путь | Тело / ответ |
|---|---|---|
| GET | `/` | `ui/index.html` (статика из `ui/`, смонтирована на `/ui/` + корень) |
| GET | `/api/status` | `{"bridge": {"connected": bool, "live_version": str\|null, "script_version": str\|null}, "llm": {"configured": bool, "model": str}, "version": str}` |
| POST | `/api/chat` | `{"conversation_id"?: str, "message": str}` → `text/event-stream` с `AgentEvent`; первое событие `{"type":"conversation","conversation_id": "..."}` |
| POST | `/api/reset` | `{"conversation_id": str}` → `{"ok": true}` |
| GET | `/api/config` | `{"model", "effort", "api_key_set": bool, "bridge_host", "bridge_port"}` |
| POST | `/api/config` | `{"api_key"?, "model"?, "effort"?}` → как GET; сохраняет в `~/.ableton-helper/config.json` |
| GET | `/api/suggestions` | `{"items": [str]}` — примеры запросов для пустого чата |

## 6. База знаний (`abhelper/knowledge/docs/*.md`)

Формат файла:
```markdown
# Заголовок темы
keywords: warp, варп, растяжение, темп сэмпла, warping

## Подраздел
Текст...
```
Поиск (`abhelper.knowledge.search.KnowledgeBase.search(query, limit=4) -> list[dict]`,
элемент: `{"file", "title", "section", "text", "score"}`) режет файлы по `## `, ищет по
словам запроса, `keywords` и заголовкам (RU/EN, совпадение по префиксу ≥ 4 символов).

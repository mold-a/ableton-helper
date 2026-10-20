# Протокол моста (Remote Script ⇄ backend)

Транспорт: TCP, `127.0.0.1:9888`. Кодировка UTF-8. **Одно сообщение = одна строка JSON,
завершённая `\n`.** Соединение долгоживущее; запросы на одном соединении обрабатываются
по порядку. Сервер принимает несколько соединений одновременно.

## Конверт

Запрос:
```json
{"id": "42", "command": "create_midi_track", "params": {"name": "Баян"}}
```
Успех:
```json
{"id": "42", "ok": true, "result": {"track_index": 3}}
```
Ошибка:
```json
{"id": "42", "ok": false, "error": {"code": "not_found", "message": "Track 7 does not exist"}}
```

`id` — строка, эхом возвращается в ответе. `params` можно опустить (= `{}`).

### Коды ошибок
| code | Когда |
|---|---|
| `bad_request` | невалидный JSON, нет `command`, неверный тип/отсутствует обязательный параметр |
| `unknown_command` | команды нет в реестре |
| `not_found` | дорожка/устройство/слот/параметр/элемент браузера не найден |
| `unsupported` | функция недоступна в этой версии Live (feature-detect через `hasattr`) |
| `conflict` | например, слот уже занят клипом при `create_clip` без `overwrite` |
| `timeout` | главный поток Live не обработал запрос за 10 с |
| `internal` | любое другое исключение (сообщение = `str(exc)`) |

## Адресация
- `track_index` — int, 0-based индекс в `song.tracks` (только обычные дорожки, без return/master).
  `-1` = последняя дорожка.
- `device_index` — int, 0-based индекс в `track.devices` (верхний уровень).
- `slot_index` — int, 0-based индекс в `track.clip_slots`.
- `parameter` — либо int (индекс в `device.parameters`), либо str (имя). Сопоставление имени:
  сначала точное, затем без учёта регистра, затем «нормализованное» (lowercase, без пробелов,
  `-`, `_`, `.`). При неоднозначности — первое совпадение.

## Объекты в ответах

`TrackSummary`:
```json
{"index": 0, "name": "1-MIDI", "type": "midi", "color_index": 12,
 "is_selected": true, "mute": false, "solo": false, "arm": false,
 "devices": [{"index": 0, "name": "Operator", "class_name": "Operator", "type": "instrument"}]}
```
`type` дорожки: `"midi" | "audio" | "group"`. `type` устройства: `"instrument" | "audio_effect" | "midi_effect" | "unknown"`.

`Parameter`:
```json
{"index": 1, "name": "Filter Freq", "value": 0.62, "min": 0.0, "max": 1.0,
 "default": 1.0, "display": "2.53 kHz", "is_quantized": false, "value_items": []}
```
Для квантованных параметров `value_items` — список строк (например `["Sine", "Saw D", ...]`),
`value` — индекс.

`BrowserItem`:
```json
{"name": "Grand Piano.adv", "uri": "query:Synths#...", "path": "sounds/Piano & Keys/Grand Piano.adv",
 "category": "sounds", "is_loadable": true, "is_device": false, "is_folder": false}
```
`category` ∈ `instruments, sounds, drums, audio_effects, midi_effects, max_for_live, plugins, clips, samples, packs, user_library, current_project, user_folders`.
`path` — человекочитаемый путь: `<category>/<имя папки>/.../<имя>`.

## Команды

### Сервис
| command | params | result |
|---|---|---|
| `ping` | — | `{"pong": true, "script_version": "0.1.0", "live_version": "12.1.5"}` |
| `get_capabilities` | — | `{"insert_device": bool, "create_audio_clip": bool, "add_new_notes": bool, "browser": bool}` |
| `batch` | `{"commands": [{"command": str, "params": {}}...], "stop_on_error": true}` | `{"results": [<конверт без id>...]}` — выполняется в одном тике главного потока |

### Сет
| command | params | result |
|---|---|---|
| `get_session_info` | — | `{"tempo": 120.0, "signature": [4,4], "is_playing": false, "track_count": 5, "return_track_count": 2, "selected_track_index": 0, "tracks": [TrackSummary...]}` |
| `set_tempo` | `{"tempo": float}` (20..999) | `{"tempo": float}` |
| `start_playback` / `stop_playback` | — | `{"is_playing": bool}` |
| `undo` / `redo` | — | `{"done": bool}` (false, если `can_undo`/`can_redo` == false) |

### Дорожки
| command | params | result |
|---|---|---|
| `get_track_info` | `{"track_index"}` | `TrackSummary` + `"clip_slots": [{"index", "has_clip", "clip_name", "clip_length", "is_playing"}]` |
| `create_midi_track` | `{"index"?: int = -1, "name"?: str, "color_index"?: int}` | `{"track_index": int}` — индекс созданной дорожки; дорожка становится выбранной |
| `create_audio_track` | то же | то же |
| `delete_track` | `{"track_index"}` | `{"deleted": true}` |
| `set_track_name` | `{"track_index", "name"}` | `{"name"}` |
| `set_track_color` | `{"track_index", "color_index": 0..69}` | `{"color_index"}` |
| `select_track` | `{"track_index"}` | `{"selected": true}` |
| `set_track_mixer` | `{"track_index", "volume"?: 0..1, "pan"?: -1..1, "mute"?: bool, "solo"?: bool, "arm"?: bool}` | текущие значения тех же полей |

`volume` — сырое значение `mixer_device.volume` (0.85 ≈ 0 dB).

### Устройства
| command | params | result |
|---|---|---|
| `load_device` | `{"track_index", "device_name": str, "position"?: int = -1}` | `{"device_index": int, "name": str, "class_name": str}` |
| `delete_device` | `{"track_index", "device_index"}` | `{"deleted": true}` |
| `get_device_parameters` | `{"track_index", "device_index"}` | `{"device": {"name", "class_name", "type"}, "parameters": [Parameter...]}` |
| `set_device_parameter` | `{"track_index", "device_index", "parameter": int\|str, "value": number\|str}` | `Parameter` (после изменения) |
| `set_device_parameters` | `{"track_index", "device_index", "values": {"<name or index>": number\|str, ...}}` | `{"applied": [Parameter...], "failed": [{"parameter", "code", "message"}]}` — не падает целиком из-за одного параметра |
| `set_device_enabled` | `{"track_index", "device_index", "enabled": bool}` | `{"enabled"}` |

`load_device` грузит **нативное** устройство по имени, как оно называется в браузере
(`"Operator"`, `"Wavetable"`, `"Reverb"`, `"EQ Eight"`, `"Chorus-Ensemble"`…). Реализация:
`track.insert_device(name, index)` если доступно (Live 12.3+, только нативные устройства), иначе поиск элемента с
`is_device` и совпадающим именем в `browser.instruments / audio_effects / midi_effects`
(рекурсивно, глубина ≤ 3) и `browser.load_item` на выбранную дорожку (новое устройство
встаёт в конец цепочки; `position` в этом случае игнорируется).
Результат `device_index` — индекс реально появившегося устройства (сравнение списков до/после).

Значение `value` в `set_device_parameter(s)`:
- `number` → сырое значение, зажимается в `[min, max]`; для квантованных округляется.
- `str` → только для квантованных: элемент `value_items` (сравнение без учёта регистра);
  иначе `bad_request`.
- `{"norm": 0..1}` → `min + norm*(max-min)`.

### Браузер
| command | params | result |
|---|---|---|
| `browser_status` | — | `{"indexed": int, "complete": bool, "scanning": bool, "truncated": bool}` |
| `browser_rescan` | `{"categories"?: [str]}` | `{"started": true}` |
| `browser_search` | `{"query": str, "categories"?: [str], "loadable_only"?: bool = true, "limit"?: int = 25}` | `{"items": [BrowserItem...], "index_complete": bool}` |
| `browser_list` | `{"path"?: str}` (пусто = список категорий) | `{"items": [BrowserItem...]}` — дети узла (без рекурсии) |
| `load_browser_item` | `{"track_index", "uri"?: str, "path"?: str}` | `{"loaded": true, "name": str, "devices": [ {index,name,class_name,type}... ]}` — устройства дорожки после загрузки |

Поиск `browser_search`: запрос разбивается на слова; элемент подходит, если **все** слова
встречаются (подстрокой, без учёта регистра) в `path`. Сортировка: сначала больше совпадений
в `name`, затем короче `path`. Индекс строится инкрементально после старта скрипта; при
`complete=false` возвращаются частичные результаты.

Лимиты индекса: глубина ≤ 8, до 60 000 элементов (иначе `truncated=true`). Порядок обхода
категорий: `instruments, sounds, drums, audio_effects, midi_effects, user_library, packs,
samples, clips, plugins, max_for_live, user_folders`.

### Клипы
| command | params | result |
|---|---|---|
| `create_clip` | `{"track_index", "slot_index"?: int (по умолч. первый пустой), "length": float (в долях, beats) = 4.0, "name"?: str, "overwrite"?: bool = false}` | `{"slot_index", "length"}` |
| `add_notes` | `{"track_index", "slot_index", "notes": [{"pitch": 0..127, "start": float, "duration": float, "velocity"?: 1..127 = 100, "mute"?: bool}], "replace"?: bool = false}` | `{"added": int}` |
| `get_clip_notes` | `{"track_index", "slot_index"}` | `{"notes": [...], "length": float}` |
| `set_clip_name` | `{"track_index", "slot_index", "name"}` | `{"name"}` |
| `fire_clip` / `stop_clip` | `{"track_index", "slot_index"}` | `{"ok": true}` |
| `delete_clip` | `{"track_index", "slot_index"}` | `{"deleted": true}` |
| `create_audio_clip` | `{"track_index", "slot_index", "file_path": str}` | `{"slot_index"}` или `unsupported` (Live < 12) |

`add_notes`: `clip.add_new_notes` (Live 11+) с `Live.Clip.MidiNoteSpecification`, иначе
`clip.set_notes`. `replace=true` — сначала удалить все ноты клипа.

## Версионирование
`script_version` по semver. Новые команды — минорная версия. Клиент проверяет `ping` при
подключении и показывает предупреждение при несовпадении мажорной версии.

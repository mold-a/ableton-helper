# AbletonHelper — MIDI Remote Script

Мост между Ableton Live и backend-ассистентом. Скрипт работает **внутри Live** (встроенный Python 3.7 в Live 11 / 3.11 в Live 12), поднимает TCP-сервер на `127.0.0.1:9888` и выполняет команды из [`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

## Как это устроено

```
backend ──TCP, JSON-строки──▶ потоки сокетов ──queue──▶ update_display() (главный поток Live) ──▶ Live API
```

- `AbletonHelper/__init__.py` — `create_instance(c_instance)`; класс `AbletonHelper` (Control Surface) в `surface.py` — тонкая обвязка.
- `server.py` — сокеты и фрейминг (по строке на сообщение, до 1 МБ). **Потоки сокетов не трогают Live API**: кладут запрос в очередь и ждут ответ до 10 с (иначе код `timeout`).
- `update_display()` (~каждые 100 мс, главный поток) разбирает очередь с бюджетом ~30 мс на тик; `batch` выполняется целиком за один тик. Остаток времени (~20 мс) идёт на индексацию браузера.
- `dispatcher.py` — реестр команд, проверка параметров, перевод исключений в коды ошибок протокола. `handlers/` — логика команд (`session`, `tracks`, `devices`, `browser`, `clips`, `service`), принимает объекты `song` / `application`, поэтому тестируется без Live.
- `browser_index.py` — индекс браузера строится генератором: старт через ~2 с после запуска, по кусочку за тик. Лимиты: глубина ≤ 8, ≤ 60 000 элементов (иначе `truncated=true`).
- Слушает только `127.0.0.1`. Порт можно сменить переменной окружения `ABHELPER_BRIDGE_PORT` (читается при старте Live). Команд типа eval/exec нет.

## Установка

```bash
python scripts/install_remote_script.py            # копирует в User Library
python scripts/install_remote_script.py --dry-run  # только показать план
python scripts/install_remote_script.py --uninstall
```

Куда копируется по умолчанию:

- macOS: `~/Music/Ableton/User Library/Remote Scripts/AbletonHelper`
- Windows: `%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\AbletonHelper`

Затем: перезапустить Live → **Settings → Link, Tempo & MIDI → Control Surface → AbletonHelper**, Input/Output = None. В строке состояния Live появится «AbletonHelper: listening on 9888».

## Если скрипта нет в списке Control Surface

1. Убедитесь, что файл `__init__.py` лежит **прямо** в `.../Remote Scripts/AbletonHelper/__init__.py`, а не на уровень глубже (`.../AbletonHelper/AbletonHelper/__init__.py`). Установщик это проверяет и печатает точный путь.
2. User Library может быть перенесена (Settings → Library → Location). Тогда положите скрипт в `Remote Scripts` внутри вашей User Library.
3. Запасной путь — папка внутри приложения Live (`--dest` указывает на папку `MIDI Remote Scripts`, внутри создастся `AbletonHelper`):
   - macOS: `/Applications/Ableton Live 12 <Edition>.app/Contents/App-Resources/MIDI Remote Scripts/`
   - Windows: `C:\ProgramData\Ableton\Live 12 <Edition>\Resources\MIDI Remote Scripts\`
   
   Например: `python scripts/install_remote_script.py --dest "/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/MIDI Remote Scripts"` (может понадобиться sudo / права администратора; после обновления Live папку придётся скопировать заново).
4. Полностью перезапустите Live (не только закройте проект).

## Диагностика и логи

- Лог Live: macOS `~/Library/Preferences/Ableton/Live <версия>/Log.txt`, Windows `%APPDATA%\Ableton\Live <версия>\Preferences\Log.txt`. Сообщения скрипта начинаются с `AbletonHelper`. Исключения пишутся с traceback и не выходят в Live.
- «port is busy» — порт 9888 занят (другой Live или процесс): задайте `ABHELPER_BRIDGE_PORT` и тот же порт в backend (`ABHELPER_BRIDGE_PORT`).
- Проверка вручную: `printf '{"id":"1","command":"ping"}\n' | nc 127.0.0.1 9888`.
- Если ответы приходят с `timeout`, главный поток Live занят (модальный диалог, тяжёлая операция).

## Тесты

```bash
python -m pytest -q remote_script/tests
```

Тесты используют фейки Live API (`tests/rs_fakes.py`), поднимают настоящий сервер на эфемерном порту и проверяют, что код совместим с синтаксисом Python 3.7 (AST-проверка).

## Требует проверки в живом Ableton

Скрипт писался без доступа к Live; всё ниже реализовано защитно (`getattr`/`hasattr`, `try/except` с запасным путём), но **не проверено**:

1. **`Track.insert_device(name, index)`** — по документации есть с Live 12.3, только нативные устройства. Скрипт определяет её через `hasattr` и при любой ошибке падает на путь через браузер. Неизвестно, вызывается ли без `index` (сейчас сперва `insert_device(name)`, при `TypeError` — `insert_device(name, len(devices))`) и что возвращает (если объект устройства — используем его для индекса).
2. **`browser.load_item(item)`** — считается синхронным. Если в какой-то версии он асинхронный, список устройств сразу после вызова не изменится: `load_browser_item` вернёт текущие `devices` и `"pending": true`; `load_device` в такой ситуации вернёт `internal` («Live did not add the device»). Нужно проверить, бывает ли так в реальности.
3. **Поиск нативного устройства в браузере**: предполагается, что у элемента `instruments/Operator` и т. п. `is_device == True` и `is_loadable == True`, а имя совпадает с именем устройства. Если `is_device` у нативных устройств False, `load_device` без `insert_device` вернёт `not_found`.
4. **Загрузка инструмента на аудио-дорожку / MIDI-эффекта** — проверяется заранее по `has_midi_input`; поведение самого Live (ошибка или молчаливый отказ) не проверено.
5. **`Device.type`** (1 instrument, 2 audio_effect, 4 midi_effect) — берётся по int; если значение 0/неизвестно, тип угадывается по `class_name` (эвристика может ошибаться на нестандартных устройствах).
6. **Нотные API**: `clip.add_new_notes` + `Live.Clip.MidiNoteSpecification(pitch, start_time, duration, velocity, mute)`, `get_notes_extended(0, 128, 0, length)`, `remove_notes_extended(from_pitch=, pitch_span=, from_time=, time_span=)` (Live 11+). Для старого пути предполагается, что `clip.set_notes()` **добавляет** ноты (не заменяет), а `get_notes(from_time, from_pitch, time_span, pitch_span)` возвращает кортежи `(pitch, time, duration, velocity, mute)`.
7. **`ClipSlot.create_audio_clip(path)`** — нужен абсолютный путь; первая версия Live с этим методом не подтверждена (~12.0.5). Без метода → `unsupported`; исключение Live (не аудио-дорожка, frozen, неподдерживаемый файл) → `bad_request`.
8. **`track.arm` на группах** падает (известный баг сторонних скриптов): везде за `can_be_armed` + `try/except`, у групп `arm=false`.
9. **Новая сцена**: если в дорожке нет пустых слотов, `create_clip` без `slot_index` вызывает `song.create_scene(len(scenes))`.
10. **Сравнение объектов Live** (`==`) используется для определения выбранной дорожки и индекса нового устройства; предполагается, что прокси-объекты одного и того же элемента равны.
11. **Категории браузера** (`user_folders` — список; `current_project` не индексируется, только в `browser_list`); ленивое чтение `item.children` у каждого элемента, скорость обхода 60 000 элементов в реальном Live неизвестна — бюджет тика (20 мс) защищает от зависаний, но полный индекс может строиться несколько минут.
12. **Частота `update_display`** (~100 мс) и то, что он вызывается всегда, пока выбран Control Surface.
13. `start_playback` / `stop_playback` возвращают намерение (`true` / `false`), а не перечитанное `song.is_playing`.

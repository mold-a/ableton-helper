# Ableton Helper

AI-ассистент, встроенный в Ableton Live, для русскоязычных продюсеров.

1. **Создаёт звуки по описанию.** Пишете «я хочу звук баяна», и в вашем сете появляется MIDI-дорожка с настроенным инструментом, эффектами и демо-клипом.
2. **Помогает ориентироваться в Ableton.** Отвечает на вопросы вроде «как включить Warp?» по встроенной базе знаний и с учётом вашего сета.

> Статус: ранняя версия (0.1). Проект работает на связке Remote Script + локальный сервер + чат; часть путей (окно чата внутри Live через Max for Live) экспериментальная. Подробности в разделе «Ограничения».

## Как это выглядит

```
Вы:        я хочу звук баяна
Ассистент: [Ищу в библиотеке звуков] [Ищу пресеты в браузере Live] [Создаю звук] ...
           Готово. Создал дорожку «Баян»: Operator (два слегка расстроенных
           пилообразных голоса, мюзет) → Chorus-Ensemble → Reverb, и добавил
           демо-клип с аккордами. Хотите звук мягче или ярче?
```

Что происходит под капотом:

1. Агент (Claude) понимает запрос и ищет подходящий **рецепт** в библиотеке (алиасы RU/EN: «баян», «гармонь», «accordion»).
2. Параллельно ищет **готовый пресет** в браузере вашего Live; если нашёл уверенно, использует его.
3. Если пресета нет, **собирает звук** из встроенных устройств Live: инструмент, параметры, эффекты. Если в библиотеке рецепта нет, модель составляет **собственный рецепт** по той же схеме.
4. Через **Remote Script** создаёт дорожку, загружает устройства, выставляет параметры и добавляет демо-клип.
5. Показывает в чате, что было сделано. Действие можно отменить (`undo`) или попросить поправить звук.

## Архитектура

```
┌──────────────────────── Ableton Live ────────────────────────┐
│                                                              │
│  [M4L device "AbletonHelper Chat"]   [Remote Script          │
│   jweb → http://127.0.0.1:8765        "AbletonHelper"]       │
│        │                                   ▲ TCP 127.0.0.1:9888
└────────┼───────────────────────────────────┼─────────────────┘
         │ HTTP + SSE                        │ JSON lines (docs/PROTOCOL.md)
┌────────▼───────────────────────────────────┴─────────────────┐
│ backend (python, пакет abhelper)                             │
│  server/   FastAPI: UI, /api/chat (SSE), /api/status         │
│  agent/    цикл tool-use с Claude, системный промпт, tools   │
│  sound/    SoundEngine: библиотека рецептов, поиск пресетов, │
│            применение рецепта через мост                     │
│  knowledge/ база знаний по Ableton + поиск                   │
│  bridge/   клиент TCP-моста + FakeBridge (эмулятор)          │
└──────────────────────────────────────────────────────────────┘
         ▲
         └── ui/ (статический веб-чат; открывается в jweb или в браузере)
```

Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), протокол моста: [docs/PROTOCOL.md](docs/PROTOCOL.md), интерфейсы модулей: [docs/INTERFACES.md](docs/INTERFACES.md).

Почему не VST/AU-плагин: плагин не имеет доступа к сету Live (создание дорожек, загрузка устройств, чтение параметров). Это умеет только Live API: из Python Remote Script и из Max for Live.

## Требования

- **Ableton Live 11 или 12** (любая редакция) для Remote Script. На Live 12.3 и новее загрузка нативных устройств быстрее и надёжнее.
- **Чат внутри Live**: нужна лицензия Max for Live (входит в Suite). Это экспериментальный путь. **Без Max for Live** откройте чат в браузере: <http://127.0.0.1:8765> и держите окно рядом с Live. Все функции доступны.
- **Python 3.10+** для локального сервера.
- **API-ключ Anthropic** (<https://console.anthropic.com>): модель отвечает через интернет. Использование оплачивается по тарифам Anthropic.
- macOS или Windows (подробно в [docs/INSTALL.md](docs/INSTALL.md)).

## Быстрый старт

```bash
# 1. Установка пакета (из корня репозитория)
pip install -e .

# 1a. API-ключ: скопируйте шаблон и впишите ключ в ANTHROPIC_API_KEY=
cp .env.example .env

# 2. Установка Remote Script в Live
python scripts/install_remote_script.py

# 3. В Live: Settings (в Live 11 Preferences) → Link, Tempo & MIDI →
#    в одном из слотов Control Surface выберите «AbletonHelper».
#    Перезапустите Live, если скрипт не появился в списке.

# 4. Запустите сервер
abhelper serve

# 5. Откройте чат: M4L-устройство (см. m4l/README.md) или браузер
#    http://127.0.0.1:8765
```

Ключ берётся из файла `.env` в корне проекта (или из переменной `ANTHROPIC_API_KEY`, или из настроек чата ⚙). Затем попробуйте: «Хочу звук баяна».

### Попробовать без Live

```bash
abhelper serve --fake        # чат с эмулятором Live (ничего не меняется в вашем сете)
abhelper chat --fake         # то же самое в терминале
```

### Диагностика и калибровка

```bash
abhelper doctor              # проверка установки: Remote Script, мост, ключ, порты
abhelper calibrate           # записывает реальные имена параметров устройств из вашего Live
                             # (по умолчанию в ~/.ableton-helper/device_catalog.json),
                             # чтобы рецепты звуков применялись точнее
abhelper calibrate --devices Operator Wavetable --out мой_каталог.json
```

Все опции: `abhelper --help`, `abhelper <команда> --help`. Live при `calibrate` должен быть запущен с включённым Remote Script.

Удаление Remote Script: `python scripts/install_remote_script.py --uninstall`. Проверка без изменений: `--dry-run`.

## Порты и настройки

| Что | По умолчанию | Переопределение |
|---|---|---|
| Мост Remote Script | `127.0.0.1:9888` | `ABHELPER_BRIDGE_PORT` |
| Веб-сервер и чат | `127.0.0.1:8765` | `ABHELPER_PORT` или `abhelper serve --port` |
| Модель | `claude-opus-5-5` | `ABHELPER_MODEL` или настройки в чате |
| API-ключ | `ANTHROPIC_API_KEY` (в окружении или в `.env`) | настройки в чате → `~/.ableton-helper/config.json` |

Всё слушает только `127.0.0.1`.

## Структура проекта

```
ableton-helper/
├── remote_script/AbletonHelper/   Python Remote Script для Live (мост, Live API)
├── backend/abhelper/              локальный сервер
│   ├── agent/                     цикл tool-use с Claude
│   ├── sound/                     рецепты звуков, поиск пресетов, применение
│   ├── knowledge/                 база знаний (RAG): BM25-поиск, synonyms.json
│   │   └── docs/{help,sound,theory}/   Markdown: справка по Live, саунд-дизайн, теория
│   ├── bridge/                    клиент моста и FakeBridge
│   └── server/                    FastAPI (HTTP + SSE)
├── ui/                            веб-чат (HTML/CSS/JS без сборки)
├── m4l/                           Max for Live устройство с окном чата
├── scripts/install_remote_script.py
└── docs/                          архитектура, протокол, интерфейсы, установка
```

Тесты интерфейса: `node --test ui/tests/*.test.js`. Тесты бэкенда: `pytest`.

## Ограничения и честность

- **Рецепты — приближение.** «Баян» из Operator или Wavetable не звучит как записанный баян: это синтез, который передаёт характер (мюзет, язычковый тембр). Лучший результат даёт пресет или сэмплер с реальными сэмплами.
- **Качество пресетов зависит от вашей библиотеки.** Ассистент находит то, что установлено в вашем Live; нет нужного пака, нет и пресета.
- **Имена параметров зависят от версии Live.** Поэтому есть нечёткое сопоставление и `abhelper calibrate`. Часть параметров может остаться неприменённой, ассистент об этом сообщает.
- **Набор встроенных устройств зависит от редакции** (Intro/Standard/Suite). Если нужного синтезатора нет, используется запасной.
- **Нужен интернет** для языковой модели; **стоимость** определяется тарифами Anthropic и выбранной моделью.
- **Окно чата внутри Live через Max for Live экспериментальное.** Патч написан без запуска Max и не проверен; гарантированный вариант: браузер. См. [m4l/README.md](m4l/README.md).
- Ассистент меняет ваш сет. Сохраняйтесь перед экспериментами; действия можно отменить.
- Проект не связан с Ableton AG; «Ableton» и «Live» — товарные знаки их владельцев.

## Похожие проекты

- [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) (MIT): MCP-сервер + Remote Script, позволяет Claude Desktop управлять Live.
- [adamjmurray/producer-pal](https://github.com/adamjmurray/producer-pal) (GPL-3.0): устройство Max for Live с MCP-сервером на Node for Max, чат в браузере; Live 12.3+.
- [ideoforms/AbletonOSC](https://github.com/ideoforms/AbletonOSC): управление Live по OSC; без загрузки пресетов из браузера.

Чем отличается Ableton Helper: упор на **создание звука по описанию** (библиотека рецептов + поиск пресетов + рецепты, которые проектирует LLM), русскоязычный интерфейс, чат внутри Live и поддержка Live 11 и 12.

## Планы (roadmap)

- Генерация сэмплов по тексту (text-to-audio) с загрузкой в Simpler.
- Режим MCP-сервера для Claude Desktop.
- Локальная LLM как альтернатива облачной.
- Голосовой ввод.

---

## English summary

**Ableton Helper** is an LLM assistant embedded in Ableton Live for Russian-speaking producers. Type "I want an accordion sound" and a MIDI track appears in your set with an instrument, effects and a demo clip. It also answers "how do I..." questions about Live from a built-in knowledge base.

Architecture: a Python MIDI Remote Script inside Live (TCP bridge on 127.0.0.1:9888) talks to a local Python backend (FastAPI + Claude tool-use agent, port 8765), which serves a web chat that can be shown inside Live through a Max for Live `jweb` device (experimental) or simply opened in a browser.

Requirements: Live 11 or 12, Python 3.10+, an Anthropic API key; Max for Live (Suite) only for the in-Live chat window.

Quick start: `pip install -e .`, `python scripts/install_remote_script.py`, enable the "AbletonHelper" control surface in Live (Settings, Link / Tempo / MIDI), `abhelper serve`, open <http://127.0.0.1:8765>. Try without Live: `abhelper serve --fake`. Troubleshooting: `abhelper doctor`; `abhelper calibrate` records real device parameter names from your Live.

Limitations: recipes approximate real instruments with synths; preset quality depends on your library; parameter names vary by Live version; the LLM needs internet access and is billed by Anthropic.

Roadmap: text-to-audio sample generation into Simpler, MCP server mode, local LLM option, voice input.

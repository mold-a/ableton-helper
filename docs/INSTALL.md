# Установка Ableton Helper

Пошаговая инструкция для macOS и Windows. Если что-то пошло не так, смотрите раздел «Если не работает» и FAQ в конце.

## Что понадобится

- **Ableton Live 11 или 12**, любая редакция (для Remote Script). Для окна чата внутри Live нужна ещё лицензия **Max for Live** (входит в Suite). Без неё чат открывается в браузере.
- **Python 3.10 или новее.** Проверка: `python3 --version` (macOS) или `python --version` (Windows).
- **API-ключ Anthropic**: создайте на <https://console.anthropic.com> в разделе API Keys. Использование оплачивается по тарифам Anthropic.
- Интернет для работы языковой модели.

Всё общение между компонентами идёт по `127.0.0.1` (только ваш компьютер).

## 1. Получите проект и установите пакет

macOS (Terminal):

```bash
cd ~/ableton-helper        # папка с репозиторием
python3 -m venv .venv      # по желанию, но рекомендуется
source .venv/bin/activate
pip install -e .
```

Windows (PowerShell):

```powershell
cd $HOME\ableton-helper
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

Если PowerShell не даёт активировать окружение, выполните один раз `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` или пропустите venv.

Проверка: команда `abhelper --version` должна напечатать версию.

## 2. Установите Remote Script в Live

```bash
python scripts/install_remote_script.py            # macOS: python3
```

Скрипт копирует папку `remote_script/AbletonHelper` в папку **Remote Scripts** вашей **User Library**:

| ОС | Куда копируется по умолчанию |
|---|---|
| macOS | `~/Music/Ableton/User Library/Remote Scripts/AbletonHelper` |
| Windows | `Документы\Ableton\User Library\Remote Scripts\AbletonHelper` (то есть `%USERPROFILE%\Documents\...`) |

Полезные ключи:

- `--dry-run`: показать, что будет сделано, ничего не копируя.
- `--dest <папка>`: установить в другую папку «Remote Scripts» (путь к папке, **содержащей** папку скрипта).
- `--uninstall`: удалить скрипт.

### Где находится User Library

Если вы переносили User Library, путь может отличаться. Узнать его можно в Live: **Settings (в Live 11 Preferences) → Library → User Library**. Скрипт устанавливает по стандартному пути; для нестандартного используйте `--dest`.

### Правильная структура

```
Remote Scripts/
└── AbletonHelper/
    ├── __init__.py        ← обязательно прямо здесь, не глубже
    └── ...
```

Если `__init__.py` окажется во вложенной папке (например, `AbletonHelper/AbletonHelper/__init__.py`), Live не увидит скрипт.

## 3. Включите Control Surface в Live

1. **Полностью перезапустите Live** (закройте приложение и откройте снова), чтобы он увидел новый скрипт.
2. Откройте настройки:
   - macOS: меню **Live → Settings…** (в Live 11 — Preferences…), сочетание **Cmd+,**;
   - Windows: меню **Options → Settings…** (в Live 11 — Preferences…), сочетание **Ctrl+,**.
3. Вкладка **Link, Tempo & MIDI** (в Live 11 она может называться Link/MIDI).
4. В одном из слотов **Control Surface** выберите **AbletonHelper**. **Input** и **Output** оставьте **None**.
5. Закройте настройки. Внизу окна Live не должно быть сообщений об ошибке.

## 4. Запустите сервер и откройте чат

```bash
abhelper serve
```

Откройте в браузере <http://127.0.0.1:8765>. В шапке чата два индикатора:

- **Live** (зелёный): Remote Script подключён;
- **AI** (зелёный): ключ API задан. Если индикатор жёлтый, нажмите шестерёнку и вставьте ключ.

Удобнее всего задать ключ в файле `.env` в корне проекта: `cp .env.example .env`, затем впишите ключ после `ANTHROPIC_API_KEY=` и перезапустите `abhelper serve`. Файл `.env` в git не попадает. Приоритет: переменная окружения `ANTHROPIC_API_KEY` > `.env` > настройки чата. В настройках чата он сохраняется в `~/.ableton-helper/config.json` (на Windows: `%USERPROFILE%\.ableton-helper\config.json`).

Попробуйте написать: «Хочу звук баяна».

Чтобы проверить чат без Live: `abhelper serve --fake`. Диагностика: `abhelper doctor`.

## 5. (По желанию) Окно чата внутри Live

Нужен Max for Live. Инструкция и честные оговорки: [m4l/README.md](../m4l/README.md). Это экспериментальный путь. Запасной вариант всегда работает: <http://127.0.0.1:8765> в браузере.

## 6. Калибровка (рекомендуется)

Когда Live запущен и Control Surface включён, выполните:

```bash
abhelper calibrate
```

Команда считывает реальные имена параметров устройств вашей версии Live (по умолчанию в `~/.ableton-helper/device_catalog.json`), чтобы звуки применялись точнее. Рекомендуется повторить после обновления Live.

## Где лежит Log.txt Live

Файл журнала Live нужен для диагностики:

- **macOS:** `~/Library/Preferences/Ableton/Live <версия>/Log.txt`
  (папка Library скрыта: в Finder выберите «Переход → Переход к папке…» и вставьте путь; `<версия>` например `12.1.5`)
- **Windows:** `%APPDATA%\Ableton\Live <версия>\Preferences\Log.txt`
  (вставьте путь в адресную строку Проводника)

Ищите в нём слова `AbletonHelper`, `Error`, `Traceback`.

## Брандмауэр и безопасность

- Сервер (порт 8765) и мост (порт 9888) слушают **только `127.0.0.1`**. Из сети они недоступны.
- На Windows брандмауэр может спросить разрешение для Python при первом запуске `abhelper serve`. Достаточно разрешить для **частных сетей**; внешний доступ не нужен.
- На macOS может появиться запрос «Принимать входящие подключения для Python?» Можно ответить «Не разрешать»: локальные подключения работают и так (если окно подтверждения не закрывается, проверьте Системные настройки → Сеть → Брандмауэр).
- Антивирусы с «веб-защитой» иногда блокируют локальные порты: добавьте исключение для `127.0.0.1:8765` и `127.0.0.1:9888`.
- Наружу идут только запросы к API Anthropic.

## Если не работает

**Control Surface «AbletonHelper» нет в списке (особенно в Live 12).**
1. Убедитесь, что структура именно `Remote Scripts/AbletonHelper/__init__.py`.
2. Полностью перезапустите Live (не только проект).
3. Откройте `Log.txt` и найдите ошибки, связанные с AbletonHelper.
4. Установите скрипт в папку приложения (запасной путь). Для этого нужны права записи в эту папку:
   - macOS: `python3 scripts/install_remote_script.py --dest "/Applications/Ableton Live 12 <Редакция>.app/Contents/App-Resources/MIDI Remote Scripts/"`
   - Windows: `python scripts\install_remote_script.py --dest "C:\ProgramData\Ableton\Live 12 <Редакция>\Resources\MIDI Remote Scripts\"`
   (подставьте вашу редакцию: Intro, Standard, Suite; для Live 11 — `Live 11`). После обновления Live такие файлы могут потребовать повторной установки.

**Индикатор Live красный.** Control Surface не выбран либо Live не запущен; проверьте также порт 9888 (может быть занят): `ABHELPER_BRIDGE_PORT`.

**Ошибка «Не настроен AI».** Не введён ключ; откройте настройки (шестерёнка).

**Белый экран в Max-устройстве.** Не запущен `abhelper serve` или другой порт; нажмите «Обновить» или используйте браузер.

**`abhelper` не найден.** Активируйте виртуальное окружение либо запускайте как `python -m abhelper serve`.

Для любых проблем начните с `abhelper doctor`.

## FAQ

**Нужно ли держать терминал открытым?** Да, пока вы пользуетесь ассистентом: сервер работает в нём. Закройте окно, чтобы остановить.

**Можно ли пользоваться без Max for Live?** Да. Откройте <http://127.0.0.1:8765> в браузере и держите окно рядом с Live.

**Какой порт использовать, если 8765 занят?** `abhelper serve --port 8800`; в M4L-устройстве поменяйте адрес.

**Как обновить?** Обновите репозиторий (`git pull`), повторите `pip install -e .` и `python scripts/install_remote_script.py`, затем перезапустите Live.

**Как удалить?** `python scripts/install_remote_script.py --uninstall`, затем `pip uninstall ableton-helper`. Конфигурация лежит в `~/.ableton-helper/`.

**Сколько это стоит?** Оплата берётся Anthropic за использование API (зависит от модели и объёма диалога). В настройках можно выбрать более лёгкую модель и уровень effort.

**Работает ли на Linux?** Live на Linux не существует; сервер можно запускать для проверки (`--fake`).

**Что делает ассистент с моим проектом?** Создаёт и настраивает дорожки по вашей просьбе; действия можно отменить в Live (Cmd/Ctrl+Z) или попросить ассистента «отмени». Перед экспериментами сохраняйте проект.

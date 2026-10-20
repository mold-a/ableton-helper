# Реалистичные инструменты из сэмплов

Синтез в Operator или Wavetable не звучит как настоящий баян, гитара или саксофон. Поэтому для таких звуков Ableton Helper использует **записанные инструменты**: скачивает бесплатные сэмпл-библиотеки (лицензия CC0) и собирает из них пресеты **Ableton Sampler**. После установки запрос «хочу звук баяна» создаёт MIDI-дорожку с Sampler, в котором играет настоящий Hohner.

> Статус: код написан и проверен тестами и на реально скачанных паках, но **на вашем Live ещё не запускался**. Первая установка — это проверка. Что именно смотреть, написано в разделе «Первый запуск».

## Как это работает

1. `abhelper samples install <пак>` скачивает архив (проверяются размер и sha256) и распаковывает его во временную папку.
2. Из SFZ-файла пака читается карта зон: диапазоны клавиш, корневые ноты, подстройка, границы циклов, слои громкости, огибающая.
3. Нужные сэмплы копируются в **User Library**, а рядом создаётся пресет Sampler (`.adv`).
4. Шаблон пресета берётся **из вашей собственной установки Live**, а не из репозитория: Live ищется в `Resources\Core Library` (и там, где Remote Script сообщил свою папку), берётся первый Sampler-пресет, и в его копии заменяются зоны сэмплов и несколько настроек. Поэтому формат всегда совпадает с вашей версией Live, а лицензии чужих шаблонов не нужны.
5. Если Live запущен, программа просит его переиндексировать браузер, и пресет сразу появляется в **User Library**.
6. Дальше работает обычный движок звуков. Название пресета начинается с `AbletonHelper`, такие пресеты получают сильную надбавку при поиске и в режиме `auto` побеждают синтез.

## Что нужно

- Python-пакет проекта с зависимостью `py7zr` (ставится вместе с `pip install -e .`; нужна для архивов `.7z`).
- Ableton Live **Suite** (устройство Sampler входит только в Suite) или Standard с дополнением Sampler.
- Интернет на время скачивания (1–10 МБ на пак).

## Команды

```bash
abhelper samples doctor                      # пути, шаблон Sampler, установленные паки
abhelper samples list                        # все паки, размер, лицензия, статус
abhelper samples install accordion-hn        # один пак (баян)
abhelper samples install all                 # все проверенные паки, около 38 МБ скачивания
abhelper samples install accordion-hn -l     # то же и с картой зон
abhelper samples install accordion-hn --force   # переустановить
abhelper samples uninstall accordion-hn      # удалить сэмплы и пресет
```

Общие параметры (для всех подкоманд):

| Параметр | Зачем |
|---|---|
| `--live-dir D:\Ableton` | папка установки Live (где лежат `Resources` и `Program`). Нужна, если шаблон не найден сам |
| `--user-library "D:\Ableton\User Library"` | если автоопределение ошиблось. Определяется по `Library.cfg` самого Live |
| `--template файл.adv` | готовый Sampler-пресет в качестве шаблона (обычно не нужен) |
| `--no-rescan` | не трогать запущенный Live после установки |
| `--fake` | эмулятор Live вместо реального (для проверки без Live) |

Те же значения можно задать переменными `ABHELPER_LIVE_DIR` и `ABHELPER_USER_LIBRARY`.

### Для вашей конфигурации (Windows, Live 11.3.25 Suite, Live в `D:\Ableton`)

```powershell
abhelper samples doctor --live-dir D:\Ableton
abhelper samples install accordion-hn --live-dir D:\Ableton
```

Live может быть запущен: Remote Script сообщит свою папку, и `--live-dir` не понадобится. Если установили скрипт в `D:\Ableton\Resources\MIDI Remote Scripts\AbletonHelper`, программа сама найдёт `D:\Ableton\Resources`. Для этого Remote Script должен быть версии 0.3.0 или новее (переустановите: `python scripts/install_remote_script.py`).

## Куда что кладётся

```
<User Library>\Samples\AbletonHelper\<id пака>\...                       сэмплы, LICENSE, ATTRIBUTION.txt, abhelper-pack.json
<User Library>\Presets\Instruments\Sampler\AbletonHelper\<имя>.adv      пресет Sampler
~\.ableton-helper\samples-cache\                                        скачанные архивы (можно удалять)
```

В Live пресеты видны в браузере: **User Library → Presets → Instruments → Sampler → AbletonHelper**. Ссылки на сэмплы в пресете заданы относительно User Library (с запасным абсолютным путём), поэтому папку можно переносить вместе с библиотекой.

Установка идемпотентна: повторный `install` ничего не делает, пока всё на месте; `--force` пересоздаёт. Повреждённая установка (нет файла сэмпла или пресета) показывается в `list` как «повреждён», лечится `install --force`.

## Шаблон Sampler

Порядок поиска: `--template`; пресет «AbletonHelper Template» в User Library; Sampler-пресеты из `Resources\Core Library` вашего Live (предпочтительно с «Sampler» в пути, самые маленькие); любой другой Sampler-пресет в `Presets\Instruments\Sampler`.

Если ничего не найдено, `install` и `doctor` скажут об этом и покажут, как сделать шаблон за минуту:

1. В Live перетащите устройство **Sampler** на пустую MIDI-дорожку.
2. Бросьте в него любой звук (хоть сэмпл из браузера).
3. Нажмите «Save Preset» (иконка дискеты в шапке устройства) и сохраните под именем **AbletonHelper Template** в `User Library\Presets\Instruments\Sampler`.
4. Повторите `abhelper samples install ...`.

## Паки и лицензии

Все паки сейчас под **CC0 1.0** (общественное достояние): копировать, менять и использовать можно без ограничений, указывать авторов не обязательно, но мы указываем. Файл `ATTRIBUTION.txt` с источником кладётся рядом с сэмплами.

| id | Инструмент | Размер | Рецепт | Авторы |
|---|---|---|---|---|
| `accordion-hn` | Hohner button accordion (баян) | 6,0 МБ | `bayan` | Jeff Stauffer (запись), michael02022 (банк), FreePats |
| `upright-piano-kw` | Пианино Kawai (small) | 3,1 МБ | `grand_piano` | Gonzalo и Roberto, FreePats |
| `spanish-classical-guitar` | Классическая гитара | 4,7 МБ | `acoustic_guitar` | Roberto, FreePats |
| `concert-harp-small` | Концертная арфа (small) | 2,6 МБ | `harp` | Versilian Community Sample Library, K. Smith, FreePats |
| `tenor-sax-small` | Тенор-саксофон (small) | 4,9 МБ | `saxophone` | Versilian Community Sample Library, FreePats |
| `clarinet` | Кларнет | 7,0 МБ | `clarinet` | Tyler Dence, Kaili Dence, Roberto, FreePats |
| `recorder` | Блокфлейта | 9,3 МБ | — | Eugene Vlaskin, Roberto, FreePats |

Источник: проект [FreePats](https://freepats.zenvoid.org/), лицензия [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Баян: <https://freepats.zenvoid.org/Organ/accordion.html>. Контрольные суммы и размеры лежат в `backend/abhelper/samples/registry.json` и проверены скачиванием.

Намеренно не включены: стальная гитара FreePats (GPL), Salamander Grand Piano (CC BY, 200+ МБ), библиотеки без проверенной прямой ссылки (например, VCSL целиком: репозиторий слишком велик, а отдельные архивы не проверены). Чтобы добавить свой пак, допишите запись в `registry.json`: правила проверки описаны в `validate_registry`, а `verified: true` требует `size_bytes` и `sha256`.

## Как ассистент выбирает этот пресет

- Рецепт (`bayan.json`) начинает `preset_search` с `AbletonHelper Accordion`. Пресеты с `AbletonHelper` в имени или пути получают надбавку и при совпадении слов в режиме `auto` выигрывают у синтеза и у обычных пресетов.
- Необязательное поле рецепта **`preset_parameters`** (те же формы значений, что у параметров инструмента, включая `{"display": "..."}`) применяется к первому инструменту только что загруженного пресета: можно подстроить огибающую или громкость Sampler. Параметры, которых нет на устройстве, попадают в `unmatched_parameters`, как и при синтезе.
- Если пресет не установлен, движок строит звук из рецепта синтезом, как раньше.

## Что берётся из SFZ

Поддерживается минимум, нужный для пакетов выше: `<control> default_path`; наследование `<global>/<master>/<group>/<region>`; `key`, `lokey`, `hikey`, `pitch_keycenter` (числа и имена нот, **C4 = 60** по соглашению SFZ); `tune` и `transpose` (целые полутона переносятся в корневую ноту, подстройка остаётся в пределах ±50 центов); `lovel`/`hivel`; `offset`/`end`; `loop_start`/`loop_end`/`loop_mode` (`loop_continuous` и `loop_sustain` дают прямой цикл, `no_loop` и `one_shot` — без цикла; если границ нет, берутся петли из самого WAV); `volume`, `pan`; `ampeg_attack/decay/sustain/release` и `amp_veltrack` для огибающей громкости Sampler. Остальное игнорируется.

Не поддерживается, и это важно знать:

- **Сэмплы «отпускания клавиши»** (`trigger=release`, папка `rel/` в баяне): Sampler не умеет запускать звук при отпускании. Их нет в пресете, в списке пропущенных регионов они перечислены.
- **Round-robin** (`lorand`/`hirand`, `seq_position`): берётся только первый вариант.
- Фильтры, LFO и модуляции из SFZ не переносятся. Фильтр, LFO и огибающая высоты в пресете выключены.

Карта зон баяна (17 зон) выводится командой `abhelper samples install accordion-hn -l` и при проверке на скачанном паке: `python scripts/check_samples_pack.py --sfz "<папка>\PRESET Button Accordion HN tuned.sfz"`. Нумерация нот в Ableton: C3 = 60 (в SFZ это C4).

## Первый запуск на вашем Live: что проверить

Формат пресета собирается по тому, что Live 11 пишет сам, но без запуска Live проверить его нельзя.

1. `abhelper samples doctor --live-dir D:\Ableton` — путь User Library и шаблон должны быть найдены.
2. `abhelper samples install accordion-hn --live-dir D:\Ableton -l`.
3. В Live: **User Library → Presets → Instruments → Sampler → AbletonHelper → AbletonHelper Accordion HN**, двойной клик на MIDI-дорожке.
4. Проверьте: Sampler открылся, во вкладке Zones 17 зон без красных «missing», звук играет по всей клавиатуре, держите ноту: звук тянется (цикл), отпускайте: затухает за ~0,13 с. Сыграйте хроматическую гамму: нет скачков высоты между зонами.
5. Скажите ассистенту «хочу звук баяна»: должен загрузиться этот пресет, а не синтез.
6. Если что-то не так, пришлите `Log.txt` Live и файл пресета (`.adv` — это gzip с XML).

## Если не работает

| Симптом | Что делать |
|---|---|
| «Не нашёл шаблон Sampler» | Укажите `--live-dir D:\Ableton` или сделайте шаблон вручную (раздел выше) |
| Пресета нет в браузере Live | Правый клик по **User Library → Refresh**, либо перезапуск Live. Проверьте, что `doctor` показывает ту же User Library, что в Live: Settings → Library |
| Пресет есть, но сэмплы «missing» | Пути к сэмплам неверны: `Samples\AbletonHelper\<пак>` должна лежать внутри User Library, показанной в `doctor`. Переустановите: `install <пак> --force`. Если вы переместили User Library, укажите новую через `--user-library` |
| Live пишет, что файл пресета повреждён | Шаблон из вашего Live не подошёл. Сделайте свой шаблон вручную (раздел выше) и пришлите пресет, чтобы доработать генератор |
| `Не удалось скачать` | Проверьте интернет/прокси (`HTTPS_PROXY`). Загрузка докачивается: повторите команду. Ошибка sha256 значит, что файл на сервере изменился: сообщите об этом |
| `для распаковки .7z нужен пакет py7zr` | `pip install py7zr` |
| Ассистент всё равно синтезирует | В `doctor` проверьте, что пак установлен; запустите в Live поиск «AbletonHelper» и убедитесь, что пресет находится. Браузер индексируется минуту после запуска Live |

Удаление: `abhelper samples uninstall <id>` убирает сэмплы и пресет (и пустые папки `AbletonHelper`). Больше ничего в User Library программа не трогает.

# Reverb: ревербератор (Live 11.3.25)
keywords: reverb, реверб, ревербератор, hall, зал, room, комната, plate, пластина, decay time, predelay, предзадержка, dry/wet, хвост, пространство, глубина, ближе, дальше, room size, diffusion, density, stereo image, freeze

## Reverb: сигнальный путь и ключевые параметры
Reverb Live состоит из входного фильтра (In LowCut On, In HighCut On, In Filter Freq, In Filter Width), блока ранних отражений (ER Spin On/Rate/Amount, ER Shape), диффузной сети (Diffusion, Scale, HiFilter, LowShelf, Chorus) и выхода (Reflect Level, Diffuse Level, Stereo Image, Dry/Wet). Главное: Decay Time — время хвоста (≈200 ms…60 s); Room Size — объём «комнаты» (маленькие значения звучат металлически, огромные — как задержка); Predelay — пауза до начала реверба (0.5…250 ms, естественно 1–25 ms; 10–30 ms отделяет сухой звук от хвоста); Dry/Wet (%). Если Reverb стоит на return-треке — ставьте Dry/Wet = 100 %, а глубину задавайте отправкой (Send); если на самом треке — 8–25 %.

## Reverb: готовые пространства
Малая комната / студия: Decay Time 0.4–0.9 s, Room Size маленький (norm 0.3–0.5), Predelay 3–8 ms, Dry/Wet 8–14 %. Комната для соло (баян, гитара, скрипка): Decay Time 1.2–1.6 s, Predelay 10–15 ms, Dry/Wet 12–18 %, HiFilter On, HiFilter Type: Shelf или Lowpass, частота 6–8 kHz (хвост темнее). Концертный зал: Decay Time 2–3 s, Room Size ≈ 0.7–0.9 (norm), Predelay 20–30 ms, Dry/Wet 18–25 %. Собор: 5–8 s, Predelay 25–40 ms, Dry/Wet 30–40 %. Пластина (ударные/вокал): Decay Time 1–2 s, Diffusion высокая, Density High. Правило: чем короче и тише — тем «ближе» звук; чем длиннее, влажнее и меньше предзадержка — тем «дальше». Для плотных быстрых партий (арпеджио) хвост не длиннее 1–1.5 s.

## Reverb: тонкая настройка и подводные камни
In LowCut On + In Filter Freq 150–300 Hz убирает муть из хвоста; In HighCut On ≈ 5–8 kHz смягчает шипение. HiShelf Gain / HiFilter Freq регулируют скорость затухания верха (темнее хвост — естественнее). Diffusion: высокая — гладко, низкая — различимые отражения. Scale — «зернистость» (при малых комнатах влияет на окраску). Density: Sparse (экономнее по CPU), Low, Mid, High (богаче). Stereo Image 0…120°: узкий — ближе и собраннее, широкий — просторнее. Chorus On добавляет модуляцию хвоста — полезно для пэдов, но для акустических соло-инструментов выключайте (Chorus On = Off): иначе хвост «плавает». ER Spin также лучше выключить на коротких реверберах, если слышно дрожание. Freeze On превращает хвост в бесконечный пэд — только для эффектов. Всегда проверяйте, что реверб не поднимает общий уровень выше −6 dBFS.

## Источники
- https://www.ableton.com/en/live-manual/11/live-audio-effect-reference/

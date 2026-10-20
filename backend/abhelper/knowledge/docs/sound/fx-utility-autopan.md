# Utility и Auto Pan (Live 11.3.25)
keywords: utility, утилита, gain, громкость, stereo width, ширина, mono, моно, bass mono, balance, баланс, phase invert, dc filter, auto pan, автопан, тремоло, tremolo, панорама, панорамирование, pan, ширина стерео, headroom, запас

## Utility: параметры
Utility — вспомогательное устройство без окраски. Gain (display −inf…+35 dB; по API −1…1 нормированное — используйте display «−3 dB») — общая громкость; Stereo Width (0…2, в интерфейсе 0…200 %): 0 % — моно, 100 % — как есть, 120–150 % — шире, до 200 % — максимум (на крайних значениях моно-совместимость падает); Mono = On — сумма в моно; Bass Mono = On и Bass Freq (50…500 Hz; display «150 Hz») — всё ниже частоты в центр (нужно для баса и кика, особенно после widening); Balance (−1…1) — стереобаланс; Channel Mode: Left, Stereo, Right, Swap; Left Inv / Right Inv — инверсия фазы; Mute; DC Filter — удаление постоянной составляющей (после сильной сатурации или в сабе). Utility чаще всего ставят последним в цепочке: поправить выходной уровень (запас 3–6 dB до 0 dBFS), сделать бас моно, ужать или расширить стерео.

## Utility: рецепты
Запас по уровню (headroom): Gain −3…−6 dB на треке после жирных эффектов. Баса в моно: Bass Mono On, Bass Freq 120–200 Hz. Чуть шире пэд: Stereo Width 120–140 %. Проверка моно-совместимости: временно Mono On — если звук исчез или упал более чем на 4–5 dB, откатите widening. Сабы и 808: DC Filter On. Для баяна/соло-инструментов: Stereo Width 80–100 %, Gain −3 dB. Не используйте Utility для «улучшения» тембра — он ничего не добавляет; для «ярче/теплее» нужны EQ и насыщение. Инверсия фазы пригодится, когда два слоя одного ударного (кик + саб) гасят друг друга: Left Inv + Right Inv на одном слое проверьте на слух.

## Auto Pan: параметры и тремоло
Auto Pan модулирует панораму (LFO). LFO Type: Frequency (Hz) или Beats (синхронно; Sync Rate 0…21), Frequency, Amount (0…1; 0 — эффект выключен, 20–35 % — мягко), Waveform: Sine, Triangle, SawDown, S&H Width (случайная), Shape (0…1 — «жёстче»), Phase (0…360°, по умолчанию 180 — левый и правый канал в противофазе = классический автопан), Offset, Spin, Stereo Mode (Phase/Spin), Width (Random), Invert. Трюк: Phase = 0° и Offset = 0° превращают Auto Pan в тремоло (оба канала меняют громкость синхронно, без движения по панораме) — подходит для электропиано/Wurlitzer (Frequency 4.5–5.5 Hz, Amount 15–30 %) и для лёгкого «дыхания» гармониума/органа (4–6 Hz, Amount ≈ 10 %). Классический автопан: Phase 180°, Waveform Sine, Rate 0.3–2 Hz, Amount 30–60 %. Для сольных инструментов в центре Auto Pan используют редко.

## Источники
- https://www.ableton.com/en/live-manual/11/live-audio-effect-reference/

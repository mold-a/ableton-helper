# Auto Filter: фильтр с огибающей и LFO (Live 11.3.25)
keywords: auto filter, автофильтр, фильтр, filter, cutoff, срез, resonance, резонанс, wah, вау, sweep, свип, lfo, envelope follower, огибающая, ярче, темнее, bandpass, notch, highpass, lowpass, morph

## Auto Filter: параметры
Auto Filter — фильтр, у которого срез модулирует огибающая входного сигнала и LFO. Filter Type: Lowpass, Highpass, Bandpass, Notch, Morph (плавный переход LP–BP–HP–Notch, параметр Morph); Filter Circuit - LP/HP: Clean, OSR, MS2, SMP, PRD (Clean без искажений; остальные — аналоговые с Drive); Slope: 12 dB или 24 dB. Frequency — срез; по API raw-шкала 20…135 соответствует номерам MIDI-нот (135 ≈ 20 kHz, 100 ≈ 2.6 kHz, 60 ≈ 260 Hz), поэтому задавайте display («1.2 kHz», «300 Hz»). Resonance (0…1.25): выше 1.0 при не-Clean схемах — самоосцилляция (свист). Drive (0…24 dB) добавляет искажение. Env. Modulation (−127…127, положительное открывает фильтр по громкости входа), Env. Attack (0.1…30 ms), Env. Release (0.1…400 ms). LFO Amount (0…30), LFO Waveform (Sine, Square, Triangle, SawUp, SawDown, S&H Stereo, S&H Mono), LFO Frequency (Hz) или LFO Sync (LFO Sync Rate), LFO Phase 180 (разный сдвиг каналов — стерео-движение), LFO Quantize. S/C — внешний сайдчейн.

## Auto Filter: типовые задачи
Сделать звук тусклее: Lowpass 12 dB, Frequency 2–4 kHz, Resonance 0.1. Вырезать низ: Highpass, Frequency 80–150 Hz (мягче, чем EQ). Телефон/радио: Bandpass, Frequency ~1.2 kHz, Resonance 0.3–0.5. Свип: LFO Amount 12–24, медленный LFO Frequency 0.1–0.4 Hz или Sync 1 бар. Квакающий «вау» на басу: Env. Modulation +40…+80, Attack 1–5 ms, Release 80–150 ms, Resonance 0.4–0.6. Ритмичный «гейт»: Square LFO в Sync 1/8–1/16, Amount 20–30, Drive 0. Нежный вокальный «нос»: Bandpass, Q (Resonance) 0.3, фиксированная частота 800–1.5 kHz без модуляции. Пример шагов: «ярче» — поднять Frequency в 1.5–2 раза (≈ +0.6…+1 октава); «темнее» — понизить в 1.5–2 раза. Держите резонанс ниже 0.5 на постоянных тонах — иначе слышен звон на определённых нотах.

## Auto Filter против фильтра инструмента
В Operator, Analog, Drift, Wavetable, Simpler есть свой фильтр, и его правят в первую очередь: он стоит до усилителя, его огибающие следуют за нотой. Auto Filter стоит после инструмента: подходит, когда нужно общее потемнение звука, вау от огибающей громкости, фильтр-свип по сборному сигналу, bandpass-эффект «телефона», или когда у инструмента нет подходящего фильтра (Drum Rack, сэмплы). Не ставьте два фильтра с высокой добротностью подряд — получится неуправляемый «писк». Для динамичного звука используйте огибающую инструмента, а Auto Filter оставляйте для эффектов.

## Источники
- https://www.ableton.com/en/live-manual/11/live-audio-effect-reference/

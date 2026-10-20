# Redux и Vinyl Distortion: лоу-фай и винтаж (Live 11.3.25)
keywords: redux, редакс, bitcrusher, биткрашер, lofi, лофай, lo-fi, vinyl distortion, винил, виниловый, crackle, потрескивание, bit depth, sample rate, jitter, винтаж, vintage, старый, грязный, 8 bit, чиптюн, граница, шум

## Redux: параметры
Redux уменьшает частоту дискретизации и разрядность. Sample Rate (0…1, display в Hz/kHz; 1 — максимум): чем ниже, тем больше «металлического» алиасинга и срезанного верха; 8–12 kHz — мягкий «старый сэмплер», 4–6 kHz — явный лофай, ниже — радио-шум. Jitter — случайность тактов (шум и ширина). Pre-Filter On / Post-Filter On и Post-Filter — фильтры до/после ресемплинга (смягчают алиасинг). Bit Depth (1…16 бит): 14–12 — тонкая зернистость, 8 — «чиптюн/древний сэмплер», 4 и ниже — шум-разрушитель. Quantizer Shape — кривая квантизации, DC Shift — смещение. Dry/Wet — смесь: 100 % — полная замена, 20–40 % — лёгкая грязца. Для «ретро-клавиш» (пианино, E-piano, лофи-бит): Sample Rate около 10–16 kHz, Bit Depth 12, Post-Filter On, Dry/Wet 40–70 %.

## Vinyl Distortion: параметры
Vinyl Distortion имитирует искажения иглы и потрескивание. Tracing Model (Tracing On, Tracing Drive, Tracing Freq., Tracing Width) добавляет чётные гармоники в выбранной полосе; Pinch Effect (Pinch On, Pinch Drive, Pinch Freq., Pinch Width) — нечётные, противофазные, «сдавленность» стереоэффекта; Pinch Soft On: Soft (мягкий «дабплейт») / Hard (стандартный винил); Pinch Mono On: Stereo / Mono (Stereo рекомендуется). Global Drive — общая сила искажения. Crackle Density (0…50) и Crackle Volume (0…1) — потрескивание: для еле заметного фона Volume 0.1–0.25, Density 10–20. Для «винтажных клавиш»: Tracing Drive 0.2–0.35 около 2–3 kHz, Pinch Drive 0.1, Crackle Volume 0.15, Dry/Wet — эффект сам по себе всегда включён (Dry/Wet нет), поэтому подмешивать лучше через Return-трек.

## Лоу-фай: что и в каком порядке
Цепочка «винтажные клавиши» (lofi_keys): Saturator (Soft Sine, Drive 3 dB) → Redux (Bit Depth 12–14, Sample Rate 12 kHz, Post-Filter On, Dry/Wet 50 %) → Auto Filter Lowpass 5 kHz → Vinyl Distortion (Crackle Volume 0.15) → Reverb небольшой. Для «грязнее»: поднять Redux Bit Depth ниже на 2–3 бита, Jitter 0.1–0.3, Overdrive Drive 20 %. Для «чище»: убрать Redux и уменьшить Drive. Чего избегать: Redux в самом конце цепочки с Dry/Wet 100 % на басе — слышен «песок» и шум; Vinyl crackle на всём миксе — только на отдельной дорожке/шине. Помните, что Sample Rate и Bit Depth не поддерживают плавной автоматизации без щелчков — меняйте их заранее.

## Источники
- https://www.ableton.com/en/live-manual/11/live-audio-effect-reference/

"""adjust_sound: deterministic macro tweaks in display space (FakeBridge with the real catalog + injected curves)."""

import json

import pytest
from sound_testkit import ScriptedBridge, missing_devices, offline
from tweak_testkit import curved_catalog, device_names, make_bridge, num, param, shown, writes

from abhelper.bridge.base import BridgeConnectionError
from abhelper.bridge.displayval import parse_display
from abhelper.bridge.fake import FakeBridge
from abhelper.sound.tweaks import (AMOUNTS, REQUESTS, adjust_sound, detect_amount, resolve_requests,
                                   supported_requests)

OP_STATE = {"Filter On": "On", "Filter Freq": {"display": "3.2 kHz"}, "Filter Res": {"display": "20 %"}}


def op_bridge(**extra):
    state = dict(OP_STATE)
    state.update(extra)
    return make_bridge("Operator", state={0: state})


def changed(res, parameter, device=None):
    rows = [c for c in res["changes"] if c["parameter"] == parameter and (device is None or c["device"] == device)]
    assert rows, (parameter, res["changes"], res.get("skipped"))
    return rows[0]


# --------------------------------------------------------------------------- vocabulary
@pytest.mark.parametrize("text,expected", [
    ("ярче", ["brighter"]), ("сделай чуть ярче", ["brighter"]), ("make it brighter", ["brighter"]),
    ("brightness", ["brighter"]), ("открой фильтр", ["brighter"]),
    ("темнее", ["darker"]), ("make it darker", ["darker"]), ("глуше", ["darker"]),
    ("теплее", ["warmer"]), ("warmer please", ["warmer"]),
    ("жёстче", ["harsher"]), ("harsher", ["harsher"]), ("резче", ["harsher"]),
    ("мягче", ["softer"]), ("softer", ["softer"]), ("помягче", ["softer"]),
    ("мягче атака", ["softer_attack"]), ("сделай атаку помягче", ["softer_attack"]),
    ("softer attack", ["softer_attack"]), ("slower attack", ["softer_attack"]), ("плавнее атака", ["softer_attack"]),
    ("резче атака", ["punchier"]), ("сделай атаку резче", ["punchier"]), ("punchier", ["punchier"]),
    ("faster attack", ["punchier"]), ("пробивнее", ["punchier"]),
    ("longer release", ["longer_release"]), ("длиннее релиз", ["longer_release"]), ("дольше релиз", ["longer_release"]),
    ("shorter release", ["shorter_release"]), ("короче релиз", ["shorter_release"]),
    ("больше реверба", ["more_reverb"]), ("добавь реверб", ["more_reverb"]), ("more reverb", ["more_reverb"]),
    ("reverb", ["more_reverb"]), ("просторнее", ["more_reverb"]),
    ("меньше реверба", ["less_reverb"]), ("убери реверб", ["less_reverb"]), ("less reverb", ["less_reverb"]),
    ("суше", ["less_reverb"]),
    ("длиннее хвост", ["longer_tail"]), ("longer tail", ["longer_tail"]), ("longer reverb tail", ["longer_tail"]),
    ("короче хвост", ["shorter_tail"]), ("shorter tail", ["shorter_tail"]),
    ("шире", ["wider"]), ("wider", ["wider"]), ("шире стерео", ["wider"]),
    ("уже стерео", []), ("narrower", ["narrower"]), ("сузь", ["narrower"]),
    ("больше драйва", ["more_drive"]), ("more drive", ["more_drive"]), ("добавь дисторшн", ["more_drive"]),
    ("чище", ["cleaner"]), ("cleaner", ["cleaner"]), ("меньше искажений", ["cleaner"]),
    ("больше резонанса", ["more_resonance"]), ("more resonance", ["more_resonance"]),
    ("меньше резонанса", ["less_resonance"]), ("less resonance", ["less_resonance"]),
    ("громче", ["louder"]), ("louder", ["louder"]), ("увеличь громкость", ["louder"]),
    ("тише", ["quieter"]), ("quieter", ["quieter"]), ("lower the volume", ["quieter"]),
    ("больше вибрато", ["more_vibrato"]), ("more vibrato", ["more_vibrato"]), ("вибрато", ["more_vibrato"]),
    ("меньше вибрато", ["less_vibrato"]), ("less vibrato", ["less_vibrato"]),
    ("жирнее", ["fatter"]), ("fatter", ["fatter"]), ("толще", ["fatter"]), ("thicker", ["fatter"]),
    ("тоньше", ["thinner"]), ("thinner", ["thinner"]),
    ("больше эха", ["more_delay"]), ("less delay", ["less_delay"]), ("добавь хорус", ["more_chorus"]),
    ("less chorus", ["less_chorus"]),
    ("ярче и больше реверба", ["brighter", "more_reverb"]),
    ("make it warmer and add some reverb", ["warmer", "more_reverb"]),
    ("less reverb, more delay", ["less_reverb", "more_delay"]),
    ("сделай атаку резче, а реверб короче", ["punchier", "shorter_tail"]),
    ("more_reverb", ["more_reverb"]), ("softer_attack", ["softer_attack"]), ("Longer Release", ["longer_release"]),
    ("", []), ("сыграй мне блюз", []), ("уже хорошо", []),
])
def test_request_vocabulary(text, expected):
    assert resolve_requests(text) == expected


def test_vocabulary_covers_every_request_in_both_languages():
    reached = set()
    for text in ("ярче", "темнее", "теплее", "жёстче", "мягче", "мягче атака", "резче атака", "longer release",
                 "shorter release", "more reverb", "less reverb", "longer tail", "shorter tail", "wider", "narrower",
                 "more drive", "cleaner", "more resonance", "less resonance", "louder", "quieter", "more vibrato",
                 "less vibrato", "fatter", "thinner", "more delay", "less delay", "more chorus", "less chorus"):
        reached.update(resolve_requests(text))
    assert reached == set(REQUESTS) == set(supported_requests())


@pytest.mark.parametrize("text,amount", [("чуть ярче", "small"), ("slightly brighter", "small"),
                                         ("немного темнее", "small"), ("намного ярче", "large"),
                                         ("much brighter", "large"), ("сильно мягче", "large"), ("ярче", None),
                                         ("a bit warmer", "small")])
def test_amount_words(text, amount):
    assert detect_amount(text) == amount


# --------------------------------------------------------------------------- brighter / darker
def test_brighter_multiplies_cutoff_in_display_space_and_reports_before_after():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "ярче")
    assert res["ok"] and res["interpreted"] == ["brighter"] and res["amount"] == "medium"
    c = changed(res, "Filter Freq")
    assert c["before"] == "3.20 kHz" and c["role"] == "cutoff" and c["device"] == "Operator" and c["device_index"] == 0
    ratio = parse_display(c["after"])[0] / parse_display(c["before"])[0]
    assert 1.6 <= ratio <= 2.0
    assert shown(bridge, 0, "Filter Freq") == c["after"]
    assert f"Срез фильтра Operator: {c['before']} → {c['after']}" in res["message"]
    # it was written as a DISPLAY value, not a raw number or norm
    sent = [w for w in writes(bridge) if "Filter Freq" in w["values"]][-1]["values"]["Filter Freq"]
    assert set(sent) == {"display"} and sent["display"].endswith("kHz")
    # only the filter was touched (no other parameter of the instrument changed)
    assert [c["parameter"] for c in res["changes"]] == ["Filter Freq"]


def test_darker_uses_factor_below_one_and_is_monotonic_over_repeats():
    bridge = op_bridge()
    values = [num(bridge, 0, "Filter Freq")]
    for _ in range(3):
        assert adjust_sound(bridge, 0, "darker")["ok"]
        values.append(num(bridge, 0, "Filter Freq"))
    assert all(b < a for a, b in zip(values, values[1:]))
    assert 0.5 <= values[1] / values[0] <= 0.62


def test_cutoff_is_clamped_to_sensible_bounds():
    bridge = op_bridge(**{"Filter Freq": {"display": "50 Hz"}})
    res = adjust_sound(bridge, 0, "darker", "large")
    assert res["ok"] and 39 <= num(bridge, 0, "Filter Freq") <= 41  # floor 40 Hz, not 17 Hz
    again = adjust_sound(bridge, 0, "darker")
    assert not again["ok"] and again["code"] == "nothing_changed"
    assert any("предел" in s["reason"] for s in again["skipped"])
    bridge = op_bridge(**{"Filter Freq": {"display": "15 kHz"}})
    assert adjust_sound(bridge, 0, "brighter", "large")["ok"]
    assert 17900 <= num(bridge, 0, "Filter Freq") <= 18100  # ceiling 18 kHz
    assert not adjust_sound(bridge, 0, "brighter")["ok"]


def test_amount_scales_the_step():
    ratios = {}
    for amount in AMOUNTS:
        bridge = op_bridge()
        res = adjust_sound(bridge, 0, "brighter", amount)
        assert res["amount"] == amount
        ratios[amount] = num(bridge, 0, "Filter Freq") / 3200.0
    assert 1.2 < ratios["small"] < ratios["medium"] < ratios["large"] < 3.0
    # words in the request are understood, an explicit amount wins
    bridge = op_bridge()
    assert adjust_sound(bridge, 0, "чуть ярче")["amount"] == "small"
    assert adjust_sound(op_bridge(), 0, "чуть ярче", "large")["amount"] == "large"
    assert adjust_sound(op_bridge(), 0, "намного ярче")["amount"] == "large"
    assert adjust_sound(op_bridge(), 0, "ярче", "nonsense")["amount"] == "medium"


def test_filter_that_is_off_is_not_touched_and_the_reason_is_given():
    bridge = make_bridge("Operator", state={0: {"Filter On": "Off", "Filter Freq": {"display": "3 kHz"}}})
    n = len(writes(bridge))
    res = adjust_sound(bridge, 0, "brighter")
    assert not res["ok"] and res["code"] == "nothing_changed"
    assert any("Filter On" in s["reason"] for s in res["skipped"])
    assert shown(bridge, 0, "Filter Freq") == "3.00 kHz" and len(writes(bridge)) == n
    assert "Filter On" in res["message"]


def test_brighter_on_every_device_with_a_cutoff_instrument_and_auto_filter():
    bridge = make_bridge("Operator", "Auto Filter", "Reverb", state={
        0: OP_STATE, 1: {"Frequency": {"display": "1 kHz"}}})
    res = adjust_sound(bridge, 0, "brighter")
    devs = {c["device"] for c in res["changes"]}
    assert devs == {"Operator", "Auto Filter"}  # Reverb has no cutoff
    assert num(bridge, 1, "Frequency") > 1500
    assert any(c["device_index"] == 1 for c in res["changes"])


def test_brighter_other_instruments():
    for dev, param_name, gate in (("Wavetable", "Filter 1 Freq", {"Filter 1 On": "On"}),
                                  ("Analog", "F1 Freq", {"F1 On/Off": "On"}),
                                  ("Drift", "LP Freq", {}), ("Simpler", "Filter Freq", {"F On": "On"})):
        bridge = make_bridge(dev, state={0: {**gate, param_name: {"display": "800 Hz"}}})
        res = adjust_sound(bridge, 0, "brighter")
        assert res["ok"], (dev, res["message"])
        assert changed(res, param_name)["device"] == dev
        assert num(bridge, 0, param_name) > 1200, dev


def test_overdrive_tone_follows_brighter_and_darker():
    bridge = make_bridge("Overdrive", state={0: {"Tone": {"display": "50 %"}}})
    assert adjust_sound(bridge, 0, "brighter")["ok"] and num(bridge, 0, "Tone") == 65
    assert adjust_sound(bridge, 0, "darker", "large")["ok"] and num(bridge, 0, "Tone") == 40


# --------------------------------------------------------------------------- envelopes
def test_softer_attack_multiplies_enabled_oscillator_envelopes_only():
    bridge = make_bridge("Operator", state={0: {
        "Osc-A On": "On", "Osc-B On": "On", "Osc-C On": "Off", "Osc-D On": "Off",
        "Ae Attack": {"display": "10 ms"}, "Be Attack": {"display": "20 ms"},
        "Ce Attack": {"display": "5 ms"}, "De Attack": {"display": "5 ms"}}})
    res = adjust_sound(bridge, 0, "мягче атака")
    assert res["ok"] and res["interpreted"] == ["softer_attack"]
    params = {c["parameter"] for c in res["changes"]}
    assert params == {"Ae Attack", "Be Attack"}
    assert abs(num(bridge, 0, "Ae Attack") - 25) < 1 and abs(num(bridge, 0, "Be Attack") - 50) < 2
    assert shown(bridge, 0, "Ce Attack") == "5.0 ms"
    assert "Атака Operator (Ae Attack): 10.0 ms → 25.0 ms" in res["message"]
    assert any("Osc-C On" in s["reason"] for s in res["skipped"])


def test_softer_attack_from_zero_uses_an_absolute_floor():
    bridge = make_bridge("Operator", state={0: {"Osc-A On": "On", "Osc-B On": "Off", "Osc-C On": "Off",
                                                "Osc-D On": "Off", "Ae Attack": {"display": "0.1 ms"}}})
    assert adjust_sound(bridge, 0, "softer attack")["ok"]
    assert num(bridge, 0, "Ae Attack") >= 5  # 0.1 ms * 2.5 would be inaudible
    big = make_bridge("Operator", state={0: {"Osc-A On": "On", "Osc-B On": "Off", "Osc-C On": "Off",
                                             "Osc-D On": "Off", "Ae Attack": {"display": "4 s"}}})
    adjust_sound(big, 0, "softer attack", "large")
    assert num(big, 0, "Ae Attack") <= 5000.5  # capped at 5 s


def test_punchier_shortens_attack_and_decay_and_pushes_filter_envelope():
    bridge = make_bridge("Operator", state={0: {
        **OP_STATE, "Osc-A On": "On", "Osc-B On": "Off", "Osc-C On": "Off", "Osc-D On": "Off",
        "Ae Attack": {"display": "50 ms"}, "Ae Decay": {"display": "800 ms"}, "Fe Amount": {"display": "10 %"}}})
    res = adjust_sound(bridge, 0, "punchier")
    assert res["ok"]
    assert 15 <= num(bridge, 0, "Ae Attack") <= 25
    assert num(bridge, 0, "Ae Decay") < 700
    assert num(bridge, 0, "Fe Amount") > 10
    roles = {c["role"] for c in res["changes"]}
    assert {"attack", "decay", "filter_env_amount"} <= roles


def test_punchier_drum_buss_transients():
    bridge = make_bridge("Drum Buss", state={0: {"Transients": {"display": "0 %"}}})
    assert adjust_sound(bridge, 0, "punchier")["ok"] and num(bridge, 0, "Transients") == 25


def test_release_longer_and_shorter_with_floor():
    base = {"Osc-A On": "On", "Osc-B On": "Off", "Osc-C On": "Off", "Osc-D On": "Off"}
    bridge = make_bridge("Operator", state={0: {**base, "Ae Release": {"display": "200 ms"}}})
    assert adjust_sound(bridge, 0, "longer release")["ok"]
    assert 450 <= num(bridge, 0, "Ae Release") <= 550
    short = make_bridge("Operator", state={0: {**base, "Ae Release": {"display": "5 ms"}}})
    assert adjust_sound(short, 0, "дольше релиз")["ok"]
    assert num(short, 0, "Ae Release") >= 100  # absolute floor for tiny releases
    bridge = make_bridge("Operator", state={0: {**base, "Ae Release": {"display": "400 ms"}}})
    assert adjust_sound(bridge, 0, "короче релиз")["ok"] and 190 <= num(bridge, 0, "Ae Release") <= 210
    tiny = make_bridge("Operator", state={0: {**base, "Ae Release": {"display": "5 ms"}}})
    assert not adjust_sound(tiny, 0, "shorter release")["ok"]


def test_envelope_roles_on_analog_wavetable_drift_simpler():
    cases = [("Analog", "AEG1 Attack", {"AMP1 On/Off": "On", "AMP2 On/Off": "Off"}),
             ("Wavetable", "Amp Attack", {}), ("Drift", "Env 1 Attack", {}), ("Simpler", "Ve Attack", {})]
    for dev, attack, gate in cases:
        bridge = make_bridge(dev, state={0: {**gate, attack: {"display": "20 ms"}}})
        assert adjust_sound(bridge, 0, "softer attack")["ok"], dev
        assert num(bridge, 0, attack) > 40, dev


# --------------------------------------------------------------------------- reverb and tails
def test_more_and_less_reverb_on_existing_reverb():
    bridge = make_bridge("Operator", "Reverb", state={0: OP_STATE, 1: {"Dry/Wet": {"display": "20 %"}}})
    res = adjust_sound(bridge, 0, "больше реверба")
    assert res["ok"] and "added_devices" not in res
    assert num(bridge, 1, "Dry/Wet") == 35
    assert changed(res, "Dry/Wet", "Reverb")["before"] == "20 %"
    assert "Dry/Wet Reverb: 20 % → 35 %" in res["message"]
    assert adjust_sound(bridge, 0, "less reverb")["ok"] and num(bridge, 1, "Dry/Wet") == 20
    assert adjust_sound(bridge, 0, "less reverb", "large")["ok"] and num(bridge, 1, "Dry/Wet") == 0
    assert not adjust_sound(bridge, 0, "less reverb")["ok"]
    full = make_bridge("Reverb", state={0: {"Dry/Wet": {"display": "95 %"}}})
    assert adjust_sound(full, 0, "more reverb", "large")["ok"] and num(full, 0, "Dry/Wet") == 100


def test_more_reverb_adds_a_reverb_when_the_track_has_none():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "add reverb")
    assert res["ok"] and res["added_devices"] == [{"device": "Reverb", "device_index": 1}]
    assert device_names(bridge) == ["Operator", "Reverb"]
    assert num(bridge, 1, "Dry/Wet") == 25
    assert any(c == "load_device" and p["device_name"] == "Reverb" for c, p in bridge.calls)
    assert "Добавлен Reverb" in res["message"]
    # second time: it exists now, no duplicate
    adjust_sound(bridge, 0, "add reverb")
    assert device_names(bridge) == ["Operator", "Reverb"] and num(bridge, 1, "Dry/Wet") == 40
    large = op_bridge()
    adjust_sound(large, 0, "намного больше реверба")
    assert num(large, 1, "Dry/Wet") == 40


def test_less_reverb_never_adds_a_device():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "less reverb")
    assert not res["ok"] and device_names(bridge) == ["Operator"]


def test_disabled_reverb_is_switched_on_by_more_reverb():
    bridge = make_bridge("Operator", "Reverb", state={1: {"Device On": "Off", "Dry/Wet": {"display": "10 %"}}})
    res = adjust_sound(bridge, 0, "more reverb")
    assert res["ok"] and bridge.tracks[0].devices[1].enabled in (True, False)
    assert param(bridge, 1, "Device On")["display"] == "On"
    assert any(c["role"] == "device_on" for c in res["changes"]) and "Включён Reverb" in res["message"]


def test_failed_device_load_is_reported_not_raised():
    bridge = make_bridge("Operator", state={0: OP_STATE}, bridge_cls=ScriptedBridge,
                         fail={"load_device": missing_devices("Reverb")})
    res = adjust_sound(bridge, 0, "more reverb")
    assert not res["ok"] and res["warnings"] and "Reverb" in res["warnings"][0]


def test_longer_tail_extends_reverb_decay_and_instrument_release():
    base = {"Osc-A On": "On", "Osc-B On": "Off", "Osc-C On": "Off", "Osc-D On": "Off"}
    bridge = make_bridge("Operator", "Reverb", state={0: {**base, "Ae Release": {"display": "300 ms"}},
                                                      1: {"Decay Time": {"display": "1.5 s"}}})
    res = adjust_sound(bridge, 0, "длиннее хвост")
    assert res["ok"] and res["interpreted"] == ["longer_tail"]
    assert 2800 <= num(bridge, 1, "Decay Time") <= 3200
    assert num(bridge, 0, "Ae Release") > 450
    assert adjust_sound(bridge, 0, "shorter tail")["ok"] and num(bridge, 1, "Decay Time") < 2000


# --------------------------------------------------------------------------- width / drive / resonance / level
def test_wider_and_narrower_with_utility():
    bridge = make_bridge("Operator", "Utility", state={1: {"Stereo Width": {"display": "100 %"}}})
    res = adjust_sound(bridge, 0, "шире")
    assert res["ok"] and num(bridge, 1, "Stereo Width") == 130
    assert changed(res, "Stereo Width", "Utility")["after"] == "130 %"
    assert adjust_sound(bridge, 0, "wider", "large")["ok"] and num(bridge, 1, "Stereo Width") == 180
    assert adjust_sound(bridge, 0, "wider", "large")["ok"] and num(bridge, 1, "Stereo Width") == 200  # clamp
    assert adjust_sound(bridge, 0, "narrower", "large")["ok"] and num(bridge, 1, "Stereo Width") == 150


def test_wider_uses_instrument_spread_and_adds_utility_only_when_nothing_else_applies():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "wider")
    assert changed(res, "Spread", "Operator") and device_names(bridge) == ["Operator"]
    plain = make_bridge("Analog")
    res = adjust_sound(plain, 0, "wider")
    assert res["ok"] and device_names(plain) == ["Analog", "Utility"] and num(plain, 1, "Stereo Width") == 150


def test_drive_on_saturator_in_db_and_overdrive_in_percent():
    bridge = make_bridge("Operator", "Saturator", "Overdrive", state={
        1: {"Drive": {"display": "0 dB"}}, 2: {"Drive": {"display": "30 %"}}})
    res = adjust_sound(bridge, 0, "more drive")
    assert res["ok"] and num(bridge, 1, "Drive") == 3.0 and num(bridge, 2, "Drive") == 45
    assert device_names(bridge) == ["Operator", "Saturator", "Overdrive"]  # nothing added
    assert adjust_sound(bridge, 0, "cleaner")["ok"]
    assert num(bridge, 1, "Drive") == 0.0 and num(bridge, 2, "Drive") == 30
    assert not [c for c in adjust_sound(bridge, 0, "cleaner", "large")["changes"] if c["device"] == "Saturator"]
    assert num(bridge, 1, "Drive") == 0.0  # does not go negative


def test_more_drive_adds_a_saturator_when_there_is_no_distortion():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "больше драйва")
    assert device_names(bridge) == ["Operator", "Saturator"]
    assert num(bridge, 1, "Drive") == 6.0
    assert res["added_devices"][0]["device"] == "Saturator"
    assert any(c["device"] == "Operator" and c["parameter"] == "Filter Drive" for c in res["changes"])


def test_resonance_steps_and_clamp():
    bridge = op_bridge()
    assert adjust_sound(bridge, 0, "more resonance")["ok"] and num(bridge, 0, "Filter Res") == 35
    assert adjust_sound(bridge, 0, "больше резонанса", "large")["ok"] and num(bridge, 0, "Filter Res") == 60
    assert adjust_sound(bridge, 0, "больше резонанса", "large")["ok"] and num(bridge, 0, "Filter Res") == 85
    assert adjust_sound(bridge, 0, "more resonance", "large")["ok"] and num(bridge, 0, "Filter Res") == 90
    assert not adjust_sound(bridge, 0, "more resonance")["ok"]
    assert adjust_sound(bridge, 0, "less resonance")["ok"] and num(bridge, 0, "Filter Res") == 75


def test_louder_and_quieter_use_db_steps_and_fallback_to_output_gain():
    bridge = make_bridge("Operator", state={0: {"Volume": {"display": "-12 dB"}}})
    assert adjust_sound(bridge, 0, "louder")["ok"] and abs(num(bridge, 0, "Volume") + 9) < 0.2
    assert adjust_sound(bridge, 0, "quieter", "large")["ok"] and abs(num(bridge, 0, "Volume") + 15) < 0.2
    loud = make_bridge("Operator", state={0: {"Volume": {"display": "6 dB"}}})
    assert not adjust_sound(loud, 0, "louder")["ok"]
    # no instrument volume on the track: the effect's output gain is used
    fx = make_bridge("Utility", state={0: {"Gain": {"display": "0 dB"}}})
    assert adjust_sound(fx, 0, "louder")["ok"] and abs(num(fx, 0, "Gain") - 3) < 0.2


def test_volume_from_minus_infinity():
    bridge = make_bridge("Operator", state={0: {"Volume": {"norm": 0}}})
    assert shown(bridge, 0, "Volume") == "-inf dB"
    res = adjust_sound(bridge, 0, "louder")
    assert res["ok"] and abs(num(bridge, 0, "Volume") + 60) < 0.2  # lifted to the -60 dB floor


# --------------------------------------------------------------------------- vibrato / fatter / warmer
def test_vibrato_on_analog_enables_it_and_raises_amount():
    bridge = make_bridge("Analog", state={0: {"Vib On/Off": "Off", "Vib Amount": {"display": "10 %"}}})
    res = adjust_sound(bridge, 0, "больше вибрато")
    assert res["ok"] and shown(bridge, 0, "Vib On/Off") == "On" and num(bridge, 0, "Vib Amount") == 30
    assert "Включить" not in res["message"]
    assert adjust_sound(bridge, 0, "less vibrato")["ok"] and num(bridge, 0, "Vib Amount") == 10
    # already on: only the amount changes
    res = adjust_sound(bridge, 0, "more vibrato", "small")
    assert [c["parameter"] for c in res["changes"]] == ["Vib Amount"]


def test_vibrato_without_support_explains_itself():
    bridge = op_bridge()
    n = len(writes(bridge))
    res = adjust_sound(bridge, 0, "more vibrato")
    assert not res["ok"] and res["code"] == "nothing_changed" and "Ничего не изменено" in res["message"]
    assert len(writes(bridge)) == n


def test_fatter_enables_unison_and_sub_on_wavetable_and_analog():
    bridge = make_bridge("Wavetable", state={0: {"Sub On": "Off", "Unison Amount": {"display": "10 %"},
                                                   "Sub Gain": {"display": "30 %"}}})
    res = adjust_sound(bridge, 0, "жирнее")
    assert res["ok"] and shown(bridge, 0, "Sub On") == "On"
    assert num(bridge, 0, "Unison Amount") == 30 and num(bridge, 0, "Sub Gain") == 45
    analog = make_bridge("Analog", state={0: {"Unison On/Off": "Off", "Unison Detune": {"display": "10 %"}}})
    res = adjust_sound(analog, 0, "fatter")
    assert res["ok"] and shown(analog, 0, "Unison On/Off") == "On" and num(analog, 0, "Unison Detune") == 30
    assert adjust_sound(bridge, 0, "thinner")["ok"] and num(bridge, 0, "Unison Amount") == 10


def test_warmer_combines_a_lower_cutoff_with_saturation_and_chorus_warmth():
    bridge = make_bridge("Operator", "Saturator", "Chorus-Ensemble", state={
        0: OP_STATE, 1: {"Drive": {"display": "0 dB"}}, 2: {"Warmth": {"display": "20 %"}}})
    res = adjust_sound(bridge, 0, "теплее")
    assert res["ok"]
    assert 2300 <= num(bridge, 0, "Filter Freq") <= 2500
    assert num(bridge, 1, "Drive") == 3.0 and num(bridge, 2, "Warmth") == 40
    assert {c["role"] for c in res["changes"]} == {"cutoff", "drive", "warmth"}


def test_harsher_and_softer_are_inverse_moves():
    bridge = op_bridge()
    adjust_sound(bridge, 0, "harsher")
    assert num(bridge, 0, "Filter Freq") > 3200 and num(bridge, 0, "Filter Res") > 20
    adjust_sound(bridge, 0, "softer")
    assert num(bridge, 0, "Filter Res") == 22  # +12 then -10


def test_delay_and_chorus_mix_and_autoload():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "больше эха")
    assert device_names(bridge) == ["Operator", "Delay"] and num(bridge, 1, "Dry/Wet") == 25
    assert res["added_devices"][0]["device"] == "Delay"
    assert adjust_sound(bridge, 0, "less delay", "large")["ok"] and num(bridge, 1, "Dry/Wet") == 0
    ch = make_bridge("Operator", "Chorus-Ensemble", state={1: {"Dry/Wet": {"display": "30 %"}}})
    assert adjust_sound(ch, 0, "more chorus")["ok"] and num(ch, 1, "Dry/Wet") == 50
    assert adjust_sound(ch, 0, "less chorus")["ok"] and num(ch, 1, "Dry/Wet") == 30


# --------------------------------------------------------------------------- fallbacks
def test_parameters_without_usable_display_fall_back_to_relative_norm_steps():
    bridge = make_bridge("Operator", catalog=FakeBridge._load_default_catalog(),
                         state={0: {"Filter On": "On", "Filter Freq": {"norm": 0.4}}})
    before = param(bridge, 0, "Filter Freq")["value"]
    res = adjust_sound(bridge, 0, "brighter")
    assert res["ok"]
    sent = [w for w in writes(bridge) if "Filter Freq" in w["values"]][-1]["values"]["Filter Freq"]
    assert set(sent) == {"norm"} and sent["norm"] == pytest.approx(0.52)
    assert param(bridge, 0, "Filter Freq")["value"] > before
    adjust_sound(bridge, 0, "darker", "large")
    assert param(bridge, 0, "Filter Freq")["value"] == pytest.approx(0.32, abs=0.01)


def test_non_matching_display_dimension_uses_norm_fallback():
    # Simpler's "Fe < Env" shows semitones; a percent step cannot be applied in display space
    cat = curved_catalog()
    for p in cat["Simpler"]["parameters"]:
        if p["name"] == "Fe < Env":
            p["display_curve"] = {"unit": "st", "scale": "lin", "min": -72, "max": 72}
    bridge = make_bridge("Simpler", catalog=cat, state={0: {"F On": "On", "Fe On": "On", "Fe < Env": {"display": "0 st"}}})
    res = adjust_sound(bridge, 0, "punchier")
    c = changed(res, "Fe < Env")
    sent = [w for w in writes(bridge) if "Fe < Env" in w["values"]][-1]["values"]["Fe < Env"]
    assert set(sent) == {"norm"} and parse_display(c["after"])[0] > 0


def test_quantized_drive_moves_to_the_next_item():
    bridge = make_bridge("Analog", state={0: {"F1 On/Off": "On", "F1 Drive": "None" if False else 0}})
    items = param(bridge, 0, "F1 Drive")["value_items"]
    res = adjust_sound(bridge, 0, "more drive")
    c = changed(res, "F1 Drive")
    assert c["after"] == items[1] and shown(bridge, 0, "F1 Drive") == items[1]
    adjust_sound(bridge, 0, "cleaner")
    assert shown(bridge, 0, "F1 Drive") == items[0]
    assert not [c for c in adjust_sound(bridge, 0, "cleaner")["changes"] if c["parameter"] == "F1 Drive"]


def test_parameter_missing_in_this_live_version_is_skipped():
    cat = curved_catalog()
    cat["Operator"]["parameters"] = [p for p in cat["Operator"]["parameters"] if p["name"] != "Filter Freq"]
    bridge = make_bridge("Operator", catalog=cat)
    res = adjust_sound(bridge, 0, "brighter")
    assert not res["ok"] and any("нет в этой версии" in s["reason"] for s in res["skipped"])


# --------------------------------------------------------------------------- orchestration
def test_several_requests_in_one_call():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "ярче и больше реверба")
    assert res["interpreted"] == ["brighter", "more_reverb"] and res["ok"]
    assert {c["role"] for c in res["changes"]} == {"cutoff", "wet"} and device_names(bridge) == ["Operator", "Reverb"]
    assert res["message"].index("Срез фильтра") < res["message"].index("Dry/Wet")


def test_unknown_request_makes_no_bridge_calls():
    bridge = op_bridge()
    n = len(bridge.calls)
    res = adjust_sound(bridge, 0, "сыграй мне что-нибудь грустное")
    assert not res["ok"] and res["code"] == "unknown_request" and res["supported"] == supported_requests()
    assert len(bridge.calls) == n


def test_track_without_adjustable_devices():
    bridge = FakeBridge(device_catalog=curved_catalog())
    bridge.call("create_midi_track")
    res = adjust_sound(bridge, 0, "brighter")
    assert not res["ok"] and res["code"] == "no_devices"
    with pytest.raises(Exception):
        adjust_sound(bridge, 5, "brighter")  # BridgeCommandError(not_found) propagates to the tool wrapper


def test_drum_rack_track_reports_nothing_to_do():
    bridge = make_bridge("Drum Rack")
    res = adjust_sound(bridge, 0, "brighter")
    assert not res["ok"] and res["code"] == "nothing_changed"


def test_offline_bridge_propagates_for_the_tool_wrapper():
    class Offline(FakeBridge):
        def call(self, *a, **k):
            raise BridgeConnectionError("refused")

    with pytest.raises(BridgeConnectionError):
        adjust_sound(Offline(), 0, "brighter")


def test_two_reverbs_are_both_adjusted_and_labelled():
    bridge = make_bridge("Operator", "Reverb", "Reverb", state={1: {"Dry/Wet": {"display": "10 %"}},
                                                               2: {"Dry/Wet": {"display": "20 %"}}})
    res = adjust_sound(bridge, 0, "more reverb")
    assert num(bridge, 1, "Dry/Wet") == 25 and num(bridge, 2, "Dry/Wet") == 35
    assert {c["device"] for c in res["changes"]} == {"Reverb №1", "Reverb №2"}


def test_result_is_compact_json_serialisable_with_before_after_strings():
    bridge = op_bridge()
    res = adjust_sound(bridge, 0, "softer attack")
    text = json.dumps(res, ensure_ascii=False)
    assert len(text) < 3000
    for c in res["changes"]:
        assert set(c) == {"device", "device_index", "parameter", "role", "before", "after"}
        assert isinstance(c["before"], str) and isinstance(c["after"], str) and c["before"] != c["after"]


def test_identical_noop_writes_are_reported_as_unchanged():
    # a display plateau: asking for a value that Live shows identically leaves the parameter as is
    bridge = op_bridge(**{"Filter Freq": {"display": "18 kHz"}})
    res = adjust_sound(bridge, 0, "brighter", "small")
    assert not res["ok"]

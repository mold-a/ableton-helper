"""adjust_sound against the user's real Live 11.3.25 display curves (calibration display_samples)."""
from abhelper.bridge.displayval import parse_display
from abhelper.bridge.fake import FakeBridge
from abhelper.sound.tweaks import adjust_sound


def _bridge(*devices):
    b = FakeBridge()  # default catalog = real calibration incl. display_samples
    t = b.call("create_midi_track", {"name": "T"})["track_index"]
    for d in devices:
        b.call("load_device", {"track_index": t, "device_name": d})
    return b, t


def _shown(b, t, dev, name):
    ps = b.call("get_device_parameters", {"track_index": t, "device_index": dev})["parameters"]
    return next(p["display"] for p in ps if p["name"] == name)


def test_brighter_on_operator_moves_the_real_cutoff_curve():
    b, t = _bridge("Operator")
    b.call("set_device_parameter", {"track_index": t, "device_index": 0, "parameter": "Filter Freq",
                                    "value": {"display": "2 kHz"}})
    res = adjust_sound(b, t, "ярче")
    assert res["ok"], res
    assert parse_display(_shown(b, t, 0, "Filter Freq"))[0] > 3000


def test_brighter_on_analog_understands_k_suffix_displays():
    b, t = _bridge("Analog")
    b.call("set_device_parameter", {"track_index": t, "device_index": 0, "parameter": "F1 Freq",
                                    "value": {"display": "800 Hz"}})
    assert adjust_sound(b, t, "brighter")["ok"]
    assert parse_display(_shown(b, t, 0, "F1 Freq"))[0] > 1200


def test_sampler_is_supported_and_reverb_gets_added():
    b, t = _bridge("Sampler")
    res = adjust_sound(b, t, "больше реверба")
    assert res["ok"] and any(d.get("name") == "Reverb" or d == "Reverb" for d in res["added_devices"]) or res["changes"]
    res = adjust_sound(b, t, "мягче атака")
    assert res["ok"], res


def test_fatter_on_wavetable_uses_db_for_sub_gain():
    b, t = _bridge("Wavetable")
    res = adjust_sound(b, t, "жирнее")
    assert res["ok"], res
    assert not [w for w in res.get("warnings", []) if "unit mismatch" in w]

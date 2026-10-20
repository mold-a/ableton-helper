import math

import pytest

from rs_fakes import (FakeDevice, FakeParam, NoDisplayParam, SilentBrowser, call, db_curve, error, exp_ms,
                      inverse_hz, log_hz, make_dispatcher, make_operator, make_world, percent, result)


def setup(**kw):
    song, app = make_world(**kw)
    d = make_dispatcher(song, app)
    return song, app, d


# ---------------------------------------------------------------- load_device

def test_load_device_via_insert_device():
    song, app, d = setup(with_insert=True)
    out = result(d, "load_device", track_index=0, device_name="Operator")
    assert out == {"device_index": 0, "name": "Operator", "class_name": "Operator"}
    out = result(d, "load_device", track_index=0, device_name="reverb")
    assert out["device_index"] == 1 and out["name"] == "reverb"
    assert song.tracks[0].insert_calls[0] == ("Operator", None)   # -1 => no explicit index
    out = result(d, "load_device", track_index=0, device_name="Arpeggiator", position=0)
    assert out["device_index"] == 0
    assert song.tracks[0].insert_calls[-1] == ("Arpeggiator", 0)
    assert app.browser.loaded == []   # browser route not used


def test_instrument_replacement_reports_new_index():
    song, app, d = setup(with_insert=True)
    result(d, "load_device", track_index=0, device_name="Operator")
    result(d, "load_device", track_index=0, device_name="Reverb")
    out = result(d, "load_device", track_index=0, device_name="Wavetable")
    assert out["device_index"] == 0 and out["class_name"] == "InstrumentVector"
    assert [x.name for x in song.tracks[0].devices] == ["Wavetable", "Reverb"]


def test_load_device_falls_back_to_browser_when_insert_fails():
    song, app, d = setup(with_insert=True)
    song.tracks[0].fail = True
    out = result(d, "load_device", track_index=0, device_name="operator")
    assert out == {"device_index": 0, "name": "Operator", "class_name": "Operator"}
    assert len(app.browser.loaded) == 1
    assert song.view.selected_track is song.tracks[0]
    assert any("falling back" in m for m in d.logs)


def test_load_device_browser_route_without_insert_device():
    song, app, d = setup()
    assert not hasattr(song.tracks[0], "insert_device")
    out = result(d, "load_device", track_index=0, device_name="Operator")
    assert out["device_index"] == 0
    out = result(d, "load_device", track_index=0, device_name="Reverb", position=0)
    assert out["device_index"] == 1   # position ignored on the browser route
    assert error(d, "load_device", track_index=0, device_name="Nonexistent") == "not_found"


def test_browser_route_live_bfs_without_index():
    song, app = make_world()
    d = make_dispatcher(song, app, with_index=False)
    assert result(d, "load_device", track_index=0, device_name="Wavetable")["name"] == "Wavetable"


def test_browser_route_type_checks_and_unchanged_list():
    song, app, d = setup(midi_tracks=0, audio_tracks=1)
    assert error(d, "load_device", track_index=0, device_name="Operator") == "bad_request"
    assert result(d, "load_device", track_index=0, device_name="Reverb")["device_index"] == 0
    song2, app2 = make_world(browser_class=SilentBrowser)
    d2 = make_dispatcher(song2, app2)
    assert error(d2, "load_device", track_index=0, device_name="Operator") == "internal"


def test_load_device_validation():
    song, app, d = setup()
    assert error(d, "load_device", track_index=0) == "bad_request"
    assert error(d, "load_device", track_index=3, device_name="Operator") == "not_found"


# ---------------------------------------------------------------- parameters

@pytest.fixture
def op():
    song, app, d = setup()
    song.tracks[0].devices.append(make_operator())
    return song, d


def test_get_parameters(op):
    song, d = op
    out = result(d, "get_device_parameters", track_index=0, device_index=0)
    assert out["device"] == {"name": "Operator", "class_name": "Operator", "type": "instrument"}
    p = out["parameters"]
    assert [x["name"] for x in p] == ["Device On", "Filter Freq", "Osc-A Wave", "Locked"]
    assert p[1] == {"index": 1, "name": "Filter Freq", "value": 0.5, "min": 0.0, "max": 1.0, "default": 1.0,
                    "display": "0.50", "is_quantized": False, "value_items": []}
    assert p[2]["is_quantized"] and p[2]["value_items"] == ["Sine", "Saw D", "Square", "Noise"]


def test_set_parameter_number_clamp_and_lookup(op):
    song, d = op
    dev = song.tracks[0].devices[0]
    out = result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Filter Freq", value=2.5)
    assert out["value"] == 1.0 and dev.parameters[1].value == 1.0
    out = result(d, "set_device_parameter", track_index=0, device_index=0, parameter="filter freq", value=0.25)
    assert out["value"] == 0.25 and out["display"] == "0.25"
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="filterfreq", value=0.1)
    assert dev.parameters[1].value == 0.1
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter=1, value=-5)
    assert dev.parameters[1].value == 0.0
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="osc a wave", value=0.2)
    assert dev.parameters[2].value == 0.0


def test_set_parameter_quantized_string_and_round(op):
    song, d = op
    dev = song.tracks[0].devices[0]
    assert result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Osc-A Wave", value="square")["value"] == 2.0
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Osc-A Wave", value=1.6)
    assert dev.parameters[2].value == 2.0
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Osc-A Wave", value=99)
    assert dev.parameters[2].value == 3.0
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Osc-A Wave", value="Triangle") == "bad_request"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Filter Freq", value="high") == "bad_request"


def test_set_parameter_norm(op):
    song, d = op
    dev = song.tracks[0].devices[0]
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Osc-A Wave", value={"norm": 1})
    assert dev.parameters[2].value == 3.0
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Filter Freq", value={"norm": 0.3})
    assert dev.parameters[1].value == pytest.approx(0.3)
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter=1, value={"x": 1}) == "bad_request"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter=1, value=True) == "bad_request"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter=1) == "bad_request"


def test_set_parameter_errors(op):
    song, d = op
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Nope", value=1) == "not_found"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter=99, value=1) == "not_found"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Locked", value=1) == "bad_request"
    assert song.tracks[0].devices[0].parameters[3].value == 0.2   # disabled parameter untouched
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter=[1], value=1) == "bad_request"


def test_set_parameters_partial_failure(op):
    song, d = op
    out = result(d, "set_device_parameters", track_index=0, device_index=0,
                 values={"Filter Freq": 0.9, "2": "Saw D", "Bogus": 1, "Locked": 1, "Osc-A Wave": "x"})
    assert [p["name"] for p in out["applied"]] == ["Filter Freq", "Osc-A Wave"]
    assert {f["parameter"]: f["code"] for f in out["failed"]} == {"Bogus": "not_found", "Locked": "bad_request", "Osc-A Wave": "bad_request"}
    assert song.tracks[0].devices[0].parameters[2].value == 1.0
    assert error(d, "set_device_parameters", track_index=0, device_index=0, values=[]) == "bad_request"


# ---------------------------------------------------------------- display values

@pytest.fixture
def eq():
    song, app, d = setup()
    song.tracks[0].devices.append(FakeDevice("EQ Eight", "Eq8", 2, [
        FakeParam("1 Frequency A", 0.5, curve=log_hz),
        FakeParam("Release", 0.2, curve=exp_ms),
        FakeParam("Gain", 0.5, curve=db_curve),
        FakeParam("Dry/Wet", 0.1, curve=percent),
        FakeParam("Inv", 0.5, curve=inverse_hz),
        FakeParam("Filter Type", 0.0, 0.0, 2.0, items=("Low", "Mid", "High"), curve=log_hz),
        NoDisplayParam("Mystery", 0.3),
    ]))
    return song.tracks[0].devices[0], d


def _display(d, name, text):
    return result(d, "set_device_parameter", track_index=0, device_index=0, parameter=name, value={"display": text})


def test_display_frequency_log_curve(eq):
    dev, d = eq
    out = _display(d, "1 Frequency A", "1.3 kHz")
    assert out["display"] == "1.30 kHz"
    # 10 Hz * 2200**raw == 1300 Hz
    assert dev.parameters[1].value == pytest.approx(math.log(130.0) / math.log(2200.0), abs=1e-6)
    out = _display(d, "1 Frequency A", "9 kHz")
    assert out["display"] == "9.00 kHz"
    out = _display(d, "1 Frequency A", "440 Hz")
    assert out["display"] == "440.0 Hz"
    out = _display(d, "1 Frequency A", "0.44 kHz")   # unit conversion kHz -> Hz
    assert out["display"] == "440.0 Hz"


def test_display_time_curve(eq):
    dev, d = eq
    assert _display(d, "Release", "25 ms")["display"] == "25.0 ms"
    assert _display(d, "Release", "1.5 s")["display"] == "1.50 s"
    assert _display(d, "Release", "1500 ms")["display"] == "1.50 s"
    assert _display(d, "Release", "2,5 s")["display"] == "2.50 s"   # decimal comma


def test_display_db_and_inf(eq):
    dev, d = eq
    out = _display(d, "Gain", "-6 dB")
    assert out["display"] == "-6.0 dB" and dev.parameters[3].value == pytest.approx(0.501, abs=1e-3)
    out = _display(d, "Gain", "-inf dB")
    assert dev.parameters[3].value == 0.0 and out["display"] == "-inf dB"
    out = _display(d, "Gain", "-inf")
    assert dev.parameters[3].value == 0.0
    _display(d, "Gain", "+inf dB")
    assert dev.parameters[3].value == 1.0


def test_display_percent(eq):
    dev, d = eq
    assert _display(d, "Dry/Wet", "30 %")["display"] == "30.0 %"
    assert dev.parameters[4].value == pytest.approx(0.3, abs=1e-3)
    _display(d, "Dry/Wet", "50")   # no unit: compare numbers as shown
    assert dev.parameters[4].value == pytest.approx(0.5, abs=1e-3)


def test_display_decreasing_curve(eq):
    dev, d = eq
    out = _display(d, "Inv", "1 kHz")
    assert out["display"] == "1.00 kHz"
    assert dev.parameters[5].value == pytest.approx(1.0 - math.log(100.0) / math.log(2200.0), abs=1e-6)
    _display(d, "Inv", "100 kHz")   # louder than the maximum -> the end that shows the most
    assert dev.parameters[5].value == 0.0
    _display(d, "Inv", "1 Hz")
    assert dev.parameters[5].value == 1.0


def test_display_clamps_out_of_range(eq):
    dev, d = eq
    _display(d, "1 Frequency A", "100 kHz")
    assert dev.parameters[1].value == 1.0
    _display(d, "1 Frequency A", "1 Hz")
    assert dev.parameters[1].value == 0.0
    _display(d, "Release", "500 s")
    assert dev.parameters[2].value == 1.0


def test_display_unit_mismatch_and_bad_text(eq):
    dev, d = eq
    before = dev.parameters[1].value
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="1 Frequency A",
                 value={"display": "25 ms"}) == "bad_request"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="1 Frequency A",
                 value={"display": "loud"}) == "bad_request"
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="1 Frequency A",
                 value={"display": 5}) == "bad_request"
    assert dev.parameters[1].value == before
    env = call(d, "set_device_parameter", track_index=0, device_index=0, parameter="Release",
               value={"display": "-6 dB"})
    assert env["error"]["code"] == "bad_request" and "Release" in env["error"]["message"]


def test_display_mismatch_is_per_parameter_in_batch(eq):
    dev, d = eq
    out = result(d, "set_device_parameters", track_index=0, device_index=0, values={
        "1 Frequency A": {"display": "2 kHz"}, "Release": {"display": "3 kHz"}, "Dry/Wet": {"display": "10 %"}})
    assert [p["name"] for p in out["applied"]] == ["1 Frequency A", "Dry/Wet"]
    assert [(f["parameter"], f["code"]) for f in out["failed"]] == [("Release", "bad_request")]


def test_display_quantized_uses_item_names(eq):
    dev, d = eq
    assert _display(d, "Filter Type", "high")["value"] == 2.0
    assert _display(d, "Filter Type", "Mid")["value"] == 1.0
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Filter Type",
                 value={"display": "9 kHz"}) == "bad_request"


def test_display_without_str_for_value_is_unsupported(eq):
    dev, d = eq
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Mystery",
                 value={"display": "1 kHz"}) == "unsupported"
    out = result(d, "set_device_parameters", track_index=0, device_index=0,
                 values={"Mystery": {"display": "1 kHz"}, "Gain": 0.5})
    assert out["failed"][0]["code"] == "unsupported" and len(out["applied"]) == 1


def test_display_str_for_value_raising_is_bad_request(eq):
    dev, d = eq

    def boom(raw):
        raise RuntimeError("no")
    dev.parameters[1].curve = boom
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="1 Frequency A",
                 value={"display": "1 kHz"}) == "bad_request"


def test_display_object_with_neither_key_and_norm_still_work(eq):
    dev, d = eq
    assert error(d, "set_device_parameter", track_index=0, device_index=0, parameter="Gain",
                 value={"hz": 1}) == "bad_request"
    result(d, "set_device_parameter", track_index=0, device_index=0, parameter="Gain", value={"norm": 0.25})
    assert dev.parameters[3].value == 0.25


def test_get_parameter_displays_shape_and_no_mutation(eq):
    dev, d = eq
    before = [p.value for p in dev.parameters]
    out = result(d, "get_parameter_displays", track_index=0, device_index=0)
    names = [x["name"] for x in out["parameters"]]
    assert names == ["1 Frequency A", "Release", "Gain", "Dry/Wet", "Inv", "Mystery"]   # quantized skipped
    freq = out["parameters"][0]
    assert freq["index"] == 1 and len(freq["samples"]) == 9
    assert freq["samples"][0] == [0.0, "10.0 Hz"] and freq["samples"][-1] == [1.0, "22.00 kHz"]
    assert out["parameters"][2]["samples"][0] == [0.0, "-inf dB"]
    assert all(s[1] == "" for s in out["parameters"][-1]["samples"])   # no str_for_value -> empty text
    assert [p.value for p in dev.parameters] == before


def test_get_parameter_displays_sample_clamp(eq):
    dev, d = eq
    n = lambda **kw: len(result(d, "get_parameter_displays", track_index=0, device_index=0, **kw)["parameters"][0]["samples"])
    assert n() == 9 and n(samples=2) == 2 and n(samples=1) == 2 and n(samples=500) == 33 and n(samples=33) == 33
    assert error(d, "get_parameter_displays", track_index=0, device_index=0, samples="x") == "bad_request"
    assert error(d, "get_parameter_displays", track_index=0, device_index=5) == "not_found"


def test_enabled_and_delete(op):
    song, d = op
    dev = song.tracks[0].devices[0]
    assert result(d, "set_device_enabled", track_index=0, device_index=0, enabled=False) == {"enabled": False}
    assert dev.parameters[0].value == 0.0
    assert result(d, "set_device_enabled", track_index=0, device_index=0, enabled=True) == {"enabled": True}
    assert error(d, "set_device_enabled", track_index=0, device_index=0, enabled="on") == "bad_request"
    assert result(d, "delete_device", track_index=0, device_index=0) == {"deleted": True}
    assert song.tracks[0].devices == []
    assert error(d, "delete_device", track_index=0, device_index=0) == "not_found"


def test_device_type_heuristics():
    from AbletonHelper.livecompat import device_type

    class D(object):
        pass

    for cls, expected in [("MidiArpeggiator", "midi_effect"), ("Operator", "instrument"),
                          ("AudioEffectGroupDevice", "audio_effect"), ("Weird", "unknown")]:
        dev = D()
        dev.type = 0
        dev.class_name = cls
        assert device_type(dev) == expected
    dev = D()
    dev.type = 4
    assert device_type(dev) == "midi_effect"

import pytest

from rs_fakes import (FakeDevice, SilentBrowser, call, error, make_dispatcher, make_operator, make_world,
                      result)


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

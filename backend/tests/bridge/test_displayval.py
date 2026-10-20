import math

import pytest

from abhelper.bridge import BridgeCommandError
from abhelper.bridge.displayval import DisplayError, parse_display, solve_display
from abhelper.bridge.fake import FakeBridge


@pytest.mark.parametrize("text,value,dim", [
    ("2.53 kHz", 2530.0, "freq"), ("830 Hz", 830.0, "freq"), ("224 ms", 224.0, "time"),
    ("1.20 s", 1200.0, "time"), ("-6.0 dB", -6.0, "level"), ("35 %", 35.0, "percent"),
    ("4.00 : 1", 4.0, "ratio"), ("0.90 Hz", 0.9, "freq"), ("12", 12.0, "number"), ("1,5 kHz", 1500.0, "freq"),
])
def test_parse_display(text, value, dim):
    assert parse_display(text) == (pytest.approx(value), dim)


def test_parse_inf():
    v, dim = parse_display("-inf dB")
    assert v == -math.inf and dim == "level"


def _log_hz(raw):           # 0..1 -> 10 Hz .. 22 kHz, like EQ Eight's frequency
    v = 10 * 2200 ** raw
    return f"{v / 1000:.2f} kHz" if v >= 1000 else f"{v:.0f} Hz"


def test_solve_log_frequency():
    raw = solve_display("1.3 kHz", 0.0, 1.0, _log_hz)
    assert parse_display(_log_hz(raw))[0] == pytest.approx(1300, rel=0.01)
    assert solve_display("5 Hz", 0.0, 1.0, _log_hz) == 0.0          # clamped
    assert solve_display("40 kHz", 0.0, 1.0, _log_hz) == 1.0


def test_solve_decreasing_and_unit_mismatch():
    fmt = lambda raw: f"{(1 - raw) * 100:.0f} %"
    assert solve_display("25 %", 0.0, 1.0, fmt) == pytest.approx(0.75, abs=0.01)
    with pytest.raises(DisplayError):
        solve_display("100 ms", 0.0, 1.0, fmt)


def test_fake_bridge_display_values():
    catalog = {"EQ Eight": {"type": "audio_effect", "parameters": [
        {"name": "3 Frequency A", "min": 0, "max": 1, "default": 0.3,
         "display_curve": {"unit": "Hz", "scale": "log", "min": 10, "max": 22000}},
        {"name": "3 Gain A", "min": -15, "max": 15, "default": 0,
         "display_samples": [[-15, "-15.0 dB"], [15, "15.0 dB"]]},
        {"name": "Mystery", "min": 0, "max": 1, "default": 0},
    ]}}
    b = FakeBridge(device_catalog=catalog)
    t = b.call("create_midi_track")["track_index"]
    d = b.call("load_device", {"track_index": t, "device_name": "EQ Eight"})["device_index"]
    res = b.call("set_device_parameters", {"track_index": t, "device_index": d, "values": {
        "3 Frequency A": {"display": "1.3 kHz"}, "3 Gain A": {"display": "3 dB"}, "Mystery": {"display": "1 kHz"}}})
    assert not res["failed"]
    shown = {p["name"]: p["display"] for p in res["applied"]}
    assert shown["3 Frequency A"].endswith("kHz") and parse_display(shown["3 Frequency A"])[0] == pytest.approx(1300, rel=0.01)
    assert shown["3 Gain A"] == "3.0 dB"
    with pytest.raises(BridgeCommandError):
        b.call("set_device_parameter", {"track_index": t, "device_index": d, "parameter": "3 Gain A",
                                        "value": {"display": "20 ms"}})
    samples = b.call("get_parameter_displays", {"track_index": t, "device_index": d, "samples": 3})["parameters"]
    assert samples[0]["samples"][0] == [0.0, "10.0 Hz"]


# Real Live 11.3.25 displays (user calibration): Analog shows its cutoff without "Hz" and with a "k" suffix.
ANALOG_F1_FREQ = [[0.0, " 30"], [0.125, " 69"], [0.25, "158"], [0.375, "363"], [0.5, "834"], [0.625, "1.9k"],
                  [0.75, "4.3k"], [0.875, "9.7k"], [1.0, "22.0k"]]


def _interp(samples):
    from abhelper.bridge.fake import FakeParam
    return FakeParam(name="x", min=samples[0][0], max=samples[-1][0], display_samples=samples).str_for_value


def test_k_suffix_and_bare_numbers_are_hertz():
    assert parse_display("1.9k") == (pytest.approx(1900.0), "freq")
    fmt = _interp(ANALOG_F1_FREQ)
    raw = solve_display("300 Hz", 0.0, 1.0, fmt)
    assert 0.3 < raw < 0.4 and parse_display(fmt(raw))[0] == pytest.approx(300, rel=0.03)
    raw = solve_display("2.2 kHz", 0.0, 1.0, fmt)
    assert parse_display(fmt(raw))[0] == pytest.approx(2200, rel=0.03)


def test_pan_displays():
    assert parse_display("C") == (0.0, "pan")
    assert parse_display("50L") == (-50.0, "pan") and parse_display("25R") == (25.0, "pan")
    fmt = lambda raw: "C" if abs(raw) < 0.01 else ("%dL" % round(-raw * 50) if raw < 0 else "%dR" % round(raw * 50))
    assert solve_display("25L", -1.0, 1.0, fmt) == pytest.approx(-0.5, abs=0.02)

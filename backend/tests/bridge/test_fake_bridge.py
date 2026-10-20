import pytest

from abhelper.bridge import BridgeCommandError
from abhelper.bridge.fake import FakeBridge


def test_create_track_load_device_and_set_params():
    catalog = {"Operator": {"class_name": "Operator", "type": "instrument", "parameters": [
        {"name": "Filter Freq", "min": 0, "max": 1, "default": 1},
        {"name": "Osc-A Wave", "min": 0, "max": 2, "value_items": ["Sine", "Saw D", "Square D"]},
    ]}}
    b = FakeBridge(device_catalog=catalog)
    t = b.call("create_midi_track", {"name": "Баян"})["track_index"]
    d = b.call("load_device", {"track_index": t, "device_name": "Operator"})["device_index"]
    res = b.call("set_device_parameters", {"track_index": t, "device_index": d, "values": {
        "filter freq": {"norm": 0.5}, "Osc-A Wave": "saw d", "Nope": 1}})
    assert [p["name"] for p in res["applied"]] == ["Filter Freq", "Osc-A Wave"]
    assert res["applied"][1]["display"] == "Saw D"
    assert res["failed"][0]["code"] == "not_found"


def test_clip_notes_and_errors():
    b = FakeBridge()
    t = b.call("create_midi_track")["track_index"]
    s = b.call("create_clip", {"track_index": t, "length": 8})["slot_index"]
    b.call("add_notes", {"track_index": t, "slot_index": s,
                         "notes": [{"pitch": 60, "start": 0, "duration": 1}]})
    assert b.call("get_clip_notes", {"track_index": t, "slot_index": s})["notes"][0]["velocity"] == 100
    with pytest.raises(BridgeCommandError) as e:
        b.call("create_clip", {"track_index": t, "slot_index": s})
    assert e.value.code == "conflict"
    with pytest.raises(BridgeCommandError) as e:
        b.call("load_device", {"track_index": t, "device_name": "Serum 9000"})
    assert e.value.code == "not_found"


def test_browser_search_and_load_and_undo():
    b = FakeBridge()
    t = b.call("create_midi_track")["track_index"]
    items = b.call("browser_search", {"query": "piano grand"})["items"]
    assert items[0]["name"] == "Grand Piano.adg"
    out = b.call("load_browser_item", {"track_index": t, "uri": items[0]["uri"]})
    assert out["devices"][0]["name"] == "Instrument Rack"
    assert b.call("undo")["done"] is True
    assert b.tracks[t].devices == []

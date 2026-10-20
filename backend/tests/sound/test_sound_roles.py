"""device_roles.json is consistent with the real catalog and with the tweak vocabulary."""

import json

import pytest

from abhelper.agent.tools import ToolExecutor
from abhelper.bridge.fake import FakeBridge
from abhelper.sound import roles as roles_mod
from abhelper.sound.roles import RoleBook, filter_parameters, load_roles
from abhelper.sound.tweaks import REQUESTS
from tweak_testkit import CATALOG

CATALOG_DEVICES = json.loads(CATALOG.read_text(encoding="utf-8"))["devices"]
BOOK = load_roles()


def test_every_catalog_device_has_a_roles_entry_and_class_names_match():
    assert set(BOOK.devices) == set(CATALOG_DEVICES)
    for name, dev in BOOK.devices.items():
        assert dev.class_name == CATALOG_DEVICES[name]["class_name"]
        assert dev.kind == ("instrument" if CATALOG_DEVICES[name]["type"] == "instrument" else "effect")


def test_all_role_parameter_names_exist_in_the_real_catalog():
    problems = []
    for name, dev in BOOK.devices.items():
        params = {p["name"]: p for p in CATALOG_DEVICES[name]["parameters"]}
        for role, plist in dev.roles.items():
            assert role in BOOK.labels, f"no label for role {role}"
            for rp in plist:
                if rp.name not in params:
                    problems.append(f"{name}.{role}: {rp.name!r}")
                if rp.when:
                    if rp.when not in params:
                        problems.append(f"{name}.{role}: when {rp.when!r}")
                    elif not params[rp.when]["is_quantized"] or params[rp.when]["value_items"][:2] != ["Off", "On"]:
                        problems.append(f"{name}.{role}: when {rp.when!r} is not an Off/On switch")
    assert not problems, problems


def test_brief_examples():
    op = BOOK.devices["Operator"]
    assert [p.name for p in op.params("cutoff")] == ["Filter Freq"]
    assert [p.name for p in op.params("resonance")] == ["Filter Res"]
    assert [p.name for p in op.params("attack")] == ["Ae Attack", "Be Attack", "Ce Attack", "De Attack"]
    assert [p.name for p in op.params("release")] == ["Ae Release", "Be Release", "Ce Release", "De Release"]
    assert [p.name for p in op.params("filter_env_amount")] == ["Fe Amount"]
    assert [p.name for p in op.params("drive")] == ["Filter Drive"]
    assert [p.name for p in op.params("volume")] == ["Volume"]
    an = BOOK.devices["Analog"]
    assert [p.name for p in an.params("cutoff")] == ["F1 Freq", "F2 Freq"]
    assert [p.name for p in an.params("attack")] == ["AEG1 Attack", "AEG2 Attack"]
    assert [p.name for p in BOOK.devices["Reverb"].params("wet")] == ["Dry/Wet"]
    assert [p.name for p in BOOK.devices["Reverb"].params("decay_time")] == ["Decay Time"]
    assert [p.name for p in BOOK.devices["Utility"].params("width")] == ["Stereo Width"]
    assert BOOK.devices["Saturator"].params("drive")[0].name == "Drive"
    assert BOOK.devices["Delay"].params("wet") and BOOK.devices["Delay"].params("feedback")
    assert BOOK.devices["Chorus-Ensemble"].params("wet")
    for synth in ("Wavetable", "Drift", "Simpler"):
        for role in ("cutoff", "resonance", "attack", "release", "volume"):
            assert BOOK.devices[synth].params(role), (synth, role)


def test_roles_lookup_by_name_class_name_and_alias():
    assert BOOK.get("Operator").name == "Operator"
    assert BOOK.get("operator").name == "Operator"
    assert BOOK.get("My Lead", "UltraAnalog").name == "Analog"
    assert BOOK.get("Chorus").name == "Chorus-Ensemble"
    assert BOOK.get("EQ 8").name == "EQ Eight"
    assert BOOK.get("Serum") is None and BOOK.get(None) is None


def test_priority_names_put_gates_after_their_parameter_and_have_no_duplicates():
    names = BOOK.devices["Operator"].priority_names()
    assert names[0] == "Filter Freq" and "Filter On" in names and "Osc-A On" in names
    assert len(names) == len(set(names))
    assert names.index("Filter On") == 1


def test_every_request_has_a_device_that_supports_its_roles():
    for name, req in REQUESTS.items():
        assert req["ru"]
        for op in req["ops"]:
            roles = op["role"] if isinstance(op["role"], list) else [op["role"]]
            supported = [d for d in BOOK.devices.values() if any(d.params(r) for r in roles)
                         and (not op.get("devices") or d.name in op["devices"])]
            assert supported, f"{name}: nothing supports {roles}"
        auto = req.get("autoload")
        if auto:
            assert auto["device"] in CATALOG_DEVICES and auto["unless"]
            pnames = {p["name"] for p in CATALOG_DEVICES[auto["device"]]["parameters"]}
            assert set(auto["init"]) <= pnames
            assert all(len(v) == 3 for v in auto["init"].values())


def test_roles_for_query_and_filter_parameters():
    assert {"cutoff", "resonance"} <= BOOK.roles_for_query("filter")
    assert BOOK.roles_for_query("attack") == {"attack"}
    assert "release" in BOOK.roles_for_query("envelope")
    rows = [{"name": p["name"]} for p in CATALOG_DEVICES["Analog"]["parameters"]]
    sel, missing = filter_parameters(BOOK, BOOK.devices["Analog"], rows, query="filter")
    assert {"F1 Freq", "F2 Resonance"} <= {r["name"] for r in sel}  # Analog names have no word "filter"
    sel, _ = filter_parameters(BOOK, BOOK.devices["Analog"], rows, query="lfo")
    assert sel and {"LFO1 Speed", "Vib Amount"} <= {r["name"] for r in sel}
    sel, missing = filter_parameters(BOOK, None, rows, names=["volume", "nope"])
    assert [r["name"] for r in sel] == ["Volume"] and missing == ["nope"]


def test_missing_or_broken_file_degrades_gracefully(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json", encoding="utf-8")
    book = roles_mod.load_roles.__wrapped__(str(bad))
    assert isinstance(book, RoleBook) and book.devices == {}
    assert roles_mod.load_roles.__wrapped__(str(tmp_path / "none.json")).devices == {}


def test_unknown_device_in_tool_is_returned_without_roles():
    ex = ToolExecutor(FakeBridge(), None, None)
    ex.bridge.call("create_midi_track")
    ex.bridge.call("load_device", {"track_index": 0, "device_name": "Compressor"})
    r = ex.execute("get_device_parameters", {"track_index": 0, "device_index": 0})
    assert r.ok and not any("role" in p for p in r.data["parameters"] if p["name"] == "Threshold")

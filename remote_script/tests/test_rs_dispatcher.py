import pytest

from AbletonHelper import dispatcher as dp
from rs_fakes import call, error, make_dispatcher, make_world, result


@pytest.fixture
def d():
    song, app = make_world()
    return make_dispatcher(song, app)


def test_envelope_echoes_id_and_ok(d):
    env = d.handle({"id": "42", "command": "ping"})
    assert env["id"] == "42" and env["ok"] is True
    assert env["result"]["pong"] is True
    assert env["result"]["script_version"] == "0.2.0"
    assert env["result"]["live_version"] == "12.1.5"


def test_params_may_be_omitted_and_null(d):
    assert d.handle({"id": "1", "command": "ping", "params": None})["ok"]


@pytest.mark.parametrize("request_obj,code", [
    ({"id": "1"}, "bad_request"),
    ({"id": "1", "command": 5}, "bad_request"),
    ({"id": "1", "command": "ping", "params": [1]}, "bad_request"),
    ({"id": "1", "command": "nope"}, "unknown_command"),
    ("not a dict", "bad_request"),
])
def test_request_errors(d, request_obj, code):
    env = d.handle(request_obj)
    assert env["ok"] is False and env["error"]["code"] == code


def test_missing_and_wrongly_typed_params(d):
    assert error(d, "get_track_info") == "bad_request"
    assert error(d, "get_track_info", track_index="0") == "bad_request"
    assert error(d, "get_track_info", track_index=True) == "bad_request"
    assert error(d, "set_tempo", tempo="fast") == "bad_request"
    assert error(d, "set_tempo", tempo=5) == "bad_request"
    assert error(d, "set_tempo", tempo=1000) == "bad_request"


def test_not_found(d):
    assert error(d, "get_track_info", track_index=7) == "not_found"
    assert error(d, "get_track_info", track_index=-2) == "not_found"
    assert error(d, "get_device_parameters", track_index=0, device_index=3) == "not_found"
    assert error(d, "fire_clip", track_index=0, slot_index=0) == "not_found"


def test_internal_error_is_mapped_and_logged():
    song, app = make_world()
    d = make_dispatcher(song, app)

    def boom(ctx, params):
        raise RuntimeError("kaboom")

    d.commands["boom"] = boom
    env = call(d, "boom")
    assert env["error"] == {"code": "internal", "message": "kaboom"}
    assert any("kaboom" in m for m in d.logs)


def test_command_error_passthrough():
    song, app = make_world()
    d = make_dispatcher(song, app)

    def bad(ctx, params):
        raise dp.CommandError("conflict", "nope")

    d.commands["bad"] = bad
    assert call(d, "bad")["error"] == {"code": "conflict", "message": "nope"}


def test_param_helpers():
    assert dp.get_int({"a": 3.0}, "a") == 3
    assert dp.get_int({}, "a", -1) == -1
    assert dp.get_int({"a": None}, "a", None) is None
    with pytest.raises(dp.CommandError):
        dp.get_int({"a": 1.5}, "a")
    with pytest.raises(dp.CommandError):
        dp.get_int({"a": 99}, "a", maximum=10)
    assert dp.get_number({"a": 2}, "a") == 2.0
    with pytest.raises(dp.CommandError):
        dp.get_number({"a": float("nan")}, "a")
    with pytest.raises(dp.CommandError):
        dp.get_str({"a": "  "}, "a")
    assert dp.get_str({"a": ""}, "a", allow_empty=True) == ""
    with pytest.raises(dp.CommandError):
        dp.get_bool({"a": 1}, "a")
    with pytest.raises(dp.CommandError):
        dp.get_list({"a": {}}, "a")
    with pytest.raises(dp.CommandError):
        dp.get_dict({"a": []}, "a")


def test_no_eval_style_commands(d):
    for name in d.commands:
        assert "eval" not in name and "exec" not in name and "script" not in name


def test_batch_runs_and_stops_on_error(d):
    out = result(d, "batch", commands=[
        {"command": "ping"},
        {"command": "get_track_info", "params": {"track_index": 9}},
        {"command": "ping"},
    ])
    assert [r["ok"] for r in out["results"]] == [True, False]
    assert out["results"][1]["error"]["code"] == "not_found"
    assert "id" not in out["results"][0]


def test_batch_continue_on_error(d):
    out = result(d, "batch", stop_on_error=False, commands=[
        {"command": "nope"}, {"command": "ping"}, {"nocommand": 1}, {"command": "batch", "params": {"commands": []}},
    ])
    codes = [r.get("error", {}).get("code") for r in out["results"]]
    assert codes == ["unknown_command", None, "bad_request", "bad_request"]


def test_batch_sequential_state(d):
    out = result(d, "batch", commands=[
        {"command": "create_midi_track", "params": {"name": "A"}},
        {"command": "create_midi_track", "params": {"name": "B"}},
        {"command": "get_session_info"},
    ])
    assert out["results"][0]["result"]["track_index"] == 1
    assert out["results"][1]["result"]["track_index"] == 2
    assert out["results"][2]["result"]["track_count"] == 3

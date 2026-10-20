import types

import pytest

from abhelper.config import Settings
from abhelper.llm import (
    AnthropicLLM,
    LLMAuthError,
    LLMError,
    ScriptedLLM,
    text_block,
    tool_use_block,
    turn,
)
from abhelper.llm.anthropic_client import block_to_dict


def test_scripted_llm_plays_turns_and_records_calls():
    llm = ScriptedLLM([turn("Привет, мир"), turn(tool_use_block("transport", {"action": "play"}, id="t1"))])
    ev = list(llm.stream("sys", [{"role": "user", "content": "hi"}], []))
    assert [e.type for e in ev] == ["text", "text", "final"]
    assert "".join(e.text for e in ev if e.type == "text") == "Привет, мир"
    assert ev[-1].stop_reason == "end_turn"
    ev2 = list(llm.stream("sys", [], []))
    assert [e.type for e in ev2] == ["final"]
    assert ev2[0].stop_reason == "tool_use" and ev2[0].content[0]["id"] == "t1"
    assert len(llm.calls) == 2 and llm.calls[0]["system"] == "sys"
    with pytest.raises(LLMError):
        list(llm.stream("sys", [], []))


def test_scripted_llm_raises_scripted_exceptions():
    llm = ScriptedLLM([LLMAuthError("bad key")])
    with pytest.raises(LLMAuthError):
        list(llm.stream("s", [], []))


def test_block_to_dict_uses_model_dump():
    class B:
        def model_dump(self, exclude_none=False):
            assert exclude_none
            return {"type": "text", "text": "x"}

    assert block_to_dict(B()) == {"type": "text", "text": "x"}
    assert block_to_dict({"type": "text"}) == {"type": "text"}


def test_build_request_follows_api_rules():
    s = Settings(api_key="k", model="claude-opus-5-5", effort="high", use_fallbacks=True)
    req = AnthropicLLM(s).build_request("SYS", [{"role": "user", "content": "x"}], [{"name": "t"}])
    assert req["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert req["thinking"] == {"type": "adaptive"}
    assert req["output_config"] == {"effort": "high"}
    assert req["betas"] == ["server-side-fallback-2026-07-01"] and req["fallbacks"] == "default"
    for forbidden in ("temperature", "top_p", "tool_choice"):
        assert forbidden not in req
    assert "budget_tokens" not in str(req)
    s.use_fallbacks = False
    req = AnthropicLLM(s).build_request("SYS", [], [])
    assert "betas" not in req and "fallbacks" not in req


def _fake_anthropic_stream(monkeypatch, events=None, error=None, final=None):
    """Patch anthropic.Anthropic with an offline fake (no network)."""
    import anthropic

    class Stream:
        def __enter__(self):
            if error:
                raise error
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(events or [])

        def get_final_message(self):
            return final

    class Client:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: Stream()))

    monkeypatch.setattr(anthropic, "Anthropic", Client)


def _final():
    blk = types.SimpleNamespace(model_dump=lambda exclude_none=False: {"type": "text", "text": "ok"})
    usage = types.SimpleNamespace(model_dump=lambda exclude_none=False: {"input_tokens": 3, "output_tokens": 2})
    return types.SimpleNamespace(content=[blk], stop_reason="end_turn", usage=usage)


def test_anthropic_stream_translates_events(monkeypatch):
    ev = [types.SimpleNamespace(type="text", text="o"), types.SimpleNamespace(type="thinking", thinking="..."),
          types.SimpleNamespace(type="text", text="k")]
    _fake_anthropic_stream(monkeypatch, events=ev, final=_final())
    out = list(AnthropicLLM(Settings(api_key="k")).stream("s", [], []))
    assert [e.type for e in out] == ["text", "text", "final"]
    assert out[-1].content == [{"type": "text", "text": "ok"}]
    assert out[-1].usage == {"input_tokens": 3, "output_tokens": 2}


def _http_error(cls, status):
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req)
    return cls("boom", response=resp, body=None)


@pytest.mark.parametrize("cls_name,status,expected", [
    ("AuthenticationError", 401, "LLMAuthError"),
    ("RateLimitError", 429, "LLMRateLimitError"),
    ("InternalServerError", 500, "LLMStatusError"),
])
def test_anthropic_errors_are_translated(monkeypatch, cls_name, status, expected):
    import anthropic

    from abhelper import llm as llm_pkg

    _fake_anthropic_stream(monkeypatch, error=_http_error(getattr(anthropic, cls_name), status))
    with pytest.raises(getattr(llm_pkg, expected)):
        list(AnthropicLLM(Settings(api_key="k")).stream("s", [], []))


def test_anthropic_connection_error_translated(monkeypatch):
    import anthropic
    import httpx

    from abhelper.llm import LLMConnectionError

    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    _fake_anthropic_stream(monkeypatch, error=err)
    with pytest.raises(LLMConnectionError):
        list(AnthropicLLM(Settings(api_key="k")).stream("s", [], []))

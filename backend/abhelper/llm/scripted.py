"""ScriptedLLM: plays back pre-scripted assistant turns (for tests and offline demos)."""

from __future__ import annotations

import copy
import itertools
from typing import Any, Iterator

from .base import LLMError, LLMStreamEvent

_ids = itertools.count(1)


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def tool_use_block(name: str, input: dict | None = None, id: str | None = None) -> dict:
    return {"type": "tool_use", "id": id or f"toolu_script_{next(_ids)}", "name": name, "input": input or {}}


def turn(*blocks: dict | str, stop_reason: str | None = None, usage: dict | None = None) -> dict:
    """Build a scripted turn. Strings become text blocks. stop_reason is inferred
    (tool_use if any tool_use block, else end_turn) unless given."""
    content = [text_block(b) if isinstance(b, str) else b for b in blocks]
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.get("type") == "tool_use" for b in content) else "end_turn"
    return {"content": content, "stop_reason": stop_reason, "usage": usage or {"input_tokens": 10, "output_tokens": 5}}


class ScriptedLLM:
    """Each ``stream()`` call consumes the next turn. A turn is a dict from :func:`turn`
    or an ``Exception`` instance (raised when reached). Requests are recorded in ``calls``."""

    def __init__(self, turns: list[dict | Exception]):
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def stream(self, system: str, messages: list[dict], tools: list[dict]) -> Iterator[LLMStreamEvent]:
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        if not self.turns:
            raise LLMError("ScriptedLLM: no more scripted turns")
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        content = copy.deepcopy(item["content"])
        for block in content:
            if block.get("type") == "text" and block.get("text"):
                text = block["text"]
                mid = len(text) // 2
                # two chunks, to exercise streaming
                for chunk in (text[:mid], text[mid:]) if mid else (text,):
                    yield LLMStreamEvent(type="text", text=chunk)
        yield LLMStreamEvent(type="final", content=content, stop_reason=item.get("stop_reason", "end_turn"),
                             usage=dict(item.get("usage", {})))

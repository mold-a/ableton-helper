"""LLM client abstraction so the agent loop is testable without network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable


class LLMError(Exception):
    """Base class for LLM failures (translated from provider SDK errors)."""

    code = "llm_error"


class LLMAuthError(LLMError):
    code = "llm_not_configured"


class LLMRateLimitError(LLMError):
    pass


class LLMConnectionError(LLMError):
    pass


class LLMStatusError(LLMError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class LLMStreamEvent:
    """``type == "text"``: a text delta in ``text``.
    ``type == "final"``: the complete assistant message in ``content`` (list of plain-dict
    content blocks), plus ``stop_reason`` and ``usage``."""

    type: str
    text: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    def stream(self, system: str, messages: list[dict], tools: list[dict]) -> Iterator[LLMStreamEvent]:
        """Yield ``text`` events, then exactly one ``final`` event."""
        ...

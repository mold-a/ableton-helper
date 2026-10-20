"""Claude implementation of LLMClient (official ``anthropic`` SDK, streaming)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterator

from .base import (
    LLMAuthError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMStatusError,
    LLMStreamEvent,
)

log = logging.getLogger(__name__)

MAX_TOKENS = 64000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    return block.model_dump(exclude_none=True)


class AnthropicLLM:
    """Reads ``settings`` on every call, so key/model changes made in the UI apply at once."""

    def __init__(self, settings: Any):
        self.settings = settings
        self._client: Any = None
        self._client_key: str | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        import anthropic

        with self._lock:
            if self._client is None or self._client_key != self.settings.api_key:
                self._client = anthropic.Anthropic(api_key=self.settings.api_key)
                self._client_key = self.settings.api_key
            return self._client

    def build_request(self, system: str, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
        s = self.settings
        kwargs: dict[str, Any] = dict(
            model=s.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": s.effort},
        )
        if s.use_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def stream(self, system: str, messages: list[dict], tools: list[dict]) -> Iterator[LLMStreamEvent]:
        import anthropic

        try:
            client = self._get_client()
            with client.beta.messages.stream(**self.build_request(system, messages, tools)) as stream:
                for event in stream:
                    if event.type == "text":
                        yield LLMStreamEvent(type="text", text=event.text)
                final = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMAuthError("Проверьте API-ключ Anthropic.") from e
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError("Превышен лимит запросов к Claude. Подождите минуту и повторите.") from e
        except anthropic.APIStatusError as e:
            raise LLMStatusError(f"Ошибка API Claude ({getattr(e, 'status_code', '?')}): {e}",
                                 getattr(e, "status_code", None)) from e
        except anthropic.APIConnectionError as e:
            raise LLMConnectionError("Нет соединения с API Claude. Проверьте интернет.") from e
        except LLMError:
            raise
        yield LLMStreamEvent(
            type="final",
            content=[block_to_dict(b) for b in final.content],
            stop_reason=final.stop_reason,
            usage=final.usage.model_dump(exclude_none=True) if getattr(final, "usage", None) else {},
        )

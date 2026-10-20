"""Claude tool-use agent: a manual agentic loop with streaming."""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ..llm.base import (
    LLMAuthError,
    LLMClient,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMStatusError,
)
from .conversation import Conversation
from .prompts import SYSTEM_PROMPT
from .tools import ToolExecutor, get_tools

log = logging.getLogger(__name__)

MAX_ITERATIONS = 25

MSG_NOT_CONFIGURED = ("Не задан API-ключ Anthropic. Откройте настройки (⚙) и вставьте ключ "
                      "или впишите ANTHROPIC_API_KEY в файл .env в корне проекта и перезапустите сервер.")
MSG_BAD_KEY = "Проверьте API-ключ Anthropic в настройках: сервер отклонил его."
MSG_REFUSAL = "Модель отказалась отвечать на этот запрос. Попробуйте переформулировать."
MSG_MAX_TOKENS = "Ответ модели оборван из-за лимита длины. Попробуйте сузить запрос."
MSG_TOO_MANY_STEPS = "Слишком много шагов подряд; остановился. Напишите, что сделать дальше."
MSG_BUSY = "Предыдущий запрос в этом диалоге ещё выполняется. Дождитесь ответа."


def _error(message: str, code: str) -> dict[str, Any]:
    return {"type": "error", "message": message, "code": code}


class AssistantAgent:
    def __init__(self, bridge: Any, engine: Any, knowledge: Any, llm: LLMClient, settings: Any,
                 recipe_validator: Any = None):
        self.bridge = bridge
        self.engine = engine
        self.knowledge = knowledge
        self.llm = llm
        self.settings = settings
        self.executor = ToolExecutor(bridge, engine, knowledge, recipe_validator)

    # ------------------------------------------------------------------ public
    def run_turn(self, conversation: Conversation, user_text: str) -> Iterator[dict[str, Any]]:
        if not self.settings.api_key:
            yield _error(MSG_NOT_CONFIGURED, "llm_not_configured")
            return
        if not conversation.try_begin():
            yield _error(MSG_BUSY, "busy")
            return
        start_len = 0
        try:
            conversation.trim()
            start_len = len(conversation.messages)
            conversation.messages.append({"role": "user", "content": user_text})
            yield from self._loop(conversation, start_len)
        except GeneratorExit:
            self._repair(conversation, start_len)
            raise
        except Exception as e:  # pragma: no cover - defensive
            log.exception("agent turn crashed")
            self._repair(conversation, start_len)
            yield _error(f"Внутренняя ошибка: {e}", "internal")
        finally:
            conversation.end()

    # ------------------------------------------------------------------ loop
    def _loop(self, conv: Conversation, start_len: int) -> Iterator[dict[str, Any]]:
        tools = get_tools(strict=getattr(self.settings, "strict_tools", True))
        usage: dict[str, int] = {}
        text_parts: list[str] = []

        for _ in range(MAX_ITERATIONS):
            final = None
            first_delta = True
            try:
                for ev in self.llm.stream(SYSTEM_PROMPT, conv.messages, tools):
                    if ev.type == "text":
                        if not ev.text:
                            continue
                        if first_delta and text_parts:
                            text_parts.append("\n\n")
                            yield {"type": "text_delta", "text": "\n\n"}
                        first_delta = False
                        text_parts.append(ev.text)
                        yield {"type": "text_delta", "text": ev.text}
                    elif ev.type == "final":
                        final = ev
            except LLMAuthError as e:
                self._repair(conv, start_len)
                yield _error(str(e) or MSG_BAD_KEY, "llm_not_configured")
                return
            except (LLMRateLimitError, LLMConnectionError, LLMStatusError, LLMError) as e:
                self._repair(conv, start_len)
                yield _error(str(e) or "Ошибка обращения к модели.", "llm_error")
                return

            if final is None:
                self._repair(conv, start_len)
                yield _error("Модель не вернула ответ.", "llm_error")
                return

            for k, v in (final.usage or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    usage[k] = usage.get(k, 0) + v

            content = final.content
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            reason = final.stop_reason

            if reason == "refusal":
                self._repair(conv, start_len)
                yield _error(MSG_REFUSAL, "llm_error")
                return
            if reason == "max_tokens" and tool_uses:
                # Never run a tool call whose input may be cut off; don't keep it in history.
                self._repair(conv, start_len)
                yield _error(MSG_MAX_TOKENS, "llm_error")
                return
            if not content:
                self._repair(conv, start_len)
                yield _error("Модель вернула пустой ответ.", "llm_error")
                return

            conv.messages.append({"role": "assistant", "content": content})

            if reason == "max_tokens" or reason == "model_context_window_exceeded":
                yield _error(MSG_MAX_TOKENS, "llm_error")
                return
            if reason == "pause_turn":
                continue
            if reason == "tool_use" and tool_uses:
                results = []
                for block in tool_uses:
                    tid, name, tinput = block.get("id"), block.get("name"), block.get("input")
                    yield {"type": "tool_start", "id": tid, "name": name, "input": tinput}
                    res = self.executor.execute(name, tinput if tinput is not None else {})
                    results.append({"type": "tool_result", "tool_use_id": tid,
                                    "content": res.model_content(), "is_error": not res.ok})
                    yield {"type": "tool_result", "id": tid, "name": name, "ok": res.ok,
                           "summary": res.summary, "data": res.ui_data()}
                conv.messages.append({"role": "user", "content": results})
                continue
            # end_turn, stop_sequence, or anything final
            yield {"type": "done", "text": "".join(text_parts), "usage": usage}
            return

        yield _error(MSG_TOO_MANY_STEPS, "llm_error")

    # ------------------------------------------------------------------ history repair
    @staticmethod
    def _repair(conv: Conversation, start_len: int) -> None:
        """Leave the history valid for the next request after an aborted turn."""
        msgs = conv.messages
        if len(msgs) <= start_len:
            return
        if len(msgs) == start_len + 1:  # only our user prompt, never answered
            del msgs[start_len:]
            return
        last = msgs[-1]
        if last.get("role") == "assistant" and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in (last.get("content") or [])):
            msgs.pop()

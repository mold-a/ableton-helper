"""In-memory conversation history."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_MESSAGES = 80          # trim old exchanges beyond this
MAX_CONVERSATIONS = 200    # evict least-recently-used beyond this


def _is_user_prompt(msg: dict) -> bool:
    """A user message that starts an exchange (not a tool_result carrier)."""
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_used: float = field(default_factory=time.time)
    _busy: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def try_begin(self) -> bool:
        """Claim the conversation for one running turn; False if a turn is already in progress."""
        ok = self._busy.acquire(blocking=False)
        if ok:
            self.last_used = time.time()
        return ok

    def end(self) -> None:
        try:
            self._busy.release()
        except RuntimeError:
            pass

    def trim(self, max_messages: int = MAX_MESSAGES) -> None:
        """Drop the oldest whole exchanges so tool_use/tool_result pairs stay intact and the
        history still begins with a user prompt. Called between turns only (history is
        append-only within a turn)."""
        if len(self.messages) <= max_messages:
            return
        cut = len(self.messages) - max_messages
        for i in range(cut, len(self.messages)):
            if _is_user_prompt(self.messages[i]):
                del self.messages[:i]
                return
        # no safe boundary in range: keep everything rather than corrupt the history

    def reset(self) -> None:
        self.messages.clear()


class ConversationStore:
    def __init__(self, max_conversations: int = MAX_CONVERSATIONS):
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()
        self.max_conversations = max_conversations

    def get(self, conversation_id: str | None = None, create: bool = True) -> Conversation | None:
        with self._lock:
            conv = self._items.get(conversation_id) if conversation_id else None
            if conv is None and create:
                conv = Conversation(id=conversation_id or uuid.uuid4().hex[:16])
                self._items[conv.id] = conv
                self._evict()
            if conv is not None:
                conv.last_used = time.time()
            return conv

    def reset(self, conversation_id: str) -> bool:
        with self._lock:
            return self._items.pop(conversation_id, None) is not None

    def __len__(self) -> int:
        return len(self._items)

    def _evict(self) -> None:
        while len(self._items) > self.max_conversations:
            oldest = min(self._items.values(), key=lambda c: c.last_used)
            del self._items[oldest.id]

"""Wiring helpers shared by the server and the CLI."""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from ..knowledge import KnowledgeBase
from ..llm import AnthropicLLM
from .agent import AssistantAgent

log = logging.getLogger(__name__)


def default_engine(bridge: Any) -> Any | None:
    """Real SoundEngine if abhelper.sound is importable, else None (sound tools then report it)."""
    try:
        from ..sound import SoundEngine  # type: ignore
    except ImportError as e:
        log.warning("abhelper.sound is not available: %s", e)
        return None
    return SoundEngine(bridge)


def build_agent(settings: Settings, bridge: Any, engine: Any = None, llm: Any = None,
                knowledge: Any = None) -> AssistantAgent:
    if engine is None:
        engine = default_engine(bridge)
    if knowledge is None:
        knowledge = KnowledgeBase()
    if llm is None:
        llm = AnthropicLLM(settings)
    return AssistantAgent(bridge, engine, knowledge, llm, settings)

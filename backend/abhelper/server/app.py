"""FastAPI app: UI + JSON API + SSE chat (docs/INTERFACES.md §5)."""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from .. import __version__
from ..agent.conversation import ConversationStore
from ..agent.factory import build_agent
from ..bridge.base import BridgeError
from ..bridge.client import SerializedBridge, TcpBridge
from ..config import EFFORTS, Settings

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_MESSAGE_CHARS = 8000

SUGGESTIONS = [
    "Хочу звук баяна",
    "Сделай тёплый пэд как в Boards of Canada",
    "Нужен жирный бас для драм-н-бейса",
    "Звук 8-битной приставки, лид для мелодии",
    "Как сделать варп лупа в Ableton?",
    "Как записать MIDI с клавиатуры?",
    "Что у меня сейчас в проекте?",
]


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str


class ResetRequest(BaseModel):
    conversation_id: str


class ConfigUpdate(BaseModel):
    api_key: str | None = None
    model: str | None = None
    effort: str | None = None


def resolve_ui_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("ABHELPER_UI_DIR")
    if env:
        return Path(env).expanduser()
    return REPO_ROOT / "ui"


def probe_bridge(bridge: Any) -> dict | None:
    try:
        if hasattr(bridge, "probe"):
            return bridge.probe()
        return bridge.call("ping")
    except BridgeError:
        return None
    except Exception:  # pragma: no cover - defensive
        log.exception("bridge probe failed")
        return None


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None, bridge: Any = None, engine: Any = None, llm: Any = None,
               knowledge: Any = None, ui_dir: str | Path | None = None) -> FastAPI:
    settings = settings or Settings.load()
    owns_bridge = bridge is None
    if bridge is None:
        bridge = TcpBridge(settings.bridge_host, settings.bridge_port)
    elif not isinstance(bridge, (TcpBridge, SerializedBridge)):
        bridge = SerializedBridge(bridge)  # HTTP workers are threads; protect non-thread-safe bridges
    agent = build_agent(settings, bridge, engine=engine, llm=llm, knowledge=knowledge)
    conversations = ConversationStore()
    ui_path = resolve_ui_dir(ui_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_bridge:
            bridge.close()

    app = FastAPI(title="Ableton Helper", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.bridge = bridge
    app.state.agent = agent
    app.state.conversations = conversations
    app.state.ui_dir = ui_path

    # ------------------------------------------------------------------ API
    @app.get("/api/status")
    def status() -> dict:
        info = probe_bridge(bridge)
        return {
            "bridge": {
                "connected": info is not None,
                "live_version": (info or {}).get("live_version"),
                "script_version": (info or {}).get("script_version"),
            },
            "llm": {"configured": bool(settings.api_key), "model": settings.model},
            "version": __version__,
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        text = req.message.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Пустое сообщение")
        if len(text) > MAX_MESSAGE_CHARS:
            raise HTTPException(status_code=413, detail="Сообщение слишком длинное")
        cid = req.conversation_id if req.conversation_id and CONVERSATION_ID_RE.match(req.conversation_id) else None
        conv = conversations.get(cid)
        assert conv is not None

        async def stream() -> AsyncIterator[str]:
            yield sse({"type": "conversation", "conversation_id": conv.id})
            gen: Iterator[dict] = agent.run_turn(conv, text)
            try:
                async for event in iterate_in_threadpool(gen):
                    yield sse(event)
            except Exception as e:  # pragma: no cover - agent already guards itself
                log.exception("chat stream failed")
                yield sse({"type": "error", "message": f"Внутренняя ошибка: {e}", "code": "internal"})
            finally:
                try:
                    gen.close()
                except ValueError:  # generator is still running in a worker thread
                    pass

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    @app.post("/api/reset")
    def reset(req: ResetRequest) -> dict:
        conversations.reset(req.conversation_id)
        return {"ok": True}

    @app.get("/api/config")
    def get_config() -> dict:
        return settings.public_dict()

    @app.post("/api/config")
    def set_config(update: ConfigUpdate) -> dict:
        changes: dict[str, str] = {}
        if update.api_key is not None:
            key = update.api_key.strip()
            if len(key) > 512 or any(c.isspace() for c in key):
                raise HTTPException(status_code=400, detail="Некорректный API-ключ")
            changes["api_key"] = key
        if update.model is not None:
            model = update.model.strip()
            if not model or len(model) > 100:
                raise HTTPException(status_code=400, detail="Некорректное имя модели")
            changes["model"] = model
        if update.effort is not None:
            effort = update.effort.strip().lower()
            if effort not in EFFORTS:
                raise HTTPException(status_code=400, detail=f"effort должен быть одним из: {', '.join(EFFORTS)}")
            changes["effort"] = effort
        if changes:
            overridden = settings.env_overrides(changes)
            staged = Settings(**{**settings.__dict__, **changes})
            try:
                staged.save(fields=list(changes))
            except OSError as e:
                raise HTTPException(status_code=500, detail=f"Не удалось сохранить настройки: {e}")
            for field_name, value in changes.items():
                if field_name not in overridden:  # an env variable keeps priority over the file
                    setattr(settings, field_name, value)
        else:
            overridden = []
        return {**settings.public_dict(), "env_overrides": overridden}

    @app.get("/api/suggestions")
    def suggestions() -> dict:
        return {"items": SUGGESTIONS}

    # ------------------------------------------------------------------ static UI
    index = ui_path / "index.html"
    if index.is_file():
        app.mount("/ui", StaticFiles(directory=str(ui_path), html=True), name="ui")
        app.mount("/", StaticFiles(directory=str(ui_path), html=True), name="ui-root")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_ui() -> str:
            return ("<!doctype html><meta charset=utf-8><title>Ableton Helper</title>"
                    "<h1>Ableton Helper</h1><p>Папка с интерфейсом не найдена: "
                    f"<code>{ui_path}</code>. Задайте ABHELPER_UI_DIR.</p>"
                    "<p>API работает: <a href=/api/status>/api/status</a></p>")

    return app

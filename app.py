from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json
import os

import logging

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from bot.application.orchestrator import Orchestrator
from bot.infrastructure.config import SETTINGS, reload_settings
from bot.infrastructure.db import ensure_schema, save_chat_summary
from bot.infrastructure.db_admin import (
    list_tables,
    list_columns,
    fetch_rows,
    insert_row,
    update_row,
    delete_row,
)
from bot.infrastructure.logging_setup import setup_logging
from bot.shared.memory import SessionStore
from bot.shared.system_prompts import load_system_prompts, save_system_prompts
from bot.shared.transcript import append_transcript
from bot.application.summary import summarize_history

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(title="Multilingual Multi-Agent Bot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

setup_logging("app")
log = logging.getLogger("api")

session_store = SessionStore(
    default_language=SETTINGS.default_language,
    default_system_prompt_id=SETTINGS.default_system_prompt_id,
    expire_seconds=SETTINGS.session.expire_minutes * 60,
)

orchestrator = Orchestrator(SETTINGS)
system_prompts = load_system_prompts()


@app.on_event("startup")
def startup() -> None:
    ensure_schema()
    log.info(
        "startup app_file=%s cwd=%s log_file=%s log_level=%s",
        str(Path(__file__).resolve()),
        str(Path.cwd()),
        str((SETTINGS.logging.dir / "app.log").resolve()),
        SETTINGS.logging.level,
    )


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    phone_number: str = Field(..., min_length=5)
    call_uuid: str = Field(..., min_length=4)
    language: str | None = None
    system_prompt_id: str | None = None
    reset: bool = False


class ChatResponse(BaseModel):
    session_id: str
    call_uuid: str
    phone_number: str
    reply: str
    language: str
    intent: str
    used_tool: str | None = None
    tool_data: dict[str, Any] | None = None
    flow: dict[str, Any] | None = None
    Chat_ended: bool = False


class SystemPromptsPayload(BaseModel):
    prompts: list[dict[str, Any]]


class DbInsertPayload(BaseModel):
    data: dict[str, Any]


class DbUpdatePayload(BaseModel):
    set: dict[str, Any]
    where: dict[str, Any]


class DbDeletePayload(BaseModel):
    where: dict[str, Any]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/runtime")
def debug_runtime() -> dict[str, Any]:
    root_logger = logging.getLogger()
    return {
        "pid": os.getpid(),
        "app_file": str(Path(__file__).resolve()),
        "cwd": str(Path.cwd()),
        "log_dir": str(SETTINGS.logging.dir.resolve()),
        "log_file": str((SETTINGS.logging.dir / "app.log").resolve()),
        "root_level": logging.getLevelName(root_logger.level),
        "handlers": [
            {
                "type": type(h).__name__,
                "level": logging.getLevelName(h.level),
                "baseFilename": getattr(h, "baseFilename", None),
            }
            for h in root_logger.handlers
        ],
    }


@app.get("/config")
def config() -> dict[str, Any]:
    settings = reload_settings()
    return {
        "default_language": settings.default_language,
        "default_system_prompt_id": settings.default_system_prompt_id,
        "llm": {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "base_url": settings.llm.base_url,
        },
    }


@app.get("/system")
def get_system_prompts() -> dict[str, Any]:
    return {"prompts": system_prompts}


@app.post("/system")
def update_system_prompts(payload: SystemPromptsPayload) -> dict[str, Any]:
    global system_prompts
    if len(payload.prompts) < 1:
        raise HTTPException(status_code=400, detail="At least one system prompt is required.")
    system_prompts = payload.prompts
    save_system_prompts(system_prompts)
    return {"prompts": system_prompts}


@app.get("/db/tables")
async def db_tables() -> dict[str, Any]:
    try:
        tables = await asyncio.to_thread(list_tables)
        return {"tables": tables}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/db/table/{table}/columns")
async def db_columns(table: str) -> dict[str, Any]:
    try:
        cols = await asyncio.to_thread(list_columns, table)
        return {"columns": cols}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/db/table/{table}/rows")
async def db_rows(table: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    try:
        rows = await asyncio.to_thread(fetch_rows, table, limit, offset)
        return {"rows": rows, "limit": limit, "offset": offset}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/db/table/{table}/rows")
async def db_insert(table: str, payload: DbInsertPayload) -> dict[str, Any]:
    try:
        row = await asyncio.to_thread(insert_row, table, payload.data)
        return {"row": row}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/db/table/{table}/rows")
async def db_update(table: str, payload: DbUpdatePayload) -> dict[str, Any]:
    try:
        rows = await asyncio.to_thread(update_row, table, payload.set, payload.where)
        return {"rows": rows}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/db/table/{table}/rows")
async def db_delete(table: str, payload: DbDeletePayload) -> dict[str, Any]:
    try:
        rows = await asyncio.to_thread(delete_row, table, payload.where)
        return {"rows": rows}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    return await _process_chat(payload)


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "detail": "Invalid JSON. Send a single JSON object per message.",
                })
                continue
            if not isinstance(data, dict):
                await websocket.send_json({
                    "type": "error",
                    "detail": "Invalid payload. Send a JSON object.",
                })
                continue
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            try:
                payload = ChatRequest(**data)
            except ValidationError as exc:
                await websocket.send_json({"type": "error", "detail": exc.errors()})
                continue
            try:
                response = await _process_chat(payload)
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "detail": exc.detail})
                continue
            await websocket.send_json({"type": "chat", **response.model_dump()})
    except WebSocketDisconnect:
        return


async def _process_chat(payload: ChatRequest) -> ChatResponse:
    if not payload.phone_number or not payload.call_uuid:
        raise HTTPException(status_code=400, detail="phone_number and call_uuid are required.")

    session, expired = session_store.get(payload.call_uuid, payload.phone_number, return_expired=True)
    if expired and expired.history:
        try:
            summary = await summarize_history(
                expired.history,
                expired.language,
                SETTINGS,
                SETTINGS.session.summary_max_chars,
            )
            if summary:
                await save_chat_summary(expired.phone_number, expired.call_uuid, summary)
        except Exception:
            log.exception("session_summary_failed", extra={"call_uuid": expired.call_uuid})
    if payload.reset:
        session = session_store.reset(session.session_id)
        session.phone_number = payload.phone_number
        session.call_uuid = payload.call_uuid

    if payload.system_prompt_id:
        session.system_prompt_id = payload.system_prompt_id

    log.info(
        "chat_request",
        extra={"call_uuid": payload.call_uuid, "phone": payload.phone_number},
    )
    log.info("chat_input call_uuid=%s message=%s", payload.call_uuid, payload.message)
    append_transcript(payload.call_uuid, "user", payload.message)

    result = await orchestrator.handle(
        message=payload.message,
        session=session,
        prompts=system_prompts,
    )
    log.info(
        "chat_result call_uuid=%s intent=%s flow=%s language=%s",
        payload.call_uuid,
        result.intent,
        result.flow_state.get("name") if result.flow_state else None,
        result.language,
    )

    session.language = result.language
    session.flow = result.flow_state

    session.history.append({"role": "user", "content": payload.message})
    session.history.append({"role": "assistant", "content": result.reply})
    append_transcript(payload.call_uuid, "assistant", result.reply)

    if len(session.history) > 40:
        session.history = session.history[-40:]

    return ChatResponse(
        session_id=session.session_id,
        call_uuid=payload.call_uuid,
        phone_number=payload.phone_number,
        reply=result.reply,
        language=result.language,
        intent=result.intent,
        used_tool=result.used_tool,
        tool_data=result.tool_data,
        flow=session.flow,
        Chat_ended=result.chat_ended,
    )

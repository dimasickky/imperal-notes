"""Notes · Shared state & extension setup."""
from __future__ import annotations

import logging
import os

import httpx

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult

log = logging.getLogger("notes")

NOTES_API_URL = os.environ["NOTES_API_URL"]
NOTES_API_KEY = os.getenv("NOTES_API_KEY", "")

_http = None

def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=NOTES_API_URL,
            headers={"x-api-key": NOTES_API_KEY},
            timeout=15.0,
        )
    return _http

def _user_id(ctx) -> str:
    return ctx.user.id if hasattr(ctx, "user") and ctx.user else ""

def _tenant_id(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user and hasattr(ctx.user, "tenant_id"):
        return ctx.user.tenant_id
    return "default"

async def _api_get(path: str, params: dict = None) -> dict:
    r = await _get_http().get(path, params=params or {})
    r.raise_for_status()
    return r.json()

async def _api_post(path: str, data: dict = None, params: dict = None) -> dict:
    r = await _get_http().post(path, json=data, params=params)
    r.raise_for_status()
    return r.json()

async def _api_patch(path: str, params: dict, data: dict) -> dict:
    r = await _get_http().patch(path, params=params, json=data)
    r.raise_for_status()
    return r.json()

async def _api_delete(path: str, params: dict) -> dict:
    r = await _get_http().delete(path, params=params)
    r.raise_for_status()
    return r.json()

from pathlib import Path as _Path
SYSTEM_PROMPT = (_Path(__file__).parent / "system_prompt.txt").read_text()

ext = Extension("notes", version="2.4.0")

chat = ChatExtension(
    ext=ext,
    tool_name="tool_notes_chat",
    description=(
        "Personal notes assistant — create, read, update, delete, search, "
        "organize notes with folders and tags, move notes, manage trash"
    ),
    system_prompt=SYSTEM_PROMPT,
    model="claude-haiku-4-5-20251001",
)

@ext.health_check
async def health(ctx) -> dict:
    try:
        await _api_get("/health")
        return {"status": "ok", "version": ext.version, "api": "reachable"}
    except Exception:
        return {"status": "degraded", "version": ext.version, "api": "unreachable"}

@ext.on_install
async def on_install(ctx):
    log.info(f"notes installed for user {ctx.user.id if ctx and hasattr(ctx, 'user') and ctx.user else 'system'}")

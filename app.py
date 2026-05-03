"""Notes · Shared state & extension setup."""
from __future__ import annotations

import logging
import os
import re

from pydantic import BaseModel

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult  # noqa: F401 — re-exported

log = logging.getLogger("notes")

NOTES_API_URL = os.environ["NOTES_API_URL"]
NOTES_API_KEY = os.getenv("NOTES_API_KEY", "")



# ─── Backend error ────────────────────────────────────────────────────────── #

class NotesAPIError(Exception):
    """HTTP error from notes-api backend."""

    def __init__(self, status_code: int, detail: str, path: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"notes-api {status_code} on {path}: {detail}")


# ─── HTTP helpers (ctx-scoped, per-request, no shared state) ─────────────── #

def _url(path: str) -> str:
    return f"{NOTES_API_URL.rstrip('/')}{path}"


def _auth() -> dict:
    return {"x-api-key": NOTES_API_KEY} if NOTES_API_KEY else {}


def _raise_from(resp, path: str) -> None:
    """Raise NotesAPIError when the SDK HTTPResponse indicates failure."""
    if resp.ok:
        return
    body = resp.body
    if isinstance(body, dict):
        detail = body.get("detail") or str(body)
    elif isinstance(body, str):
        detail = body
    else:
        detail = f"HTTP {resp.status_code}"
    raise NotesAPIError(resp.status_code, detail, path)


async def _api_get(ctx, path: str, params: dict | None = None) -> dict:
    r = await ctx.http.get(_url(path), params=params or {}, headers=_auth())
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_post(ctx, path: str, data: dict | None = None, params: dict | None = None) -> dict:
    r = await ctx.http.post(_url(path), json=data, params=params, headers=_auth())
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_patch(ctx, path: str, params: dict, data: dict) -> dict:
    r = await ctx.http.patch(_url(path), params=params, json=data, headers=_auth())
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_delete(ctx, path: str, params: dict) -> dict:
    r = await ctx.http.delete(_url(path), params=params, headers=_auth())
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_upload(ctx, path: str, params: dict, filename: str,
                      data: bytes, content_type: str) -> dict:
    r = await ctx.http.post(
        _url(path),
        params=params,
        headers=_auth(),
        files={"file": (filename, data, content_type)},
    )
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


# ─── Identity helpers ─────────────────────────────────────────────────────── #

def _user_id(ctx) -> str:
    """Return user ID or '' for anonymous contexts (panels, skeletons)."""
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


def require_user_id(ctx) -> str:
    """Return user ID or raise. Every @chat.function handler must call this."""
    uid = _user_id(ctx)
    if not uid:
        raise RuntimeError(
            "No authenticated user on context. Refusing to query notes-api "
            "with an empty user_id (would silently return no data)."
        )
    return uid


def _tenant_id(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user:
        return getattr(ctx.user, "tenant_id", None) or "default"
    return "default"


# ─── Folder name resolver (shared by delete handlers) ────────────────────── #

async def _resolve_folder_id_or_name(ctx, value: str) -> str:
    """Accept a folder UUID or display name. Returns UUID or '' if not found."""
    v = value.strip()
    if not v:
        return ""
    if _UUID_RE.match(v):
        return v
    return await _resolve_folder_name(ctx, v) or ""


async def _resolve_folder_name(ctx, name: str) -> str | None:
    """Return folder UUID for a given display name (case-insensitive, fuzzy). None if not found."""
    target = name.strip().lower()
    if not target:
        return None
    try:
        folders = (await _api_get(ctx, "/folders", {
            "user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx),
        })).get("folders", [])
    except Exception:
        return None
    exact = next((f for f in folders if f["name"].strip().lower() == target), None)
    if exact:
        return exact["id"]
    prefix = next((f for f in folders if f["name"].strip().lower().startswith(target)), None)
    if prefix:
        return prefix["id"]
    contain = next((f for f in folders if target in f["name"].strip().lower()), None)
    return contain["id"] if contain else None


# ─── Extension ───────────────────────────────────────────────────────────── #

ext = Extension(
    "notes",
    version="3.3.0",
    capabilities=["notes:read", "notes:write"],
    display_name="Notes",
    description=(
        "Personal notes with folders, tags, full-text search, "
        "and trash management for your workspace."
    ),
    icon="icon.svg",
    actions_explicit=True,
)


# ─── Cache models (SDK 4.0 ctx.cache, Pydantic-typed, per-user TTL) ───────── #

@ext.cache_model("folders_list")
class FoldersCacheEntry(BaseModel):
    folders: list[dict]


@ext.cache_model("tags_list")
class TagsCacheEntry(BaseModel):
    tags: list[str]


@ext.cache_model("folder_stats")
class FolderStatsCacheEntry(BaseModel):
    counts: dict


# ─── Emitted events (UEB manifest §M7, SDK 3.6+) ─────────────────────────── #

@ext.emits("notes.created")
@ext.emits("notes.updated")
@ext.emits("notes.deleted")
@ext.emits("notes.permanently_deleted")
@ext.emits("notes.moved")
@ext.emits("notes.restored")
@ext.emits("notes.emptied")
@ext.emits("notes.bulk_deleted")
@ext.emits("notes.folder_created")
@ext.emits("notes.folder_renamed")
@ext.emits("notes.folder_deleted")
@ext.emits("notes.folder_with_contents_deleted")
async def _declare_events() -> None:  # pragma: no cover
    pass


# ─── ChatExtension ────────────────────────────────────────────────────────── #

from pathlib import Path as _Path
SYSTEM_PROMPT = (_Path(__file__).parent / "system_prompt.txt").read_text()

chat = ChatExtension(
    ext=ext,
    tool_name="tool_notes_chat",
    description=(
        "Personal notes assistant — create, read, update, delete, search, "
        "organize notes with folders and tags, move notes, manage trash"
    ),
    system_prompt=SYSTEM_PROMPT,
)


# ─── Lifecycle ────────────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await ctx.http.get(_url("/health"), headers=_auth())
        if not r.ok:
            return {"status": "degraded", "version": ext.version, "api": "unreachable"}
        return {"status": "ok", "version": ext.version, "api": "reachable"}
    except Exception as exc:
        log.warning("notes health check failed: %s", exc)
        return {"status": "degraded", "version": ext.version, "api": "unreachable"}


@ext.on_install
async def on_install(ctx) -> None:
    log.info("notes installed for user %s", _user_id(ctx) or "system")

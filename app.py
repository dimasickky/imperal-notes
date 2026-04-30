"""Notes · Shared state & extension setup."""
from __future__ import annotations

import logging
import os

import httpx

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult
from imperal_sdk.http import HTTPClient

log = logging.getLogger("notes")

NOTES_API_URL = os.environ["NOTES_API_URL"]
NOTES_API_KEY = os.getenv("NOTES_API_KEY", "")


# ─── HTTP via SDK HTTPClient (replaces direct httpx.AsyncClient) ──────── #
#
# Module-level HTTPClient chosen because _api_* helpers are called from
# panel renderers + handlers alike — threading ctx through every layer
# would be invasive. Same wrapper ctx.http uses under the hood: typed
# HTTPResponse (.ok / .status_code / .body / .json()), per-request httpx
# session, no cross-tenant state bleed.

_http_client: HTTPClient | None = None


def _http() -> HTTPClient:
    global _http_client
    if _http_client is None:
        _http_client = HTTPClient(timeout=15)
    return _http_client


def _url(path: str) -> str:
    return f"{NOTES_API_URL.rstrip('/')}{path}"


def _auth_headers() -> dict:
    return {"x-api-key": NOTES_API_KEY} if NOTES_API_KEY else {}


def _raise_from(resp, path: str) -> None:
    """Mirror httpx.raise_for_status() using the SDK response shape.

    Preserves the `httpx.HTTPStatusError` type that handlers already catch,
    so the migration doesn't ripple into every handler's except-clauses.
    """
    if resp.ok:
        return
    # Synthesise a minimal httpx.Request/Response pair so HTTPStatusError
    # holds the real status code + body for handlers that inspect them.
    body = resp.body
    if isinstance(body, dict):
        import json as _json
        raw = _json.dumps(body).encode()
    elif isinstance(body, str):
        raw = body.encode()
    elif isinstance(body, bytes):
        raw = body
    else:
        raw = f"HTTP {resp.status_code}".encode()
    req = httpx.Request("GET", _url(path))
    httpx_resp = httpx.Response(status_code=resp.status_code, content=raw, request=req)
    raise httpx.HTTPStatusError(
        f"notes-api {resp.status_code} on {path}",
        request=req, response=httpx_resp,
    )


# ─── Identity helpers ─────────────────────────────────────────────────── #
#
# _user_id returns "" when ctx has no user attached. This is correct for
# panel/skeleton renderers which may fire for anonymous sessions and must
# tolerate absence (they return empty shapes). Chat handlers MUST use
# require_user_id() so an empty ctx surfaces a loud error instead of
# silently scoping the backend query to "no-user" and returning 0 rows.

def _user_id(ctx) -> str:
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


def require_user_id(ctx) -> str:
    """Return ctx.user.imperal_id or raise. Use from every @chat.function handler.

    When a chain step arrives without ctx.user populated (kernel-side bug
    observed 2026-04-23), a silent "" would scope every backend query to
    no-user and hand back empty lists — indistinguishable from a real
    empty folder. Raising makes the failure loud and catchable.
    """
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


async def _api_get(path: str, params: dict = None) -> dict:
    r = await _http().get(_url(path), params=params or {}, headers=_auth_headers())
    _raise_from(r, path)
    return r.json()


async def _api_post(path: str, data: dict = None, params: dict = None) -> dict:
    r = await _http().post(_url(path), json=data, params=params, headers=_auth_headers())
    _raise_from(r, path)
    return r.json()


async def _api_patch(path: str, params: dict, data: dict) -> dict:
    r = await _http().patch(_url(path), params=params, json=data, headers=_auth_headers())
    _raise_from(r, path)
    return r.json()


async def _api_delete(path: str, params: dict) -> dict:
    r = await _http().delete(_url(path), params=params, headers=_auth_headers())
    _raise_from(r, path)
    return r.json()


async def _api_upload(path: str, params: dict, filename: str, data: bytes, content_type: str) -> dict:
    r = await _http().post(
        _url(path),
        params=params,
        headers=_auth_headers(),
        files={"file": (filename, data, content_type)},
    )
    _raise_from(r, path)
    return r.json()

from pathlib import Path as _Path
SYSTEM_PROMPT = (_Path(__file__).parent / "system_prompt.txt").read_text()

ext = Extension(
    "notes",
    version="2.6.4",
    capabilities=["notes:read", "notes:write"],
)

# SDK 3.3+ — `model=` deprecated; LLM resolution moved to kernel ctx-injection
# (see ctx._llm_configs). Will be hard-removed in SDK 4.0.
chat = ChatExtension(
    ext=ext,
    tool_name="tool_notes_chat",
    description=(
        "Personal notes assistant — create, read, update, delete, search, "
        "organize notes with folders and tags, move notes, manage trash"
    ),
    system_prompt=SYSTEM_PROMPT,
)

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await _http().get(_url("/health"), headers=_auth_headers())
        if not r.ok:
            return {"status": "degraded", "version": ext.version, "api": "unreachable"}
        return {"status": "ok", "version": ext.version, "api": "reachable"}
    except Exception as exc:
        log.warning("notes health check failed: %s", exc)
        return {"status": "degraded", "version": ext.version, "api": "unreachable"}

@ext.on_install
async def on_install(ctx):
    log.info(f"notes installed for user {_user_id(ctx) or 'system'}")

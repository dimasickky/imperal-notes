"""Notes · Shared state, HTTP helpers, Extension instance.

Loader entry point: panels / skeleton / lifecycle wiring all runs off the
module-level ``ext`` instance so the kernel (which discovers extensions by
walking for an attribute with ``.tools: dict`` + ``.signals``) picks it up
unchanged. Tool methods live on the ``NotesExtension`` subclass declared in
``tools.py`` (v2.0 class-based surface).
"""
from __future__ import annotations

import logging
import os

import httpx

from imperal_sdk.http import HTTPClient

from tools import NotesExtension

log = logging.getLogger("notes")

# ─── Config ──────────────────────────────────────────────────────────── #

NOTES_API_URL = os.environ["NOTES_API_URL"]
NOTES_API_KEY = os.getenv("NOTES_API_KEY", "")


# ─── HTTP via SDK HTTPClient ─────────────────────────────────────────── #
#
# Module-level client because ``_api_*`` helpers are shared between tools,
# panels, and skeleton refreshers. Threading ctx.http through every layer
# would be invasive for no federal gain — HTTPClient is the same wrapper
# ctx.http uses under the hood (per-request httpx.AsyncClient, no cross-
# tenant bleed). The backend enforces authn via `x-api-key` + user_id on
# every request, so no tenant state leaks at this layer.

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
    """Mirror httpx.raise_for_status() on the SDK response shape.

    Preserves the ``httpx.HTTPStatusError`` type so callers can catch the
    familiar exception and inspect ``.response.status_code`` / ``.response.text``.
    """
    if resp.ok:
        return
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
# ``_user_id`` returns "" on missing ctx.user — correct for panel / skeleton
# renderers that may fire for anonymous sessions and must tolerate absence.
# Tool handlers MUST use ``require_user_id`` so an empty ctx surfaces a loud
# error instead of silently scoping the backend query to no-user (which
# would return 0 rows indistinguishable from a genuinely empty folder).

def _user_id(ctx) -> str:
    return ctx.user.id if hasattr(ctx, "user") and ctx.user else ""


def require_user_id(ctx) -> str:
    uid = _user_id(ctx)
    if not uid:
        raise RuntimeError(
            "No authenticated user on context. Refusing to query notes-api "
            "with an empty user_id (would silently return no data).",
        )
    return uid


def _tenant_id(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user and hasattr(ctx.user, "tenant_id"):
        return ctx.user.tenant_id
    return "default"


# ─── Backend API helpers ─────────────────────────────────────────────── #

async def _api_get(path: str, params: dict | None = None) -> dict:
    r = await _http().get(_url(path), params=params or {}, headers=_auth_headers())
    _raise_from(r, path)
    return r.json()


async def _api_post(
    path: str, data: dict | None = None, params: dict | None = None,
) -> dict:
    r = await _http().post(
        _url(path), json=data, params=params, headers=_auth_headers(),
    )
    _raise_from(r, path)
    return r.json()


async def _api_patch(path: str, params: dict, data: dict) -> dict:
    r = await _http().patch(
        _url(path), params=params, json=data, headers=_auth_headers(),
    )
    _raise_from(r, path)
    return r.json()


async def _api_delete(path: str, params: dict) -> dict:
    r = await _http().delete(_url(path), params=params, headers=_auth_headers())
    _raise_from(r, path)
    return r.json()


# ─── Extension instance (loader entry point) ─────────────────────────── #

ext = NotesExtension(
    app_id="notes",
    version="3.0.0",
    capabilities=["notes:read", "notes:write"],
)


# ─── Lifecycle / health ──────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await _http().get(_url("/health"), headers=_auth_headers())
        if not r.ok:
            return {"status": "degraded", "version": ext.version, "api": "unreachable"}
        return {"status": "ok", "version": ext.version, "api": "reachable"}
    except Exception:
        return {"status": "degraded", "version": ext.version, "api": "unreachable"}


@ext.on_install
async def on_install(ctx):
    uid = _user_id(ctx) or "system"
    log.info("notes installed for user %s", uid)

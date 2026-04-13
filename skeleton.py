"""Notes · Skeleton tools."""
from __future__ import annotations

import logging

from app import ext, _api_get, _user_id, _tenant_id

log = logging.getLogger("notes")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.tool("skeleton_refresh_notes", scopes=["notes.read"], description="Background refresh: note statistics.")
async def skeleton_refresh_notes(ctx, **kwargs) -> dict:
    uid, tid = _user_id(ctx), _tenant_id(ctx)
    try:
        notes = (await _api_get("/notes", {"user_id": uid, "tenant_id": tid, "limit": 100})).get("notes", [])
        trash = (await _api_get("/notes", {"user_id": uid, "tenant_id": tid, "is_archived": True, "limit": 100})).get("notes", [])
        response = {
            "total_notes": len(notes),
            "pinned_notes": sum(1 for n in notes if n.get("is_pinned")),
            "trash_count": len(trash),
            "recent_notes": [{"note_id": n["id"], "title": n["title"]} for n in notes[:5]],
        }
        return {"response": response}
    except Exception as e:
        log.error("Skeleton refresh failed: %s", e)
        return {"response": {"total_notes": 0, "recent_notes": [], "error": str(e)}}


@ext.tool("skeleton_alert_notes", scopes=["notes.read"], description="Alert on significant note changes.")
async def skeleton_alert_notes(ctx, old: dict = None, new: dict = None, **kwargs) -> dict:
    return {"response": "No alerts for notes overview changes."}

"""Notes · Skeleton tools."""
from __future__ import annotations

import asyncio
import logging

from app import ext, _api_get, _user_id, _tenant_id

log = logging.getLogger("notes")


@ext.skeleton(
    "notes",
    alert=False,
    ttl=300,
    description="Note statistics: total count, pinned, trash, recent titles.",
)
async def skeleton_refresh_notes(ctx) -> dict:
    """Refresh note statistics. Pure read — idempotent."""
    uid, tid = _user_id(ctx), _tenant_id(ctx)
    try:
        _results = await asyncio.gather(
            _api_get(ctx, "/notes", {"user_id": uid, "tenant_id": tid, "limit": 5}),
            _api_get(ctx, "/notes", {"user_id": uid, "tenant_id": tid, "is_pinned": True, "limit": 1}),
            _api_get(ctx, "/notes", {"user_id": uid, "tenant_id": tid, "is_trashed": True, "limit": 1}),
            return_exceptions=True,
        )
        notes_resp  = _results[0] if not isinstance(_results[0], Exception) else {}
        pinned_resp = _results[1] if not isinstance(_results[1], Exception) else {}
        trash_resp  = _results[2] if not isinstance(_results[2], Exception) else {}
        recent = notes_resp.get("notes", [])
        total_notes  = int(notes_resp.get("total_count", 0))
        pinned_notes = int(pinned_resp.get("total_count", 0))
        trash_count  = int(trash_resp.get("total_count", 0))

        return {"response": {
            "total_notes":  total_notes,
            "pinned_notes": pinned_notes,
            "trash_count":  trash_count,
            "recent_notes": [
                {"note_id": n["id"], "title": n["title"]}
                for n in recent
            ],
        }}
    except Exception as e:
        log.error("skeleton refresh failed: %s", e)
        return {"response": {
            "total_notes":  0,
            "pinned_notes": 0,
            "trash_count":  0,
            "recent_notes": [],
        }}

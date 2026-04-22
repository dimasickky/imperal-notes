"""Notes · Skeleton tools."""
from __future__ import annotations

import asyncio
import logging

from app import ext, _api_get, _user_id, _tenant_id

log = logging.getLogger("notes")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.skeleton(
    "notes",
    alert=False,
    ttl=300,
    description="Note statistics: total count, pinned, trash, recent titles.",
)
async def skeleton_refresh_notes(ctx, **kwargs) -> dict:
    """Refresh note statistics. Pure read — idempotent.

    Return shape: scalar fields (total_notes, pinned_notes, trash_count)
    surface directly in the classifier envelope as
    `notes.notes: total_notes=N, pinned_notes=K, ...`. The `recent_notes`
    list collapses to a shape hint.
    """
    uid, tid = _user_id(ctx), _tenant_id(ctx)
    try:
        # Parallel fetch — halves refresh latency vs sequential awaits.
        notes_resp, trash_resp = await asyncio.gather(
            _api_get("/notes", {"user_id": uid, "tenant_id": tid, "limit": 100}),
            _api_get(
                "/notes",
                {"user_id": uid, "tenant_id": tid, "is_archived": True, "limit": 100},
            ),
        )
        notes = notes_resp.get("notes", [])
        # Prefer DB-wide total_count (notes-api v2026-04-22+); fall back to
        # the page length for backward compatibility with older backends.
        total_notes = int(notes_resp.get("total_count", len(notes)))
        trash_count = int(
            trash_resp.get("total_count", len(trash_resp.get("notes", [])))
        )

        return {"response": {
            "total_notes":  total_notes,
            "pinned_notes": sum(1 for n in notes if n.get("is_pinned")),
            "trash_count":  trash_count,
            "recent_notes": [
                {"note_id": n["id"], "title": n["title"]}
                for n in notes[:5]
            ],
        }}
    except Exception as e:
        log.error("Skeleton refresh failed: %s", e)
        return {"response": {
            "total_notes":  0,
            "pinned_notes": 0,
            "trash_count":  0,
            "recent_notes": [],
            "error": str(e),
        }}

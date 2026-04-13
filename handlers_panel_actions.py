"""Notes · Panel-specific action handlers.

Separate from chat handlers — these are called from DUI panels
and return refresh_panels to control which panels update.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import (
    chat, ActionResult,
    _api_get, _api_patch, _user_id,
)


# ─── Models ───────────────────────────────────────────────────────────── #

class NoteSaveParams(BaseModel):
    """Save a note field from the editor panel."""
    note_id: str = Field(description="Note UUID")
    field: str = Field(description="Field to save: title, content, pin")
    title: str = Field(default="", description="New title (when field=title)")
    content_text: str = Field(default="", description="HTML content (when field=content)")


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "note_save",
    action_type="write",
    description="Save a note field from the editor. Internal panel action.",
)
async def fn_note_save(ctx, params: NoteSaveParams) -> ActionResult:
    """Save note title, content, or toggle pin. Returns targeted refresh."""
    uid = _user_id(ctx)

    try:
        if params.field == "title":
            if not params.title:
                return ActionResult.error("Title cannot be empty")
            await _api_patch(
                f"/notes/{params.note_id}",
                {"user_id": uid},
                {"title": params.title},
            )
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "title",
                      "refresh_panels": ["sidebar"]},
                summary=f"Title saved",
            )

        if params.field == "content":
            await _api_patch(
                f"/notes/{params.note_id}",
                {"user_id": uid},
                {"content_text": params.content_text},
            )
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "content",
                      "refresh_panels": []},
                summary="Saved",
            )

        if params.field == "pin":
            note_data = await _api_get(
                f"/notes/{params.note_id}", {"user_id": uid},
            )
            current = note_data.get("note", {}).get("is_pinned", False)
            await _api_patch(
                f"/notes/{params.note_id}",
                {"user_id": uid},
                {"is_pinned": not current},
            )
            label = "unpinned" if current else "pinned"
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "pin",
                      "refresh_panels": ["sidebar"]},
                summary=f"Note {label}",
            )

        return ActionResult.error(f"Unknown field: {params.field}")

    except Exception as e:
        return ActionResult.error(f"Save failed: {e}")

"""Notes · Panel-specific action handlers.

Separate from chat handlers — these are called from DUI panels
and return refresh_panels to control which panels update.
"""
from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app import (
    chat, ActionResult,
    _api_get, _api_patch, require_user_id,
)


# ─── Models ───────────────────────────────────────────────────────────── #

class NoteSaveParams(BaseModel):
    """Save a note field from the editor panel.

    Although this is fired by the DUI editor panel (`note_save` ui.Call),
    it is registered as a `@chat.function` and therefore exposed to the
    LLM tool surface. Aliases keep an LLM-emitted call (`noteId`/`action`/
    `body`) from leaking a Pydantic stack-trace into chat.
    """
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(
        default="", description="Note UUID. Required.",
        validation_alias=AliasChoices("note_id", "noteId", "id", "uuid"),
    )
    field: str = Field(
        default="", description="Field to save: title, content, pin",
        validation_alias=AliasChoices("field", "action", "kind", "type"),
    )
    title: str = Field(
        default="", description="New title (when field=title)",
        validation_alias=AliasChoices("title", "name", "subject", "heading"),
    )
    content_text: str = Field(
        default="", description="HTML content (when field=content)",
        validation_alias=AliasChoices("content_text", "content", "body", "text", "html"),
    )
    tags: list[str] = Field(
        default_factory=list, description="Tag list (when field=tags)",
        validation_alias=AliasChoices("tags", "tag_list", "labels"),
    )
    folder_id: str = Field(
        default="", description="Folder UUID or empty string to remove (when field=folder)",
        validation_alias=AliasChoices("folder_id", "folderId", "folder"),
    )


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "note_save",
    action_type="write",
    event="updated",
    description="Save a note field from the editor. Internal panel action.",
)
async def fn_note_save(ctx, params: NoteSaveParams) -> ActionResult:
    """Save note title, content, or toggle pin. Returns targeted refresh."""
    uid = require_user_id(ctx)

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

        if params.field == "tags":
            await _api_patch(
                f"/notes/{params.note_id}",
                {"user_id": uid},
                {"tags": params.tags},
            )
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "tags",
                      "refresh_panels": ["sidebar"]},
                summary="Tags saved",
            )

        if params.field == "folder":
            new_folder = params.folder_id if params.folder_id else None
            await _api_patch(
                f"/notes/{params.note_id}",
                {"user_id": uid},
                {"folder_id": new_folder},
            )
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "folder",
                      "refresh_panels": ["sidebar"]},
                summary="Folder updated",
            )

        if params.field in ("archive", "unarchive"):
            is_archived = params.field == "archive"
            await _api_patch(
                f"/notes/{params.note_id}",
                {"user_id": uid},
                {"is_archived": is_archived, "is_trashed": False},
            )
            label = "archived" if is_archived else "restored"
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": params.field,
                      "refresh_panels": ["sidebar"]},
                summary=f"Note {label}",
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

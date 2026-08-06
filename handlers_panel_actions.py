"""Notes · Panel-specific action handlers."""

import logging

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

log = logging.getLogger("notes.handlers")

from app import (
    chat, ActionResult, NotesAPIError,
    _api_get, _api_patch,
    require_user_id, _bad_id,
)
from models_return import NoteSaveResult
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, INTERNAL
from error_codes import NOTES_INVALID_NOTE_ID


class NoteSaveParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(
        default="", description="Note UUID. Required.",
        validation_alias=AliasChoices("note_id", "noteId", "id", "uuid"),
    )
    field: str = Field(
        default="", description="Field to save: title | content | tags | folder | archive | unarchive | pin",
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


class NoteAutosaveParams(BaseModel):
    """Params for the editor's debounced content autosave."""
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(
        default="", description="Note UUID. Required.",
        validation_alias=AliasChoices("note_id", "noteId", "id", "uuid"),
    )
    content_text: str = Field(
        default="", description="HTML content from the editor",
        validation_alias=AliasChoices("content_text", "content", "body", "text", "html"),
    )


@chat.function(
    "note_autosave",
    action_type="write",
    chain_callable=True,
    id_projection="note_id",
    effects=["update:note"],
    # NO event= — deliberately, and this is the whole reason the function exists
    # separately from note_save instead of being another field on it.
    #
    # An `event=` here would publish a domain event on every debounced save. The
    # sidebar subscribes to notes.* events, and the host's event handler re-fetches
    # EVERY discovered panel — the open editor included, remounting it. That is
    # what made an earlier autosave attempt unusable: the editor was rebuilt from
    # under the cursor every half second while typing.
    #
    # Returning refresh_panels: [] is not enough on its own, because that only
    # governs the direct response to this call; the event path is separate and
    # fires regardless. Both have to stay silent, so: no event, no refresh.
    # A title/tags/folder change still refreshes the sidebar through note_save —
    # only the body, which the sidebar does not display, saves silently.
    description=(
        "Silently save the note body from the editor as the user types (debounced "
        "autosave). Does not refresh any panel and does not emit an update event, "
        "so typing is never interrupted. For explicit saves use note_save."
    ),
    data_model=NoteSaveResult,
)
async def fn_note_autosave(ctx, params: NoteAutosaveParams) -> ActionResult:
    uid = require_user_id(ctx)
    if err := _bad_id(params.note_id):
        return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
    try:
        await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                         {"content_text": params.content_text})
        return ActionResult.success(
            data={"note_id": params.note_id, "saved": "content", "refresh_panels": []},
            summary="Autosaved",
        )
    except NotesAPIError as e:
        log.error("note_autosave: API error %s %s", e.status_code, e.detail)
        return ActionResult.error("Autosave failed. Your text is still in the editor.",
                                  retryable=True, code=INTERNAL)
    except Exception as e:
        log.error("note_autosave: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.",
                                  retryable=True, code=INTERNAL)


@chat.function(
    "note_save",
    action_type="write",
    chain_callable=True,
    id_projection="note_id",
    effects=["update:note"],
    event="updated",
    description="Save a note field from the editor panel (title, content, tags, folder, pin, archive).",
    data_model=NoteSaveResult,
)
async def fn_note_save(ctx, params: NoteSaveParams) -> ActionResult:
    uid = require_user_id(ctx)
    if err := _bad_id(params.note_id):
        return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)

    try:
        if params.field == "title":
            if not params.title:
                return ActionResult.error("Title cannot be empty", code=VALIDATION_MISSING_FIELD)
            await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                             {"title": params.title})
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "title", "refresh_panels": ["sidebar"]},
                summary="Title saved",
            )

        if params.field == "content":
            await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                             {"content_text": params.content_text})
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "content", "refresh_panels": []},
                summary="Saved",
            )

        if params.field == "tags":
            await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                             {"tags": params.tags})
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "tags", "refresh_panels": ["sidebar"]},
                summary="Tags saved",
            )

        if params.field == "folder":
            new_folder = params.folder_id if params.folder_id else None
            await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                             {"folder_id": new_folder})
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "folder", "refresh_panels": ["sidebar"]},
                summary="Folder updated",
            )

        if params.field in ("archive", "unarchive"):
            is_archived = params.field == "archive"
            await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                             {"is_archived": is_archived, "is_trashed": False})
            label = "archived" if is_archived else "restored"
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": params.field, "refresh_panels": ["sidebar"]},
                summary=f"Note {label}",
            )

        if params.field == "pin":
            note_data = await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": uid})
            current = note_data.get("note", {}).get("is_pinned", False)
            await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": uid},
                             {"is_pinned": not current})
            label = "unpinned" if current else "pinned"
            return ActionResult.success(
                data={"note_id": params.note_id, "saved": "pin", "refresh_panels": ["sidebar"]},
                summary=f"Note {label}",
            )

        log.error("note_save: unknown field %r", params.field)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)

    except NotesAPIError as e:
        log.error("note_save: API error %s %s", e.status_code, e.detail)
        return ActionResult.error("Save failed. Please try again.", retryable=True, code=INTERNAL)
    except Exception as e:
        log.error("note_save: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)

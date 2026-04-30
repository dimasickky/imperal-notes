"""Notes · Folder & trash handlers."""
from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app import chat, ActionResult, _api_get, _api_post, _api_patch, _api_delete, require_user_id, _tenant_id


# ─── Models ───────────────────────────────────────────────────────────── #
#
# Same hardening rationale as models_notes.py: every field that an LLM is
# observed to confuse is wired with `validation_alias=AliasChoices(...)`,
# and all "id"/"name"-shaped required fields carry a safe default so a
# missing arg becomes a friendly ActionResult.error instead of a Pydantic
# stack trace surfaced in the chat.

_MODEL_CONFIG = ConfigDict(populate_by_name=True)


class FolderIdParams(BaseModel):
    """Target a specific folder."""
    model_config = _MODEL_CONFIG

    folder_id: str = Field(
        default="", description="Folder UUID. Required.",
        validation_alias=AliasChoices("folder_id", "folder", "folderId", "id", "uuid"),
    )


class CreateFolderParams(BaseModel):
    """Create a new folder."""
    model_config = _MODEL_CONFIG

    name: str = Field(
        default="", description="Folder name. Required.",
        validation_alias=AliasChoices("name", "title", "folder_name", "folderName"),
    )


class RenameFolderParams(BaseModel):
    """Rename an existing folder."""
    model_config = _MODEL_CONFIG

    folder_id: str = Field(
        default="", description="Folder UUID to rename. Required.",
        validation_alias=AliasChoices("folder_id", "folder", "folderId", "id", "uuid"),
    )
    name: str = Field(
        default="", description="New folder name. Required.",
        validation_alias=AliasChoices("name", "title", "new_name", "folder_name"),
    )


class RestoreNoteParams(BaseModel):
    """Restore a trashed note."""
    model_config = _MODEL_CONFIG

    note_id: str = Field(
        default="", description="Note UUID to restore. Required.",
        validation_alias=AliasChoices("note_id", "id", "noteId", "uuid"),
    )


class ResolveFolderParams(BaseModel):
    """Find a folder by name (case-insensitive)."""
    model_config = _MODEL_CONFIG

    name: str = Field(
        default="",
        description="Folder name to resolve (case-insensitive, whitespace-trimmed). Required.",
        validation_alias=AliasChoices("name", "title", "folder_name", "folderName", "query"),
    )


# ─── Folder Handlers ──────────────────────────────────────────────────── #

@chat.function("list_folders", action_type="read", description="List all note folders.")
async def fn_list_folders(ctx) -> ActionResult:
    """List all note folders."""
    try:
        folders = (await _api_get("/folders", {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx)})).get("folders", [])
        return ActionResult.success(
            data={"folders": [{"folder_id": f["id"], "name": f["name"]} for f in folders], "total": len(folders)},
            summary=f"Found {len(folders)} folder(s)",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "resolve_folder", action_type="read",
    description=(
        "Resolve a folder by name (case-insensitive). Returns the folder_id "
        "plus match_quality ('exact' | 'prefix' | 'contains' | 'none'). Use "
        "this INSTEAD of list_folders+manual-match when you only need one "
        "folder — it's a single call and gives a stable ID across chain steps."
    ),
)
async def fn_resolve_folder(ctx, params: ResolveFolderParams) -> ActionResult:
    """Find a folder by name — exact match preferred, then prefix, then substring."""
    try:
        target = params.name.strip().lower()
        if not target:
            return ActionResult.error("Folder name is required. Pass name (or title/folder_name).")

        folders = (await _api_get("/folders", {
            "user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
        })).get("folders", [])

        exact   = [f for f in folders if f["name"].strip().lower() == target]
        prefix  = [f for f in folders if f["name"].strip().lower().startswith(target)]
        contain = [f for f in folders if target in f["name"].strip().lower()]

        if exact:
            hit, quality = exact[0], "exact"
        elif prefix:
            hit, quality = prefix[0], "prefix"
        elif contain:
            hit, quality = contain[0], "contains"
        else:
            return ActionResult.success(
                data={"folder_id": None, "name": None, "match_quality": "none",
                      "candidates": [{"folder_id": f["id"], "name": f["name"]} for f in folders]},
                summary=f"No folder named '{params.name}' — {len(folders)} folder(s) exist",
            )

        return ActionResult.success(
            data={"folder_id": hit["id"], "name": hit["name"], "match_quality": quality},
            summary=f"Resolved '{params.name}' -> '{hit['name']}' ({quality} match)",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("create_folder", action_type="write", event="folder_created", description="Create a new folder.")
async def fn_create_folder(ctx, params: CreateFolderParams) -> ActionResult:
    """Create a new folder."""
    try:
        name = params.name.strip()
        if not name:
            return ActionResult.error("Folder name is required. Pass name (or title/folder_name).")
        folder = (await _api_post("/folders", {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
                                               "name": name, "icon": "folder"})).get("folder", {})
        return ActionResult.success(
            data={"folder_id": folder.get("id"), "name": folder.get("name"),
                  "refresh_panels": ["sidebar"]},
            summary=f"Folder created: {folder.get('name', params.name)}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("rename_folder", action_type="write", event="folder_renamed", description="Rename an existing folder.")
async def fn_rename_folder(ctx, params: RenameFolderParams) -> ActionResult:
    """Rename a folder."""
    try:
        if not params.folder_id.strip():
            return ActionResult.error(
                "Folder id is required. Find one with resolve_folder first."
            )
        if not params.name.strip():
            return ActionResult.error("New folder name must not be empty.")
        # notes-api PATCH /folders/{id} reads name/icon/sort_order as Query
        # parameters, not from the request body. Body is empty; auth + data
        # travel in the query string.
        await _api_patch(
            f"/folders/{params.folder_id}",
            {"user_id": require_user_id(ctx), "name": params.name},
            {},
        )
        return ActionResult.success(
            data={"folder_id": params.folder_id, "name": params.name,
                  "refresh_panels": ["sidebar"]},
            summary=f"Folder renamed to: {params.name}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("delete_folder", action_type="destructive", event="folder_deleted", description="Delete a folder (notes move to root).")
async def fn_delete_folder(ctx, params: FolderIdParams) -> ActionResult:
    """Delete a folder (notes move to root)."""
    try:
        if not params.folder_id.strip():
            return ActionResult.error(
                "Folder id is required. Find one with resolve_folder first."
            )
        await _api_delete(f"/folders/{params.folder_id}", {"user_id": require_user_id(ctx)})
        return ActionResult.success(
            data={"folder_id": params.folder_id, "refresh_panels": ["sidebar"]},
            summary="Folder deleted, notes moved to root",
        )
    except Exception as e:
        return ActionResult.error(str(e))


# ─── Trash Handlers ───────────────────────────────────────────────────── #

@chat.function("list_trash", action_type="read", description="List all notes in trash.")
async def fn_list_trash(ctx) -> ActionResult:
    """List all notes in trash."""
    try:
        notes = (await _api_get("/notes", {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
                                           "is_archived": True, "limit": 50})).get("notes", [])
        return ActionResult.success(
            data={"trash_notes": [{"note_id": n["id"], "title": n["title"], "word_count": n.get("word_count", 0),
                                   "tags": n.get("tags", [])} for n in notes], "total": len(notes)},
            summary=f"Trash contains {len(notes)} note(s)",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("restore_note", action_type="write", event="restored", description="Restore a note from trash.")
async def fn_restore_note(ctx, params: RestoreNoteParams) -> ActionResult:
    """Restore a note from trash."""
    try:
        if not params.note_id.strip():
            return ActionResult.error(
                "Note id is required to restore. Find one with list_trash first."
            )
        data = await _api_patch(f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)}, {"is_trashed": False})
        note = data.get("note", {})
        return ActionResult.success(
            data={"note_id": params.note_id, "title": note.get("title", ""), "folder_id": note.get("folder_id")},
            summary=f"Note restored: {note.get('title', '')}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("empty_trash", action_type="destructive", event="emptied", description="Permanently delete all trashed notes.")
async def fn_empty_trash(ctx) -> ActionResult:
    """Permanently delete all trashed notes."""
    try:
        data = await _api_post("/notes/trash/empty", params={"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx)})
        return ActionResult.success(data={"deleted_count": data.get("deleted_count", 0)},
                                    summary=f"Permanently deleted {data.get('deleted_count', 0)} note(s)")
    except Exception as e:
        return ActionResult.error(str(e))

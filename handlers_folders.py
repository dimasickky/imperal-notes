"""Notes · Folder & trash handlers."""
from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app import (
    chat, ActionResult, NotesAPIError,
    _api_get, _api_post, _api_patch, _api_delete,
    require_user_id, _tenant_id,
)


# ─── Models ───────────────────────────────────────────────────────────────── #

_MODEL_CONFIG = ConfigDict(populate_by_name=True)


class NoParams(BaseModel):
    """Empty params model for @chat.function handlers that take no business inputs (V17)."""
    model_config = _MODEL_CONFIG


class FolderIdParams(BaseModel):
    model_config = _MODEL_CONFIG

    folder_id: str = Field(
        default="", description="Folder UUID. Required.",
        validation_alias=AliasChoices("folder_id", "folder", "folderId", "id", "uuid"),
    )


class CreateFolderParams(BaseModel):
    model_config = _MODEL_CONFIG

    name: str = Field(
        default="", description="Folder name. Required.",
        validation_alias=AliasChoices("name", "title", "folder_name", "folderName"),
    )


class RenameFolderParams(BaseModel):
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
    model_config = _MODEL_CONFIG

    note_id: str = Field(
        default="", description="Note UUID to restore. Required.",
        validation_alias=AliasChoices("note_id", "id", "noteId", "uuid"),
    )


class ResolveFolderParams(BaseModel):
    model_config = _MODEL_CONFIG

    name: str = Field(
        default="",
        description="Folder name to resolve (case-insensitive, whitespace-trimmed). Required.",
        validation_alias=AliasChoices("name", "title", "folder_name", "folderName", "query"),
    )


# ─── Folder Handlers ──────────────────────────────────────────────────────── #

@chat.function(
    "list_folders",
    action_type="read",
    description="List all note folders.",
)
async def fn_list_folders(ctx) -> ActionResult:
    try:
        folders = (await _api_get(ctx, "/folders", {
            "user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
        })).get("folders", [])
        return ActionResult.success(
            data={"folders": [{"folder_id": f["id"], "name": f["name"]} for f in folders],
                  "total": len(folders)},
            summary=f"Found {len(folders)} folder(s)",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"list_folders backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "resolve_folder",
    action_type="read",
    description=(
        "Resolve a folder by name (case-insensitive). Returns the folder_id "
        "plus match_quality ('exact' | 'prefix' | 'contains' | 'none'). Use "
        "this INSTEAD of list_folders+manual-match when you only need one "
        "folder — it's a single call and gives a stable ID across chain steps."
    ),
)
async def fn_resolve_folder(ctx, params: ResolveFolderParams) -> ActionResult:
    try:
        target = params.name.strip().lower()
        if not target:
            return ActionResult.error("Folder name is required. Pass name (or title/folder_name).")

        folders = (await _api_get(ctx, "/folders", {
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
                data={
                    "folder_id":     None,
                    "name":          None,
                    "match_quality": "none",
                    "candidates":    [{"folder_id": f["id"], "name": f["name"]} for f in folders],
                },
                summary=f"No folder named '{params.name}' — {len(folders)} folder(s) exist",
            )

        return ActionResult.success(
            data={"folder_id": hit["id"], "name": hit["name"], "match_quality": quality},
            summary=f"Resolved '{params.name}' -> '{hit['name']}' ({quality} match)",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"resolve_folder backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "create_folder",
    action_type="write",
    chain_callable=True,
    effects=["create:folder"],
    event="folder_created",
    description="Create a new folder.",
)
async def fn_create_folder(ctx, params: CreateFolderParams) -> ActionResult:
    try:
        name = params.name.strip()
        if not name:
            return ActionResult.error("Folder name is required. Pass name (or title/folder_name).")
        folder = (await _api_post(ctx, "/folders", {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "name":      name,
            "icon":      "folder",
        })).get("folder", {})
        return ActionResult.success(
            data={"folder_id": folder.get("id"), "name": folder.get("name"),
                  "refresh_panels": ["sidebar"]},
            summary=f"Folder created: {folder.get('name', params.name)}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"create_folder backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "rename_folder",
    action_type="write",
    chain_callable=True,
    effects=["update:folder"],
    event="folder_renamed",
    description="Rename an existing folder.",
)
async def fn_rename_folder(ctx, params: RenameFolderParams) -> ActionResult:
    try:
        if not params.folder_id.strip():
            return ActionResult.error("Folder id is required. Find one with resolve_folder first.")
        if not params.name.strip():
            return ActionResult.error("New folder name must not be empty.")
        # notes-api PATCH /folders/{id} reads name as a Query param, not body.
        await _api_patch(
            ctx,
            f"/folders/{params.folder_id}",
            {"user_id": require_user_id(ctx), "name": params.name},
            {},
        )
        return ActionResult.success(
            data={"folder_id": params.folder_id, "name": params.name,
                  "refresh_panels": ["sidebar"]},
            summary=f"Folder renamed to: {params.name}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"rename_folder backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "delete_folder",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:folder"],
    event="folder_deleted",
    description="Delete a folder (notes move to root).",
)
async def fn_delete_folder(ctx, params: FolderIdParams) -> ActionResult:
    try:
        if not params.folder_id.strip():
            return ActionResult.error("Folder id is required. Find one with resolve_folder first.")
        await _api_delete(ctx, f"/folders/{params.folder_id}", {"user_id": require_user_id(ctx)})
        return ActionResult.success(
            data={"folder_id": params.folder_id, "refresh_panels": ["sidebar"]},
            summary="Folder deleted, notes moved to root",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"delete_folder backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


# ─── Trash Handlers ───────────────────────────────────────────────────────── #

@chat.function(
    "list_trash",
    action_type="read",
    description="List all notes in trash.",
)
async def fn_list_trash(ctx) -> ActionResult:
    try:
        notes = (await _api_get(ctx, "/notes", {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "is_trashed": True,
            "limit":     50,
        })).get("notes", [])
        return ActionResult.success(
            data={"trash_notes": [
                {"note_id": n["id"], "title": n["title"],
                 "word_count": n.get("word_count", 0), "tags": n.get("tags", [])}
                for n in notes
            ], "total": len(notes)},
            summary=f"Trash contains {len(notes)} note(s)",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"list_trash backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "restore_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="restored",
    description="Restore a note from trash.",
)
async def fn_restore_note(ctx, params: RestoreNoteParams) -> ActionResult:
    try:
        if not params.note_id.strip():
            return ActionResult.error("Note id is required to restore. Find one with list_trash first.")
        data = await _api_patch(ctx, f"/notes/{params.note_id}",
                                {"user_id": require_user_id(ctx)},
                                {"is_trashed": False})
        note = data.get("note", {})
        return ActionResult.success(
            data={"note_id": params.note_id, "title": note.get("title", ""),
                  "folder_id": note.get("folder_id")},
            summary=f"Note restored: {note.get('title', '')}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"restore_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "empty_trash",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:note"],
    event="emptied",
    description="Permanently delete all trashed notes.",
)
async def fn_empty_trash(ctx) -> ActionResult:
    try:
        data = await _api_post(ctx, "/notes/trash/empty",
                               params={"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx)})
        count = data.get("deleted_count", 0)
        return ActionResult.success(
            data={"deleted_count": count},
            summary=f"Permanently deleted {count} note(s)",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"empty_trash backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))

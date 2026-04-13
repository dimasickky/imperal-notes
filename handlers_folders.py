"""Notes · Folder & trash handlers."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import chat, ActionResult, _api_get, _api_post, _api_patch, _api_delete, _user_id, _tenant_id


# ─── Models ───────────────────────────────────────────────────────────── #

class FolderIdParams(BaseModel):
    """Target a specific folder."""
    folder_id: str = Field(description="Folder UUID")


class CreateFolderParams(BaseModel):
    """Create a new folder."""
    name: str = Field(description="Folder name")


class RestoreNoteParams(BaseModel):
    """Restore a trashed note."""
    note_id: str = Field(description="Note UUID to restore")


# ─── Folder Handlers ──────────────────────────────────────────────────── #

@chat.function("list_folders", action_type="read", description="List all note folders.")
async def fn_list_folders(ctx) -> ActionResult:
    try:
        folders = (await _api_get("/folders", {"user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx)})).get("folders", [])
        return ActionResult.success(
            data={"folders": [{"folder_id": f["id"], "name": f["name"]} for f in folders], "total": len(folders)},
            summary=f"Found {len(folders)} folder(s)",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("create_folder", action_type="write", event="folder_created", description="Create a new folder.")
async def fn_create_folder(ctx, params: CreateFolderParams) -> ActionResult:
    try:
        folder = (await _api_post("/folders", {"user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx),
                                               "name": params.name, "icon": "folder"})).get("folder", {})
        return ActionResult.success(
            data={"folder_id": folder.get("id"), "name": folder.get("name")},
            summary=f"Folder created: {folder.get('name', params.name)}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("delete_folder", action_type="destructive", event="folder_deleted", description="Delete a folder (notes move to root).")
async def fn_delete_folder(ctx, params: FolderIdParams) -> ActionResult:
    try:
        await _api_delete(f"/folders/{params.folder_id}", {"user_id": _user_id(ctx)})
        return ActionResult.success(data={"folder_id": params.folder_id}, summary="Folder deleted, notes moved to root")
    except Exception as e:
        return ActionResult.error(str(e))


# ─── Trash Handlers ───────────────────────────────────────────────────── #

@chat.function("list_trash", action_type="read", description="List all notes in trash.")
async def fn_list_trash(ctx) -> ActionResult:
    try:
        notes = (await _api_get("/notes", {"user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx),
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
    try:
        data = await _api_patch(f"/notes/{params.note_id}", {"user_id": _user_id(ctx)}, {"is_archived": False})
        note = data.get("note", {})
        return ActionResult.success(
            data={"note_id": params.note_id, "title": note.get("title", ""), "folder_id": note.get("folder_id")},
            summary=f"Note restored: {note.get('title', '')}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("empty_trash", action_type="destructive", event="emptied", description="Permanently delete all trashed notes.")
async def fn_empty_trash(ctx) -> ActionResult:
    try:
        data = await _api_post("/notes/trash/empty", params={"user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx)})
        return ActionResult.success(data={"deleted_count": data.get("deleted_count", 0)},
                                    summary=f"Permanently deleted {data.get('deleted_count', 0)} note(s)")
    except Exception as e:
        return ActionResult.error(str(e))

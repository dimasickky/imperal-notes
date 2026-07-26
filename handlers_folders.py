"""Notes · Folder & trash handlers."""

import logging
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app import (
    chat, ActionResult, NotesAPIError,
    _api_get, _api_post, _api_patch, _api_delete,
    require_user_id, _tenant_id, _resolve_folder_name, _resolve_folder_names,
    _resolve_folder_id_or_name, _bad_id,
)
from models_return import (
    ListFoldersResult, ResolveFolderResult, CreateFolderResult, RenameFolderResult,
    DeleteFolderResult, DeleteFolderWithContentsResult, BulkDeleteFoldersResult,
    ListTrashResult, RestoreNoteResult, EmptyTrashResult,
    FolderEntity, TrashNoteItem,
)
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, INTERNAL
from error_codes import NOTES_INVALID_NOTE_ID, NOTES_FOLDER_NOT_FOUND, NOTES_BACKEND_ERROR

log = logging.getLogger("notes.handlers")

# ─── Models ───────────────────────────────────────────────────────────────── #

_MODEL_CONFIG = ConfigDict(populate_by_name=True)


class NoParams(BaseModel):
    """Empty params model for @chat.function handlers that take no business inputs."""
    model_config = _MODEL_CONFIG


class FolderIdParams(BaseModel):
    model_config = _MODEL_CONFIG

    folder_id: str = Field(
        default="", description="Folder UUID. Required.",
        validation_alias=AliasChoices("folder_id", "folder", "folderId", "id", "uuid"),
    )


class DeleteFoldersParams(BaseModel):
    """Bulk-delete multiple folders by ID and/or name in one call.

    Pass folder_ids when you already have them (e.g. from the GUI multi-select,
    which injects checked IDs as message_ids into this same field), or
    folder_names to auto-resolve by display name.
    """
    model_config = _MODEL_CONFIG

    folder_ids: Optional[list[str]] = Field(
        default=None,
        description="List of folder UUIDs to delete. Use when you already have the IDs.",
        validation_alias=AliasChoices("folder_ids", "message_ids", "ids", "folder_id"),
    )
    folder_names: Optional[list[str]] = Field(
        default=None,
        description="List of folder names to find and delete. Auto-resolved to UUIDs.",
        validation_alias=AliasChoices("folder_names", "names", "titles"),
    )
    with_contents: bool = Field(
        default=False,
        description=(
            "If true, notes inside each folder are moved to trash (or permanently "
            "deleted if permanent=true) before the folder is removed. "
            "If false (default), notes are just detached (moved to root)."
        ),
    )
    permanent: bool = Field(
        default=False,
        description="Only applies when with_contents=true: permanently delete notes instead of trashing them.",
    )


class DeleteFolderWithContentsParams(BaseModel):
    model_config = _MODEL_CONFIG

    folder_id: str = Field(
        default="",
        description=(
            "Folder UUID OR folder name — pass the name directly (e.g. 'Groceries'), "
            "it will be auto-resolved to UUID. Do NOT leave empty."
        ),
        validation_alias=AliasChoices("folder_id", "folder", "folderId", "id", "uuid", "name"),
    )
    permanent: bool = Field(
        default=False,
        description=(
            "If true, permanently delete all notes (cannot be undone). "
            "If false (default), move notes to trash first, then delete folder."
        ),
        validation_alias=AliasChoices("permanent", "hard_delete", "force_delete"),
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
    data_model=ListFoldersResult,
)
async def fn_list_folders(ctx, params: NoParams) -> ActionResult:
    try:
        folders = (await _api_get(ctx, "/folders", {
            "user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
        })).get("folders", [])
        return ActionResult.success(
            data={"items": [FolderEntity(id=f["id"], title=f["name"], kind="folder").model_dump() for f in folders],
                  "total": len(folders)},
            summary=f"Found {len(folders)} folder(s)",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"list_folders backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("list_folders: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "resolve_folder",
    action_type="read",
    description=(
        "Resolve a notes folder by name (case-insensitive). Returns the folder_id "
        "plus match_quality ('exact' | 'prefix' | 'contains' | 'none'). Use "
        "this INSTEAD of list_folders+manual-match when you only need one "
        "folder — it's a single call and gives a stable ID across chain steps."
    ),
    data_model=FolderEntity,
)
async def fn_resolve_folder(ctx, params: ResolveFolderParams) -> ActionResult:
    try:
        target = params.name.strip().lower()
        if not target:
            return ActionResult.error("Folder name is required. Pass name (or title/folder_name).", code=VALIDATION_MISSING_FIELD)

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
            available = ", ".join(f["name"] for f in folders[:10])
            return ActionResult.error(
                f"Folder '{params.name}' not found. Available folders: {available}",
                code=NOTES_FOLDER_NOT_FOUND,
            )

        entity = FolderEntity(id=hit["id"], title=hit["name"], kind="folder")
        return ActionResult.success(
            data=entity,
            summary=f"Folder '{entity.title}' (id={entity.id}) — {quality} match",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"resolve_folder backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("resolve_folder: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "create_folder",
    action_type="write",
    chain_callable=True,
    effects=["create:folder"],
    event="folder_created",
    description="Create a new notes folder.",
    data_model=CreateFolderResult,
)
async def fn_create_folder(ctx, params: CreateFolderParams) -> ActionResult:
    try:
        name = params.name.strip()
        if not name:
            return ActionResult.error("Folder name is required. Pass name (or title/folder_name).", code=VALIDATION_MISSING_FIELD)
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
        return ActionResult.error(f"create_folder backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("create_folder: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "rename_folder",
    action_type="write",
    chain_callable=True,
    effects=["update:folder"],
    event="folder_renamed",
    description="Rename an existing notes folder.",
    data_model=RenameFolderResult,
)
async def fn_rename_folder(ctx, params: RenameFolderParams) -> ActionResult:
    try:
        if not params.name.strip():
            return ActionResult.error("New folder name must not be empty.", code=VALIDATION_MISSING_FIELD)
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        # the backend PATCH /folders/{id} reads name as a Query param, not body.
        await _api_patch(
            ctx,
            f"/folders/{folder_id}",
            {"user_id": require_user_id(ctx), "name": params.name},
            {},
        )
        return ActionResult.success(
            data={"folder_id": folder_id, "name": params.name,
                  "refresh_panels": ["sidebar"]},
            summary=f"Folder renamed to: {params.name}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"rename_folder backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("rename_folder: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_folder",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:folder"],
    event="folder_deleted",
    description="Delete a folder (notes move to root).",
    data_model=DeleteFolderResult,
)
async def fn_delete_folder(ctx, params: FolderIdParams) -> ActionResult:
    try:
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        await _api_delete(ctx, f"/folders/{folder_id}", {"user_id": require_user_id(ctx)})
        return ActionResult.success(
            data={"folder_id": folder_id, "refresh_panels": ["sidebar"]},
            summary="Folder deleted, notes moved to root",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"delete_folder backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_folder: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_folder_with_contents",
    action_type="destructive",
    chain_callable=True,
    id_projection="folder_id",
    effects=["trash:note", "delete:note", "delete:folder"],
    event="folder_with_contents_deleted",
    description=(
        "Delete a folder AND all notes inside it. "
        "folder_id accepts a folder UUID OR a folder name — auto-resolved either way. "
        "By default moves notes to trash then deletes the folder; "
        "pass permanent=true to permanently delete notes instead."
    ),
    data_model=DeleteFolderWithContentsResult,
)
async def fn_delete_folder_with_contents(
    ctx, params: DeleteFolderWithContentsParams,
) -> ActionResult:
    try:
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id.strip())
        if not folder_id:
            return ActionResult.error(
                "Folder not found. Pass folder_id with the folder name or UUID.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        uid = require_user_id(ctx)

        # Step 1: delete all notes in the folder via bulk endpoint
        notes_resp = await _api_delete(ctx, "/notes/bulk", {
            "user_id":   uid,
            "folder_id": folder_id,
            "permanent": "true" if params.permanent else "false",
        })
        deleted_count = notes_resp.get("deleted_count", 0)

        # Step 2: delete the folder itself (now empty)
        await _api_delete(ctx, f"/folders/{folder_id}", {"user_id": uid})

        action = "permanently deleted" if params.permanent else "moved to trash"
        return ActionResult.success(
            data={
                "folder_id":     folder_id,
                "deleted_count": deleted_count,
                "permanent":     params.permanent,
                "refresh_panels": ["sidebar"],
            },
            summary=f"Folder deleted; {deleted_count} note(s) {action}",
        )
    except NotesAPIError as e:
        return ActionResult.error(
            f"delete_folder_with_contents backend returned {e.status_code}: {e.detail}",
            code=NOTES_BACKEND_ERROR,
        )
    except Exception as e:
        log.error("delete_folder_with_contents: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_folders",
    action_type="destructive",
    effects=["delete:folder"],
    event="folders_bulk_deleted",
    description=(
        "Delete MULTIPLE folders at once. Pass folder_ids (list) OR folder_names "
        "(list of names). By default notes inside are just detached (moved to root); "
        "pass with_contents=true to trash (or permanent=true to permanently delete) "
        "the notes inside each folder too. Use for bulk/multi-select folder cleanup."
    ),
    data_model=BulkDeleteFoldersResult,
)
async def fn_delete_folders(ctx, params: DeleteFoldersParams) -> ActionResult:
    try:
        uid = require_user_id(ctx)

        ids: list = []
        seen: set = set()
        for fid in (params.folder_ids or []):
            fid = (fid or "").strip()
            if fid and fid not in seen:
                seen.add(fid)
                ids.append(fid)

        not_found: list = []
        # ONE backend call for every name, instead of one per name: the old loop
        # called _resolve_folder_name per entry and that refetches the whole
        # folder list each time. Dedup against ids already collected from
        # folder_ids, so naming a folder that was also passed by id does not
        # delete-count it twice.
        resolved_ids, not_found = await _resolve_folder_names(ctx, params.folder_names)
        for resolved in resolved_ids:
            if resolved not in seen:
                seen.add(resolved)
                ids.append(resolved)

        if not ids:
            return ActionResult.error(
                "No valid folders to delete. Pass folder_ids or folder_names "
                "(use list_folders() first to get real IDs/names).",
                code=VALIDATION_MISSING_FIELD,
            )

        resp = await _api_post(ctx, "/folders/bulk-delete", {
            "user_id":       uid,
            "folder_ids":    ids,
            "with_contents": params.with_contents,
            "permanent":     params.permanent,
        })
        deleted_count = resp.get("deleted_count", 0)
        deleted_ids = resp.get("folder_ids", ids)

        summary = f"Deleted {deleted_count} folder(s)"
        if not_found:
            summary += f"; {len(not_found)} name(s) not found: {', '.join(not_found)}"

        return ActionResult.success(
            data={
                "deleted_count":  deleted_count,
                "folder_ids":     deleted_ids,
                "not_found":      not_found,
                "with_contents":  params.with_contents,
                "permanent":      params.permanent,
                "refresh_panels": ["sidebar"],
            },
            summary=summary,
        )
    except NotesAPIError as e:
        return ActionResult.error(f"delete_folders backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_folders: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


# ─── Trash Handlers ───────────────────────────────────────────────────────── #

@chat.function(
    "list_trash",
    action_type="read",
    description="List all notes in trash.",
    data_model=ListTrashResult,
)
async def fn_list_trash(ctx, params: NoParams) -> ActionResult:
    try:
        resp = await _api_get(ctx, "/notes", {
            "user_id":    require_user_id(ctx),
            "tenant_id":  _tenant_id(ctx),
            "is_trashed": True,
            "limit":      50,
        })
        notes = resp.get("notes", [])
        total_count = resp.get("total_count")
        has_more = resp.get("has_more", False)
        return ActionResult.success(
            data={
                "items": [
                    TrashNoteItem(
                        id=n["id"], title=n["title"], kind="note",
                        word_count=n.get("word_count", 0), tags=n.get("tags", []),
                    ).model_dump()
                    for n in notes
                ],
                "page_size":   len(notes),
                "total_count": int(total_count) if total_count is not None else None,
                "has_more":    has_more,
            },
            summary=(
                f"Trash: {len(notes)} note(s)"
                + (f" of {total_count} total" if total_count is not None else "")
                + ("; more available — call list_trash again with offset" if has_more else "")
            ),
        )
    except NotesAPIError as e:
        return ActionResult.error(f"list_trash backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("list_trash: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "restore_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="restored",
    description="Restore a note from trash.",
    data_model=RestoreNoteResult,
)
async def fn_restore_note(ctx, params: RestoreNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
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
        return ActionResult.error(f"restore_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("restore_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "empty_trash",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:note"],
    event="emptied",
    description="Permanently delete all trashed notes.",
    data_model=EmptyTrashResult,
)
async def fn_empty_trash(ctx, params: NoParams) -> ActionResult:
    try:
        data = await _api_post(ctx, "/notes/trash/empty",
                               params={"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx)})
        count = data.get("deleted_count", 0)
        return ActionResult.success(
            data={"deleted_count": count},
            summary=f"Permanently deleted {count} note(s)",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"empty_trash backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("empty_trash: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)

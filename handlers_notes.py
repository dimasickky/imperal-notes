"""Notes · CRUD handlers."""
from __future__ import annotations

import logging

from app import (
    chat, ActionResult,
    NotesAPIError,
    _api_get, _api_patch, _api_post, _api_delete,
    require_user_id, _tenant_id, _resolve_folder_id_or_name, _bad_id,
)
from models_notes import (  # noqa: E402
    MAX_NOTES_PER_PAGE, MAX_SEARCH_PER_PAGE,
    AppendNoteParams, CreateNoteParams, DeleteNotesFromFolderParams, ListNotesParams,
    MoveNoteParams, NoteIdParams, SearchNotesParams, UpdateNoteParams,
    BulkNotesParams, DeleteNotesParams,
)
from models_return import (
    ListNotesResult, NoteEntity, NoteListItem, SearchNoteItem,
    CreateNoteResult, UpdateNoteResult,
    MoveNoteResult, DeleteNoteResult, BulkDeleteNotesResult, SearchNotesResult,
    BulkNotesActionResult,
)
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, INTERNAL
from error_codes import NOTES_INVALID_NOTE_ID, NOTES_FOLDER_NOT_FOUND, NOTES_BACKEND_ERROR, NOTES_NOTE_NOT_FOUND

log = logging.getLogger("notes.handlers")


@chat.function(
    "list_notes",
    action_type="read",
    description=(
        "List notes (paginated). Returns up to `limit` rows per call "
        f"(max {MAX_NOTES_PER_PAGE}). If `has_more` is true, call again with "
        "`offset=offset+limit` to fetch the next page."
    ),
    data_model=ListNotesResult,
)
async def fn_list_notes(ctx, params: ListNotesParams) -> ActionResult:
    try:
        qp: dict = {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "limit":     params.limit,
            "offset":    params.offset,
        }
        if params.folder_id:
            folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
            if not folder_id:
                return ActionResult.error(
                    f"Folder '{params.folder_id}' not found. "
                    "Use list_folders() to see available folders.",
                    code=NOTES_FOLDER_NOT_FOUND,
                )
            qp["folder_id"] = folder_id
        if params.search:                  qp["search"] = params.search
        if params.tags:                    qp["tags"] = ",".join(params.tags)
        if params.is_archived is not None: qp["is_archived"] = params.is_archived
        if params.is_trashed is not None:  qp["is_trashed"] = params.is_trashed

        resp = await _api_get(ctx, "/notes", qp)
        notes = resp.get("notes", [])

        total_count = resp.get("total_count")
        if total_count is None:
            has_more = len(notes) == params.limit
            total_known = False
        else:
            has_more = (params.offset + len(notes)) < int(total_count)
            total_known = True

        next_offset = params.offset + len(notes) if has_more else None

        return ActionResult.success(
            data={
                "items": [
                    NoteListItem(
                        id=n["id"],
                        title=n["title"] or "Untitled",
                        kind="note",
                        tags=n.get("tags") or [],
                        is_pinned=n.get("is_pinned", False),
                        is_archived=n.get("is_archived", False),
                        is_trashed=n.get("is_trashed", False),
                        word_count=n.get("word_count", 0),
                        folder_id=n.get("folder_id"),
                        created_at=str(n.get("created_at") or ""),
                        updated_at=str(n.get("updated_at") or ""),
                    ).model_dump()
                    for n in notes
                ],
                "page_size":   len(notes),
                "offset":      params.offset,
                "limit":       params.limit,
                "has_more":    has_more,
                "next_offset": next_offset,
                "total_count": int(total_count) if total_known else None,
            },
            summary=(
                f"{len(notes)} note(s) on this page"
                + (f" of {total_count} total" if total_known else "")
                + (f"; more available (next_offset={next_offset})" if has_more else "")
            ),
        )
    except NotesAPIError as e:
        return ActionResult.error(f"list_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("list_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "get_note",
    action_type="read",
    description="Get full content of a note by ID.",
    data_model=NoteEntity,
)
async def fn_get_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        data = await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)})
        note = data.get("note", {})
        entity = NoteEntity(
            id=note.get("id"),
            title=note.get("title") or "Untitled",
            kind="note",
            body=note.get("content_text", ""),
            tags=note.get("tags") or [],
            is_pinned=note.get("is_pinned", False),
            is_archived=note.get("is_archived", False),
            is_trashed=note.get("is_trashed", False),
            word_count=note.get("word_count", 0),
            folder_id=note.get("folder_id"),
            created_at=str(note.get("created_at") or ""),
            updated_at=str(note.get("updated_at") or ""),
        )
        return ActionResult.success(
            data=entity,
            summary=f"Note '{entity.title}' (id={entity.id})",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"get_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("get_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "create_note",
    action_type="write",
    chain_callable=True,
    effects=["create:note"],
    event="created",
    description="Create a new note with title, content, tags, and optional folder.",
    data_model=CreateNoteResult,
)
async def fn_create_note(ctx, params: CreateNoteParams) -> ActionResult:
    try:
        title   = params.title.strip()
        content = params.content_text

        if not title and not content.strip():
            return ActionResult.error(
                "Note must have a title or content. Pass title and/or content_text.",
                code=VALIDATION_MISSING_FIELD,
            )

        if title and len(title) >= 3 and content.startswith(title):
            log.warning(
                "title-bleed detected on create_note (title=%r); stripping duplicate prefix",
                title[:40],
            )
            content = content[len(title):].lstrip(": \n\t")

        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if params.folder_id and not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )

        body: dict = {
            "user_id":      require_user_id(ctx),
            "tenant_id":    _tenant_id(ctx),
            "title":        title,
            "content_text": content,
            "tags":         params.tags,
        }
        if folder_id:
            body["folder_id"] = folder_id

        note = (await _api_post(ctx, "/notes", body)).get("note", {})
        return ActionResult.success(
            data={
                "note_id":   note.get("id"),
                "title":     note.get("title"),
                "folder_id": folder_id or None,
            },
            summary=f"Note created: {note.get('title', params.title)}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"create_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("create_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "update_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="updated",
    description=(
        "Update note fields (title, tags, pin) or REPLACE its content. "
        "WARNING: content_text OVERWRITES the entire body — to ADD text to an "
        "existing note use append_to_note instead."
    ),
    data_model=UpdateNoteResult,
)
async def fn_update_note(ctx, params: UpdateNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        updates: dict = {}
        if params.title:                 updates["title"] = params.title
        if params.content_text:          updates["content_text"] = params.content_text
        if params.tags is not None:      updates["tags"] = params.tags
        if params.is_pinned is not None: updates["is_pinned"] = params.is_pinned
        if not updates:
            return ActionResult.error("No fields to update", code=VALIDATION_MISSING_FIELD)

        user_id = require_user_id(ctx)
        current = (await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": user_id})).get("note", {})

        changed: dict = {}
        for field, value in updates.items():
            cur = current.get(field)
            if field == "tags":
                if set(value) != set(cur or []):
                    changed[field] = value
            else:
                if value != cur:
                    changed[field] = value

        title = current.get("title", "")

        if not changed:
            return ActionResult.success(
                data={"note_id": params.note_id, "title": title, "was_changed": False},
                summary=f"Note is already up to date: {title}",
            )

        data = await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": user_id}, changed)
        title = data.get("note", {}).get("title", title)
        return ActionResult.success(
            data={"note_id": params.note_id, "title": title, "fields_updated": list(changed.keys()), "was_changed": True},
            summary=f"Note updated: {title}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"update_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("update_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "append_to_note",
    action_type="write",
    chain_callable=True,
    id_projection="note_id",
    effects=["update:note"],
    event="updated",
    description=(
        "Append text to the END of an existing note's body WITHOUT overwriting it. "
        "Reads the current note, adds the new text after the existing content, then saves. "
        "Use this for any 'add to note / append / допиши / добавь в заметку' request — never "
        "use update_note to add content, because update_note REPLACES the whole body."
    ),
    data_model=NoteEntity,
)
async def fn_append_to_note(ctx, params: AppendNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        addition = params.content_text.strip()
        if not addition:
            return ActionResult.error(
                "Nothing to append. Pass content_text with the text to add.",
                code=VALIDATION_MISSING_FIELD,
            )

        user_id = require_user_id(ctx)
        current = (await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": user_id})).get("note", {})
        existing = (current.get("content_text") or "").rstrip()
        merged = f"{existing}\n\n{addition}" if existing else addition

        note = (await _api_patch(
            ctx, f"/notes/{params.note_id}",
            {"user_id": user_id},
            {"content_text": merged},
        )).get("note", {})

        entity = NoteEntity(
            id=note.get("id") or params.note_id,
            title=note.get("title") or current.get("title") or "Untitled",
            kind="note",
            body=note.get("content_text", merged),
            tags=note.get("tags") or [],
            is_pinned=note.get("is_pinned", False),
            is_archived=note.get("is_archived", False),
            word_count=note.get("word_count", 0),
            folder_id=note.get("folder_id"),
        )
        return ActionResult.success(
            data=entity,
            summary=f"Appended to note '{entity.title}'",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"append_to_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("append_to_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "move_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="moved",
    description="Move note to a folder, or root with empty folder_id.",
    data_model=MoveNoteResult,
)
async def fn_move_note(ctx, params: MoveNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if params.folder_id and not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        data = await _api_patch(
            ctx, f"/notes/{params.note_id}",
            {"user_id": require_user_id(ctx)},
            {"folder_id": folder_id if folder_id else None},
        )
        target = folder_id or "All Notes"
        return ActionResult.success(
            data={
                "note_id":   params.note_id,
                "title":     data.get("note", {}).get("title", ""),
                "folder_id": folder_id or None,
                "moved_to":  target,
            },
            summary=f"Note moved to {target}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"move_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("move_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_note",
    action_type="destructive",
    chain_callable=True,
    effects=["trash:note"],
    event="deleted",
    description="Delete a note (moves to trash).",
    data_model=DeleteNoteResult,
)
async def fn_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        await _api_delete(ctx, f"/notes/{params.note_id}",
                          {"user_id": require_user_id(ctx), "permanent": "false"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note moved to trash")
    except NotesAPIError as e:
        return ActionResult.error(f"delete_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "permanent_delete_note",
    action_type="destructive",
    chain_callable=True,
    id_projection="note_id",
    effects=["delete:note"],
    event="permanently_deleted",
    description="Permanently delete a note. Cannot be undone.",
    data_model=DeleteNoteResult,
)
async def fn_permanent_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        await _api_delete(ctx, f"/notes/{params.note_id}",
                          {"user_id": require_user_id(ctx), "permanent": "true"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note permanently deleted")
    except NotesAPIError as e:
        return ActionResult.error(f"permanent_delete_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("permanent_delete_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_notes_from_folder",
    action_type="destructive",
    chain_callable=True,
    id_projection="folder_id",
    effects=["trash:note", "delete:note"],
    event="bulk_deleted",
    description=(
        "Delete ALL notes in a folder (bulk). By default moves them to trash; "
        "pass permanent=true to permanently delete instead. "
        "folder_id accepts a folder UUID OR a folder name — auto-resolved either way."
    ),
    data_model=BulkDeleteNotesResult,
)
async def fn_delete_notes_from_folder(ctx, params: DeleteNotesFromFolderParams) -> ActionResult:
    try:
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id.strip())
        if not folder_id:
            return ActionResult.error(
                "Folder not found. Pass folder_id with the folder name or UUID.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        resp = await _api_delete(ctx, "/notes/bulk", {
            "user_id":   require_user_id(ctx),
            "folder_id": folder_id,
            "permanent": "true" if params.permanent else "false",
        })
        deleted = resp.get("deleted_count", 0)
        action  = "permanently deleted" if params.permanent else "moved to trash"
        return ActionResult.success(
            data={"deleted_count": deleted, "folder_id": folder_id,
                  "permanent": params.permanent},
            summary=f"{deleted} note(s) {action}" if deleted else "No notes in folder — nothing to delete",
        )
    except NotesAPIError as e:
        return ActionResult.error(
            f"delete_notes_from_folder backend returned {e.status_code}: {e.detail}",
            code=NOTES_BACKEND_ERROR,
        )
    except Exception as e:
        log.error("delete_notes_from_folder: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


# ── Bulk actions over an explicit note-id set ─────────────────────────────── #

async def _resolve_bulk_ids(ctx, note_ids, note_titles, scope_filter: dict) -> tuple[list, list]:
    """Resolve note_ids + note_titles → (resolved_ids, not_found_titles). De-duped.

    Titles are matched against notes in the given scope (active / archived /
    trashed) via the list endpoint — NOT fulltext search, which by design never
    returns archived or trashed rows (so restore/unarchive by title would
    otherwise always miss the very notes they target).
    """
    ids: list = []
    seen: set = set()
    for nid in (note_ids or []):
        nid = (nid or "").strip()
        if nid and not _bad_id(nid) and nid not in seen:
            seen.add(nid)
            ids.append(nid)
    not_found: list = []
    titles = [t.strip() for t in (note_titles or []) if (t or "").strip()]
    if titles:
        qp = {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
              "limit": MAX_NOTES_PER_PAGE, "offset": 0}
        qp.update(scope_filter)
        resp = await _api_get(ctx, "/notes", qp)
        pool = resp.get("notes", []) if isinstance(resp, dict) else []
        for title in titles:
            tl = title.lower()
            match = next(
                (n for n in pool if (n.get("title") or "").strip().lower() == tl),
                next((n for n in pool if tl in (n.get("title") or "").strip().lower()), None),
            )
            if match and match.get("id") and match["id"] not in seen:
                seen.add(match["id"])
                ids.append(match["id"])
            elif not match:
                not_found.append(title)
    return ids, not_found


# Title-resolution scopes per action (list-endpoint filters).
_SCOPE_ACTIVE   = {"is_archived": False, "is_trashed": False}
_SCOPE_ARCHIVED = {"is_archived": True}
_SCOPE_TRASHED  = {"is_trashed": True}


async def _bulk_action(ctx, params, *, action: str, ok_verb: str, scope_filter: dict) -> ActionResult:
    ids, not_found = await _resolve_bulk_ids(ctx, params.note_ids, params.note_titles, scope_filter)
    if not ids:
        if not_found:
            return ActionResult.error(f"No matching notes found for: {', '.join(not_found)}.", code=NOTES_NOTE_NOT_FOUND)
        return ActionResult.error("Pass note_ids or note_titles — nothing to act on.", code=VALIDATION_MISSING_FIELD)
    resp = await _api_post(ctx, "/notes/bulk-action", {
        "user_id": require_user_id(ctx), "note_ids": ids, "action": action,
    })
    affected = resp.get("affected_count", 0) if isinstance(resp, dict) else 0
    summary = f"{affected} note(s) {ok_verb}"
    if not_found:
        summary += f" ({len(not_found)} not found: {', '.join(not_found)})"
    return ActionResult.success(
        data={
            "affected_count": affected,
            "action": action,
            "note_ids": (resp.get("note_ids", ids) if isinstance(resp, dict) else ids),
            "not_found": not_found,
            "refresh_panels": ["__panel__sidebar"],
        },
        summary=summary,
    )


@chat.function(
    "delete_notes",
    action_type="destructive",
    chain_callable=True,
    effects=["trash:note", "delete:note"],
    event="bulk_deleted",
    description=(
        "Delete MULTIPLE notes at once. Pass note_ids (list of IDs) OR note_titles "
        "(list of names, auto-resolved). Moves them to trash by default; pass "
        "permanent=true to delete permanently. Use when the user wants to delete 2+ notes."
    ),
    data_model=BulkNotesActionResult,
)
async def fn_delete_notes(ctx, params: DeleteNotesParams) -> ActionResult:
    try:
        return await _bulk_action(
            ctx, params,
            action="permanent" if params.permanent else "trash",
            ok_verb="permanently deleted" if params.permanent else "moved to trash",
            scope_filter=_SCOPE_ACTIVE,
        )
    except NotesAPIError as e:
        return ActionResult.error(f"delete_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "archive_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_archived",
    description="Archive MULTIPLE notes at once. Pass note_ids (list) OR note_titles (list of names).",
    data_model=BulkNotesActionResult,
)
async def fn_archive_notes(ctx, params: BulkNotesParams) -> ActionResult:
    try:
        return await _bulk_action(ctx, params, action="archive", ok_verb="archived",
                                  scope_filter=_SCOPE_ACTIVE)
    except NotesAPIError as e:
        return ActionResult.error(f"archive_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("archive_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "unarchive_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_unarchived",
    description="Remove MULTIPLE notes from the archive (unarchive). Pass note_ids OR note_titles.",
    data_model=BulkNotesActionResult,
)
async def fn_unarchive_notes(ctx, params: BulkNotesParams) -> ActionResult:
    try:
        return await _bulk_action(ctx, params, action="unarchive", ok_verb="unarchived",
                                  scope_filter=_SCOPE_ARCHIVED)
    except NotesAPIError as e:
        return ActionResult.error(f"unarchive_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("unarchive_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "restore_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_restored",
    description="Restore MULTIPLE notes from trash. Pass note_ids OR note_titles.",
    data_model=BulkNotesActionResult,
)
async def fn_restore_notes(ctx, params: BulkNotesParams) -> ActionResult:
    try:
        return await _bulk_action(ctx, params, action="restore", ok_verb="restored",
                                  scope_filter=_SCOPE_TRASHED)
    except NotesAPIError as e:
        return ActionResult.error(f"restore_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("restore_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "search_notes",
    action_type="read",
    description=(
        "Full-text search across all notes (paginated). Returns up to `limit` "
        f"results per call (max {MAX_SEARCH_PER_PAGE}). If `has_more` is true, "
        "call again with `offset=offset+limit` to fetch the next page. "
        "Do NOT claim to have searched all notes until `has_more` is false."
    ),
    data_model=SearchNotesResult,
)
async def fn_search_notes(ctx, params: SearchNotesParams) -> ActionResult:
    try:
        if not params.query.strip():
            return ActionResult.error("Search query is required. Pass query (or q).", code=VALIDATION_MISSING_FIELD)
        resp = await _api_get(ctx, "/notes/search/fulltext", {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "q":         params.query,
            "limit":     params.limit,
            "offset":    params.offset,
            "include_archived": params.include_archived,
            "include_trashed":  params.include_trashed,
        })
        results = resp.get("results", [])

        total_count = resp.get("total_count")
        if total_count is None:
            has_more = len(results) == params.limit
            total_known = False
        else:
            has_more = (params.offset + len(results)) < int(total_count)
            total_known = True

        next_offset = params.offset + len(results) if has_more else None

        return ActionResult.success(
            data={
                "items": [
                    SearchNoteItem(
                        id=r.get("id"),
                        title=r.get("title") or "Untitled",
                        kind="note",
                        excerpt=r.get("excerpt", "")[:200],
                    ).model_dump()
                    for r in results
                ],
                "query":       params.query,
                "page_size":   len(results),
                "offset":      params.offset,
                "limit":       params.limit,
                "has_more":    has_more,
                "next_offset": next_offset,
                "total_count": int(total_count) if total_known else None,
            },
            summary=(
                f"{len(results)} result(s) on this page for '{params.query}'"
                + (f" of {total_count} total" if total_known else "")
                + (f"; more available (next_offset={next_offset})" if has_more else "")
            ),
        )
    except NotesAPIError as e:
        return ActionResult.error(f"search_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("search_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)

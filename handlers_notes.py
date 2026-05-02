"""Notes · CRUD handlers."""
from __future__ import annotations

import logging
import re

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _bad_id(note_id: str) -> str | None:
    """Return error message if note_id is not a valid UUID4, else None."""
    if not note_id or not note_id.strip():
        return "note_id is required. Call list_notes() or search_notes() first to get real IDs."
    if not _UUID_RE.match(note_id.strip()):
        return (
            f"'{note_id}' is not a valid note ID. Note IDs are UUID4 strings "
            "(e.g. '3f2504e0-4f89-11d3-9a0c-0305e82c3301'). "
            "Call list_notes() or search_notes() first to get real IDs — never guess them."
        )
    return None


from app import (  # noqa: E402
    chat, ActionResult,
    NotesAPIError,
    _api_get, _api_patch, _api_post, _api_delete,
    require_user_id, _tenant_id,
)
from models_notes import (  # noqa: E402
    MAX_NOTES_PER_PAGE, MAX_SEARCH_PER_PAGE,
    CreateNoteParams, DeleteNotesFromFolderParams, ListNotesParams, MoveNoteParams,
    NoteIdParams, SearchNotesParams, UpdateNoteParams,
)

log = logging.getLogger("notes.handlers")


@chat.function(
    "list_notes",
    action_type="read",
    description=(
        "List notes (paginated). Returns up to `limit` rows per call "
        f"(max {MAX_NOTES_PER_PAGE}). If `has_more` is true, call again with "
        "`offset=offset+limit` to fetch the next page."
    ),
)
async def fn_list_notes(ctx, params: ListNotesParams) -> ActionResult:
    try:
        qp: dict = {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "limit":     params.limit,
            "offset":    params.offset,
        }
        if params.folder_id: qp["folder_id"] = params.folder_id
        if params.search:    qp["search"] = params.search
        if params.tags:      qp["tags"] = ",".join(params.tags)

        resp = await _api_get(ctx, "/notes", qp)
        notes = resp.get("notes", [])

        if params.tags:
            wanted = {t.strip().lower() for t in params.tags if t.strip()}
            if wanted:
                notes = [
                    n for n in notes
                    if wanted.issubset({str(t).lower() for t in n.get("tags", [])})
                ]

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
                "notes": [{
                    "note_id":     n["id"],
                    "title":       n["title"],
                    "word_count":  n.get("word_count", 0),
                    "is_pinned":   n.get("is_pinned", False),
                    "is_archived": n.get("is_archived", False),
                    "tags":        n.get("tags", []),
                    "folder_id":   n.get("folder_id"),
                } for n in notes],
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
        return ActionResult.error(f"list_notes backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "get_note",
    action_type="read",
    description="Get full content of a note by ID.",
)
async def fn_get_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        data = await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)})
        note = data.get("note", {})
        return ActionResult.success(
            data={
                "note_id":     note.get("id"),
                "title":       note.get("title"),
                "content":     note.get("content_text", ""),
                "tags":        note.get("tags", []),
                "is_pinned":   note.get("is_pinned", False),
                "is_archived": note.get("is_archived", False),
                "word_count":  note.get("word_count", 0),
                "folder_id":   note.get("folder_id"),
            },
            summary=f"Note: {note.get('title', 'Untitled')}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"get_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "create_note",
    action_type="write",
    chain_callable=True,
    effects=["create:note"],
    event="created",
    description="Create a new note with title, content, tags, and optional folder.",
)
async def fn_create_note(ctx, params: CreateNoteParams) -> ActionResult:
    try:
        title   = params.title.strip()
        content = params.content_text

        if not title and not content.strip():
            return ActionResult.error(
                "Note must have a title or content. Pass title and/or content_text."
            )

        if title and len(title) >= 3 and content.startswith(title):
            log.warning(
                "title-bleed detected on create_note (title=%r); stripping duplicate prefix",
                title[:40],
            )
            content = content[len(title):].lstrip(": \n\t")

        body: dict = {
            "user_id":      require_user_id(ctx),
            "tenant_id":    _tenant_id(ctx),
            "title":        title,
            "content_text": content,
            "tags":         params.tags,
        }
        if params.folder_id:
            body["folder_id"] = params.folder_id

        note = (await _api_post(ctx, "/notes", body)).get("note", {})
        return ActionResult.success(
            data={
                "note_id":   note.get("id"),
                "title":     note.get("title"),
                "folder_id": params.folder_id or None,
            },
            summary=f"Note created: {note.get('title', params.title)}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"create_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "update_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="updated",
    description="Update note title, content, tags, or pin status.",
)
async def fn_update_note(ctx, params: UpdateNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        updates: dict = {}
        if params.title:                 updates["title"] = params.title
        if params.content_text:          updates["content_text"] = params.content_text
        if params.tags is not None:      updates["tags"] = params.tags
        if params.is_pinned is not None: updates["is_pinned"] = params.is_pinned
        if not updates:
            return ActionResult.error("No fields to update")
        data = await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)}, updates)
        title = data.get("note", {}).get("title", "")
        return ActionResult.success(
            data={"note_id": params.note_id, "title": title, "fields_updated": list(updates.keys())},
            summary=f"Note updated: {title}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"update_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "move_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="moved",
    description="Move note to a folder, or root with empty folder_id.",
)
async def fn_move_note(ctx, params: MoveNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        data = await _api_patch(
            ctx, f"/notes/{params.note_id}",
            {"user_id": require_user_id(ctx)},
            {"folder_id": params.folder_id if params.folder_id else None},
        )
        target = params.folder_id or "All Notes"
        return ActionResult.success(
            data={
                "note_id":   params.note_id,
                "title":     data.get("note", {}).get("title", ""),
                "folder_id": params.folder_id or None,
                "moved_to":  target,
            },
            summary=f"Note moved to {target}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"move_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "delete_note",
    action_type="destructive",
    chain_callable=True,
    effects=["trash:note"],
    event="deleted",
    description="Delete a note (moves to trash).",
)
async def fn_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        await _api_delete(ctx, f"/notes/{params.note_id}",
                          {"user_id": require_user_id(ctx), "permanent": "false"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note moved to trash")
    except NotesAPIError as e:
        return ActionResult.error(f"delete_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "permanent_delete_note",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:note"],
    event="permanently_deleted",
    description="Permanently delete a note. Cannot be undone.",
)
async def fn_permanent_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        await _api_delete(ctx, f"/notes/{params.note_id}",
                          {"user_id": require_user_id(ctx), "permanent": "true"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note permanently deleted")
    except NotesAPIError as e:
        return ActionResult.error(f"permanent_delete_note backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))


_BULK_PAGE = 200  # notes per fetch page (backend max)
_BULK_MAX  = 500  # safety cap — refuse to process more than this in one call


@chat.function(
    "delete_notes_from_folder",
    action_type="destructive",
    chain_callable=True,
    effects=["trash:note", "delete:note"],
    event="bulk_deleted",
    description=(
        "Delete ALL notes in a folder (bulk). By default moves them to trash; "
        "pass permanent=true to permanently delete instead. "
        "Use resolve_folder first if you only have the folder name, not its UUID."
    ),
)
async def fn_delete_notes_from_folder(ctx, params: DeleteNotesFromFolderParams) -> ActionResult:
    try:
        if not params.folder_id.strip():
            return ActionResult.error(
                "folder_id is required. Use resolve_folder first to get the UUID from a folder name."
            )
        uid           = require_user_id(ctx)
        tenant_id     = _tenant_id(ctx)
        permanent_str = "true" if params.permanent else "false"

        # ── Collect all note IDs in folder (paginate until exhausted or cap) ──
        note_ids: list[str] = []
        offset    = 0
        truncated = False

        while True:
            resp = await _api_get(ctx, "/notes", {
                "user_id":   uid,
                "tenant_id": tenant_id,
                "folder_id": params.folder_id,
                "limit":     _BULK_PAGE,
                "offset":    offset,
            })
            page = resp.get("notes", [])
            note_ids.extend(n["id"] for n in page)

            if len(note_ids) >= _BULK_MAX:
                truncated = True
                note_ids  = note_ids[:_BULK_MAX]
                break

            total_count = resp.get("total_count")
            if total_count is not None:
                has_more = (offset + len(page)) < int(total_count)
            else:
                has_more = len(page) == _BULK_PAGE

            if not has_more:
                break
            offset += len(page)

        if not note_ids:
            return ActionResult.success(
                data={"deleted_count": 0, "folder_id": params.folder_id,
                      "permanent": params.permanent},
                summary="No notes in folder — nothing to delete",
            )

        # ── Delete each note, collect errors ──────────────────────────
        deleted = 0
        errors  = 0
        for note_id in note_ids:
            try:
                await _api_delete(ctx, f"/notes/{note_id}",
                                  {"user_id": uid, "permanent": permanent_str})
                deleted += 1
            except NotesAPIError as exc:
                log.warning("bulk delete: skip note_id=%s err=%s", note_id, exc)
                errors += 1

        action  = "permanently deleted" if params.permanent else "moved to trash"
        summary = f"{deleted} note(s) {action}"
        if errors:
            summary += f" ({errors} failed)"
        if truncated:
            summary += f" (capped at {_BULK_MAX} — folder may still contain more notes)"

        return ActionResult.success(
            data={
                "deleted_count": deleted,
                "error_count":   errors,
                "folder_id":     params.folder_id,
                "permanent":     params.permanent,
                "truncated":     truncated,
            },
            summary=summary,
        )
    except NotesAPIError as e:
        return ActionResult.error(
            f"delete_notes_from_folder backend returned {e.status_code}: {e.detail}"
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "search_notes",
    action_type="read",
    description=(
        "Full-text search across all notes (paginated). Returns up to `limit` "
        f"results per call (max {MAX_SEARCH_PER_PAGE}). If `has_more` is true, "
        "call again with `offset=offset+limit` to fetch the next page. "
        "Do NOT claim to have searched all notes until `has_more` is false."
    ),
)
async def fn_search_notes(ctx, params: SearchNotesParams) -> ActionResult:
    try:
        if not params.query.strip():
            return ActionResult.error("Search query is required. Pass query (or q).")
        resp = await _api_get(ctx, "/notes/search/fulltext", {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "q":         params.query,
            "limit":     params.limit,
            "offset":    params.offset,
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
                "results": [{
                    "note_id":     r.get("id"),
                    "title":       r.get("title"),
                    "excerpt":     r.get("excerpt", "")[:200],
                    "is_archived": r.get("is_archived", False),
                } for r in results],
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
        return ActionResult.error(f"search_notes backend returned {e.status_code}: {e.detail}")
    except Exception as e:
        return ActionResult.error(str(e))

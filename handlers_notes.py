"""Notes · CRUD handlers."""
from __future__ import annotations

import logging
import re

import httpx

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

from app import chat, ActionResult, _api_get, _api_patch, _api_post, _api_delete, require_user_id, _tenant_id

log = logging.getLogger("notes.handlers")
from models_notes import (
    MAX_NOTES_PER_PAGE,
    MAX_SEARCH_PER_PAGE,
    CreateNoteParams,
    ListNotesParams,
    MoveNoteParams,
    NoteIdParams,
    SearchNotesParams,
    UpdateNoteParams,
)


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "list_notes", action_type="read",
    description=(
        "List notes (paginated). Returns up to `limit` rows per call "
        f"(max {MAX_NOTES_PER_PAGE}). If `has_more` is true, call again with "
        "`offset=offset+limit` to fetch the next page."
    ),
)
async def fn_list_notes(ctx, params: ListNotesParams) -> ActionResult:
    """List all notes with titles, tags, word count."""
    try:
        qp: dict = {
            "user_id": require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "limit": params.limit,
            "offset": params.offset,
        }
        if params.folder_id: qp["folder_id"] = params.folder_id
        if params.search:    qp["search"] = params.search
        if params.tags:      qp["tags"] = ",".join(params.tags)

        resp = await _api_get("/notes", qp)
        notes = resp.get("notes", [])

        # Extension-side tag fallback: if the backend doesn't yet understand
        # ?tags=a,b it will ignore the filter and return everything. Filter
        # AND-style client-side so the LLM sees a stable contract regardless
        # of backend version. Once notes-api ships server-side tag filtering,
        # this becomes a no-op (the backend has already filtered).
        if params.tags:
            wanted = {t.strip().lower() for t in params.tags if t.strip()}
            if wanted:
                notes = [
                    n for n in notes
                    if wanted.issubset({str(t).lower() for t in n.get("tags", [])})
                ]

        # Prefer true DB-wide count if notes-api provides it (new field after
        # the upcoming backend patch). Fall back to page-length heuristic so
        # older backends still work without surfacing misleading totals.
        total_count = resp.get("total_count")
        if total_count is None:
            # heuristic: a full page likely means there are more rows
            has_more = len(notes) == params.limit
            total_known = False
        else:
            has_more = (params.offset + len(notes)) < int(total_count)
            total_known = True

        next_offset = params.offset + len(notes) if has_more else None

        return ActionResult.success(
            data={
                "notes": [{
                    "note_id": n["id"], "title": n["title"],
                    "word_count": n.get("word_count", 0),
                    "is_pinned": n.get("is_pinned", False),
                    "is_archived": n.get("is_archived", False),
                    "tags": n.get("tags", []),
                    "folder_id": n.get("folder_id"),
                } for n in notes],
                "page_size":    len(notes),
                "offset":       params.offset,
                "limit":        params.limit,
                "has_more":     has_more,
                "next_offset":  next_offset,
                "total_count":  int(total_count) if total_known else None,
            },
            summary=(
                f"{len(notes)} note(s) on this page"
                + (f" of {total_count} total" if total_known else "")
                + (f"; more available (next_offset={next_offset})" if has_more else "")
            ),
        )
    except httpx.HTTPStatusError as e:
        # Convert raw client errors (422, 500 from backend) into a clean
        # ActionResult.error so the LLM can react, not the user.
        try:
            detail = e.response.json().get("detail") or e.response.text
        except Exception:
            detail = e.response.text
        return ActionResult.error(
            f"list_notes backend returned {e.response.status_code}: {detail}"
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("get_note", action_type="read", description="Get full content of a note by ID.")
async def fn_get_note(ctx, params: NoteIdParams) -> ActionResult:
    """Get full content of a note by ID."""
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        note = (await _api_get(f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)})).get("note", {})
        return ActionResult.success(
            data={"note_id": note.get("id"), "title": note.get("title"), "content": note.get("content_text", ""),
                  "tags": note.get("tags", []), "is_pinned": note.get("is_pinned", False),
                  "is_archived": note.get("is_archived", False),
                  "word_count": note.get("word_count", 0), "folder_id": note.get("folder_id")},
            summary=f"Note: {note.get('title', 'Untitled')}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("create_note", action_type="write", event="created", description="Create a new note.")
async def fn_create_note(ctx, params: CreateNoteParams) -> ActionResult:
    """Create a new note."""
    try:
        title   = params.title.strip()
        content = params.content_text

        # If both title and content are empty, the call is almost certainly
        # an LLM mistake (it forgot what to write). Fail loud rather than
        # creating yet another empty note.
        if not title and not content.strip():
            return ActionResult.error(
                "Note must have a title or content. "
                "Pass title and/or content_text."
            )

        # If the LLM put a folder name into title (observed pattern: title set to a folder name),
        # it's recoverable but worth a log so we can iterate on system_prompt later.
        if title and not content.strip():
            log.info("create_note: empty content, title=%r — possible folder/title confusion", title[:80])

        # Title-bleed guard: defend against automation/template bugs where an
        # interpolated title ends up concatenated into the content (observed
        # in prod 2026-04-23 as notes whose title was 'X' and whose content
        # began with 'XX: ...'). If title is a non-trivial prefix of content,
        # strip the duplicate from the content start so the data is clean
        # at rest regardless of whoever called us.
        if title and len(title) >= 3 and content.startswith(title):
            log.warning(
                "title-bleed detected on create_note (title=%r); stripping duplicate prefix from content",
                title[:40],
            )
            content = content[len(title):].lstrip(": \n\t")

        body: dict = {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
                      "title": title, "content_text": content, "tags": params.tags}
        if params.folder_id: body["folder_id"] = params.folder_id
        note = (await _api_post("/notes", body)).get("note", {})
        return ActionResult.success(
            data={"note_id": note.get("id"), "title": note.get("title"), "folder_id": params.folder_id or None},
            summary=f"Note created: {note.get('title', params.title)}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("update_note", action_type="write", event="updated", description="Update note title, content, tags, or pin.")
async def fn_update_note(ctx, params: UpdateNoteParams) -> ActionResult:
    """Update note title, content, tags, or pin."""
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        updates: dict = {}
        if params.title:              updates["title"] = params.title
        if params.content_text:       updates["content_text"] = params.content_text
        if params.tags is not None:   updates["tags"] = params.tags
        if params.is_pinned is not None: updates["is_pinned"] = params.is_pinned
        if not updates:
            return ActionResult.error("No fields to update")
        data = await _api_patch(f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)}, updates)
        title = data.get("note", {}).get("title", "")
        return ActionResult.success(
            data={"note_id": params.note_id, "title": title, "fields_updated": list(updates.keys())},
            summary=f"Note updated: {title}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("move_note", action_type="write", event="moved", description="Move note to a folder, or root with empty folder_id.")
async def fn_move_note(ctx, params: MoveNoteParams) -> ActionResult:
    """Move note to a folder, or root with empty folder_id."""
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        data = await _api_patch(f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)},
                                {"folder_id": params.folder_id if params.folder_id else None})
        target = params.folder_id or "All Notes"
        return ActionResult.success(
            data={"note_id": params.note_id, "title": data.get("note", {}).get("title", ""),
                  "folder_id": params.folder_id or None, "moved_to": target},
            summary=f"Note moved to {target}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("delete_note", action_type="destructive", event="deleted", description="Delete a note (moves to trash).")
async def fn_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    """Delete a note (moves to trash)."""
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        await _api_delete(f"/notes/{params.note_id}", {"user_id": require_user_id(ctx), "permanent": "false"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note moved to trash")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("permanent_delete_note", action_type="destructive", event="permanently_deleted",
               description="Permanently delete a note. Cannot be undone.")
async def fn_permanent_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    """Permanently delete a note. Cannot be undone."""
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err)
        await _api_delete(f"/notes/{params.note_id}", {"user_id": require_user_id(ctx), "permanent": "true"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note permanently deleted")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function(
    "search_notes", action_type="read",
    description=(
        "Full-text search across all notes (paginated). Returns up to `limit` "
        f"results per call (max {MAX_SEARCH_PER_PAGE}). If `has_more` is true, "
        "call again with `offset=offset+limit` to fetch the next page. "
        "Do NOT claim to have searched all notes until `has_more` is false."
    ),
)
async def fn_search_notes(ctx, params: SearchNotesParams) -> ActionResult:
    """Full-text search across all notes."""
    try:
        if not params.query.strip():
            return ActionResult.error("Search query is required. Pass query (or q).")
        resp = await _api_get("/notes/search/fulltext", {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "q":         params.query,
            "limit":     params.limit,
            "offset":    params.offset,
        })
        results = resp.get("results", [])

        # Same pagination contract as list_notes: prefer DB-wide total from
        # backend, fall back to a full-page heuristic so an older backend
        # doesn't surface a misleading "total".
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
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail") or e.response.text
        except Exception:
            detail = e.response.text
        return ActionResult.error(
            f"search_notes backend returned {e.response.status_code}: {detail}"
        )
    except Exception as e:
        return ActionResult.error(str(e))

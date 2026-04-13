"""Notes · CRUD handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, _api_get, _api_patch, _api_post, _api_delete, _user_id, _tenant_id


# ─── Models ───────────────────────────────────────────────────────────── #

class ListNotesParams(BaseModel):
    """List notes with optional filters."""
    limit: int     = Field(default=50, description="Max notes to return")
    folder_id: str = Field(default="", description="Filter by folder")
    search: str    = Field(default="", description="Filter by text")


class NoteIdParams(BaseModel):
    """Target a specific note."""
    note_id: str = Field(description="Note UUID")


class CreateNoteParams(BaseModel):
    """Create a new note."""
    title: str        = Field(description="Note title")
    content_text: str = Field(description="Note content")
    tags: list[str]   = Field(default_factory=list, description="Tags list")
    folder_id: str    = Field(default="", description="Folder ID")


class UpdateNoteParams(BaseModel):
    """Update an existing note."""
    note_id: str                   = Field(description="Note UUID")
    title: str                     = Field(default="", description="New title")
    content_text: str              = Field(default="", description="New content")
    tags: Optional[list[str]]      = Field(default=None, description="New tags")
    is_pinned: Optional[bool]      = Field(default=None, description="Pin status")


class MoveNoteParams(BaseModel):
    """Move note to a folder."""
    note_id: str   = Field(description="Note UUID to move")
    folder_id: str = Field(default="", description="Target folder. Empty = root.")


class SearchNotesParams(BaseModel):
    """Full-text search."""
    query: str = Field(description="Search query")


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function("list_notes", action_type="read", description="List all notes with titles, tags, word count.")
async def fn_list_notes(ctx, params: ListNotesParams) -> ActionResult:
    try:
        qp: dict = {"user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx), "limit": params.limit}
        if params.folder_id: qp["folder_id"] = params.folder_id
        if params.search:    qp["search"] = params.search
        notes = (await _api_get("/notes", qp)).get("notes", [])
        return ActionResult.success(
            data={"notes": [{"note_id": n["id"], "title": n["title"], "word_count": n.get("word_count", 0),
                             "is_pinned": n.get("is_pinned", False), "tags": n.get("tags", []),
                             "folder_id": n.get("folder_id")} for n in notes], "total": len(notes)},
            summary=f"Found {len(notes)} note(s)",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("get_note", action_type="read", description="Get full content of a note by ID.")
async def fn_get_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        note = (await _api_get(f"/notes/{params.note_id}", {"user_id": _user_id(ctx)})).get("note", {})
        return ActionResult.success(
            data={"note_id": note.get("id"), "title": note.get("title"), "content": note.get("content_text", ""),
                  "tags": note.get("tags", []), "is_pinned": note.get("is_pinned", False),
                  "word_count": note.get("word_count", 0), "folder_id": note.get("folder_id")},
            summary=f"Note: {note.get('title', 'Untitled')}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("create_note", action_type="write", event="created", description="Create a new note.")
async def fn_create_note(ctx, params: CreateNoteParams) -> ActionResult:
    try:
        body: dict = {"user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx),
                      "title": params.title, "content_text": params.content_text, "tags": params.tags}
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
    try:
        updates: dict = {}
        if params.title:              updates["title"] = params.title
        if params.content_text:       updates["content_text"] = params.content_text
        if params.tags is not None:   updates["tags"] = params.tags
        if params.is_pinned is not None: updates["is_pinned"] = params.is_pinned
        if not updates:
            return ActionResult.error("No fields to update")
        data = await _api_patch(f"/notes/{params.note_id}", {"user_id": _user_id(ctx)}, updates)
        title = data.get("note", {}).get("title", "")
        return ActionResult.success(
            data={"note_id": params.note_id, "title": title, "fields_updated": list(updates.keys())},
            summary=f"Note updated: {title}",
        )
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("move_note", action_type="write", event="moved", description="Move note to a folder, or root with empty folder_id.")
async def fn_move_note(ctx, params: MoveNoteParams) -> ActionResult:
    try:
        data = await _api_patch(f"/notes/{params.note_id}", {"user_id": _user_id(ctx)},
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
    try:
        await _api_delete(f"/notes/{params.note_id}", {"user_id": _user_id(ctx), "permanent": "false"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note moved to trash")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("permanent_delete_note", action_type="destructive", event="permanently_deleted",
               description="Permanently delete a note. Cannot be undone.")
async def fn_permanent_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        await _api_delete(f"/notes/{params.note_id}", {"user_id": _user_id(ctx), "permanent": "true"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note permanently deleted")
    except Exception as e:
        return ActionResult.error(str(e))


@chat.function("search_notes", action_type="read", description="Full-text search across all notes.")
async def fn_search_notes(ctx, params: SearchNotesParams) -> ActionResult:
    try:
        results = (await _api_get("/notes/search/fulltext",
                   {"user_id": _user_id(ctx), "q": params.query, "tenant_id": _tenant_id(ctx), "limit": 10})).get("results", [])
        return ActionResult.success(
            data={"results": [{"note_id": r.get("id"), "title": r.get("title"),
                               "excerpt": r.get("excerpt", "")[:200]} for r in results],
                  "total": len(results), "query": params.query},
            summary=f"Found {len(results)} result(s) for '{params.query}'",
        )
    except Exception as e:
        return ActionResult.error(str(e))

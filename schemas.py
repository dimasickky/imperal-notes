"""Notes · Pydantic output schemas.

Every `@sdk_ext.tool` declares an `output_schema` so the Webbee Narrator can
ground its prose in typed fields (I-TOOL-SCHEMA-REQUIRED). Errors travel
inside the schema (ok=False, error=<msg>) instead of exceptions — the
Narrator reads both success and error states from the same shape and
composes a single Webbee-voice response.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# notes-api caps `limit` at 200 (FastAPI Query(le=200)). Pinned here so tools
# can validate inputs before a 422 round-trip to the backend.
MAX_NOTES_PER_PAGE = 200


# ─── Shared base ─────────────────────────────────────────────────────── #

class _ToolResult(BaseModel):
    """Base for every tool output. ok=False + error=<msg> on failure."""
    ok: bool = True
    error: str | None = None


# ─── Leaf types ──────────────────────────────────────────────────────── #

class NoteSummary(BaseModel):
    """Condensed note entry used in list views."""
    note_id: str
    title: str
    word_count: int = 0
    is_pinned: bool = False
    is_archived: bool = False
    tags: list[str] = Field(default_factory=list)
    folder_id: str | None = None


class FolderRef(BaseModel):
    folder_id: str
    name: str


class SearchHit(BaseModel):
    note_id: str
    title: str
    excerpt: str = ""
    is_archived: bool = False


class TrashedNote(BaseModel):
    note_id: str
    title: str
    word_count: int = 0
    tags: list[str] = Field(default_factory=list)


# ─── Tool outputs: notes CRUD ────────────────────────────────────────── #

class NoteListResult(_ToolResult):
    notes: list[NoteSummary] = Field(default_factory=list)
    page_size: int = 0
    offset: int = 0
    limit: int = 0
    has_more: bool = False
    next_offset: int | None = None
    # DB-wide count when notes-api supplies it; None = unknown on older backends.
    total_count: int | None = None


class NoteDetail(_ToolResult):
    note_id: str = ""
    title: str = ""
    content_text: str = ""
    tags: list[str] = Field(default_factory=list)
    is_pinned: bool = False
    is_archived: bool = False
    word_count: int = 0
    folder_id: str | None = None


class NoteCreated(_ToolResult):
    note_id: str = ""
    title: str = ""
    folder_id: str | None = None


class NoteUpdated(_ToolResult):
    note_id: str = ""
    title: str = ""
    fields_updated: list[str] = Field(default_factory=list)


class NoteMoved(_ToolResult):
    note_id: str = ""
    title: str = ""
    folder_id: str | None = None
    # "All Notes" when moved to root, otherwise folder_id.
    moved_to: str = ""


class NoteDeleted(_ToolResult):
    note_id: str = ""
    permanent: bool = False


class NoteRestored(_ToolResult):
    note_id: str = ""
    title: str = ""
    folder_id: str | None = None


class SearchResult(_ToolResult):
    query: str = ""
    results: list[SearchHit] = Field(default_factory=list)
    page_size: int = 0
    offset: int = 0
    limit: int = 0
    has_more: bool = False
    next_offset: int | None = None
    total_count: int | None = None


# ─── Tool outputs: folders ───────────────────────────────────────────── #

class FolderList(_ToolResult):
    folders: list[FolderRef] = Field(default_factory=list)
    total: int = 0


class FolderResolved(_ToolResult):
    folder_id: str | None = None
    name: str | None = None
    # exact | prefix | contains | none
    match_quality: str = "none"
    candidates: list[FolderRef] = Field(default_factory=list)


class FolderCreated(_ToolResult):
    folder_id: str = ""
    name: str = ""


class FolderRenamed(_ToolResult):
    folder_id: str = ""
    name: str = ""


class FolderDeleted(_ToolResult):
    folder_id: str = ""


# ─── Tool outputs: trash ─────────────────────────────────────────────── #

class TrashList(_ToolResult):
    trash_notes: list[TrashedNote] = Field(default_factory=list)
    total: int = 0


class TrashEmptied(_ToolResult):
    deleted_count: int = 0


# ─── Tool outputs: panel action ──────────────────────────────────────── #

class NoteSaved(_ToolResult):
    note_id: str = ""
    # title | content | pin
    saved_field: str = ""
    # populated when saved_field == "pin"
    is_pinned: bool | None = None

"""Notes · Pydantic parameter models for @chat.function handlers.

All input fields that the LLM is observed to confuse are wired with
`AliasChoices(...)` so that synonyms (`content`/`content_text`/`body`,
`name`/`title`, `id`/`note_id`, …) are silently accepted instead of
falling through Pydantic with a `MISSING_FIELD` validation error
that ends up surfaced to the user in chat. Required text fields also
carry safe defaults so a missing arg becomes an empty value the
handler can normalize, never a stack trace.

Aliases here are *input-only* (`validation_alias`); serialization keeps
the canonical field name so the wire contract with the backend stays
stable.
"""
from typing import List, Optional

from imperal_sdk import sdl
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


# List endpoint caps at 200; search endpoint caps at 50 (FULLTEXT cost).
MAX_NOTES_PER_PAGE = 200
MAX_SEARCH_PER_PAGE = 50


_MODEL_CONFIG = ConfigDict(populate_by_name=True)


def _coerce_tags(v):
    """Accept ``["a","b"]`` (canonical), ``"a,b"``, ``"a, b"``, or ``"a"``.

    LLMs occasionally emit a single string for list-shaped params. Without
    this coercion Pydantic raises ``list_type`` and the user sees a stack
    trace in chat. Empty strings collapse to ``[]``.
    """
    if v is None:
        return []
    if isinstance(v, str):
        return [t.strip() for t in v.split(",") if t.strip()]
    return v


class ListNotesParams(BaseModel):
    """List notes with optional filters."""
    model_config = _MODEL_CONFIG

    limit: int      = Field(
        default=50, ge=1, le=MAX_NOTES_PER_PAGE,
        description=f"Max notes per page (1-{MAX_NOTES_PER_PAGE}). Use offset to paginate.",
        validation_alias=AliasChoices("limit", "page_size", "per_page"),
    )
    offset: int     = Field(
        default=0, ge=0, description="Pagination offset",
        validation_alias=AliasChoices("offset", "skip"),
    )
    folder_id: str  = Field(
        default="", description="Filter by folder — accepts folder UUID or folder name (auto-resolved).",
        validation_alias=AliasChoices("folder_id", "folder", "folderId"),
    )
    search: str     = Field(
        default="", description="Filter by text",
        validation_alias=AliasChoices("search", "query", "q"),
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Filter by tag names (AND-match: a note must have all listed tags).",
        validation_alias=AliasChoices("tags", "labels"),
    )
    is_archived: bool | None = Field(
        default=None,
        description=(
            "Filter by archive status. None (default) = active notes only. "
            "True = archived notes only. False = explicitly active only."
        ),
        validation_alias=AliasChoices("is_archived", "archived"),
    )
    is_trashed: bool | None = Field(
        default=None,
        description=(
            "Filter by trash status. None (default) = not-trashed only. "
            "True = trashed notes only (the trash bin). "
            "Use this to count/list notes in trash."
        ),
        validation_alias=AliasChoices("is_trashed", "trashed", "in_trash"),
    )

    _coerce_tags = field_validator("tags", mode="before")(_coerce_tags)


class NoteIdParams(BaseModel):
    """Target a specific note."""
    model_config = _MODEL_CONFIG

    note_id: str = Field(
        default="", description="Note UUID. Required.",
        validation_alias=AliasChoices("note_id", "id", "noteId", "uuid"),
    )


class CreateNoteParams(BaseModel):
    """Create a new note.

    `title` and `content_text` both have safe defaults — handler-side
    normalization decides what to do with empty values rather than
    Pydantic rejecting the call. LLMs occasionally pass `content`,
    `body`, `text` instead of `content_text` — accepted via aliases.
    """
    model_config = _MODEL_CONFIG

    title: str        = Field(
        default="",
        description="Note title. Field name is 'title' — never the folder name.",
        validation_alias=AliasChoices("title", "name", "subject", "heading"),
    )
    content_text: str = Field(
        default="",
        description=(
            "Note body text. Field name in tool calls is 'content_text' — "
            "never 'content', 'body', or 'text', though those are accepted as aliases."
        ),
        validation_alias=AliasChoices("content_text", "content", "body", "text"),
    )
    tags: list[str]   = Field(
        default_factory=list, description="Tags list",
        validation_alias=AliasChoices("tags", "labels"),
    )
    folder_id: str    = Field(
        default="",
        description="Folder UUID or folder name — auto-resolved by the handler. Pass the name directly.",
        validation_alias=AliasChoices("folder_id", "folder", "folderId"),
    )

    _coerce_tags = field_validator("tags", mode="before")(_coerce_tags)


class UpdateNoteParams(BaseModel):
    """Update an existing note."""
    model_config = _MODEL_CONFIG

    note_id: str              = Field(
        default="", description="Note UUID. Required.",
        validation_alias=AliasChoices("note_id", "id", "noteId", "uuid"),
    )
    title: str                = Field(
        default="", description="New title (omit to keep).",
        validation_alias=AliasChoices("title", "name", "subject", "heading"),
    )
    content_text: str         = Field(
        default="", description="New content (omit to keep).",
        validation_alias=AliasChoices("content_text", "content", "body", "text"),
    )
    tags: Optional[list[str]] = Field(
        default=None, description="New tags (omit to keep).",
        validation_alias=AliasChoices("tags", "labels"),
    )
    is_pinned: Optional[bool] = Field(
        default=None, description="Pin status (omit to keep).",
        validation_alias=AliasChoices("is_pinned", "pinned", "pin"),
    )

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags_optional(cls, v):
        # Same coercion as the elsewhere helper, but `None` stays `None`
        # because UpdateNoteParams treats omitted `tags` as "keep existing".
        if v is None:
            return None
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v


class AppendNoteParams(BaseModel):
    """Append text to the END of an existing note's body (never overwrites)."""
    model_config = _MODEL_CONFIG

    note_id: str      = Field(
        default="", description="Note UUID to append to. Required.",
        validation_alias=AliasChoices("note_id", "id", "noteId", "uuid"),
    )
    content_text: str = Field(
        default="",
        description=(
            "Text to append AFTER the existing note body. The existing content is "
            "preserved; this text is added to the end. Field name is 'content_text'."
        ),
        validation_alias=AliasChoices("content_text", "content", "body", "text", "append"),
    )


class MoveNoteParams(BaseModel):
    """Move note to a folder."""
    model_config = _MODEL_CONFIG

    note_id: str   = Field(
        default="", description="Note UUID to move. Required.",
        validation_alias=AliasChoices("note_id", "id", "noteId", "uuid"),
    )
    folder_id: str = Field(
        default="",
        description="Target folder UUID or folder name — auto-resolved. Empty string moves to root.",
        validation_alias=AliasChoices("folder_id", "folder", "folderId"),
    )


class SearchNotesParams(BaseModel):
    """Full-text search."""
    model_config = _MODEL_CONFIG

    query: str  = Field(
        default="", description="Search query. Required (non-empty).",
        validation_alias=AliasChoices("query", "q", "search", "text"),
    )
    limit: int  = Field(
        default=20, ge=1, le=MAX_SEARCH_PER_PAGE,
        description=f"Max results per page (1-{MAX_SEARCH_PER_PAGE}). Use offset to paginate.",
        validation_alias=AliasChoices("limit", "page_size", "per_page"),
    )
    offset: int = Field(
        default=0, ge=0, description="Pagination offset",
        validation_alias=AliasChoices("offset", "skip"),
    )
    include_archived: bool = Field(
        default=False,
        description="Also search archived notes (default search skips them).",
        validation_alias=AliasChoices("include_archived", "with_archived"),
    )
    include_trashed: bool = Field(
        default=False,
        description="Also search notes in trash (default search skips them).",
        validation_alias=AliasChoices("include_trashed", "with_trashed"),
    )


class DeleteNotesFromFolderParams(BaseModel):
    """Bulk-delete all notes in a folder."""
    model_config = _MODEL_CONFIG

    folder_id: str = Field(
        default="",
        description=(
            "Folder UUID OR folder name — pass the name directly (e.g. 'Groceries'), "
            "it will be auto-resolved to UUID. Do NOT leave empty."
        ),
        validation_alias=AliasChoices("folder_id", "folder", "folderId", "name"),
    )
    permanent: bool = Field(
        default=False,
        description=(
            "If true, permanently delete all notes (cannot be undone). "
            "If false (default), move to trash."
        ),
        validation_alias=AliasChoices("permanent", "hard_delete", "force_delete"),
    )


class BulkNotesParams(BaseModel):
    """Operate on an explicit set of notes by ID and/or by title.

    Pass note_ids when you already have them, or note_titles to auto-resolve.
    The GUI multi-select sends the checked note IDs into this same field.
    """
    model_config = _MODEL_CONFIG

    note_ids: Optional[List[str]] = sdl.field(
        role="ref.target_id",
        default=None,
        description="List of note IDs to act on. Use when you already have the IDs.",
        validation_alias=AliasChoices("note_ids", "message_ids", "ids", "note_id"),
    )
    note_titles: Optional[List[str]] = Field(
        default=None,
        description="List of note titles to find and act on. Auto-resolved to IDs via search.",
        validation_alias=AliasChoices("note_titles", "titles", "names"),
    )


class DeleteNotesParams(BulkNotesParams):
    """Bulk delete: trash by default, or permanent."""
    permanent: bool = Field(
        default=False,
        description="If true, permanently delete (cannot be undone). If false (default), move to trash.",
        validation_alias=AliasChoices("permanent", "hard_delete", "force_delete"),
    )

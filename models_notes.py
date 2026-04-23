"""Notes · Pydantic parameter models for @chat.function handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# Notes-api caps `limit` at 200 via FastAPI `Query(le=200)`. Keep the extension
# aligned so the LLM can't ask for 500 and blow up with a raw 422.
MAX_NOTES_PER_PAGE = 200


class ListNotesParams(BaseModel):
    """List notes with optional filters."""
    limit: int      = Field(
        default=50, ge=1, le=MAX_NOTES_PER_PAGE,
        description=f"Max notes per page (1-{MAX_NOTES_PER_PAGE}). Use offset to paginate.",
    )
    offset: int     = Field(default=0, ge=0, description="Pagination offset")
    folder_id: str  = Field(default="", description="Filter by folder")
    search: str     = Field(default="", description="Filter by text")
    tags: list[str] = Field(
        default_factory=list,
        description="Filter by tag names (AND-match: a note must have all listed tags).",
    )


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
    note_id: str              = Field(description="Note UUID")
    title: str                = Field(default="", description="New title")
    content_text: str         = Field(default="", description="New content")
    tags: Optional[list[str]] = Field(default=None, description="New tags")
    is_pinned: Optional[bool] = Field(default=None, description="Pin status")


class MoveNoteParams(BaseModel):
    """Move note to a folder."""
    note_id: str   = Field(description="Note UUID to move")
    folder_id: str = Field(default="", description="Target folder. Empty = root.")


class SearchNotesParams(BaseModel):
    """Full-text search."""
    query: str  = Field(description="Search query")
    limit: int  = Field(
        default=20, ge=1, le=MAX_NOTES_PER_PAGE,
        description=f"Max results per page (1-{MAX_NOTES_PER_PAGE}). Use offset to paginate.",
    )
    offset: int = Field(default=0, ge=0, description="Pagination offset")

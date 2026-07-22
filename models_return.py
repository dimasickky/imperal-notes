"""Notes · Typed return models for @chat.function data_model= contracts (SDK 5.2.0 SDL)."""

from typing import Any, Optional

from pydantic import BaseModel

from imperal_sdk import sdl


# ─── SDL Entity types (SDK 5.2.0) ─────────────────────────────────────────── #

class NoteEntity(sdl.Entity, sdl.Bodied, sdl.Categorized):
    """Full SDL note entity. id=note_id (UUID), title=note title, kind="note".
    sdl.Bodied provides: body (content), body_format.
    sdl.Categorized provides: tags."""
    is_pinned: bool = False
    is_archived: bool = False
    is_trashed: bool = False
    word_count: int = 0
    folder_id: Optional[str] = None
    created_at: str = ""   # ISO 8601 — when the note was created
    updated_at: str = ""   # ISO 8601 — last edit time


class NoteListItem(sdl.Entity, sdl.Categorized):
    """Slim SDL note entity for list results."""
    is_pinned: bool = False
    is_archived: bool = False
    is_trashed: bool = False
    word_count: int = 0
    folder_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


class SearchNoteItem(sdl.Entity):
    """Slim SDL note entity for search results."""
    excerpt: str = ""


class FolderEntity(sdl.Entity):
    """SDL folder. id=folder_id (UUID), title=folder name, kind="folder"."""


# ─── handlers_notes ───────────────────────────────────────────────────────── #

class ListNotesResult(sdl.EntityList[NoteListItem]):
    """list_notes — a REAL sdl.EntityList[NoteListItem] (items=[...], x-sdl='entity-list').
    Pagination cursors carried as additive typed fields; has_more inherited from EntityList."""
    page_size: int = 0
    offset: int = 0
    limit: int = 0
    next_offset: Optional[int] = None
    total_count: Optional[int] = None


class CreateNoteResult(BaseModel):
    note_id: Optional[str] = None
    title: Optional[str] = None
    folder_id: Optional[str] = None


class UpdateNoteResult(BaseModel):
    note_id: str
    title: str
    was_changed: bool
    fields_updated: Optional[list[str]] = None


class MoveNoteResult(BaseModel):
    note_id: str
    title: str
    folder_id: Optional[str]
    moved_to: str


class DeleteNoteResult(BaseModel):
    note_id: str


class BulkDeleteNotesResult(BaseModel):
    deleted_count: int
    folder_id: str
    permanent: bool


class BulkNotesActionResult(BaseModel):
    """Result of a bulk action over an explicit note-id set."""
    affected_count: int
    action: str
    note_ids: list[str] = []
    not_found: list[str] = []
    refresh_panels: list[str] = []


class SearchNotesResult(sdl.EntityList[SearchNoteItem]):
    """search_notes — a REAL sdl.EntityList[SearchNoteItem]; query + pagination cursors
    carried as additive typed fields; has_more inherited from EntityList."""
    query: str = ""
    page_size: int = 0
    offset: int = 0
    limit: int = 0
    next_offset: Optional[int] = None
    total_count: Optional[int] = None


# ─── handlers_folders ─────────────────────────────────────────────────────── #

class ListFoldersResult(sdl.EntityList[FolderEntity]):
    """list_folders — a REAL sdl.EntityList[FolderEntity] (items=[...], total=N,
    x-sdl='entity-list')."""
    pass


class ResolveFolderResult(BaseModel):
    folder_id: Optional[str]
    name: Optional[str]
    match_quality: str
    candidates: Optional[list[FolderEntity]] = None


class CreateFolderResult(BaseModel):
    folder_id: Optional[str]
    name: Optional[str]
    refresh_panels: list[str]


class RenameFolderResult(BaseModel):
    folder_id: str
    name: str
    refresh_panels: list[str]


class DeleteFolderResult(BaseModel):
    folder_id: str
    refresh_panels: list[str]


class DeleteFolderWithContentsResult(BaseModel):
    folder_id: str
    deleted_count: int
    permanent: bool
    refresh_panels: list[str]


class BulkDeleteFoldersResult(BaseModel):
    """Result of a bulk delete over an explicit folder-id set."""
    deleted_count: int
    folder_ids: list[str] = []
    not_found: list[str] = []
    with_contents: bool = False
    permanent: bool = False
    refresh_panels: list[str] = []


class TrashNoteItem(sdl.Entity, sdl.Categorized):
    """Slim SDL note entity for trash list results. id=note_id, kind='note';
    sdl.Categorized provides tags."""
    word_count: int = 0


class ListTrashResult(sdl.EntityList[TrashNoteItem]):
    """list_trash — a REAL sdl.EntityList[TrashNoteItem]; page_size + total_count
    carried as additive typed fields; has_more inherited from EntityList."""
    page_size: int = 0
    total_count: Optional[int] = None


class RestoreNoteResult(BaseModel):
    note_id: str
    title: str
    folder_id: Optional[str]


class EmptyTrashResult(BaseModel):
    deleted_count: int


# ─── handlers_attachments ─────────────────────────────────────────────────── #

class UploadAttachmentResult(BaseModel):
    attachment: Any
    refresh_panels: list[str]


class DeleteAttachmentResult(BaseModel):
    att_id: str
    refresh_panels: list[str]


# ─── handlers_export ──────────────────────────────────────────────────────── #

class DuplicateNoteResult(BaseModel):
    note_id: Optional[str]
    refresh_panels: list[str]


class ExportMarkdownResult(BaseModel):
    title: str
    markdown: str


# ─── handlers_panel_actions ───────────────────────────────────────────────── #

class NoteSaveResult(BaseModel):
    note_id: str
    saved: str
    refresh_panels: list[str]

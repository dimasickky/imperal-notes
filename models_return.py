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
    word_count: int = 0
    folder_id: Optional[str] = None


class NoteListItem(sdl.Entity, sdl.Categorized):
    """Slim SDL note entity for list results."""
    is_pinned: bool = False
    is_archived: bool = False
    word_count: int = 0
    folder_id: Optional[str] = None


class SearchNoteItem(sdl.Entity):
    """Slim SDL note entity for search results."""
    excerpt: str = ""


class FolderEntity(sdl.Entity):
    """SDL folder. id=folder_id (UUID), title=folder name, kind="folder"."""


# ─── handlers_notes ───────────────────────────────────────────────────────── #

class ListNotesResult(BaseModel):
    notes: list[NoteListItem]
    page_size: int
    offset: int
    limit: int
    has_more: bool
    next_offset: Optional[int]
    total_count: Optional[int]


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


class SearchNotesResult(BaseModel):
    results: list[SearchNoteItem]
    query: str
    page_size: int
    offset: int
    limit: int
    has_more: bool
    next_offset: Optional[int]
    total_count: Optional[int]


# ─── handlers_folders ─────────────────────────────────────────────────────── #

class ListFoldersResult(BaseModel):
    folders: list[FolderEntity]
    total: int


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


class TrashNoteItem(BaseModel):
    note_id: str
    title: str
    word_count: int
    tags: list[str]


class ListTrashResult(BaseModel):
    trash_notes: list[TrashNoteItem]
    page_size: int
    total_count: Optional[int]
    has_more: bool


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

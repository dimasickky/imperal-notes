"""Notes · Typed return models for @chat.function data_model= contracts (SDK 5.0.1)."""

from typing import Any

from pydantic import BaseModel


# ─── Shared primitives ────────────────────────────────────────────────────── #

class NoteListItem(BaseModel):
    note_id: str
    title: str
    word_count: int
    is_pinned: bool
    is_archived: bool
    tags: list[str]
    folder_id: str | None


class FolderItem(BaseModel):
    folder_id: str
    name: str


# ─── handlers_notes ───────────────────────────────────────────────────────── #

class ListNotesResult(BaseModel):
    notes: list[NoteListItem]
    page_size: int
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None
    total_count: int | None


class NoteRecord(BaseModel):
    note_id: str | None
    title: str | None
    content: str
    tags: list[str]
    is_pinned: bool
    is_archived: bool
    word_count: int
    folder_id: str | None


class CreateNoteResult(BaseModel):
    note_id: str | None
    title: str | None
    folder_id: str | None


class UpdateNoteResult(BaseModel):
    note_id: str
    title: str
    was_changed: bool
    fields_updated: list[str] | None = None


class MoveNoteResult(BaseModel):
    note_id: str
    title: str
    folder_id: str | None
    moved_to: str


class DeleteNoteResult(BaseModel):
    note_id: str


class BulkDeleteNotesResult(BaseModel):
    deleted_count: int
    folder_id: str
    permanent: bool


class SearchNoteItem(BaseModel):
    note_id: str | None
    title: str | None
    excerpt: str
    is_archived: bool


class SearchNotesResult(BaseModel):
    results: list[SearchNoteItem]
    query: str
    page_size: int
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None
    total_count: int | None


# ─── handlers_folders ─────────────────────────────────────────────────────── #

class ListFoldersResult(BaseModel):
    folders: list[FolderItem]
    total: int


class ResolveFolderResult(BaseModel):
    folder_id: str | None
    name: str | None
    match_quality: str
    candidates: list[FolderItem] | None = None


class CreateFolderResult(BaseModel):
    folder_id: str | None
    name: str | None
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
    total_count: int | None
    has_more: bool


class RestoreNoteResult(BaseModel):
    note_id: str
    title: str
    folder_id: str | None


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
    note_id: str | None
    refresh_panels: list[str]


class ExportMarkdownResult(BaseModel):
    title: str
    markdown: str


# ─── handlers_panel_actions ───────────────────────────────────────────────── #

class NoteSaveResult(BaseModel):
    note_id: str
    saved: str
    refresh_panels: list[str]

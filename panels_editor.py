"""Notes · Editor panel (center overlay with RichEditor)."""
from __future__ import annotations

import logging
from datetime import datetime

from imperal_sdk import ui

from app import (
    ext, _api_get, _api_post, _user_id, _tenant_id,
    FoldersCacheEntry, TagsCacheEntry,
)

log = logging.getLogger("notes")


def _format_date(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M")
    except Exception:
        return iso_str[:16]


def _prepare_content(note: dict) -> str:
    """Extract and prepare note content for RichEditor."""
    raw = note.get("content") or note.get("content_text") or ""
    if not raw:
        return ""
    if "<" in raw and ("</" in raw or "<br" in raw or "<p>" in raw):
        return raw
    try:
        import markdown
        return markdown.markdown(raw, extensions=["extra", "nl2br", "sane_lists"])
    except Exception:
        lines = raw.split("\n\n")
        return "".join(f"<p>{line}</p>" for line in lines if line.strip())


@ext.panel("editor", slot="center", title="Editor", icon="Edit")
async def notes_editor(ctx, note_id: str = "", **kwargs):
    uid, tid = _user_id(ctx), _tenant_id(ctx)

    if not note_id:
        return ui.Empty(message="Select a note to edit", icon="FileText")

    # ── Create new note ───────────────────────────────────────────────────
    if note_id == "new":
        try:
            result = await _api_post(ctx, "/notes", {
                "user_id": uid, "tenant_id": tid,
                "title": "Untitled", "content_text": "",
            })
            note    = result.get("note", {})
            note_id = note.get("id", "")
            if not note_id:
                return ui.Error(message="Failed to create note")
        except Exception as e:
            return ui.Error(message=f"Failed to create note: {e}")
    else:
        try:
            data = await _api_get(ctx, f"/notes/{note_id}", {"user_id": uid})
            note = data.get("note", {})
        except Exception as e:
            log.warning("editor: failed to fetch note %s: %s", note_id, e)
            return ui.Error(
                message=f"Could not load note: {e}",
                retry=ui.Call("__panel__editor", note_id=note_id),
            )

    title        = note.get("title", "Untitled")
    content_html = _prepare_content(note)
    word_count   = note.get("word_count", 0)
    is_pinned    = note.get("is_pinned", False)
    is_archived  = note.get("is_archived", False)
    tags         = note.get("tags", [])
    created      = _format_date(note.get("created_at", ""))
    updated      = _format_date(note.get("updated_at", ""))

    # ── Cached sidebar data ───────────────────────────────────────────────
    all_tags: list = []
    try:
        async def _load_tags():
            data = await _api_get(ctx, "/notes/tags", {"user_id": uid, "tenant_id": tid})
            return TagsCacheEntry(tags=data.get("tags", []))

        tags_entry = await ctx.cache.get_or_fetch(
            f"tags:{uid}", TagsCacheEntry, ttl_seconds=120, fetcher=_load_tags,
        )
        all_tags = tags_entry.tags
    except Exception:
        pass

    folders: list = []
    try:
        async def _load_folders():
            data = await _api_get(ctx, "/folders", {"user_id": uid, "tenant_id": tid})
            return FoldersCacheEntry(folders=data.get("folders", []))

        folders_entry = await ctx.cache.get_or_fetch(
            f"folders:{uid}", FoldersCacheEntry, ttl_seconds=60, fetcher=_load_folders,
        )
        folders = folders_entry.folders
    except Exception:
        pass

    # ── Action bar ────────────────────────────────────────────────────────
    pin_label    = "Unpin" if is_pinned else "Pin"
    pin_icon     = "PinOff" if is_pinned else "Pin"
    archive_label = "Unarchive" if is_archived else "Archive"
    archive_icon  = "ArchiveRestore" if is_archived else "Archive"
    archive_field = "unarchive" if is_archived else "archive"

    more_menu = ui.Menu(
        items=[
            {"label": "Duplicate",       "icon": "Copy",     "on_click": ui.Call("duplicate_note",  note_id=note_id)},
            {"label": "Export Markdown", "icon": "FileDown", "on_click": ui.Call("export_markdown", note_id=note_id)},
            {"separator": True},
            {"label": archive_label,     "icon": archive_icon,
             "on_click": ui.Call("note_save", note_id=note_id, field=archive_field)},
            {"label": "Delete",          "icon": "Trash2",   "on_click": ui.Call("delete_note", note_id=note_id)},
        ],
        trigger=ui.Button("", icon="MoreHorizontal", variant="ghost", size="sm"),
    )

    action_bar = ui.Stack([
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__sidebar")),
        ui.Button(pin_label, icon=pin_icon, variant="outline", size="sm",
                  on_click=ui.Call("note_save", note_id=note_id, field="pin")),
        more_menu,
    ], direction="h", wrap=True, sticky=True)

    # ── Title ─────────────────────────────────────────────────────────────
    title_input = ui.Input(
        placeholder="Note title...",
        value=title,
        param_name="title",
        on_submit=ui.Call("note_save", note_id=note_id, field="title"),
    )

    # ── Folder selector ───────────────────────────────────────────────────
    current_folder_id = note.get("folder_id") or ""
    folder_options = [{"label": "No folder", "value": ""}] + [
        {"label": f["name"], "value": f["id"]} for f in folders
    ]
    folder_select = ui.Select(
        options=folder_options,
        value=current_folder_id,
        placeholder="Move to folder...",
        param_name="folder_id",
        on_change=ui.Call("note_save", note_id=note_id, field="folder"),
    )

    # ── Metadata ──────────────────────────────────────────────────────────
    meta_pairs = []
    if word_count:
        meta_pairs.append({"key": "Words", "value": str(word_count)})
    if created:
        meta_pairs.append({"key": "Created", "value": created})
    if updated:
        meta_pairs.append({"key": "Modified", "value": updated})
    meta_pairs.append({"key": "ID", "value": note_id[:12] + "..."})

    tag_input = ui.TagInput(
        values=tags,
        suggestions=all_tags,
        placeholder="Add tags...",
        param_name="tags",
        on_change=ui.Call("note_save", note_id=note_id, field="tags"),
    )

    # ── Rich Editor ───────────────────────────────────────────────────────
    editor = ui.RichEditor(
        content=content_html,
        placeholder="Start writing...",
        param_name="content_text",
        on_save=ui.Call("note_save", note_id=note_id, field="content"),
        on_change=ui.Call("note_save", note_id=note_id, field="content"),
    )

    children = [action_bar, title_input, folder_select]
    if meta_pairs:
        children.append(ui.KeyValue(meta_pairs))
    children.append(tag_input)
    children.append(editor)

    return ui.Stack(children=children, gap=2, className="px-4 pb-4")

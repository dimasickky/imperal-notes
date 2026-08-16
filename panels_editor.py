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


def _fmt_size(n) -> str:
    if not isinstance(n, (int, float)) or n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def _attachments_section(note_id: str, attachments: list[dict]) -> object:
    """Upload/list/delete card — thin panel wrapper over upload_attachment/
    delete_attachment. Mirrors tasks/panels_task.py's _attachments_section:
    same shape, same reasoning, adapted for notes' own backend storage
    (base64 upload to /notes/{note_id}/attachments) instead of Vikunja."""
    items = [
        ui.ListItem(
            id=f"attachment_{a.get('id') or a.get('att_id')}",
            title=a.get("filename") or a.get("name") or "file",
            subtitle=_fmt_size(a.get("size")),
            icon="Paperclip",
            actions=[{
                "icon": "Trash2",
                "label": "Delete",
                "on_click": ui.Call("delete_attachment", note_id=note_id,
                                    att_id=a.get("id") or a.get("att_id")),
                "confirm": f"Delete attachment '{a.get('filename') or a.get('name') or 'file'}'?",
            }],
        )
        for a in attachments if (a.get("id") or a.get("att_id"))
    ]
    return ui.Card(
        title=f"Attachments ({len(items)})",
        content=ui.Stack([
            ui.List(
                items=items, selectable=True,
                bulk_actions=[
                    {"label": "Delete", "icon": "Trash2",
                     "action": ui.Call("delete_attachments")},
                ],
            ) if items else ui.Text("No attachments yet.", variant="caption"),
            ui.FileUpload(
                param_name="files",
                multiple=True,
                max_size_mb=20,
                on_upload=ui.Call("upload_attachment", note_id=note_id),
                title="Attach files",
                hint="Up to 20MB each — select several at once.",
            ),
        ], gap=2),
    )


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
        # "new" is not a note id, it is an instruction — and the host keeps it.
        #
        # Panel params are sticky: the host merges each call's params over the
        # previous ones for that panel, and a refresh (which any write event can
        # trigger) re-invokes the panel with the merged set. So `note_id="new"`
        # from the New Note button stays in that set and every later refresh
        # arrives here again and creates ANOTHER note. Nine empty "Untitled"
        # notes in the database came from this — four of them for one user
        # inside seventy seconds, which is no one's clicking speed.
        #
        # The branch is therefore made idempotent instead of merely fast: if the
        # user already has an untouched blank note, that one is reopened rather
        # than a second one being made. A blank note is defined as Untitled with
        # an empty body, not archived and not trashed — a note the user has typed
        # anything into no longer matches and is never recycled.
        try:
            existing_blank = ""
            try:
                probe = await _api_get(ctx, "/notes", {
                    "user_id": uid, "tenant_id": tid,
                    "limit": 20, "offset": 0,
                    "is_archived": False, "is_trashed": False,
                })
                # The list endpoint deliberately does NOT return the body (it
                # selects metadata only), so emptiness is judged by word_count,
                # which it does return. Checking a missing content field here
                # would read as "empty" for EVERY note and could recycle one that
                # is full of text — the body is confirmed below before reuse.
                for candidate in (probe.get("notes") or []):
                    if (
                        (candidate.get("title") or "").strip() in ("", "Untitled")
                        and not candidate.get("word_count")
                        and not candidate.get("attachment_count")
                    ):
                        existing_blank = candidate.get("id") or ""
                        break
            except Exception as probe_err:  # noqa: BLE001 — probe is an optimisation
                log.warning("editor: blank-note probe failed, creating fresh: %s", probe_err)

            note = {}
            if existing_blank:
                # Confirm on the full note before reusing it: word_count is a
                # derived column, and reopening a note that turned out to hold
                # text would be worse than the extra empty note this avoids.
                try:
                    data = await _api_get(ctx, f"/notes/{existing_blank}", {"user_id": uid})
                    candidate_note = data.get("note", {})
                    body = (candidate_note.get("content_text") or candidate_note.get("content") or "")
                    if not body.strip():
                        log.info("editor: reusing blank note %s instead of creating another", existing_blank)
                        note_id = existing_blank
                        note = candidate_note
                    else:
                        existing_blank = ""
                except Exception as confirm_err:  # noqa: BLE001
                    log.warning("editor: blank-note confirm failed, creating fresh: %s", confirm_err)
                    existing_blank = ""

            if not existing_blank:
                result = await _api_post(ctx, "/notes", {
                    "user_id": uid, "tenant_id": tid,
                    "title": "Untitled", "content_text": "",
                })
                note    = result.get("note", {})
                note_id = note.get("id", "")
                if not note_id:
                    return ui.Error(message="Failed to create note")
        except Exception as e:
            log.error("editor: create new note failed: %s", e)
            return ui.Error(message="Failed to create note. Please try again.")
    else:
        try:
            data = await _api_get(ctx, f"/notes/{note_id}", {"user_id": uid})
            note = data.get("note", {})
        except Exception as e:
            log.warning("editor: failed to fetch note %s: %s", note_id, e)
            return ui.Error(
                message="Could not load note. Please try again.",
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
    # The backend already tracks per-note attachments (list_notes returns
    # attachment_count); get_note's raw response is read defensively here in
    # case it inlines the attachment array too — if it doesn't, this is just
    # an empty list and upload still works, it only means the freshly
    # uploaded file won't show until the next backend release adds the field.
    attachments  = note.get("attachments") or []

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
    # on_save (Ctrl+S) and on_change (debounced 500ms in the editor component)
    # go to two DIFFERENT functions on purpose. on_change → note_autosave, which
    # emits no event and refreshes nothing, so typing is never interrupted;
    # on_save → note_save, the explicit save, which behaves as before.
    editor = ui.RichEditor(
        content=content_html,
        placeholder="Start writing...",
        param_name="content_text",
        on_save=ui.Call("note_save", note_id=note_id, field="content"),
        on_change=ui.Call("note_autosave", note_id=note_id),
    )

    children = [action_bar, title_input, folder_select]
    if meta_pairs:
        children.append(ui.KeyValue(meta_pairs))
    children.append(tag_input)
    children.append(editor)
    children.append(_attachments_section(note_id, attachments))

    return ui.Stack(children=children, gap=2, className="px-4 pb-4")

"""Notes · Editor panel (center overlay with RichEditor)."""
from __future__ import annotations

import logging
from datetime import datetime

from imperal_sdk import ui

from app import ext, _api_get, _api_post, _user_id, _tenant_id

log = logging.getLogger("notes")


# ── Helpers ───────────────────────────────────────────────────────────────


def _format_date(iso_str: str) -> str:
    """Format ISO date to human-readable."""
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
        html = markdown.markdown(raw, extensions=["extra", "nl2br", "sane_lists"])
        return html
    except Exception:
        lines = raw.split("\n\n")
        return "".join(f"<p>{line}</p>" for line in lines if line.strip())


# ── Editor Panel (CENTER OVERLAY) ─────────────────────────────────────────


@ext.panel("editor", slot="center", title="Editor", icon="Edit")
async def notes_editor(ctx, note_id: str = "", **kwargs):
    """Note editor — opens as center overlay with RichEditor."""
    uid, tid = _user_id(ctx), _tenant_id(ctx)

    if not note_id:
        return ui.Empty(message="Select a note to edit", icon="FileText")

    if note_id == "new":
        try:
            result = await _api_post("/notes", {
                "user_id": uid, "tenant_id": tid,
                "title": "Untitled", "content_text": "",
            })
            note = result.get("note", {})
            note_id = note.get("id", "")
            if not note_id:
                return ui.Error(message="Failed to create note")
        except Exception as e:
            return ui.Error(message=f"Failed to create note: {e}")
    else:
        try:
            data = await _api_get(f"/notes/{note_id}", {"user_id": uid})
            note = data.get("note", {})
        except Exception as e:
            log.warning("Editor: failed to fetch note %s: %s", note_id, e)
            return ui.Error(
                message=f"Could not load note: {e}",
                retry=ui.Call("__panel__editor", note_id=note_id),
            )

    title = note.get("title", "Untitled")
    content_html = _prepare_content(note)
    word_count = note.get("word_count", 0)
    is_pinned = note.get("is_pinned", False)
    tags = note.get("tags", [])
    created = _format_date(note.get("created_at", ""))
    updated = _format_date(note.get("updated_at", ""))

    pin_label = "Unpin" if is_pinned else "Pin"
    pin_icon = "PinOff" if is_pinned else "Pin"

    action_bar = ui.Stack([
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__sidebar")),
        ui.Button(pin_label, icon=pin_icon, variant="outline", size="sm",
                  on_click=ui.Call("note_save", note_id=note_id, field="pin")),
        ui.Button("Delete", icon="Trash2", variant="destructive", size="sm",
                  on_click=ui.Call("delete_note", note_id=note_id)),
    ], direction="horizontal", wrap=True, sticky=True)

    title_input = ui.Input(
        placeholder="Note title...",
        value=title,
        param_name="title",
        on_submit=ui.Call("note_save", note_id=note_id, field="title"),
    )

    meta_pairs = []
    if word_count:
        meta_pairs.append({"key": "Words", "value": str(word_count)})
    if created:
        meta_pairs.append({"key": "Created", "value": created})
    if updated:
        meta_pairs.append({"key": "Modified", "value": updated})
    if tags:
        meta_pairs.append({"key": "Tags", "value": " ".join(f"#{t}" for t in tags[:5])})
    meta_pairs.append({"key": "ID", "value": note_id[:12] + "..."})

    editor = ui.RichEditor(
        content=content_html,
        placeholder="Start writing...",
        param_name="content_text",
        on_save=ui.Call("note_save", note_id=note_id, field="content"),
        on_change=ui.Call("note_save", note_id=note_id, field="content"),
    )

    children = [action_bar, title_input]
    if meta_pairs:
        children.append(ui.KeyValue(meta_pairs))
    children.append(editor)

    return ui.Stack(children=children, gap=2, className="px-4 pb-4")

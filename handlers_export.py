"""Notes · Duplicate and Export Markdown handlers."""
from __future__ import annotations

import urllib.parse

import html2text

from app import chat, ActionResult, NotesAPIError, _api_get, _api_post, require_user_id, _tenant_id
from imperal_sdk import ui
from models_notes import NoteIdParams


def _make_h2t() -> html2text.HTML2Text:
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    return h


@chat.function(
    "duplicate_note",
    action_type="write",
    chain_callable=True,
    effects=["create:note"],
    event="notes.created",
    description="Duplicate a note — copies title, content, folder, and tags into a new note.",
)
async def fn_duplicate_note(ctx, params: NoteIdParams) -> ActionResult:
    uid = require_user_id(ctx)
    tid = _tenant_id(ctx)
    if not params.note_id:
        return ActionResult.error("note_id required")

    try:
        data = await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": uid})
        note = data.get("note", {})

        result = await _api_post(ctx, "/notes", {
            "user_id":      uid,
            "tenant_id":    tid,
            "title":        f"{note.get('title', 'Untitled')} (copy)",
            "content_text": note.get("content_text") or note.get("content") or "",
            "folder_id":    note.get("folder_id"),
            "tags":         note.get("tags", []),
        })
        new_note = result.get("note", {})
        return ActionResult.success(
            data={"note_id": new_note.get("id"), "refresh_panels": ["sidebar"]},
            summary=f"Duplicated as '{new_note.get('title', '')}'",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"Duplicate failed: {e.status_code} {e.detail}")
    except Exception as e:
        return ActionResult.error(f"Duplicate failed: {e}")


@chat.function(
    "export_markdown",
    action_type="read",
    description="Export a note as Markdown. Returns the converted content with a download button.",
)
async def fn_export_markdown(ctx, params: NoteIdParams) -> ActionResult:
    uid = require_user_id(ctx)
    if not params.note_id:
        return ActionResult.error("note_id required")

    try:
        data = await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": uid})
        note = data.get("note", {})

        html = note.get("content_text") or note.get("content") or ""
        title = note.get("title", "Untitled")
        tags  = note.get("tags", [])

        md_parts = [f"# {title}"]
        if tags:
            md_parts.append(" ".join(f"#{t}" for t in tags))
        md_parts.append("")
        md_parts.append(_make_h2t().handle(html).strip() if html else "")
        markdown = "\n".join(md_parts)

        data_uri = "data:text/markdown;charset=utf-8," + urllib.parse.quote(markdown)

        return ActionResult.success(
            data={
                "title":    title,
                "markdown": markdown,
                "ui": ui.Stack([
                    ui.Button(
                        f"Download {title[:40]}.md",
                        icon="Download",
                        variant="primary",
                        on_click=ui.Open(data_uri),
                    ),
                    ui.Text("If the button opens text instead of downloading — copy from the block below."),
                    ui.Code(markdown, language="markdown"),
                ]),
            },
            summary=f"Exported '{title}' as Markdown",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"Export failed: {e.status_code} {e.detail}")
    except Exception as e:
        return ActionResult.error(f"Export failed: {e}")

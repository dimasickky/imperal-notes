"""Notes · Duplicate and Export Markdown handlers."""
from __future__ import annotations

import html2text
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app import chat, ActionResult, _api_get, _api_post, require_user_id, _tenant_id
from imperal_sdk import ui


_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = True
_h2t.body_width = 0  # no line wrapping


class NoteIdParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    note_id: str = Field(
        default="", description="Note UUID",
        validation_alias=AliasChoices("note_id", "noteId", "id"),
    )


@chat.function(
    "duplicate_note",
    action_type="write",
    event="notes.created",
    description="Duplicate a note — copies title and content into a new note.",
)
async def fn_duplicate_note(ctx, params: NoteIdParams) -> ActionResult:
    uid = require_user_id(ctx)
    tid = _tenant_id(ctx)
    if not params.note_id:
        return ActionResult.error("note_id required")

    try:
        data = await _api_get(f"/notes/{params.note_id}", {"user_id": uid})
        note = data.get("note", {})

        result = await _api_post("/notes", {
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
    except Exception as e:
        return ActionResult.error(f"Duplicate failed: {e}")


@chat.function(
    "export_markdown",
    action_type="read",
    description="Export a note as Markdown. Returns the converted content.",
)
async def fn_export_markdown(ctx, params: NoteIdParams) -> ActionResult:
    uid = require_user_id(ctx)
    if not params.note_id:
        return ActionResult.error("note_id required")

    try:
        data = await _api_get(f"/notes/{params.note_id}", {"user_id": uid})
        note = data.get("note", {})

        html = note.get("content_text") or note.get("content") or ""
        title = note.get("title", "Untitled")
        tags = note.get("tags", [])

        md_parts = [f"# {title}"]
        if tags:
            md_parts.append(" ".join(f"#{t}" for t in tags))
        md_parts.append("")
        md_parts.append(_h2t.handle(html).strip() if html else "")
        markdown = "\n".join(md_parts)

        return ActionResult.success(
            data={
                "title":    title,
                "markdown": markdown,
                "ui": ui.Stack([
                    ui.Text(f"Export: **{title}.md** — select all and copy to save as a file."),
                    ui.Code(markdown, language="markdown"),
                ]),
            },
            summary=f"Exported '{title}' as Markdown (copy from the code block to save as .md)",
        )
    except Exception as e:
        return ActionResult.error(f"Export failed: {e}")

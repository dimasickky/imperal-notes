"""Notes · NotesExtension — class-based v2.0 tool surface.

All user-visible operations live here as `@sdk_ext.tool` methods on a single
`Extension` subclass. The SDK loader discovers the instance (`app.ext =
NotesExtension(...)`) and the kernel drives each tool directly — there is no
per-extension LLM loop or `ChatExtension`. Webbee Narrator renders all prose
from the returned `output_schema` (I-WEBBEE-SOLE-NARRATOR).

Contract:
- Every tool returns its declared Pydantic `output_schema`. No raises on
  domain errors — errors surface as `ok=False, error=<msg>` inside the
  schema so the Narrator composes one response across both branches.
- HTTP / auth exceptions from the backend are caught and flattened to the
  same error envelope. `require_user_id` still raises on a missing ctx.user
  (kernel bug-class fail-loud) — that propagates and the kernel reports it
  with a classified error_code.
- `cost_credits=1` marks destructive ops that always trigger the pre-ACK
  confirmation gate regardless of user's default confirmation setting.
"""
from __future__ import annotations

import logging

import httpx
from imperal_sdk import Extension, ext as sdk_ext

from schemas import (
    FolderCreated,
    FolderDeleted,
    FolderList,
    FolderRef,
    FolderRenamed,
    FolderResolved,
    MAX_NOTES_PER_PAGE,
    NoteCreated,
    NoteDeleted,
    NoteDetail,
    NoteListResult,
    NoteMoved,
    NoteRestored,
    NoteSaved,
    NoteSummary,
    NoteUpdated,
    SearchHit,
    SearchResult,
    TrashedNote,
    TrashEmptied,
    TrashList,
)

log = logging.getLogger("notes.tools")


# ─── HTTP error → envelope helper ─────────────────────────────────────── #

def _explain_http_error(exc: Exception) -> str:
    """Flatten an httpx / api-client exception into one human sentence."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail") or exc.response.text
        except Exception:
            detail = exc.response.text
        return f"notes-api {exc.response.status_code}: {detail}"
    return str(exc) or exc.__class__.__name__


# ─── Notes Extension ──────────────────────────────────────────────────── #

class NotesExtension(Extension):
    """Personal notes extension — CRUD, folders, trash, full-text search.

    Backend: notes-api (api-server:8097). Wire contract is frozen — this class
    only translates between tool args and `/notes` / `/folders` REST calls.
    """

    app_id = "notes"

    # ── Notes: read ───────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description=(
            "List the user's notes with optional folder / full-text / tag filters. "
            "Paginated up to 200 per page — when has_more=true, call again with "
            "offset=offset+limit to continue."
        ),
        output_schema=NoteListResult,
        scopes=["notes:read"],
    )
    async def list_notes(
        self,
        ctx,
        folder_id: str = "",
        search: str = "",
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> NoteListResult:
        from app import _api_get, _tenant_id, require_user_id

        try:
            tags = list(tags or [])
            limit = max(1, min(int(limit), MAX_NOTES_PER_PAGE))
            offset = max(0, int(offset))

            qp: dict = {
                "user_id": require_user_id(ctx),
                "tenant_id": _tenant_id(ctx),
                "limit": limit,
                "offset": offset,
            }
            if folder_id:
                qp["folder_id"] = folder_id
            if search:
                qp["search"] = search
            if tags:
                qp["tags"] = ",".join(tags)

            resp = await _api_get("/notes", qp)
            raw = resp.get("notes", [])

            # AND-tag client fallback: older notes-api ignored ?tags= and
            # returned everything. Filtering here gives the LLM a stable
            # contract regardless of backend version — no-op when the backend
            # has already filtered.
            if tags:
                wanted = {t.strip().lower() for t in tags if t.strip()}
                if wanted:
                    raw = [
                        n for n in raw
                        if wanted.issubset({str(t).lower() for t in n.get("tags", [])})
                    ]

            total_count = resp.get("total_count")
            if total_count is None:
                has_more = len(raw) == limit
                total_known = False
            else:
                has_more = (offset + len(raw)) < int(total_count)
                total_known = True

            return NoteListResult(
                notes=[
                    NoteSummary(
                        note_id=n["id"],
                        title=n["title"],
                        word_count=n.get("word_count", 0),
                        is_pinned=n.get("is_pinned", False),
                        is_archived=n.get("is_archived", False),
                        tags=list(n.get("tags", [])),
                        folder_id=n.get("folder_id"),
                    ) for n in raw
                ],
                page_size=len(raw),
                offset=offset,
                limit=limit,
                has_more=has_more,
                next_offset=(offset + len(raw)) if has_more else None,
                total_count=int(total_count) if total_known else None,
            )
        except Exception as e:
            return NoteListResult(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description="Retrieve the full content, tags and metadata of a single note by ID.",
        output_schema=NoteDetail,
        scopes=["notes:read"],
    )
    async def get_note(self, ctx, note_id: str) -> NoteDetail:
        from app import _api_get, require_user_id

        try:
            resp = await _api_get(f"/notes/{note_id}", {"user_id": require_user_id(ctx)})
            n = resp.get("note", {}) or {}
            return NoteDetail(
                note_id=n.get("id", note_id),
                title=n.get("title", ""),
                content_text=n.get("content_text", ""),
                tags=list(n.get("tags", [])),
                is_pinned=n.get("is_pinned", False),
                is_archived=n.get("is_archived", False),
                word_count=n.get("word_count", 0),
                folder_id=n.get("folder_id"),
            )
        except Exception as e:
            return NoteDetail(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description=(
            "Full-text search across the user's notes. Paginated up to 200 per "
            "page; has_more / next_offset allow iteration. Do not claim to have "
            "searched everything until has_more=false."
        ),
        output_schema=SearchResult,
        scopes=["notes:read"],
    )
    async def search_notes(
        self, ctx, query: str, limit: int = 20, offset: int = 0,
    ) -> SearchResult:
        from app import _api_get, _tenant_id, require_user_id

        try:
            limit = max(1, min(int(limit), MAX_NOTES_PER_PAGE))
            offset = max(0, int(offset))
            resp = await _api_get("/notes/search/fulltext", {
                "user_id":   require_user_id(ctx),
                "tenant_id": _tenant_id(ctx),
                "q":         query,
                "limit":     limit,
                "offset":    offset,
            })
            raw = resp.get("results", [])
            total_count = resp.get("total_count")
            if total_count is None:
                has_more = len(raw) == limit
                total_known = False
            else:
                has_more = (offset + len(raw)) < int(total_count)
                total_known = True
            return SearchResult(
                query=query,
                results=[
                    SearchHit(
                        note_id=r.get("id", ""),
                        title=r.get("title", ""),
                        excerpt=(r.get("excerpt", "") or "")[:200],
                        is_archived=r.get("is_archived", False),
                    ) for r in raw
                ],
                page_size=len(raw),
                offset=offset,
                limit=limit,
                has_more=has_more,
                next_offset=(offset + len(raw)) if has_more else None,
                total_count=int(total_count) if total_known else None,
            )
        except Exception as e:
            return SearchResult(ok=False, error=_explain_http_error(e), query=query)

    # ── Notes: write ──────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description=(
            "Create a new note with the given title and text content. Optionally "
            "place it in a folder and attach tags at creation time."
        ),
        output_schema=NoteCreated,
        scopes=["notes:write"],
    )
    async def create_note(
        self,
        ctx,
        title: str,
        content_text: str,
        tags: list[str] | None = None,
        folder_id: str = "",
    ) -> NoteCreated:
        from app import _api_post, _tenant_id, require_user_id

        try:
            # Title-bleed guard: defend against automation/template bugs where an
            # interpolated title ends up concatenated into the content (observed
            # in prod 2026-04-23). Strip the duplicate prefix so data is clean
            # at rest regardless of whoever called us.
            if title and len(title) >= 3 and content_text.startswith(title):
                log.warning(
                    "title-bleed detected on create_note (title=%r); stripping prefix",
                    title[:40],
                )
                content_text = content_text[len(title):].lstrip(": \n\t")

            body: dict = {
                "user_id":      require_user_id(ctx),
                "tenant_id":    _tenant_id(ctx),
                "title":        title,
                "content_text": content_text,
                "tags":         list(tags or []),
            }
            if folder_id:
                body["folder_id"] = folder_id

            n = (await _api_post("/notes", body)).get("note", {}) or {}
            return NoteCreated(
                note_id=n.get("id", ""),
                title=n.get("title", title),
                folder_id=folder_id or None,
            )
        except Exception as e:
            return NoteCreated(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description=(
            "Update title, text content, tags or pin-state of a note. Arguments "
            "left at their default ('', None) are not touched — only provided "
            "fields are sent to the backend."
        ),
        output_schema=NoteUpdated,
        scopes=["notes:write"],
    )
    async def update_note(
        self,
        ctx,
        note_id: str,
        title: str = "",
        content_text: str = "",
        tags: list[str] | None = None,
        is_pinned: bool | None = None,
    ) -> NoteUpdated:
        from app import _api_patch, require_user_id

        try:
            updates: dict = {}
            if title:
                updates["title"] = title
            if content_text:
                updates["content_text"] = content_text
            if tags is not None:
                updates["tags"] = list(tags)
            if is_pinned is not None:
                updates["is_pinned"] = bool(is_pinned)
            if not updates:
                return NoteUpdated(ok=False, error="No fields to update", note_id=note_id)

            resp = await _api_patch(
                f"/notes/{note_id}", {"user_id": require_user_id(ctx)}, updates,
            )
            saved_title = (resp.get("note", {}) or {}).get("title", title)
            return NoteUpdated(
                note_id=note_id,
                title=saved_title,
                fields_updated=list(updates.keys()),
            )
        except Exception as e:
            return NoteUpdated(ok=False, error=_explain_http_error(e), note_id=note_id)

    @sdk_ext.tool(
        description=(
            "Move a note to a different folder. Pass an empty folder_id to move "
            "the note back to the root (All Notes) view."
        ),
        output_schema=NoteMoved,
        scopes=["notes:write"],
    )
    async def move_note(self, ctx, note_id: str, folder_id: str = "") -> NoteMoved:
        from app import _api_patch, require_user_id

        try:
            resp = await _api_patch(
                f"/notes/{note_id}",
                {"user_id": require_user_id(ctx)},
                {"folder_id": folder_id if folder_id else None},
            )
            saved_title = (resp.get("note", {}) or {}).get("title", "")
            return NoteMoved(
                note_id=note_id,
                title=saved_title,
                folder_id=folder_id or None,
                moved_to=folder_id or "All Notes",
            )
        except Exception as e:
            return NoteMoved(ok=False, error=_explain_http_error(e), note_id=note_id)

    @sdk_ext.tool(
        description=(
            "Move a note to the trash. The note can be restored with restore_note "
            "until the trash is emptied permanently."
        ),
        output_schema=NoteDeleted,
        scopes=["notes:write"],
    )
    async def delete_note(self, ctx, note_id: str) -> NoteDeleted:
        from app import _api_delete, require_user_id

        try:
            await _api_delete(
                f"/notes/{note_id}",
                {"user_id": require_user_id(ctx), "permanent": "false"},
            )
            return NoteDeleted(note_id=note_id, permanent=False)
        except Exception as e:
            return NoteDeleted(ok=False, error=_explain_http_error(e), note_id=note_id)

    @sdk_ext.tool(
        description=(
            "Permanently delete a note bypassing the trash. This cannot be undone — "
            "prefer delete_note unless the user explicitly asks to purge."
        ),
        output_schema=NoteDeleted,
        scopes=["notes:write"],
        cost_credits=1,
    )
    async def permanent_delete_note(self, ctx, note_id: str) -> NoteDeleted:
        from app import _api_delete, require_user_id

        try:
            await _api_delete(
                f"/notes/{note_id}",
                {"user_id": require_user_id(ctx), "permanent": "true"},
            )
            return NoteDeleted(note_id=note_id, permanent=True)
        except Exception as e:
            return NoteDeleted(
                ok=False, error=_explain_http_error(e), note_id=note_id, permanent=True,
            )

    # ── Folders ───────────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description="List every note folder owned by the user.",
        output_schema=FolderList,
        scopes=["notes:read"],
    )
    async def list_folders(self, ctx) -> FolderList:
        from app import _api_get, _tenant_id, require_user_id

        try:
            resp = await _api_get("/folders", {
                "user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
            })
            folders = resp.get("folders", []) or []
            return FolderList(
                folders=[FolderRef(folder_id=f["id"], name=f["name"]) for f in folders],
                total=len(folders),
            )
        except Exception as e:
            return FolderList(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description=(
            "Resolve a folder by name (case-insensitive). Returns folder_id plus "
            "match_quality (exact | prefix | contains | none). Prefer this over "
            "list_folders when you need a single folder in a chain."
        ),
        output_schema=FolderResolved,
        scopes=["notes:read"],
    )
    async def resolve_folder(self, ctx, name: str) -> FolderResolved:
        from app import _api_get, _tenant_id, require_user_id

        try:
            target = (name or "").strip().lower()
            if not target:
                return FolderResolved(ok=False, error="Folder name cannot be empty")

            resp = await _api_get("/folders", {
                "user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
            })
            folders = resp.get("folders", []) or []

            exact   = [f for f in folders if f["name"].strip().lower() == target]
            prefix  = [f for f in folders if f["name"].strip().lower().startswith(target)]
            contain = [f for f in folders if target in f["name"].strip().lower()]

            if exact:
                hit, quality = exact[0], "exact"
            elif prefix:
                hit, quality = prefix[0], "prefix"
            elif contain:
                hit, quality = contain[0], "contains"
            else:
                return FolderResolved(
                    match_quality="none",
                    candidates=[
                        FolderRef(folder_id=f["id"], name=f["name"]) for f in folders
                    ],
                )

            return FolderResolved(
                folder_id=hit["id"], name=hit["name"], match_quality=quality,
            )
        except Exception as e:
            return FolderResolved(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description="Create a new note folder with the given display name.",
        output_schema=FolderCreated,
        scopes=["notes:write"],
    )
    async def create_folder(self, ctx, name: str) -> FolderCreated:
        from app import _api_post, _tenant_id, require_user_id

        try:
            if not (name or "").strip():
                return FolderCreated(ok=False, error="Folder name cannot be empty")
            resp = await _api_post("/folders", {
                "user_id":   require_user_id(ctx),
                "tenant_id": _tenant_id(ctx),
                "name":      name,
                "icon":      "folder",
            })
            f = resp.get("folder", {}) or {}
            return FolderCreated(folder_id=f.get("id", ""), name=f.get("name", name))
        except Exception as e:
            return FolderCreated(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description="Rename an existing folder to a new display name.",
        output_schema=FolderRenamed,
        scopes=["notes:write"],
    )
    async def rename_folder(self, ctx, folder_id: str, name: str) -> FolderRenamed:
        from app import _api_patch, require_user_id

        try:
            if not (name or "").strip():
                return FolderRenamed(
                    ok=False, error="Folder name cannot be empty", folder_id=folder_id,
                )
            await _api_patch(
                f"/folders/{folder_id}",
                {"user_id": require_user_id(ctx), "name": name},
                data={},
            )
            return FolderRenamed(folder_id=folder_id, name=name)
        except Exception as e:
            return FolderRenamed(
                ok=False, error=_explain_http_error(e), folder_id=folder_id,
            )

    @sdk_ext.tool(
        description=(
            "Delete a folder. Notes that were inside are moved to the root (All "
            "Notes), not deleted — but the folder itself is gone."
        ),
        output_schema=FolderDeleted,
        scopes=["notes:write"],
        cost_credits=1,
    )
    async def delete_folder(self, ctx, folder_id: str) -> FolderDeleted:
        from app import _api_delete, require_user_id

        try:
            await _api_delete(
                f"/folders/{folder_id}", {"user_id": require_user_id(ctx)},
            )
            return FolderDeleted(folder_id=folder_id)
        except Exception as e:
            return FolderDeleted(
                ok=False, error=_explain_http_error(e), folder_id=folder_id,
            )

    # ── Trash ─────────────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description="List every note currently in the trash (archived notes).",
        output_schema=TrashList,
        scopes=["notes:read"],
    )
    async def list_trash(self, ctx) -> TrashList:
        from app import _api_get, _tenant_id, require_user_id

        try:
            resp = await _api_get("/notes", {
                "user_id": require_user_id(ctx),
                "tenant_id": _tenant_id(ctx),
                "is_archived": True,
                "limit": 50,
            })
            notes = resp.get("notes", []) or []
            return TrashList(
                trash_notes=[
                    TrashedNote(
                        note_id=n["id"],
                        title=n["title"],
                        word_count=n.get("word_count", 0),
                        tags=list(n.get("tags", [])),
                    ) for n in notes
                ],
                total=len(notes),
            )
        except Exception as e:
            return TrashList(ok=False, error=_explain_http_error(e))

    @sdk_ext.tool(
        description="Restore a note from the trash back to its previous folder.",
        output_schema=NoteRestored,
        scopes=["notes:write"],
    )
    async def restore_note(self, ctx, note_id: str) -> NoteRestored:
        from app import _api_patch, require_user_id

        try:
            resp = await _api_patch(
                f"/notes/{note_id}",
                {"user_id": require_user_id(ctx)},
                {"is_archived": False},
            )
            n = resp.get("note", {}) or {}
            return NoteRestored(
                note_id=note_id,
                title=n.get("title", ""),
                folder_id=n.get("folder_id"),
            )
        except Exception as e:
            return NoteRestored(
                ok=False, error=_explain_http_error(e), note_id=note_id,
            )

    @sdk_ext.tool(
        description=(
            "Permanently delete every note currently in the trash. This cannot "
            "be undone — always ask the user to confirm before calling."
        ),
        output_schema=TrashEmptied,
        scopes=["notes:write"],
        cost_credits=1,
    )
    async def empty_trash(self, ctx) -> TrashEmptied:
        from app import _api_post, _tenant_id, require_user_id

        try:
            resp = await _api_post(
                "/notes/trash/empty",
                data=None,
                params={
                    "user_id":   require_user_id(ctx),
                    "tenant_id": _tenant_id(ctx),
                },
            )
            return TrashEmptied(deleted_count=int(resp.get("deleted_count", 0)))
        except Exception as e:
            return TrashEmptied(ok=False, error=_explain_http_error(e))

    # ── Panel action (internal, called by editor panel) ──────────────── #

    @sdk_ext.tool(
        description=(
            "Internal panel action: save a single field (title, content, pin) of "
            "a note from the editor UI. Not for LLM routing — prefer update_note."
        ),
        output_schema=NoteSaved,
        scopes=["notes:write"],
    )
    async def note_save(
        self,
        ctx,
        note_id: str,
        field: str,
        title: str = "",
        content_text: str = "",
    ) -> NoteSaved:
        from app import _api_get, _api_patch, require_user_id

        try:
            uid = require_user_id(ctx)

            if field == "title":
                if not title:
                    return NoteSaved(
                        ok=False, error="Title cannot be empty",
                        note_id=note_id, saved_field="title",
                    )
                await _api_patch(f"/notes/{note_id}", {"user_id": uid}, {"title": title})
                return NoteSaved(note_id=note_id, saved_field="title")

            if field == "content":
                await _api_patch(
                    f"/notes/{note_id}", {"user_id": uid},
                    {"content_text": content_text},
                )
                return NoteSaved(note_id=note_id, saved_field="content")

            if field == "pin":
                current = (
                    (await _api_get(f"/notes/{note_id}", {"user_id": uid}))
                    .get("note", {}) or {}
                ).get("is_pinned", False)
                new_state = not current
                await _api_patch(
                    f"/notes/{note_id}", {"user_id": uid}, {"is_pinned": new_state},
                )
                return NoteSaved(
                    note_id=note_id, saved_field="pin", is_pinned=new_state,
                )

            return NoteSaved(
                ok=False, error=f"Unknown field: {field}",
                note_id=note_id, saved_field=field,
            )
        except Exception as e:
            return NoteSaved(
                ok=False, error=_explain_http_error(e),
                note_id=note_id, saved_field=field,
            )

# Changelog

All notable changes to Imperal Notes are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [3.0.0] — 2026-04-24

**BREAKING · SDK v2.0.0 / Webbee Single Voice migration.**

Full rebuild on the v2.0 class-based tool surface. No ChatExtension, no
per-extension system prompt — Webbee Narrator composes all user-facing
prose kernel-side from typed output schemas. No user-visible feature
regressions: all 16 business operations preserved, wire contract to
notes-api (api-server:8097) unchanged.

### Added

- **`schemas.py`** — 17 Pydantic output schemas, one per tool. Every
  schema carries `ok: bool = True` + `error: str | None = None` plus
  the domain fields. Errors flow through the schema instead of raising,
  so the Narrator can ground prose on both success and failure states
  via a single shape. Grounding is federal-safe: leaf fields are
  human-readable (`note_id`, `title`, `folder_id`, `match_quality`),
  allowing the Narrator verifier to claim-check by substring / exact
  match (I-CLAIM-GROUNDING-TYPES).
- **`tools.py` · `NotesExtension(Extension)`** — class-based tool host.
  17 `@sdk_ext.tool` methods with direct-arg signatures (no Pydantic
  params wrapper), explicit `ctx` after `self`, typed return.
- **`cost_credits=1` on destructive tools** — `permanent_delete_note`,
  `delete_folder`, `empty_trash` trigger the pre-ACK confirmation gate
  regardless of user's default confirmation setting.
- **`note_save` promoted to top-level tool** — still panel-internal
  (description explicitly advises LLM to prefer `update_note`), but now
  visible in the manifest for audit.

### Removed

- **`ChatExtension`** + `tool_notes_chat` orchestrator. Per-extension
  LLM loops are gone in v2 — the kernel dispatches each tool directly.
- **`_system_prompt` + `system_prompt.txt`** (I-LOADER-REJECT-SYSTEM-PROMPT).
  All identity / voice / persona moved to the Webbee Narrator.
- **`@chat.function` + `ActionResult.success/.error`** envelope. Every
  handler replaced by `@sdk_ext.tool`; success/error flows through
  output_schema fields.
- **`action_type="read|write|destructive"`** kwarg. In v2 this signal
  moves to the Navigation classifier (coarse read/write/destructive
  resolution) and the `cost_credits` gate.
- **`handlers_notes.py`, `handlers_folders.py`, `handlers_panel_actions.py`,
  `models_notes.py`** — collapsed into `tools.py` + `schemas.py`.

### Changed

- **`imperal.json`** — `sdk_version: "2.0.0"`, per-tool manifest with
  minimal scopes + description, legacy `tool_notes_chat` entry removed.
- **`requirements.txt`** — `imperal-sdk>=2.0.0,<3.0.0`.
- **`main.py`** — bootstrap now imports `app` (which instantiates
  `NotesExtension` and exposes it as `ext`), then side-effect-imports
  `skeleton`, `panels`, `panels_editor`. The kernel loader discovers
  `ext` by duck-typing (`hasattr(attr, 'tools')` + `hasattr(attr, 'signals')`).

### Preserved (unchanged shape, same module paths)

- `skeleton.py` — `@ext.skeleton("notes", ttl=300)` refresher, same
  `{"response": {...}}` contract.
- `panels.py` (sidebar, left slot) and `panels_editor.py` (editor,
  center_overlay slot) — `@ext.panel` decorators unchanged.
- Backend wire contract with notes-api (paths, query params, body
  fields, response shapes).

### Migration

No user-visible change on the panel. Developer Portal redeploy from
`sdk-v2-migration` branch. Rollback: checkout tag `v2.4.1` +
`pip install imperal-sdk==1.6.2` in worker venv + restart kernel.

---

## [2.4.1] — 2026-04-23

Fundamental hygiene pass after deep audit of a broken Webbee session where the LLM silently no-op'd on "delete notes tagged X", claimed to have "searched all 187 notes" after a 10-row window, and produced a 92→0 count drift across chain steps. No behaviour changes for the LLM, but the extension now closes the feature gaps and observability holes that let those bugs hide. Mirror-patch of the sql-db 1.3.0 refactor.

### Added

- **`resolve_folder(name)`** — case-insensitive single-call folder lookup. Returns `folder_id` + `match_quality` (`exact` / `prefix` / `contains` / `none`) plus candidates on miss. Replaces the `list_folders` + re-match-by-name chain pattern, which was flaking under kernel `ctx` propagation drift.
- **`list_notes(tags=[...])` filter** — AND-match tag filter on list. Passed to backend as `?tags=a,b`; extension-side fallback filter applied so the contract is stable even if the backend ignores the param (older notes-api versions).
- **`search_notes(limit, offset)`** — real pagination. Returns `has_more` / `next_offset` / `total_count` / `page_size` mirroring `list_notes`. Previously hardcoded `limit=10` with no pagination surface → LLM would claim "searched all N" after seeing a 10-row window.
- **`is_archived` on list/search/get results** — lets the LLM distinguish trashed notes from live without a round-trip to trash listing.
- **`require_user_id(ctx)` helper** — raises when `ctx` has no user attached. Used by every `@chat.function` handler so a kernel-side chain step that drops `ctx.user` surfaces a loud error instead of silently scoping every backend query to no-user (indistinguishable from a real empty folder — directly produced the 92→0 count drift in prod).
- **Title-bleed guard in `create_note`** — if `title` is a ≥3-char prefix of `content_text`, the duplicate is stripped from content start with a `log.warning`. Defends against automation/template bugs where an interpolated title ends up concatenated into the body.

### Changed

- **Raw `httpx.AsyncClient` → SDK `HTTPClient`** (`app.py`). Typed `HTTPResponse`, per-request sessioning, no cross-tenant bleed. `_raise_from()` preserves the `httpx.HTTPStatusError` contract so existing handler except-clauses keep working without ripple edits.
- **Manifest hygiene** (`imperal.json`):
  - Dropped legacy `scopes: ["*"]` wildcard on `tool_notes_chat`.
  - Dropped manually-declared `skeleton_refresh_notes` — auto-derived from `@ext.skeleton` since SDK 1.5.22.
  - `required_scopes` normalized to colon-form (`notes:read`, `notes:write`); `"*"` umbrella removed.
  - `note_save` scope: `notes.write` → `notes:write` (canonical colon-form).
- **`Extension(...)` capabilities** — now declares `capabilities=["notes:read", "notes:write"]` explicitly at construction time.
- **Pydantic models extracted** — all `BaseModel` params pulled out of `handlers_notes.py` into new `models_notes.py`. Keeps `handlers_notes.py` focused on `@chat.function` logic and safely under the 300-line cap (283 lines post-refactor).
- **`system_prompt.txt` hardening:**
  - Anti-refusal denylist extended with `"недоступна в контексте"`, `"в контексте выполнения"`, `"в контексте цепочки"`, `"chain context"`, `"execution context"`, `"функция не найдена"` — covers the hallucination pattern observed when the kernel returned misrouted tool errors.
  - NEW `PAGINATION HONESTY` block forbidding "searched all notes" claims unless `has_more=false` AND `total_count` is populated. Instructs the LLM to paginate via `next_offset` for exhaustive requests.
  - Routing updated to prefer `resolve_folder` over `list_folders`+match for single-folder lookups.
- **SDK pin** — `imperal-sdk>=1.5.26,<1.6` (from `v1.5.24` git URL). Absorbs narration guardrail, `@ext.skeleton` polish, structural contradiction guard, `check_write_arg_bleed`.

### Known limitations / deferred

- **Server-side bulk delete** — `delete_notes_by_filter(tags, folder_id, title_prefix)` deferred pending a notes-api `/notes/bulk-delete` endpoint. For now the LLM must loop `list_notes(tags=[...]) + delete_note(note_id)`; the `system_prompt.txt` CAPABILITY HONESTY block instructs it to do exactly that instead of silently claiming success.
- **Backend `total_count` on list/search** — `list_notes` / `search_notes` pagination prefers a DB-wide `total_count` from notes-api when provided; falls back to a full-page heuristic otherwise. Pending notes-api patch to surface the true count.
- **`ActionResult.error(error_code=...)` not yet adopted.** SDK 1.5.26's signature is `(error: str, retryable: bool = False)`. Same limitation as sql-db 1.3.0. Deferred pending SDK API expansion.

### Why this release matters

The Webbee session of 2026-04-23 produced three visible failure modes: (a) "delete notes tagged автоматизация" ended with `"Пожалуйста!"` and nothing happened; (b) `search_notes("Текущее время")` said "3 exact matches" then "0 exact matches" on the very next turn; (c) `list_notes(folder="отчёты")` said 92 → 90 → 0 across chain steps. This release closes every extension-side contribution:

- **(a)** feature gap — no `tags` filter, no bulk op — now has the filter, the prompt tells the LLM to loop, and the extension will no longer pretend to succeed.
- **(b)** search hidden-cap — now has `has_more`/`total_count`, the prompt forbids false coverage claims.
- **(c)** silent `user_id=""` scoping — now raises loudly via `require_user_id`, so a kernel `ctx` drop becomes a visible `ActionResult.error` instead of an empty list.

Kernel-side bugs (chain-path `ctx.user` propagation drift, misrouted tool errors producing LLM-synthesised Russian refusals) are tracked separately and not in scope for this release.

---

## [2.4.0] — 2026-04-13

### Added
- `@ext.panel("editor")` — center overlay editor with `ui.RichEditor`, auto-save on change
- `@ext.panel("sidebar")` — left panel with folder tree, note list, trash view, drag & drop
- `note_save` handler — panel-specific save for title, content, pin toggle
- `@ext.health_check` — health probe for platform monitoring
- `@ext.on_install` lifecycle hook
- `panels_editor.py` split from `panels.py` (V1 file structure compliance)
- Markdown → HTML conversion in editor (`_prepare_content`)
- Folder counts in sidebar (notes per folder)
- Auto-open most recent note when no note is active

### Changed
- V1 file split: `main.py` → `app.py` + `handlers_notes.py` + `handlers_folders.py` + `handlers_panel_actions.py` + `skeleton.py` + `panels.py` + `panels_editor.py`
- All `@chat.function` params migrated to Pydantic `BaseModel` with `Field(description=...)`
- System prompt externalized to `system_prompt.txt`
- Version bump 2.3.0 → 2.4.0

---

## [2.3.0] — 2026-04-11

### Added
- `get_panel_data` — Declarative UI via `/call` endpoint (tabs: All Notes, folders, Unfiled)
- `panels.py` with `@ext.panel("sidebar")` initial implementation
- `handlers_panel_actions.py` — panel action handlers separated from chat handlers
- `imperal.json` auto-generated manifest

### Changed
- Extension split into V1 multi-file structure
- `panels.py` introduced as separate file

---

## [2.2.0] — 2026-04-08

### Added
- `move_note` — move note to folder or root
- Context strip fix in `NotesAIChat.tsx` (robust string-based approach)
- 2-Step Confirmation exact-category matching support

### Fixed
- `stripNoteContext()` regex failure due to encoding — replaced with string-based parser

---

## [2.1.0] — 2026-04-05

### Added
- Trash / Recycle Bin — soft-delete pattern
- `list_trash`, `restore_note`, `empty_trash` functions
- `permanent_delete_note` — permanent delete with disk cleanup
- Folder restore validation (folder existence check on restore)

---

## [2.0.0] — 2026-03-28

### Added
- `ChatExtension` pattern — single `tool_notes_chat` entry point
- LLM internal routing via tool_use (replaces manual dispatch)
- `create_note`, `update_note`, `delete_note`, `search_notes`
- `list_folders`, `create_folder`, `delete_folder`
- `skeleton_refresh_notes` — background stats (total, pinned, trash count, recent)
- `skeleton_alert_notes` — alert stub
- Tags support on notes
- Pin/unpin via `update_note(is_pinned=...)`

### Changed
- Full rewrite from raw `@ext.tool` to `ChatExtension` pattern
- Notes API moved to a dedicated hosted backend service (FastAPI + MySQL-compatible DB)

---

## [1.0.0] — 2026-03-01

### Added
- Initial release
- Basic note CRUD via `@ext.tool`
- Folder support
- Fulltext search (MySQL MATCH/AGAINST)
- Attachment upload and serving
- Panel UI: NotesSidebar + NoteEditor + NotesAIChat (React/Next.js)

# Changelog

All notable changes to Imperal Notes are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [3.4.1] — 2026-05-05

### Fixed

- **Intent classifier anchoring** — `create_folder`, `rename_folder`, `resolve_folder` descriptions did not contain the word "notes". The intent classifier sees all tool descriptions from all extensions simultaneously with no extension-name context; generic descriptions like "Create a new folder." are ambiguous against tasks project/bucket concepts. Fixed by adding the "notes" qualifier: "Create a new notes folder.", "Rename an existing notes folder.", "Resolve a notes folder by name...".

---

## [3.4.0] — 2026-05-05

### Changed

- **SDK upgraded to `imperal-sdk==4.1.2`** — picks up Pydantic feedback-loop (4.1.0), narration schema tightening (4.1.1), and `id_projection` chain dispatch (4.1.2).
- **`id_projection` added to all compound-named chain functions** — fixes kernel chain-step target projection for names where the verb-prefix heuristic produced a non-existent field:
  - `upload_attachment` → `id_projection="note_id"` (heuristic: `attachment_id` ✗)
  - `delete_attachment` → `id_projection="note_id"` (heuristic: `attachment_id` → wrong alias)
  - `delete_folder_with_contents` → `id_projection="folder_id"` (heuristic: `folder_with_contents_id` ✗)
  - `permanent_delete_note` → `id_projection="note_id"` (heuristic strips "permanent" → `delete_note_id` ✗)
  - `note_save` → `id_projection="note_id"` (heuristic strips "note" → `save_id` ✗)

---

## [3.3.1] — 2026-05-04

### Fixed

- **Removed kernel PROJECTIONS bypass** — `app.py` was importing `imperal_kernel.orchestration.target_resolver.PROJECTIONS` directly and mutating it from extension code. This violates the Federal Extension Contract (extensions must use SDK primitives only). In chain context, the projection for `create_note` was injecting only `folder_id` from the previous step result, causing "Note must have a title or content" errors when the kernel tried to auto-invoke `create_note` downstream. Projections removed; the underlying kernel heuristic bug (`delete_notes_from_folder` → wrong field name `notes_from_folder_id`) is tracked separately as a kernel-side fix.
- **`create_note` empty params** — system prompt now explicitly instructs the LLM to ask the user for title or content (in the conversation language) instead of calling `create_note` with empty params when no details are provided.

---

## [3.3.0] — 2026-05-04

### Fixed

- **Folder operations by name** — `delete_notes_from_folder` and `delete_folder_with_contents` now accept a folder name OR UUID in `folder_id`. `_resolve_folder_id_or_name` in `app.py` detects non-UUID input and auto-resolves via `GET /folders` (exact → prefix → contains match). No separate `resolve_folder` call required from the LLM.
- **Kernel `PROJECTIONS` registration** — the kernel's `_derive_id_field_from_tool_name` heuristic incorrectly derives `notes_from_folder_id` from `delete_notes_from_folder` (strips `delete_` prefix, appends `_id`). Registered explicit projections for `delete_notes_from_folder`, `delete_folder_with_contents`, `create_note`, and `list_notes` so the `action_executor` AA_BRANCH path correctly maps `folder_id` from the resolved folder item instead of throwing an INTERNAL exception.
- **`folder_id` field description** — updated in both `DeleteNotesFromFolderParams` and `DeleteFolderWithContentsParams` to explicitly state "UUID or folder name — auto-resolved". Prevents LLM from treating the field as UUID-only and passing empty value.
- **`_UUID_RE` moved to `app.py`** — shared regex for UUID detection, used by `_resolve_folder_id_or_name`.

### Changed

- **`system_prompt.txt` routing rules 13a/13b** — updated to `folder_id=X` (name or UUID), removing the mandatory two-step `resolve_folder → delete` pattern. Both paths still work; direct name passing is now the primary.

---

## [3.2.0] — 2026-05-03

### Added

- **`delete_notes_from_folder` audit fixes** — sidebar refresh now triggers on `notes.bulk_deleted` and `notes.folder_with_contents_deleted` (previously missing); removed stale `notes.archived` / `notes.unarchived` from refresh trigger (events were never emitted).

### Fixed

- **`handlers_export.py`** — module-level `html2text.HTML2Text()` singleton replaced with `_make_h2t()` factory function; avoids shared mutable state across concurrent requests.
- **`handlers_export.py`** — removed duplicate `NoteIdParams` class; now imports canonical version from `models_notes`.
- **`main.py`** — added `models_notes` to `sys.modules` purge list so hot-reload correctly picks up model changes.
- **`system_prompt.txt`** — function count corrected 19 → 23; `duplicate_note`, `export_markdown`, `note_save`, `upload_attachment`, `delete_attachment` documented.

### Changed

- **`requirements.txt`** — SDK pin bumped `4.0.1` → `4.1.0` (Pydantic feedback loop, runtime invariants).

---

## [3.1.0] — 2026-05-02

### Added

- **`delete_notes_from_folder`** — bulk-delete all notes in a folder via `DELETE /notes/bulk`. `permanent=false` moves to trash; `permanent=true` hard-deletes. Replaces the previous loop pattern.
- **`delete_folder_with_contents`** — two-step atomic operation: (1) `DELETE /notes/bulk` for all notes in folder, (2) `DELETE /folders/{id}`. Needed because backend `DELETE /folders/{id}` only orphans notes (sets `folder_id=NULL`), it does not cascade-delete them.
- **`DELETE /notes/bulk` backend endpoint** — added to `notes-api routes_notes.py`; accepts `user_id`, `folder_id`, `permanent` query params. Removes or trashes all non-trashed notes in the folder in a single DB operation.
- **`system_prompt.txt` routing** — rules 13a (`delete_folder_with_contents`), 13b (`delete_notes_from_folder`), 13c (`resolve_folder`) added. Rule 13 clarified: `delete_folder` keeps notes (moves to root), does not cascade.

---

## [3.0.0] — 2026-05-01

### Breaking
- Requires `imperal-sdk==4.0.1` (federal contract v4.0.0)

### Changed
- **SDK 4.0.1 migration** — `Extension()` now declares `display_name`, `description`, `icon`, `actions_explicit=True` (V14/V15/V21 compliance)
- **ctx.http** — replaced module-level `HTTPClient` singleton with per-request `ctx.http`; eliminates shared state between concurrent user requests
- **NotesAPIError** — replaced `httpx.HTTPStatusError` synthesis with a clean `NotesAPIError(status_code, detail, path)`; removed httpx dependency from extension code
- **chain_callable=True + effects=[]** on all write/destructive handlers (federal typed-dispatch contract; kernel chain planner now dispatches directly without LLM router)
- **@ext.emits declarations** — 10 event types registered for UEB manifest §M7
- **ctx.cache** — folders list (TTL=60s) and folder stats (TTL=30s) cached in sidebar; folders (60s) and tags (120s) cached in editor; reduces API calls per panel render
- **Manifest schema v3** — `imperal.json` regenerated with per-tool `action_type`, `chain_callable`, `effects`, `owner_chat_tool`
- **skeleton.py** — removed `**kwargs` from `skeleton_refresh_notes`; fixed trash count query (`is_trashed=True`, was incorrectly using `is_archived=True`)
- **panels.py** — helper functions `_append_archived` / `_append_trash` now receive `ctx` directly (cleaner than `uid, tid` threading)
- **Stack direction** — updated to `"h"` / `"v"` (SDK canonical form)

### Fixed
- Skeleton trash count was reporting archived note count, not trashed note count

---

## [2.6.1] — 2026-04-30

### Fixed

- **Archive ≠ Trash** — `is_trashed` column added to DB (migration `001_add_is_trashed.sql`). Soft-delete (trash) now uses `is_trashed=TRUE`; `is_archived` is a separate flag for the Archive feature. Trash and Archived views now show different notes.
- **"Back to Notes" button** — passes `view=""` explicitly; platform was preserving previous view state without it.
- **Tag search** — backend `GET /notes` now accepts `tags=a,b` query param with `JSON_CONTAINS` per-tag filtering. Client-side fallback (capped at 200) removed.
- **Export Markdown** — `ui.Code` block with copy hint replaces the previous silent no-op. Browser file download not available from within DUI platform.
- **Restore from trash** — `restore_note` now patches `is_trashed=False` (was `is_archived=False`).

---

## [2.6.0] — 2026-04-30

### Added

- **⋮ Menu in editor action bar** — replaces standalone Archive/Delete buttons with a `ui.Menu` dropdown: Duplicate, Export Markdown, separator, Archive/Unarchive, Delete. Pin button stays standalone.
- **Duplicate note** — `duplicate_note` handler copies title, content, folder, and tags into a new note; refreshes the sidebar.
- **Export Markdown** — `export_markdown` handler converts note HTML→Markdown via `html2text`, returns `ui.Code` block with the result.
- **`handlers_export.py`** — new file for duplicate and export handlers.
- **`html2text>=2024.0.0`** — added to `requirements.txt`.

---

## [2.5.9] — 2026-04-30

### Added

- **Archive tab** — new "Archived" button in the sidebar toolbar opens a dedicated view of all archived notes with Unarchive / Delete actions. Sidebar refreshes on `notes.archived` and `notes.unarchived` events.
- **Archive/Unarchive button** in the editor action bar — toggles between "Archive" and "Unarchive" depending on the note's current state.
- **`fn_note_save` field="archive"/"unarchive"** — PATCHes `is_archived` boolean and refreshes the sidebar.

### Fixed

- **Trash "Back" button** — added explicit "← Back to Notes" button at the top of the trash view (toggling the "Trash" button was not obvious enough as a way to exit).

---

## [2.5.8] — 2026-04-30

### Fixed

- **Search pagination** — `GET /notes/search/fulltext` now supports `offset` parameter and returns `total_count` (DB-accurate, via COUNT(*)) instead of the previous `total: len(results)` which was always the page size. Extension correctly uses `total_count` to compute `has_more` and `next_offset`.
- **Search limit cap** — `SearchNotesParams.limit` max corrected from 200 → 50 to match the backend FULLTEXT cap. Added `MAX_SEARCH_PER_PAGE = 50` constant alongside existing `MAX_NOTES_PER_PAGE = 200`.

---

## [2.5.7] — 2026-04-30

### Added

- **Attachments** — new `ui.Accordion` section in the editor panel with `ui.FileUpload` (images, PDF, txt, md up to 20MB) and a list of existing attachments with delete buttons. Upload/delete handlers auto-refresh the editor panel.
- **`handlers_attachments.py`** — new file with `upload_attachment` and `delete_attachment` `@chat.function` handlers; base64 FileUpload payload decoded and forwarded to backend as multipart.
- **`_api_upload` helper** — added to `app.py` for multipart file uploads via `HTTPClient`.

---

## [2.5.6] — 2026-04-30

### Added

- **Folder selector** — `ui.Select` in the editor panel lets users move a note to a different folder without leaving the editor. Options are fetched from `GET /folders`, includes "No folder" to remove from any folder. Changes auto-save via `note_save(field="folder")` and refresh the sidebar.
- **`fn_note_save` field="folder"** — new save path in `handlers_panel_actions.py`; PATCHes `/notes/{id}` with the new `folder_id` (or `None` to unset).

---

## [2.5.5] — 2026-04-30

### Added

- **Tags editing** — `ui.TagInput` in the editor panel replaces the read-only `KeyValue("Tags: #a #b")` display. Tags are now editable inline with autocomplete suggestions sourced from all tags the user has used across their notes. Changes auto-save via `note_save(field="tags")`.
- **`GET /notes/tags` backend endpoint** — new `notes-api` route returns all unique tags for a user across active (non-archived) notes; used by the editor for tag suggestions.
- **`fn_note_save` field="tags"** — new save path in `handlers_panel_actions.py`; PATCHes `/notes/{id}` with the updated tag list and refreshes the sidebar.

---

## [2.5.4] — 2026-04-30

### Fixed

- **`handlers_folders.py`** — `fn_rename_folder` was sending `name` in the JSON body (2.5.2 regression). `notes-api PATCH /folders/{id}` reads `name` as a Query parameter, not from the request body — so the body-driven path saw nothing to change and silently no-op'd. Moved `name` back to the query string; body is now empty `{}` as the API expects.
- **`requirements.txt`** — SDK pin bumped `==3.4.1` → `==3.5.0` to match the actual worker venv (`/home/imperal-platform-worker/venv`). Discrepancy was a deployment drift risk.

---

## [2.5.3] — 2026-04-29

### Changed

- **`requirements.txt`** — bump `imperal-sdk==3.0.0` → `==3.4.1`. Pulls in the LLM-FU-1/FU-2 stack (gpt-5 / o-series `max_completion_tokens` rename + `temperature` drop) so chains routed through reasoning models stop falling over to `anthropic/haiku`. No source changes — extension code already complies with the 3.x surface (3.3.0 `ChatExtension(model=)` removal done in 2.5.2; 3.4.0 panel-slot whitelist already met by `panels.py` `slot="left"` + `panels_editor.py` `slot="center"`).

---

## [2.5.2] — 2026-04-29

Architecture audit pass: rename_folder fix + LLM-input hardening on the panel-action handler + SDK 3.3 deprecation cleanup.

### Fixed (P1)

- **`handlers_folders.py`** — `fn_rename_folder` previously sent the new name in the **query string** (`?name=…`) and an empty body to notes-api PATCH. Body-driven update path saw nothing to change and the rename silently no-op'd. Moved `name` into the JSON body, query string now only carries `user_id`. Matches the pattern used by every other PATCH call in the file.

### Fixed (P2)

- **`handlers_panel_actions.py`** — `NoteSaveParams` now declares `validation_alias=AliasChoices(...)` on `note_id` / `field` / `title` / `content_text`, plus `model_config = ConfigDict(populate_by_name=True)`. Although the handler is invoked by the DUI editor's `ui.Call("note_save", ...)`, it is registered as `@chat.function` and therefore exposed to LLM tool surface; the previous shape would raise `VALIDATION_MISSING_FIELD` into chat on `noteId`/`action`/`body` calls.
- **`models_notes.py`** — `tags` field on `ListNotesParams`, `CreateNoteParams`, and `UpdateNoteParams` accepts a comma-separated string from the LLM in addition to a list (`"work,personal"` → `["work","personal"]`). LLMs occasionally serialize lists as strings; without coercion Pydantic raised `list_type` straight into chat.
- **`app.py`** — `ChatExtension(model="claude-haiku-4-5-20251001")` removed (deprecated since SDK 3.3.0). LLM model resolution now flows through kernel ctx-injection (`ctx._llm_configs`); the parameter will hard-error in SDK 4.0.
- **`app.py`** — health-check `except: pass`-style fallback now `log.warning(exc)` so probe failures show in the worker log, per the Dimasickky enterprise quality bar.
- **`main.py`** — module docstring no longer carries a stale `v2.4.0` version; entrypoint stays version-free, source of truth is `Extension(version=…)`.

### Compatibility

- SDK pin unchanged (`imperal-sdk==3.0.0`). 3.4.0 panel-slot validator (`slot="main"` → `ValueError`) does not affect this extension — `panels.py` already declares `slot="left"` and `panels_editor.py` `slot="center"`, both on the new whitelist.
- Wire contract with notes-api unchanged. The `rename_folder` body shape was always the documented contract; pre-2.5.2 the extension just wasn't using it correctly.

---

## [2.5.1] — 2026-04-27

User-visible strings flipped to English to match the workspace English-only UI policy.

### Why

The Dimasickky enterprise quality bar was updated 2026-04-27: all user-visible static strings (`ActionResult.error/success` messages, `ui.Empty.message`, `ui.Input` placeholders, `ui.Button` labels, panel headers, footer status, validation errors) live in English. Webbee LLM localizes chat replies to the user's language automatically; static UI does not get ad-hoc translations. The previous "по-русски" directive predated international/federal-grade product positioning and is now retired.

### Changed

- **`handlers_notes.py`** — 6 `ActionResult.error(...)` strings flipped to English (note id required, content/title required, search query required).
- **`handlers_folders.py`** — 4 `ActionResult.error(...)` strings flipped (folder name required, folder id required, restore note id required, new folder name empty).
- **`panels.py`** — 2 `ui.Empty(message=...)` flipped (sidebar load failure, trash load failure) plus inline RU comments replaced with English.

### Not changed

- Backend (notes-api), wire contract, SDK pin (`imperal-sdk==3.0.0`), `system_prompt.txt` (Russian phrases there are LLM negative-training corpus, intentional). Handler logic, routing, validation rules — all byte-equivalent to 2.5.0.

---

## [2.5.0] — 2026-04-27

SDK migration: `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0` (Identity Contract Unification, W1).

### Why

SDK 3.0.0 (released 2026-04-27 by Valentin) deletes `imperal_sdk.auth.user.User`, makes `User`/`UserContext` frozen Pydantic v2 models with `extra="forbid"`, and renames `.id` → `.imperal_id` on user objects. There is no alias — `ctx.user.id` raises `AttributeError` on 3.x. Production worker venv was upgraded to 3.0.0 (shared across all extensions on whm-ai-worker), so any 2.x-pinned extension breaks on every panel/skeleton/handler call that reads identity. Migration is mechanical but mandatory.

### Changed

- **`app.py`** — `_user_id(ctx)` and the `on_install` log line read `ctx.user.imperal_id` instead of `ctx.user.id`. `_tenant_id` already used `getattr(ctx.user, "tenant_id", None)` so it's unchanged. `require_user_id` docstring updated to reference `imperal_id`.
- **`requirements.txt`** — `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0`. Equality pin retained as the workspace invariant.

### Not changed

- All other Python source, manifest, system_prompt, panels, models, handlers — byte-for-byte identical to 2.4.7. Yesterday's `/folders/stats` sidebar fix and the v2.4.x enterprise-quality hardening stand.

---

## [2.4.7] — 2026-04-27

Sidebar counters больше не упираются в 200. Раньше у юзеров с >200 заметок счётчики папок в sidebar были систематически занижены — панель тянула `/notes?limit=200` (server hard-cap) и считала bucket'ы по этим 200 строкам in-memory. Глобальный сортировщик `is_pinned DESC, updated_at DESC` смещал выборку, поэтому в разрезе папок количество было непредсказуемо неполным.

### Fixed

- **`panels.py`** — sidebar теперь читает per-folder counts из нового backend endpoint `GET /folders/stats`, который выдаёт DB-точный `GROUP BY folder_id` за один запрос. Counts для All Notes / Unfiled / каждой папки берутся из этих stats; in-memory bucketing остаётся только как graceful fallback на случай старого backend (capped, как было).

### Backend (notes-api)

- Новый endpoint `GET /folders/stats?user_id=&tenant_id=` (frozen wire contract, чисто аддитивный путь — старые ответы не меняются). Возвращает `{"counts": {"<folder_id>": N, "__unfiled__": M, "__all__": T, "__archived__": K}}`. Один SQL с `SUM(CASE WHEN is_archived=…)` агрегацией.
- **Bonus fix** — `POST /notes` и `POST /folders` больше не делают `SELECT *` после `INSERT`. Старый паттерн под нагрузкой давал flaky 500 (`fetchone() → None` → `AttributeError`) на ~1 из 11 параллельных insert'ов; вероятно ProxySQL routing INSERT→master / SELECT→replica с лагом. Response теперь собирается из known data + явных `created_at/updated_at` timestamp'ов.

### Not changed

- SDK pin: `imperal-sdk==2.0.1` (без изменений).
- Wire contract существующих endpoint'ов: byte-for-byte identical.

---

## [2.4.6] — 2026-04-26

Pin bump only: `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. No source changes.

### Why

`imperal-sdk` 2.0.1 (released 2026-04-25 by Valentin) supersedes the rolled-back 2.0.0 by restoring the v1.6.2 contract and shipping two ICNLI Action Authority hotfixes inside the kernel:

- `chat/guards.py` — destructive actions return `ESCALATE` instead of `BLOCK`, mirroring the existing write-action behaviour and deferring to the federal `confirmation_gate` (`I-CHATEXT-DESTRUCTIVE-ESCALATE`).
- `core/intent.action_plan.args` — JSON-encoded string for OpenAI strict-mode compatibility (`I-ACTION-PLAN-ARGS-JSON-STRING`).

Both hotfixes are kernel-internal; the SDK API surface exposed to extensions is identical to 1.6.2. Per Valentin's release note: *"v1.6.2 extensions upgrade by pin bump only."*

### Changed

- **`requirements.txt`** — `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. Equality pin retained as the workspace invariant.

### Not changed

- All Python source, manifest tools list, system_prompt, panels, models, handlers — byte-for-byte identical to 2.4.5. Yesterday's enterprise-quality hardening (AliasChoices + fail-loud guards + AlertTriangle on API failure) stands.

---

## [2.4.5] — 2026-04-26

Enterprise-grade input hardening: no more raw Pydantic validation traces leaking to chat, no more silent `0` counters when an API call fails. First pass of the `feedback_dimasickky_enterprise_quality` checklist.

### Why this matters

Yesterday a user saw `1 validation error for CreateNoteParams content_text Field required [type=missing, input_value={'content': '...', 'title': 'Работа222'}, input_type=dict]` directly in chat. The classifier-LLM had passed `content` (a synonym) instead of `content_text`, Pydantic rejected, and the stack trace surfaced verbatim. That class of leak — internal validator output reaching the user — is incompatible with a paid extension on `panel.imperal.io`.

### Fixed

- **All Pydantic input fields wired with `validation_alias=AliasChoices(...)`** so LLM synonyms (`content`/`body`/`text` for `content_text`, `name`/`subject` for `title`, `id`/`uuid` for `note_id`, `q`/`search` for `query`, `folder`/`folderId` for `folder_id`, `labels` for `tags`, `pinned` for `is_pinned`, `page_size`/`per_page` for `limit`, `skip` for `offset`) are silently accepted instead of producing `MISSING_FIELD` errors. Wire contract with notes-api stays stable — aliases are input-only.
- **All previously-required text fields now carry safe `default=""` / `default_factory=...`** — handlers normalize empty values explicitly with friendly Russian errors (`"Не указан note_id. Сначала найди заметку через search_notes."`) instead of letting Pydantic reject with a stack trace.
- **`fn_create_note` no longer creates empty notes** when both `title` and `content_text` are missing — returns an explicit error asking the LLM to provide at least one. Logs an `INFO` line when only `title` is filled (suspected folder/title confusion) so the system_prompt can be tuned later.
- **`models_notes.py` and `handlers_folders.py` model classes** all carry `model_config = ConfigDict(populate_by_name=True)` so both the canonical name and any alias can populate the field interchangeably.

### Sidebar UX

- **`panels.py` no longer renders a misleading `0` counter when the API call fails.** Both the active-notes and folders fetches now log a `WARNING` with the user id and the underlying exception, and the panel renders an explicit `ui.Empty(message="Не удалось загрузить заметки. Попробуй обновить страницу.", icon="AlertTriangle")` so the user can distinguish "no data" from "load failed". Trash view applies the same pattern.

### Out of scope

- `tool_notes_chat` system_prompt rules for title-vs-folder_id confusion and `total_count` discipline — slated for the next patch.
- `handlers_panel_actions.py` (`NoteSaveParams`) — it's panel-internal, not LLM-callable; not hardened in this pass.
- `models_notes.py` field type for `tags` (`list[str]`) when the LLM passes a comma-separated string — also next pass.

---

## [2.4.4] — 2026-04-26

Hotfix on top of 2.4.3 — sidebar showed `0` because the bumped fetch limit hit a notes-api server-side cap.

### Fixed

- **`panels.py` active-notes fetch limit reverted from `1000` to `200`.** notes-api enforces `limit ≤ 200` at the FastAPI query-validator level and returns HTTP 422 for anything higher; `_api_get` raised, the surrounding `try/except` caught it and fell through to the empty-list branch, so `total_count` ended up `0` and the sidebar displayed `0` for every user.
- **The global "All Notes" counter still reads `total_count` from the response** (the 2.4.3 intent), and that number is correct at any fetch limit — including 200 — because the API computes it server-side from the database, not from the returned page. So users past 200 notes still see the honest total.
- **Per-folder counters** stay computed from the fetched 200-item array; no folder in current production exceeds 200 notes, so the bucketing remains correct. If that changes, lifting the cap belongs in notes-api, not the panel.

### Why this slipped past 2.4.3

There is no schema-shape test on `_api_get("/notes", {"limit": ...})` against the live notes-api validator; the change was reasoned from a curl test at `limit=1` and a PRD assumption that the cap was 200 at the panel layer, not the API layer. Adding a smoke check against `notes-api/app.py` query bounds before bumping limits anywhere is the lesson.

---

## [2.4.3] — 2026-04-26

Fix sidebar counters for users past the 200-note threshold. Trash counter likewise.

### Fixed

- **`panels.py` "All Notes" counter** now reads `total_count` from the notes-api response instead of `len(all_notes)`. Previously the sidebar fetched `limit=200` and reported the array length as the global total, so any user with more than 200 active notes saw `200` as the counter regardless of their actual count (e.g. 278 → displayed `200`).
- **Per-folder and unfiled counters** continue to be computed locally over the fetched array. To keep them accurate for larger libraries, the active-notes fetch limit moved from `200` to `1000`. Users approaching that ceiling will need a second-page fetch eventually — captured as future work, not addressed here.
- **Trash limit** raised from `50` to `200` for the same reason — archived counts past 50 were silently truncated.

### Why this matters

When the assistant said "you have 0 notes" yesterday, the underlying call was `list_notes(limit=1)` which returned a 1-element array; the LLM read the array length instead of the `total_count` field. The chat handlers (`handlers_notes.py`, `skeleton.py`) already use `total_count` correctly — only the sidebar panel and trash view were stuck on the array-length pattern. With this fix, panel UI and chat surface report the same number.

### Not changed

- `tool_notes_chat` system prompt — the LLM-side count hallucination is a separate concern (read `total_count` from the tool result instead of the array). Tracked, not patched here.

---

## [2.4.2] — 2026-04-25

Pin `imperal-sdk==1.6.2` after rolling back the v3.0.0 / SDK v2.0 / Webbee Single Voice rebuild. Code unchanged from 2.4.1; only the SDK constraint moves from `>=1.5.26,<1.6` to the exact runtime version in production. The v2.0 work is preserved on the `sdk-v2-migration` branch (and tagged `pre-1.6.2-rebuild-2026-04-25` on main pre-reset) for incremental re-roll once the kernel `direct_call.py` path stabilises.

### Changed

- **`requirements.txt`** — `imperal-sdk>=1.5.26,<1.6` → `imperal-sdk==1.6.2`. Hard pin is required because PyPI `imperal-sdk==2.0.0` is immutable and resolver picks it without an explicit constraint (per fresh-session rollback validation 2026-04-25).

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

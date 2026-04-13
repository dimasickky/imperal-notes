<div align="center">

# Imperal Notes

### Your personal AI-powered notebook on Imperal Cloud.

**Write. Organize. Ask. — all in one place.**

[![Platform](https://img.shields.io/badge/platform-Imperal%20Cloud-blue)](https://imperal.io)
[![SDK](https://img.shields.io/badge/imperal--sdk-1.5.0-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-2.4.0-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[Features](#-features) | [Functions](#-functions) | [Architecture](#-architecture) | [Development](#-development) | [Platform](https://imperal.io)

</div>

---

## What is Imperal Notes?

**Imperal Notes** is a first-party AI extension for [Imperal Cloud](https://imperal.io) — the world's first AI Cloud OS.

It gives users a personal notebook where they can create, organize, and interact with their notes through natural language. The AI assistant understands context, remembers structure, and executes real operations — no manual clicking required.

```
User: "Create a note about today's meeting in the Work folder"
  → Notes creates the note, places it in Work, confirms instantly.

User: "Find all my notes about Python and summarize them"
  → Notes searches, fetches content, AI summarizes across all results.

User: "Move everything from Ideas to Work and pin the most important one"
  → Notes executes all three operations in sequence.
```

---

## Features

| Feature | Description |
|---------|-------------|
| **AI Chat** | Full natural language interface — create, search, edit, organize by talking |
| **Rich Editor** | Tiptap-powered editor with headings, lists, code blocks, images |
| **Folders** | Organize notes into folders with drag & drop support |
| **Full-text Search** | MySQL-powered search across all note content |
| **Trash & Restore** | Soft-delete with recycle bin, restore or permanently delete |
| **Pin Notes** | Pin important notes to the top of any list |
| **Tags** | Tag notes for cross-folder organization |
| **Declarative UI** | Sidebar + Editor panels built with Imperal SDK UI components |
| **Skeleton** | Background refresh of note statistics — always up to date |
| **Auto-save** | Editor auto-saves on every change, no manual save needed |

---

## Functions

All functions are exposed through a single `ChatExtension` entry point (`tool_notes_chat`). The AI routes user intent to the correct function automatically.

### Notes

| Function | Action | Description |
|----------|--------|-------------|
| `list_notes` | read | List notes with optional folder/search filters |
| `get_note` | read | Get full content of a note by ID |
| `create_note` | write | Create a note with title, content, tags, folder |
| `update_note` | write | Update title, content, tags, or pin status |
| `move_note` | write | Move note to a folder or back to root |
| `delete_note` | destructive | Soft-delete — moves to trash |
| `permanent_delete_note` | destructive | Permanently delete a note |
| `search_notes` | read | Full-text search across all notes |

### Folders

| Function | Action | Description |
|----------|--------|-------------|
| `list_folders` | read | List all folders |
| `create_folder` | write | Create a new folder |
| `delete_folder` | destructive | Delete folder (notes move to root) |

### Trash

| Function | Action | Description |
|----------|--------|-------------|
| `list_trash` | read | List all notes in trash |
| `restore_note` | write | Restore a note from trash |
| `empty_trash` | destructive | Permanently delete all trashed notes |

### Panel

| Function | Action | Description |
|----------|--------|-------------|
| `note_save` | write | Auto-save from editor panel (title, content, pin toggle) |

---

## Architecture

```
Imperal Panel (panel.imperal.io)
        │
        ├── Sidebar Panel (left)          ← @ext.panel("sidebar")
        │   folders + note list + trash     panels.py
        │
        └── Editor Panel (center)         ← @ext.panel("editor")
            RichEditor + metadata           panels_editor.py

Hub (imperal-hub namespace)
        │
        └── execute_sdk_tool
                │
                └── tool_notes_chat  ← ChatExtension entry point
                        │
                        ├── handlers_notes.py      (CRUD + search)
                        ├── handlers_folders.py    (folders + trash)
                        ├── handlers_panel_actions.py (editor save)
                        └── skeleton.py            (background stats)

Notes API  (api-server:8097, FastAPI)
        │
        └── MySQL / Galera cluster (notes_db)
```

### File Structure

```
imperal-notes/
├── main.py                    # Entry point — sys.modules cleanup + imports
├── app.py                     # Extension setup, HTTP helpers, health check
├── handlers_notes.py          # Note CRUD + search functions
├── handlers_folders.py        # Folder management + trash functions
├── handlers_panel_actions.py  # Panel-specific save handler
├── panels.py                  # Sidebar panel (left slot)
├── panels_editor.py           # Editor panel (center slot)
├── skeleton.py                # Background stats refresh
├── system_prompt.txt          # AI assistant instructions
└── imperal.json               # Extension manifest
```

---

## Events

The extension publishes the following events for use in Automation Rules:

| Event | Trigger |
|-------|---------|
| `notes.created` | Note created |
| `notes.updated` | Note content or metadata updated |
| `notes.moved` | Note moved to a different folder |
| `notes.deleted` | Note moved to trash |
| `notes.permanently_deleted` | Note permanently deleted |
| `notes.restored` | Note restored from trash |
| `notes.emptied` | Trash emptied |
| `notes.folder_created` | Folder created |
| `notes.folder_deleted` | Folder deleted |

---

## Development

Built with [Imperal SDK](https://github.com/imperalcloud/imperal-sdk) v1.5.0.

```bash
pip install imperal-sdk==1.5.0
imperal validate
imperal dev
```

### SDK Compliance

Passes all 12 Imperal SDK validation rules (V1–V12):
- Single `ChatExtension` entry point
- All `@chat.function` handlers return `ActionResult`
- Pydantic `BaseModel` params with `Field(description=...)`
- All write/destructive functions declare `event=`
- No files exceed 300 lines
- `@ext.health_check` registered
- No hardcoded credentials

---

## Links

- **Platform:** [imperal.io](https://imperal.io)
- **SDK:** [github.com/imperalcloud/imperal-sdk](https://github.com/imperalcloud/imperal-sdk)
- **PyPI:** [pypi.org/project/imperal-sdk](https://pypi.org/project/imperal-sdk/)
- **License:** [MIT](LICENSE)

---

<div align="center">

**Built for [Imperal Cloud](https://imperal.io)**

*The AI Cloud OS.*

</div>

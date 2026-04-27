"""Notes · Sidebar panel (left)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext, _api_get, _user_id, _tenant_id

log = logging.getLogger("notes")


# ── Sidebar Panel (LEFT) ─────────────────────────────────────────────────


@ext.panel(
    "sidebar", slot="left", title="Notes", icon="StickyNote",
    default_width=280, min_width=200, max_width=500,
    refresh=(
        "on_event:"
        "notes.created,notes.updated,notes.deleted,notes.moved,"
        "notes.restored,notes.permanently_deleted,notes.emptied,"
        "notes.folder_created,notes.folder_renamed,notes.folder_deleted"
    ),
)
async def notes_sidebar(ctx, folder_id: str = "", view: str = "notes",
                        active_note_id: str = "", **kwargs):
    """Notes sidebar — folders + note list + trash."""
    uid, tid = _user_id(ctx), _tenant_id(ctx)

    folders_failed = False
    try:
        folders = (await _api_get("/folders", {"user_id": uid, "tenant_id": tid})).get("folders", [])
    except Exception as e:
        log.warning("sidebar: GET /folders failed for user=%s: %s", uid, e)
        folders = []
        folders_failed = True

    notes_failed = False
    try:
        # notes-api caps limit at 200 server-side (HTTP 422 above that).
        # The fetch is for sidebar's note-list rendering; per-folder counts
        # come from /folders/stats (DB-accurate GROUP BY) below.
        notes_resp = await _api_get("/notes", {
            "user_id": uid, "tenant_id": tid, "limit": 200,
        }) or {}
        all_notes = notes_resp.get("notes", [])
        total_count = int(notes_resp.get("total_count", len(all_notes)))
    except Exception as e:
        log.warning("sidebar: GET /notes failed for user=%s: %s", uid, e)
        all_notes = []
        total_count = 0
        notes_failed = True

    # DB-accurate per-folder counts (independent of the 200-row sidebar fetch).
    # Until /folders/stats was added, sidebar bucketed in-memory из тех 200
    # строк → счётчики занижены у юзеров с >200 заметок. Fallback на
    # in-memory count если endpoint недоступен (старый backend).
    stats: dict = {}
    try:
        stats_resp = await _api_get("/folders/stats", {
            "user_id": uid, "tenant_id": tid,
        }) or {}
        stats = stats_resp.get("counts", {}) or {}
    except Exception as e:
        log.warning("sidebar: GET /folders/stats failed for user=%s: %s — "
                    "falling back to in-memory bucketing (capped at 200)", uid, e)

    children: list = []

    trash_variant = "secondary" if view == "trash" else "ghost"
    new_folder_variant = "secondary" if view == "new_folder" else "ghost"
    children.append(ui.Stack([
        ui.Button("New Note", icon="Plus", variant="primary", size="sm",
                  on_click=ui.Call("__panel__editor", note_id="new")),
        ui.Button("New Folder", icon="FolderPlus", variant=new_folder_variant, size="sm",
                  on_click=ui.Call("__panel__sidebar",
                                  view="notes" if view == "new_folder" else "new_folder",
                                  folder_id=folder_id)),
        ui.Button("Trash", icon="Trash2", variant=trash_variant, size="sm",
                  on_click=ui.Call("__panel__sidebar",
                                  view="notes" if view == "trash" else "trash")),
    ], direction="horizontal", wrap=True, sticky=True))

    if view == "new_folder":
        children.append(ui.Input(
            placeholder="Folder name, press Enter...",
            param_name="name",
            on_submit=ui.Call("create_folder", name="{{value}}"),
        ))

    rename_target_id = ""
    if view.startswith("rename_folder:"):
        rename_target_id = view.split(":", 1)[1]
        current = next((f["name"] for f in folders if f["id"] == rename_target_id), "")
        children.append(ui.Input(
            placeholder="New folder name, press Enter...",
            param_name="name",
            value=current,
            on_submit=ui.Call("rename_folder",
                             folder_id=rename_target_id,
                             name="{{value}}"),
        ))

    if view == "trash":
        await _append_trash(children, uid, tid)
    elif notes_failed or folders_failed:
        # Don't render a misleading "0" counter when the API call failed —
        # show an explicit error state with a refresh hint instead.
        children.append(ui.Empty(
            message="Не удалось загрузить заметки. Попробуй обновить страницу.",
            icon="AlertTriangle",
        ))
    else:
        _append_folders(children, folders, folder_id, all_notes, total_count, stats)
        _append_notes(children, all_notes, folder_id, folders, active_note_id)

    root = ui.Stack(children=children, gap=2, className="min-h-full")

    if not active_note_id and all_notes and view != "trash":
        root.props["auto_action"] = ui.Call(
            "__panel__editor", note_id=all_notes[0]["id"],
        )

    return root


def _count_notes_in_folder(notes: list, folder_id: str) -> int:
    return sum(1 for n in notes if n.get("folder_id") == folder_id)


def _append_folders(children: list, folders: list, active_folder: str,
                    all_notes: list, total: int, stats: dict) -> None:
    # Prefer DB-accurate stats from /folders/stats (works past 200);
    # fall back to in-memory counts if backend predates the endpoint.
    all_count = stats.get("__all__", total)
    unfiled = stats.get(
        "__unfiled__",
        sum(1 for n in all_notes if not n.get("folder_id")),
    )

    items = [
        ui.ListItem(
            id="__all__",
            title="All Notes",
            icon="FileText",
            meta=str(all_count),
            selected=(not active_folder or active_folder == "__all__"),
            on_click=ui.Call("__panel__sidebar", folder_id=""),
        ),
    ]
    for f in folders:
        count = stats.get(f["id"], _count_notes_in_folder(all_notes, f["id"]))
        items.append(ui.ListItem(
            id=f["id"],
            title=f["name"],
            icon="Folder",
            meta=str(count),
            selected=(active_folder == f["id"]),
            droppable=True,
            on_drop=ui.Call("move_note", folder_id=f["id"]),
            on_click=ui.Call("__panel__sidebar", folder_id=f["id"]),
            actions=[
                {
                    "icon": "Pencil",
                    "on_click": ui.Call("__panel__sidebar",
                                       view=f"rename_folder:{f['id']}",
                                       folder_id=f["id"]),
                },
                {
                    "icon": "Trash2",
                    "on_click": ui.Call("delete_folder", folder_id=f["id"]),
                    "confirm": f"Delete folder '{f['name']}'? Notes move to root.",
                },
            ],
        ))
    items.append(ui.ListItem(
        id="__unfiled__",
        title="Unfiled",
        icon="Inbox",
        meta=str(unfiled),
        selected=(active_folder == "__unfiled__"),
        droppable=True,
        on_drop=ui.Call("move_note", folder_id=""),
        on_click=ui.Call("__panel__sidebar", folder_id="__unfiled__"),
    ))
    children.append(ui.Divider("Folders"))
    children.append(ui.List(items=items))


def _append_notes(children: list, all_notes: list, folder_id: str,
                  folders: list, active_note_id: str) -> None:
    if folder_id and folder_id != "__unfiled__":
        notes = [n for n in all_notes if n.get("folder_id") == folder_id]
    elif folder_id == "__unfiled__":
        notes = [n for n in all_notes if not n.get("folder_id")]
    else:
        notes = all_notes

    folder_map = {f["id"]: f["name"] for f in folders}

    items = []
    for n in notes:
        subtitle_parts = []
        if n.get("word_count"):
            subtitle_parts.append(f"{n['word_count']} words")
        fid = n.get("folder_id")
        if fid and fid in folder_map and not folder_id:
            subtitle_parts.append(folder_map[fid])

        items.append(ui.ListItem(
            id=n["id"],
            title=n.get("title", "Untitled"),
            subtitle=" · ".join(subtitle_parts) if subtitle_parts else "",
            badge=ui.Badge("pinned", color="yellow") if n.get("is_pinned") else None,
            selected=(n["id"] == active_note_id),
            draggable=True,
            on_click=ui.Call("__panel__editor", note_id=n["id"]),
            actions=[{
                "icon": "Trash2",
                "on_click": ui.Call("delete_note", note_id=n["id"]),
                "confirm": f"Move '{n.get('title', 'Untitled')}' to trash?",
            }],
        ))

    children.append(ui.Divider(f"Notes ({len(items)})"))
    children.append(ui.List(items=items, searchable=True, page_size=20))


async def _append_trash(children: list, uid: str, tid: str) -> None:
    try:
        trash = (await _api_get("/notes", {
            "user_id": uid, "tenant_id": tid,
            "is_archived": True, "limit": 200,
        })).get("notes", [])
    except Exception as e:
        log.warning("sidebar trash: GET /notes is_archived=true failed for user=%s: %s", uid, e)
        children.append(ui.Empty(
            message="Не удалось загрузить корзину. Попробуй обновить страницу.",
            icon="AlertTriangle",
        ))
        return

    if not trash:
        children.append(ui.Empty(message="Trash is empty", icon="CheckCircle"))
        return

    items = []
    for n in trash:
        items.append(ui.ListItem(
            id=n["id"],
            title=n.get("title", "Untitled"),
            subtitle=f"{n.get('word_count', 0)} words",
            icon="Trash2",
            actions=[
                {
                    "icon": "RotateCcw",
                    "on_click": ui.Call("restore_note", note_id=n["id"]),
                },
                {
                    "icon": "XCircle",
                    "on_click": ui.Call("permanent_delete_note", note_id=n["id"]),
                    "confirm": f"Permanently delete '{n.get('title', 'Untitled')}'?",
                },
            ],
        ))

    children.append(ui.Divider(f"Trash ({len(trash)})"))
    children.append(ui.List(items=items))
    children.append(ui.Button(
        "Empty Trash", icon="Trash2", variant="destructive", size="sm",
        on_click=ui.Call("empty_trash"),
    ))

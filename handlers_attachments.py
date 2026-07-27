"""Notes · Attachment handlers (upload / delete)."""

import base64
import logging
from typing import List

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

log = logging.getLogger("notes.handlers")

from app import chat, ActionResult, NotesAPIError, _api_delete, _api_upload, require_user_id
# The batch below reuses the note batches' fan-out helpers rather than growing
# a second, subtly different copy here. main.py imports handlers_notes first
# and that module does not import this one, so there is no cycle.
from handlers_notes import _check_batch_size, _run_fanout
from models_return import UploadAttachmentResult, DeleteAttachmentResult, BulkFanoutResult
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, VALIDATION_TYPE_ERROR, INTERNAL
from error_codes import NOTES_BACKEND_ERROR


def _extract_b64(payload) -> tuple[str, str, str]:
    """Return (data_base64, filename, content_type) from FileUpload payload."""
    if isinstance(payload, list) and payload:
        item = payload[0] if isinstance(payload[0], dict) else {}
    elif isinstance(payload, dict):
        item = payload
    else:
        return "", "", ""
    b64 = item.get("data_base64", "")
    if b64.startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]
    return b64, item.get("name", "file"), item.get("content_type", "application/octet-stream")


class AttachmentUploadParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(
        default="", description="Note UUID",
        validation_alias=AliasChoices("note_id", "noteId"),
    )
    files: object = Field(
        default=None,
        description="FileUpload payload (list[dict] with data_base64/name/content_type)",
        validation_alias=AliasChoices("files", "file", "upload"),
    )


class AttachmentDeleteParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note_id: str = Field(
        default="", description="Note UUID",
        validation_alias=AliasChoices("note_id", "noteId"),
    )
    att_id: str = Field(
        default="", description="Attachment UUID",
        validation_alias=AliasChoices("att_id", "attId", "attachment_id", "id"),
    )


@chat.function(
    "upload_attachment",
    action_type="write",
    chain_callable=True,
    id_projection="note_id",
    effects=["create:attachment"],
    event="attachment.uploaded",
    description="Upload a file attachment to a note.",
    data_model=UploadAttachmentResult,
)
async def fn_upload_attachment(ctx, params: AttachmentUploadParams) -> ActionResult:
    uid = require_user_id(ctx)
    if not params.note_id:
        return ActionResult.error("note_id required", code=VALIDATION_MISSING_FIELD)

    b64, filename, content_type = _extract_b64(params.files)
    if not b64:
        return ActionResult.error("No file data received", code=VALIDATION_MISSING_FIELD)

    try:
        file_bytes = base64.b64decode(b64)
    except Exception:
        return ActionResult.error("Invalid file data (base64 decode failed)", code=VALIDATION_TYPE_ERROR)

    try:
        result = await _api_upload(
            ctx,
            f"/notes/{params.note_id}/attachments",
            {"user_id": uid},
            filename, file_bytes, content_type,
        )
        att = result.get("attachment", {})
        return ActionResult.success(
            data={"attachment": att, "refresh_panels": ["editor"]},
            summary=f"Uploaded {filename}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"Upload failed: {e.status_code} {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("upload_attachment: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_attachment",
    action_type="write",
    chain_callable=True,
    id_projection="att_id",
    effects=["delete:attachment"],
    event="attachment.deleted",
    description="Delete a file attachment from a note.",
    data_model=DeleteAttachmentResult,
)
async def fn_delete_attachment(ctx, params: AttachmentDeleteParams) -> ActionResult:
    uid = require_user_id(ctx)
    if not params.att_id:
        return ActionResult.error("att_id required", code=VALIDATION_MISSING_FIELD)

    try:
        await _api_delete(ctx, f"/attachments/{params.att_id}", {"user_id": uid})
        return ActionResult.success(
            data={"att_id": params.att_id, "refresh_panels": ["editor"]},
            summary="Attachment deleted",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"Delete failed: {e.status_code} {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_attachment: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


class AttachmentsDeleteParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    att_ids: List[str] = Field(
        default_factory=list,
        description="List of attachment UUIDs to delete.",
        validation_alias=AliasChoices("att_ids", "attachment_ids", "ids"),
    )


@chat.function(
    "delete_attachments",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:attachment"],
    event="attachments.deleted",
    description=(
        "Delete SEVERAL file attachments at once. Pass att_ids (list of attachment UUIDs). "
        "Use when the user wants to remove 2+ attachments in one request."
    ),
    data_model=BulkFanoutResult,
)
async def fn_delete_attachments(ctx, params: AttachmentsDeleteParams) -> ActionResult:
    """Delete a set of attachments, reported per attachment.

    Clearing out a note's files was one call per file until now. There is no
    bulk endpoint for attachments, so this fans out one DELETE each, bounded
    and with a row per item — reusing the exact helpers the note batches use
    rather than growing a second, subtly different pattern in this file.

    Unlike notes, attachments have no trash to fall back on, so a row that
    fails is reported by id and the rest still go through: on a cleanup run,
    knowing which two of eight survived is the whole point.
    """
    uid = require_user_id(ctx)

    oversized = _check_batch_size(params.att_ids, "attachments")
    if oversized:
        return oversized

    rows = [(a.strip(), a.strip()) for a in params.att_ids if (a or "").strip()]
    if not rows:
        return ActionResult.error("No attachments given.", code=VALIDATION_MISSING_FIELD)

    async def _delete_one(att_id: str) -> str | None:
        try:
            await _api_delete(ctx, f"/attachments/{att_id}", {"user_id": uid})
            return None
        except NotesAPIError as e:
            return f"{e.status_code} {e.detail}"

    results = await _run_fanout(ctx, rows, _delete_one)

    succeeded = sum(1 for r in results if r["ok"])
    failed = len(results) - succeeded
    if failed:
        broken = ", ".join(r["id"] for r in results if not r["ok"])
        summary = f"Deleted {succeeded} of {len(results)} attachment(s) — {failed} failed: {broken}"
    else:
        summary = f"Deleted {succeeded} attachment(s)"

    return ActionResult.success(
        data={
            "succeeded_count": succeeded,
            "failed_count": failed,
            "results": results,
            "not_found": [],
            "refresh_panels": ["editor"],
        },
        summary=summary,
    )

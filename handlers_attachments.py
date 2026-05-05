"""Notes · Attachment handlers (upload / delete)."""
from __future__ import annotations

import base64

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app import chat, ActionResult, NotesAPIError, _api_delete, _api_upload, require_user_id


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
)
async def fn_upload_attachment(ctx, params: AttachmentUploadParams) -> ActionResult:
    uid = require_user_id(ctx)
    if not params.note_id:
        return ActionResult.error("note_id required")

    b64, filename, content_type = _extract_b64(params.files)
    if not b64:
        return ActionResult.error("No file data received")

    try:
        file_bytes = base64.b64decode(b64)
    except Exception:
        return ActionResult.error("Invalid file data (base64 decode failed)")

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
        return ActionResult.error(f"Upload failed: {e.status_code} {e.detail}")
    except Exception as e:
        return ActionResult.error(f"Upload failed: {e}")


@chat.function(
    "delete_attachment",
    action_type="write",
    chain_callable=True,
    id_projection="note_id",
    effects=["delete:attachment"],
    event="attachment.deleted",
    description="Delete a file attachment from a note.",
)
async def fn_delete_attachment(ctx, params: AttachmentDeleteParams) -> ActionResult:
    uid = require_user_id(ctx)
    if not params.att_id:
        return ActionResult.error("att_id required")

    try:
        await _api_delete(ctx, f"/attachments/{params.att_id}", {"user_id": uid})
        return ActionResult.success(
            data={"att_id": params.att_id, "refresh_panels": ["editor"]},
            summary="Attachment deleted",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"Delete failed: {e.status_code} {e.detail}")
    except Exception as e:
        return ActionResult.error(f"Delete failed: {e}")

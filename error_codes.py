"""App-declared structured error codes for notes.

These pair with the platform taxonomy (`imperal_sdk.chat.error_codes`) for
cases that taxonomy doesn't cover — problems specific to the notes backend
and note/folder resolution, not the Imperal backend itself. Every code here
matches the SDK's app-declared pattern `^[A-Z][A-Z0-9_]{2,63}$`
(imperal_sdk.types.action_result.ActionResult.error).

Platform codes (imported directly where they apply — validation, internal,
backend 5xx) are used as-is; these NOTES_* codes only exist where no
platform code honestly fits.
"""

NOTES_INVALID_NOTE_ID = "NOTES_INVALID_NOTE_ID"      # note_id missing or not a valid UUID4
NOTES_FOLDER_NOT_FOUND = "NOTES_FOLDER_NOT_FOUND"     # folder_id/name doesn't resolve to a real folder
NOTES_NOTE_NOT_FOUND = "NOTES_NOTE_NOT_FOUND"         # note title(s) didn't resolve to a real note
NOTES_BACKEND_ERROR = "NOTES_BACKEND_ERROR"           # notes backend returned a non-2xx HTTP status

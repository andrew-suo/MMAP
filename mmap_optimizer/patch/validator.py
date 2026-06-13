"""Validation for optimizer patches."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from .schema import Patch

TEXT_LEVEL_OPERATION_MODES = {"replace_in_section", "insert_after", "insert_before"}


class PatchValidationError(ValueError):
    """Raised when a patch is invalid before application."""


def _coerce_patch(patch: Patch | Mapping[str, Any]) -> Patch:
    if isinstance(patch, Patch):
        return patch
    if isinstance(patch, Mapping):
        return Patch.from_mapping(patch)
    raise TypeError(f"Unsupported patch type: {type(patch)!r}")


def _is_non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _is_section_frozen(document: Any, section_id: str) -> bool:
    # Imported lazily to avoid an import cycle at module load time.
    from .applier import is_section_frozen, PatchApplyError

    try:
        return is_section_frozen(document, section_id)
    except PatchApplyError as exc:
        raise PatchValidationError(str(exc)) from exc


def validate_patch(document: Any, patch: Patch | Mapping[str, Any]) -> Patch:
    """Validate a patch and return the normalized :class:`Patch` object."""

    patch_obj = _coerce_patch(patch)
    section_id = patch_obj.effective_section_id
    if not _is_non_empty_text(section_id):
        raise PatchValidationError("Patch requires non-empty section_id or target_section")

    if _is_section_frozen(document, section_id):
        raise PatchValidationError(f"Target section is frozen: {section_id!r}")

    mode = patch_obj.operation_mode
    if mode not in TEXT_LEVEL_OPERATION_MODES:
        return patch_obj

    if mode == "replace_in_section":
        if not _is_non_empty_text(patch_obj.locator_value("old_text")):
            raise PatchValidationError("replace_in_section requires non-empty locator old_text")
        replacement = patch_obj.payload_value("new_text", "patch_text")
        if replacement is None:
            replacement = patch_obj.patch_text
        if not isinstance(replacement, str):
            raise PatchValidationError("replace_in_section requires new_text or patch_text payload")
        return patch_obj

    if mode in {"insert_after", "insert_before"}:
        if not _is_non_empty_text(patch_obj.locator_value("target_text")):
            raise PatchValidationError(f"{mode} requires non-empty locator target_text")
        insert_text = patch_obj.payload_value("insert_text", "patch_text")
        if insert_text is None:
            insert_text = patch_obj.patch_text
        if not _is_non_empty_text(insert_text):
            raise PatchValidationError(f"{mode} requires non-empty insert_text or patch_text payload")
        return patch_obj

    return patch_obj

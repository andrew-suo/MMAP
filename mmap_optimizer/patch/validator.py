"""Validation for section-level and text-level patches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .alignment import ensure_exact_text, find_section_range, normalize_section_id
from .schema import Patch, TEXT_OPERATION_MODES


class PatchValidationError(ValueError):
    """Raised when a patch cannot be safely applied."""


def _as_patch(patch: Patch | Mapping[str, Any]) -> Patch:
    return patch if isinstance(patch, Patch) else Patch.from_mapping(patch)


def _is_blank(value: str | None) -> bool:
    return value is None or value == ""


def _is_frozen(section_id: str, frozen_sections: Sequence[str] | None) -> bool:
    if not frozen_sections:
        return False
    wanted = {normalize_section_id(section) for section in frozen_sections}
    return section_id in frozen_sections or normalize_section_id(section_id) in wanted


def _section_text(document: str | Mapping[str, str], section_id: str) -> str:
    if isinstance(document, Mapping):
        try:
            return document[section_id]
        except KeyError as exc:
            raise PatchValidationError(f"Section not found: {section_id}") from exc
    try:
        section_range = find_section_range(document, section_id)
    except ValueError as exc:
        raise PatchValidationError(str(exc)) from exc
    return document[section_range.start : section_range.end]


def validate_patch(
    patch: Patch | Mapping[str, Any],
    document: str | Mapping[str, str],
    *,
    frozen_sections: Sequence[str] | None = None,
) -> Patch:
    """Validate a patch against a document and return its normalized schema.

    Text-level patches are intentionally strict: if a caller supplies an exact
    locator, the locator must be non-empty and present inside the target section.
    Failed alignment is rejected here instead of letting the applier append the
    content elsewhere.
    """

    patch_obj = _as_patch(patch)
    operation_mode = patch_obj.effective_operation_mode

    if _is_frozen(patch_obj.section_id, frozen_sections):
        raise PatchValidationError(f"Cannot patch frozen section: {patch_obj.section_id}")

    has_locator = patch_obj.target_text is not None or patch_obj.old_text is not None
    if operation_mode not in TEXT_OPERATION_MODES:
        if has_locator:
            raise PatchValidationError(
                f"Locator fields require a text-level operation mode, got {operation_mode!r}"
            )
        return patch_obj

    section_text = _section_text(document, patch_obj.section_id)

    if operation_mode == "replace_in_section":
        locator = patch_obj.replacement_locator()
        field_name = "old_text" if patch_obj.old_text is not None else "target_text"
        if _is_blank(locator):
            raise PatchValidationError(
                "replace_in_section requires non-empty old_text or target_text"
            )
        try:
            ensure_exact_text(section_text, locator or "", field_name=field_name)
        except ValueError as exc:
            raise PatchValidationError(str(exc)) from exc
        if patch_obj.new_text is None:
            raise PatchValidationError("replace_in_section requires new_text")
        return patch_obj

    if operation_mode in {"insert_after", "insert_before"}:
        if _is_blank(patch_obj.target_text):
            raise PatchValidationError(f"{operation_mode} requires non-empty target_text")
        if _is_blank(patch_obj.insertion_text()):
            raise PatchValidationError(f"{operation_mode} requires non-empty new_text or content")
        try:
            ensure_exact_text(section_text, patch_obj.target_text or "", field_name="target_text")
        except ValueError as exc:
            raise PatchValidationError(str(exc)) from exc
        return patch_obj

    raise PatchValidationError(f"Unsupported text-level operation mode: {operation_mode}")

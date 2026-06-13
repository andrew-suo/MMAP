"""Apply section-level and exact text-level patches."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from .alignment import ensure_exact_text, find_section_range
from .schema import Patch
from .validator import validate_patch


def _as_patch(patch: Patch | Mapping[str, Any]) -> Patch:
    return patch if isinstance(patch, Patch) else Patch.from_mapping(patch)


def _apply_to_section_text(section_text: str, patch: Patch) -> str:
    operation_mode = patch.effective_operation_mode

    if operation_mode == "replace_in_section":
        locator = patch.replacement_locator()
        assert locator is not None
        position = ensure_exact_text(section_text, locator, field_name="old_text")
        return (
            section_text[:position]
            + (patch.new_text or "")
            + section_text[position + len(locator) :]
        )

    if operation_mode in {"insert_after", "insert_before"}:
        assert patch.target_text is not None
        insertion = patch.insertion_text()
        assert insertion is not None
        position = ensure_exact_text(section_text, patch.target_text, field_name="target_text")
        if operation_mode == "insert_after":
            position += len(patch.target_text)
        return section_text[:position] + insertion + section_text[position:]

    if operation_mode == "prepend":
        return (patch.content or "") + section_text
    if operation_mode == "replace_section":
        return patch.content or ""
    if operation_mode == "append":
        return section_text + (patch.content or "")

    raise ValueError(f"Unsupported operation mode: {operation_mode}")


def apply_patch(
    document: str | Mapping[str, str],
    patch: Patch | Mapping[str, Any],
    *,
    frozen_sections: Sequence[str] | None = None,
) -> str | dict[str, str]:
    """Apply a patch to a Markdown document string or section mapping.

    Exact text-level operations are validated before mutation.  If a locator is
    present but cannot be aligned within the section, the patch is rejected and
    no append fallback is attempted.
    """

    patch_obj = validate_patch(_as_patch(patch), document, frozen_sections=frozen_sections)

    if isinstance(document, Mapping):
        if patch_obj.section_id not in document:
            raise ValueError(f"Section not found: {patch_obj.section_id}")
        updated: MutableMapping[str, str] = dict(document)
        updated[patch_obj.section_id] = _apply_to_section_text(
            updated[patch_obj.section_id], patch_obj
        )
        return dict(updated)

    section_range = find_section_range(document, patch_obj.section_id)
    section_text = document[section_range.start : section_range.end]
    updated_section = _apply_to_section_text(section_text, patch_obj)
    return document[: section_range.start] + updated_section + document[section_range.end :]

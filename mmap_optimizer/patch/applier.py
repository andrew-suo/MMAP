"""Patch application helpers."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, MutableMapping
from typing import Any

from .schema import Patch
from .validator import TEXT_LEVEL_OPERATION_MODES, validate_patch


class PatchApplyError(ValueError):
    """Raised when a patch cannot be applied exactly."""


def _coerce_patch(patch: Patch | Mapping[str, Any]) -> Patch:
    if isinstance(patch, Patch):
        return patch
    if isinstance(patch, Mapping):
        return Patch.from_mapping(patch)
    raise TypeError(f"Unsupported patch type: {type(patch)!r}")


def _section_text(section: Any) -> str:
    if isinstance(section, str):
        return section
    if isinstance(section, MutableMapping):
        for key in ("text", "content", "body"):
            value = section.get(key)
            if isinstance(value, str):
                return value
    for key in ("text", "content", "body"):
        value = getattr(section, key, None)
        if isinstance(value, str):
            return value
    raise PatchApplyError("Target section has no text/content/body string field")


def _set_section_text(container: Any, key: Any, section: Any, new_text: str) -> None:
    if isinstance(section, str):
        container[key] = new_text
        return
    if isinstance(section, MutableMapping):
        for text_key in ("text", "content", "body"):
            if isinstance(section.get(text_key), str):
                section[text_key] = new_text
                return
    for text_key in ("text", "content", "body"):
        if isinstance(getattr(section, text_key, None), str):
            setattr(section, text_key, new_text)
            return
    raise PatchApplyError("Target section has no writable text/content/body string field")


def _section_matches(section: Any, section_id: str) -> bool:
    if isinstance(section, MutableMapping):
        return any(section.get(key) == section_id for key in ("id", "section_id", "name", "title"))
    return any(getattr(section, key, None) == section_id for key in ("id", "section_id", "name", "title"))


def _locate_section(document: Any, section_id: str) -> tuple[Any, Any, Any]:
    """Return ``(container, key, section)`` for a section id."""

    if isinstance(document, MutableMapping):
        sections = document.get("sections")
        if isinstance(sections, MutableMapping):
            if section_id in sections:
                return sections, section_id, sections[section_id]
            for key, section in sections.items():
                if _section_matches(section, section_id):
                    return sections, key, section
        if isinstance(sections, list):
            for index, section in enumerate(sections):
                if _section_matches(section, section_id):
                    return sections, index, section
        if section_id in document and isinstance(document[section_id], (str, MutableMapping)):
            return document, section_id, document[section_id]

    sections = getattr(document, "sections", None)
    if isinstance(sections, MutableMapping):
        if section_id in sections:
            return sections, section_id, sections[section_id]
        for key, section in sections.items():
            if _section_matches(section, section_id):
                return sections, key, section
    if isinstance(sections, list):
        for index, section in enumerate(sections):
            if _section_matches(section, section_id):
                return sections, index, section

    raise PatchApplyError(f"Target section not found: {section_id!r}")


def _is_frozen(section: Any) -> bool:
    if isinstance(section, MutableMapping):
        return bool(section.get("frozen") or section.get("is_frozen") or section.get("status") == "frozen")
    return bool(
        getattr(section, "frozen", False)
        or getattr(section, "is_frozen", False)
        or getattr(section, "status", None) == "frozen"
    )


def is_section_frozen(document: Any, section_id: str) -> bool:
    """Return whether a section is frozen; used by the validator."""

    _, _, section = _locate_section(document, section_id)
    return _is_frozen(section)


def _require_non_empty(value: Any, field_name: str, operation_mode: str) -> str:
    if not isinstance(value, str) or value == "":
        raise PatchApplyError(f"{operation_mode} requires non-empty {field_name}")
    return value


def _apply_text_operation(section_text: str, patch: Patch) -> str:
    mode = patch.operation_mode
    if mode == "replace_in_section":
        old_text = _require_non_empty(patch.locator_value("old_text"), "old_text", mode)
        replacement = patch.payload_value("new_text", "patch_text")
        if replacement is None:
            replacement = patch.patch_text
        if not isinstance(replacement, str):
            raise PatchApplyError("replace_in_section requires new_text or patch_text payload")
        if old_text not in section_text:
            raise PatchApplyError("replace_in_section locator failed: old_text not found in target section")
        return section_text.replace(old_text, replacement, 1)

    if mode in {"insert_after", "insert_before"}:
        target_text = _require_non_empty(patch.locator_value("target_text"), "target_text", mode)
        insert_text = patch.payload_value("insert_text", "patch_text")
        if insert_text is None:
            insert_text = patch.patch_text
        insert_text = _require_non_empty(insert_text, "insert_text or patch_text", mode)
        index = section_text.find(target_text)
        if index == -1:
            raise PatchApplyError(f"{mode} locator failed: target_text not found in target section")
        if mode == "insert_after":
            index += len(target_text)
        return section_text[:index] + insert_text + section_text[index:]

    raise PatchApplyError(f"Unsupported text operation_mode: {mode!r}")


def apply_patch(document: Any, patch: Patch | Mapping[str, Any], *, validate: bool = True, copy: bool = True) -> Any:
    """Apply a patch and return the updated document.

    Text-level locator failures raise :class:`PatchApplyError`; they never fall
    back to appending text.
    """

    patch_obj = _coerce_patch(patch)
    working_document = deepcopy(document) if copy else document

    if validate:
        try:
            validate_patch(working_document, patch_obj)
        except ValueError as exc:
            raise PatchApplyError(str(exc)) from exc

    section_id = patch_obj.effective_section_id
    if not section_id:
        raise PatchApplyError("Patch requires section_id or target_section")
    container, key, section = _locate_section(working_document, section_id)

    if _is_frozen(section):
        raise PatchApplyError(f"Target section is frozen: {section_id!r}")

    if patch_obj.operation_mode in TEXT_LEVEL_OPERATION_MODES:
        new_text = _apply_text_operation(_section_text(section), patch_obj)
        _set_section_text(container, key, section, new_text)
        return working_document

    if patch_obj.operation_mode == "replace_section":
        replacement = patch_obj.patch_text or patch_obj.payload_value("text", "content", "new_text")
        replacement = _require_non_empty(replacement, "patch_text", patch_obj.operation_mode)
        _set_section_text(container, key, section, replacement)
        return working_document

    raise PatchApplyError(f"Unsupported operation_mode: {patch_obj.operation_mode!r}")


def apply_patches(document: Any, patches: list[Patch | Mapping[str, Any]], *, validate: bool = True) -> Any:
    """Apply patches in order, returning the final document."""

    result = deepcopy(document)
    for patch in patches:
        result = apply_patch(result, patch, validate=validate, copy=False)
    return result

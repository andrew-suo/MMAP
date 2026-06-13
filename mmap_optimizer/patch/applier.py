"""Apply deterministic section and text-level patches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .alignment import AlignedPatchResult, align_patches
from .schema import Patch, TEXT_LEVEL_OPERATIONS
from .validator import PatchValidationError, validate_patch


class PatchApplicationError(RuntimeError):
    """Raised when patch application cannot proceed safely."""


def _replace_exactly_once(
    section_text: str, old_text: str, new_text: str, patch: Patch
) -> str:
    count = section_text.count(old_text)
    if count != 1:
        raise PatchApplicationError(
            f"Unable to apply '{patch.operation}' to section '{patch.section}': "
            f"locator matched {count} times; expected exactly one."
        )
    return section_text.replace(old_text, new_text, 1)


def replace_in_section(section_text: str, old_text: str, new_text: str) -> str:
    """Replace ``old_text`` exactly once inside ``section_text``."""

    patch = Patch(
        operation="replace_in_section",
        section="<direct>",
        old_text=old_text,
        new_text=new_text,
    )
    return _replace_exactly_once(section_text, old_text, new_text, patch)


def insert_after(section_text: str, target_text: str, new_text: str) -> str:
    """Insert ``new_text`` immediately after a unique ``target_text`` anchor."""

    patch = Patch(
        operation="insert_after",
        section="<direct>",
        target_text=target_text,
        new_text=new_text,
    )
    return _replace_exactly_once(
        section_text, target_text, f"{target_text}{new_text}", patch
    )


def insert_before(section_text: str, target_text: str, new_text: str) -> str:
    """Insert ``new_text`` immediately before a unique ``target_text`` anchor."""

    patch = Patch(
        operation="insert_before",
        section="<direct>",
        target_text=target_text,
        new_text=new_text,
    )
    return _replace_exactly_once(section_text, target_text, f"{new_text}{target_text}", patch)


def _apply_text_patch(section_text: str, patch: Patch) -> str:
    if patch.new_text is None or patch.new_text == "":
        raise PatchApplicationError(
            f"Unable to apply '{patch.operation}' to section '{patch.section}': new_text is required."
        )

    if patch.operation == "replace_in_section":
        old_text = patch.replacement_target
        if old_text is None or old_text == "":
            raise PatchApplicationError(
                f"Unable to apply 'replace_in_section' to section '{patch.section}': "
                "old_text or target_text is required."
            )
        return replace_in_section(section_text, old_text, patch.new_text)

    if patch.operation in {"insert_after", "insert_before"}:
        target_text = patch.target_text
        if target_text is None or target_text == "":
            raise PatchApplicationError(
                f"Unable to apply '{patch.operation}' to section '{patch.section}': target_text is required."
            )
        if patch.operation == "insert_after":
            return insert_after(section_text, target_text, patch.new_text)
        return insert_before(section_text, target_text, patch.new_text)

    raise PatchApplicationError(f"Unsupported text-level operation '{patch.operation}'.")


def _reject_unresolved(aligned_result: AlignedPatchResult) -> None:
    if not aligned_result.unresolved:
        return
    descriptions = ", ".join(
        f"{patch.operation}:{patch.section}" for patch in aligned_result.unresolved
    )
    raise PatchApplicationError(
        f"Unresolved patch locators cannot be applied: {descriptions}."
    )


def apply_aligned_result(
    sections: Mapping[str, str],
    aligned_result: AlignedPatchResult,
    *,
    frozen_sections: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    """Apply a pre-aligned patch result.

    Any unresolved locator is rejected before a mutation happens.
    """

    _reject_unresolved(aligned_result)
    return _apply_resolved_patches(
        sections, aligned_result.patches, frozen_sections=frozen_sections
    )


def _apply_resolved_patches(
    sections: Mapping[str, str],
    patches: Sequence[Patch],
    *,
    frozen_sections: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    updated_sections = dict(sections)
    for patch in patches:
        try:
            validate_patch(patch, updated_sections, frozen_sections=frozen_sections)
        except PatchValidationError as exc:
            raise PatchApplicationError(str(exc)) from exc

        if patch.operation in TEXT_LEVEL_OPERATIONS:
            if patch.section not in updated_sections:
                raise PatchApplicationError(
                    f"Patch targets unknown section '{patch.section}'."
                )
            updated_sections[patch.section] = _apply_text_patch(
                updated_sections[patch.section], patch
            )
        else:
            raise PatchApplicationError(f"Unsupported patch operation '{patch.operation}'.")
    return updated_sections


def apply_patches(
    sections: Mapping[str, str],
    patches: Sequence[Patch],
    *,
    frozen_sections: set[str] | frozenset[str] | None = None,
    aligned_result: AlignedPatchResult | None = None,
    align: bool = True,
) -> dict[str, str]:
    """Apply patches to sections.

    By default patches are passed through ``align_patches`` before application.
    A supplied ``aligned_result`` is used directly, and unresolved locators are
    rejected rather than being appended to any section.
    """

    result = aligned_result if aligned_result is not None else None
    if result is None and align:
        result = align_patches(patches, sections)
    if result is not None:
        return apply_aligned_result(sections, result, frozen_sections=frozen_sections)
    return _apply_resolved_patches(sections, patches, frozen_sections=frozen_sections)

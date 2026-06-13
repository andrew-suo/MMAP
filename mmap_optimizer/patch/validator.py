"""Validation for patch operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .schema import Patch, TEXT_LEVEL_OPERATIONS


class PatchValidationError(ValueError):
    """Raised when a patch cannot be validated against its target sections."""


def _require_non_empty(value: str | None, field_name: str, patch: Patch) -> str:
    if value is None or value == "":
        raise PatchValidationError(
            f"Patch operation '{patch.operation}' for section '{patch.section}' "
            f"requires non-empty {field_name}."
        )
    return value


def _require_section(sections: Mapping[str, str], patch: Patch) -> str:
    if patch.section not in sections:
        raise PatchValidationError(f"Patch targets unknown section '{patch.section}'.")
    return sections[patch.section]


def _require_exact_match(section_text: str, needle: str, patch: Patch) -> None:
    match_count = section_text.count(needle)
    if match_count != 1:
        raise PatchValidationError(
            f"Patch operation '{patch.operation}' for section '{patch.section}' "
            f"requires locator text to match exactly once; found {match_count} matches."
        )


def validate_patch(
    patch: Patch,
    sections: Mapping[str, str],
    *,
    frozen_sections: set[str] | frozenset[str] | None = None,
) -> None:
    """Validate that a patch can be applied deterministically.

    Text-level operations require a non-empty locator and a non-empty payload,
    and the locator must match exactly once inside the target section.
    """

    frozen = frozen_sections or frozenset()
    if patch.section in frozen:
        raise PatchValidationError(f"Patch targets frozen section '{patch.section}'.")

    if patch.operation not in TEXT_LEVEL_OPERATIONS:
        return

    section_text = _require_section(sections, patch)
    _require_non_empty(patch.new_text, "new_text", patch)

    if patch.operation == "replace_in_section":
        locator_text = _require_non_empty(
            patch.replacement_target, "old_text or target_text", patch
        )
    else:
        locator_text = _require_non_empty(patch.target_text, "target_text", patch)

    _require_exact_match(section_text, locator_text, patch)


def validate_patches(
    patches: Sequence[Patch],
    sections: Mapping[str, str],
    *,
    frozen_sections: set[str] | frozenset[str] | None = None,
) -> None:
    """Validate a patch sequence against sections."""

    working_sections = dict(sections)
    for patch in patches:
        validate_patch(patch, working_sections, frozen_sections=frozen_sections)
        if patch.operation == "replace_in_section":
            locator = patch.replacement_target
            if locator is not None and patch.new_text is not None:
                working_sections[patch.section] = working_sections[patch.section].replace(
                    locator, patch.new_text, 1
                )
        elif patch.operation == "insert_after":
            working_sections[patch.section] = working_sections[patch.section].replace(
                patch.target_text or "",
                f"{patch.target_text}{patch.new_text}",
                1,
            )
        elif patch.operation == "insert_before":
            working_sections[patch.section] = working_sections[patch.section].replace(
                patch.target_text or "",
                f"{patch.new_text}{patch.target_text}",
                1,
            )

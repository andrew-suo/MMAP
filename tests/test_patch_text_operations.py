import pytest

from mmap_optimizer.patch.alignment import AlignedPatchResult, align_patches
from mmap_optimizer.patch.applier import PatchApplicationError, apply_aligned_result, apply_patches
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidationError, validate_patch


def test_replace_in_section_replaces_exact_locator():
    sections = {"summary": "alpha beta gamma"}
    patches = [
        Patch(
            operation="replace_in_section",
            section="summary",
            old_text="beta",
            new_text="BETA",
        )
    ]

    assert apply_patches(sections, patches) == {"summary": "alpha BETA gamma"}


def test_insert_after_uses_target_anchor_without_appending():
    sections = {"summary": "alpha beta gamma"}
    patches = [
        Patch(
            operation="insert_after",
            section="summary",
            target_text="beta",
            new_text=" INSERTED",
        )
    ]

    assert apply_patches(sections, patches) == {"summary": "alpha beta INSERTED gamma"}


def test_insert_before_uses_target_anchor_without_appending():
    sections = {"summary": "alpha beta gamma"}
    patches = [
        Patch(
            operation="insert_before",
            section="summary",
            target_text="beta",
            new_text="INSERTED ",
        )
    ]

    assert apply_patches(sections, patches) == {"summary": "alpha INSERTED beta gamma"}


def test_locator_failure_is_rejected_instead_of_appended():
    sections = {"summary": "alpha beta gamma"}
    patch = Patch(
        operation="insert_after",
        section="summary",
        target_text="missing",
        new_text=" SHOULD_NOT_APPEND",
    )

    with pytest.raises(PatchApplicationError, match="Unresolved patch locators"):
        apply_patches(sections, [patch])

    assert sections["summary"] == "alpha beta gamma"


def test_frozen_section_rejects_text_operation():
    sections = {"summary": "alpha beta gamma"}
    patch = Patch(
        operation="replace_in_section",
        section="summary",
        old_text="beta",
        new_text="BETA",
    )

    with pytest.raises(PatchApplicationError, match="frozen section"):
        apply_patches(sections, [patch], frozen_sections={"summary"})


def test_validator_requires_non_empty_locator_and_exact_match():
    sections = {"summary": "alpha beta beta gamma"}
    empty_locator = Patch(
        operation="insert_before",
        section="summary",
        target_text="",
        new_text="x",
    )
    ambiguous_locator = Patch(
        operation="replace_in_section",
        section="summary",
        old_text="beta",
        new_text="BETA",
    )

    with pytest.raises(PatchValidationError, match="requires non-empty target_text"):
        validate_patch(empty_locator, sections)
    with pytest.raises(PatchValidationError, match="found 2 matches"):
        validate_patch(ambiguous_locator, sections)


def test_unresolved_aligned_result_is_rejected_before_application():
    sections = {"summary": "alpha beta gamma"}
    unresolved_patch = Patch(
        operation="replace_in_section",
        section="summary",
        old_text="missing",
        new_text="MISSING",
    )
    resolved_patch = Patch(
        operation="insert_after",
        section="summary",
        target_text="beta",
        new_text=" INSERTED",
    )
    aligned = AlignedPatchResult(patches=(resolved_patch,), unresolved=(unresolved_patch,))

    with pytest.raises(PatchApplicationError, match="Unresolved patch locators"):
        apply_aligned_result(sections, aligned)

    assert sections["summary"] == "alpha beta gamma"


def test_alignment_resolves_stale_locator_before_successful_application():
    sections = {"summary": "alpha better gamma\n"}
    patches = [
        Patch(
            operation="replace_in_section",
            section="summary",
            old_text="alpha beta gamma\n",
            new_text="alpha BETA gamma\n",
        )
    ]

    aligned = align_patches(patches, sections)

    assert aligned.resolved
    assert aligned.patches[0].old_text == "alpha better gamma\n"
    assert apply_aligned_result(sections, aligned) == {"summary": "alpha BETA gamma\n"}

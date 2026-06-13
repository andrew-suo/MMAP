from __future__ import annotations

import pytest

from mmap_optimizer.patch.applier import PatchApplyError, apply_patch
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidationError, validate_patch
from mmap_optimizer.testing.patch_tester import test_patch


def document():
    return {
        "sections": [
            {"id": "intro", "text": "alpha beta gamma", "frozen": False, "payload": {"keep": True}},
            {"id": "locked", "text": "do not touch", "frozen": True},
        ],
        "payload": {"source": "fixture"},
    }


def section_text(doc, section_id="intro"):
    return next(section["text"] for section in doc["sections"] if section["id"] == section_id)


def test_replace_in_section_success_with_new_text():
    patched = apply_patch(
        document(),
        Patch(
            operation_mode="replace_in_section",
            section_id="intro",
            old_text="beta",
            new_text="BETA",
        ),
    )

    assert section_text(patched) == "alpha BETA gamma"


def test_replace_in_section_success_with_nested_locator_and_payload():
    patched = apply_patch(
        document(),
        Patch(
            operation_mode="replace_in_section",
            section_id="intro",
            locator={"old_text": "alpha"},
            payload={"new_text": "ALPHA", "keep": {"this": "payload"}},
        ),
    )

    assert section_text(patched) == "ALPHA beta gamma"


def test_insert_after_success_with_patch_text():
    patched = apply_patch(
        document(),
        Patch(
            operation_mode="insert_after",
            section_id="intro",
            target_text="beta",
            patch_text=" INSERTED",
        ),
    )

    assert section_text(patched) == "alpha beta INSERTED gamma"


def test_insert_before_success_with_insert_text():
    patched = apply_patch(
        document(),
        Patch(
            operation_mode="insert_before",
            section_id="intro",
            target_text="beta",
            insert_text="INSERTED ",
        ),
    )

    assert section_text(patched) == "alpha INSERTED beta gamma"


def test_locator_failure_raises_without_append_fallback():
    with pytest.raises(PatchApplyError, match="target_text not found"):
        apply_patch(
            document(),
            Patch(
                operation_mode="insert_after",
                section_id="intro",
                target_text="missing",
                patch_text=" SHOULD_NOT_APPEND",
            ),
        )


def test_patch_tester_marks_locator_failure_rejected():
    result = test_patch(
        document(),
        Patch(
            operation_mode="replace_in_section",
            section_id="intro",
            old_text="missing",
            new_text="replacement",
        ),
    )

    assert result.rejected
    assert result.status == "rejected"
    assert "old_text not found" in result.error


def test_validator_rejects_frozen_section():
    with pytest.raises(PatchValidationError, match="frozen"):
        validate_patch(
            document(),
            Patch(
                operation_mode="insert_before",
                section_id="locked",
                target_text="touch",
                patch_text="never ",
            ),
        )


def test_document_and_nested_payload_are_preserved():
    source = document()
    patch = Patch(
        operation_mode="insert_after",
        section_id="intro",
        locator={"target_text": "alpha"},
        payload={"insert_text": " preserved", "extra": {"keep": True}},
    )

    patched = apply_patch(source, patch)

    assert patched["payload"] == {"source": "fixture"}
    assert patched["sections"][0]["payload"] == {"keep": True}
    assert patch.payload == {"insert_text": " preserved", "extra": {"keep": True}}
    assert section_text(source) == "alpha beta gamma"
    assert section_text(patched) == "alpha preserved beta gamma"


def test_alignment_after_prior_patch_remains_applicable():
    aligned = apply_patch(
        document(),
        Patch(
            operation_mode="replace_in_section",
            section_id="intro",
            old_text="beta",
            new_text="beta aligned",
        ),
    )

    patched = apply_patch(
        aligned,
        Patch(
            operation_mode="insert_after",
            section_id="intro",
            target_text="beta aligned",
            patch_text=" + applied",
        ),
    )

    assert section_text(patched) == "alpha beta aligned + applied gamma"

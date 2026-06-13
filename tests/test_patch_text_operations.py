import pytest

from mmap_optimizer.patch import Patch, PatchValidationError, apply_patch


@pytest.fixture
def document():
    return (
        "# Intro\nWelcome.\n\n"
        "# Target\nAlpha beta gamma.\nPayload stays here.\n\n"
        "# Frozen\nDo not touch.\n"
    )


def test_replace_in_section_success(document):
    patch = Patch(
        section_id="Target",
        operation_mode="replace_in_section",
        old_text="Alpha beta gamma.",
        new_text="Alpha beta delta.",
    )

    updated = apply_patch(document, patch)

    assert "Alpha beta delta." in updated
    assert "Alpha beta gamma." not in updated
    assert "Welcome." in updated


def test_insert_after_success(document):
    patch = Patch(
        section_id="Target",
        operation_mode="insert_after",
        target_text="Alpha beta gamma.",
        new_text="\nInserted after.",
    )

    updated = apply_patch(document, patch)

    assert "Alpha beta gamma.\nInserted after.\nPayload stays here." in updated


def test_insert_before_success(document):
    patch = Patch(
        section_id="Target",
        operation_mode="insert_before",
        target_text="Payload stays here.",
        new_text="Inserted before.\n",
    )

    updated = apply_patch(document, patch)

    assert "Alpha beta gamma.\nInserted before.\nPayload stays here." in updated


def test_locator_failure_rejects_without_append(document):
    patch = Patch(
        section_id="Target",
        operation_mode="insert_after",
        target_text="Missing locator.",
        new_text="SHOULD NOT APPEND",
    )

    with pytest.raises(PatchValidationError, match="target_text was not found"):
        apply_patch(document, patch)

    assert "SHOULD NOT APPEND" not in document


def test_patch_payload_is_preserved(document):
    payload = {"trace_id": "abc123", "nested": {"keep": True}}
    patch = Patch(
        section_id="Target",
        operation_mode="replace_in_section",
        old_text="Payload stays here.",
        new_text="Payload still stays here.",
        payload=payload,
    )

    apply_patch(document, patch)

    assert patch.payload is payload
    assert patch.payload == {"trace_id": "abc123", "nested": {"keep": True}}


def test_frozen_section_rejects_text_patch(document):
    patch = Patch(
        section_id="Frozen",
        operation_mode="replace_in_section",
        old_text="Do not touch.",
        new_text="Touched.",
    )

    with pytest.raises(PatchValidationError, match="frozen section"):
        apply_patch(document, patch, frozen_sections=["Frozen"])

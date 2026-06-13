from __future__ import annotations

import pytest

from tests._compat import candidate_modules, find_symbol

PATCH_MODULES = candidate_modules(
    "mmap.patch",
    "mmap.patching",
    "mmap.patch_text",
    "mmap.text_patch",
    "mmap_engine.patch",
    "src.patch",
)


def _apply_text_ops(text: str, operations: list[dict]) -> str:
    apply_ops = find_symbol(
        PATCH_MODULES,
        "apply_text_operations",
        "apply_patch_operations",
        "apply_text_patch",
        "apply_patch",
    )
    return apply_ops(text, operations)


def test_replace_operation_targets_only_the_located_span() -> None:
    result = _apply_text_ops(
        "alpha beta gamma beta",
        [
            {
                "op": "replace",
                "locator": {"text": "beta", "occurrence": 2},
                "text": "delta",
            }
        ],
    )

    assert result == "alpha beta gamma delta"


def test_insert_operation_supports_before_and_after_locators() -> None:
    result = _apply_text_ops(
        "one three",
        [
            {"op": "insert", "locator": {"text": "three", "position": "before"}, "text": "two "},
            {"op": "insert", "locator": {"text": "three", "position": "after"}, "text": " four"},
        ],
    )

    assert result == "one two three four"


def test_text_locator_failure_is_explicit_and_does_not_mutate_input() -> None:
    original = "unchanged body"

    with pytest.raises((LookupError, ValueError, RuntimeError)) as excinfo:
        _apply_text_ops(
            original,
            [{"op": "replace", "locator": {"text": "missing anchor"}, "text": "new"}],
        )

    assert "missing anchor" in str(excinfo.value)

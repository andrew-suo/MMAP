"""Initialize prompt versions with optional standardization passes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .refactor import fix_ordered_list_numbering
from .standardizer import normalize_markdown_spacing, unique_heading_titles


def _coerce_prompt_text(prompt: Any) -> str:
    """Coerce supported prompt inputs to text without changing legacy strings."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, Path):
        return prompt.read_text()
    if hasattr(prompt, "read") and callable(prompt.read):
        return prompt.read()
    return str(prompt)


def initialize_prompt_version(
    prompt: Any,
    *legacy_args: Any,
    fix_numbering: bool = False,
    normalize_spacing: bool = False,
    unique_headings: bool = False,
    **legacy_kwargs: Any,
) -> str:
    """Return initialized prompt text.

    The three formatting flags default to ``False`` so callers that do not opt
    in receive the legacy prompt text unchanged. ``legacy_args`` and
    ``legacy_kwargs`` are accepted for compatibility with older call sites that
    passed additional metadata to the initializer.
    """
    del legacy_args, legacy_kwargs

    prompt_text = _coerce_prompt_text(prompt)
    transforms: list[Callable[[str], str]] = []
    if fix_numbering:
        transforms.append(fix_ordered_list_numbering)
    if normalize_spacing:
        transforms.append(normalize_markdown_spacing)
    if unique_headings:
        transforms.append(unique_heading_titles)

    for transform in transforms:
        prompt_text = transform(prompt_text)
    return prompt_text

"""Patch locator alignment helpers.

Alignment resolves stale text locators before patch application. The applier
rejects any aligned result that still contains unresolved text-level patches.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping, Sequence

from .schema import Patch, TEXT_LEVEL_OPERATIONS


@dataclass(frozen=True)
class AlignedPatchResult:
    """Result of aligning patches to current section text."""

    patches: tuple[Patch, ...]
    unresolved: tuple[Patch, ...] = ()

    @property
    def resolved(self) -> bool:
        return not self.unresolved


def _best_unique_alignment(needle: str, haystack: str) -> str | None:
    """Return a unique best matching line when exact matching is unavailable."""

    candidates = [line for line in haystack.splitlines(keepends=True) if line.strip()]
    if not candidates:
        candidates = haystack.splitlines() or [haystack]

    scored = [
        (SequenceMatcher(None, needle, candidate).ratio(), candidate)
        for candidate in candidates
    ]
    scored.sort(reverse=True, key=lambda item: item[0])
    if not scored or scored[0][0] < 0.72:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def align_patch(patch: Patch, sections: Mapping[str, str]) -> tuple[Patch, bool]:
    """Resolve one patch locator against current sections.

    Returns ``(patch, True)`` when resolved, otherwise ``(patch, False)``.
    Exact matches are considered resolved. If a text-level locator no longer
    matches, this function attempts a conservative unique line-level alignment.
    """

    if patch.operation not in TEXT_LEVEL_OPERATIONS:
        return patch, True
    if patch.section not in sections:
        return patch, False

    section_text = sections[patch.section]
    if patch.operation == "replace_in_section":
        locator_text = patch.replacement_target
        locator_field = "old_text" if patch.old_text is not None else "target_text"
    else:
        locator_text = patch.target_text
        locator_field = "target_text"

    if locator_text is None or locator_text == "":
        return patch, False
    if section_text.count(locator_text) == 1:
        return patch, True

    aligned_locator = _best_unique_alignment(locator_text, section_text)
    if aligned_locator is None or section_text.count(aligned_locator) != 1:
        return patch, False

    if locator_field == "old_text":
        return Patch(
            operation=patch.operation,
            section=patch.section,
            old_text=aligned_locator,
            target_text=patch.target_text,
            new_text=patch.new_text,
            payload=patch.payload,
            metadata=patch.metadata,
        ), True
    return Patch(
        operation=patch.operation,
        section=patch.section,
        old_text=patch.old_text,
        target_text=aligned_locator,
        new_text=patch.new_text,
        payload=patch.payload,
        metadata=patch.metadata,
    ), True


def align_patches(patches: Sequence[Patch], sections: Mapping[str, str]) -> AlignedPatchResult:
    """Align a sequence of patches to current section text."""

    resolved_patches: list[Patch] = []
    unresolved_patches: list[Patch] = []
    for patch in patches:
        aligned_patch, resolved = align_patch(patch, sections)
        resolved_patches.append(aligned_patch)
        if not resolved:
            unresolved_patches.append(patch)
    return AlignedPatchResult(tuple(resolved_patches), tuple(unresolved_patches))

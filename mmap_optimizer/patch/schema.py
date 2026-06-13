"""Schemas for document patches.

The :class:`Patch` model deliberately keeps the original section-level patch
shape (``section_id`` + ``content`` + ``operation_mode``) while adding optional
text-level locator fields.  Callers that do not set a locator continue to get
section-level behavior from the applier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


TEXT_OPERATION_MODES = {"replace_in_section", "insert_after", "insert_before"}
SECTION_OPERATION_MODES = {"append", "prepend", "replace_section"}


@dataclass(slots=True)
class Patch:
    """A patch against a named document section.

    Attributes:
        section_id: The target section name or slug.
        content: Backward-compatible section-level payload.  For insert
            operations this may also be used as the inserted text when
            ``new_text`` is omitted.
        operation_mode: Section-level modes (``append``, ``prepend``,
            ``replace_section``) or text-level modes (``replace_in_section``,
            ``insert_after``, ``insert_before``).
        target_text: Exact text locator used by insert operations, and as a
            fallback locator for replacements when ``old_text`` is omitted.
        old_text: Exact text to replace for ``replace_in_section``.
        new_text: Exact replacement/insertion text for text-level operations.
        insert_position: Optional structured locator hint for callers that
            prefer an explicit field.  The applier accepts ``before`` or
            ``after`` and maps them to the corresponding insert operation.
        payload: Arbitrary caller metadata.  The applier and validator never
            mutate this dictionary.
    """

    section_id: str
    content: str | None = None
    operation_mode: str = "append"
    target_text: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    insert_position: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Patch":
        """Build a patch from a mapping without discarding structured locators."""

        allowed = {
            "section_id",
            "content",
            "operation_mode",
            "target_text",
            "old_text",
            "new_text",
            "insert_position",
            "payload",
        }
        kwargs = {key: value[key] for key in allowed if key in value}
        return cls(**kwargs)

    def is_text_level(self) -> bool:
        """Return whether this patch asks for exact text-level application."""

        return self.effective_operation_mode in TEXT_OPERATION_MODES

    @property
    def effective_operation_mode(self) -> str:
        """Resolve insert-position hints into concrete operation modes."""

        if self.operation_mode in {"insert", "insert_in_section"}:
            if self.insert_position == "before":
                return "insert_before"
            if self.insert_position == "after":
                return "insert_after"
        return self.operation_mode

    def replacement_locator(self) -> str | None:
        """Return the exact locator text for a replacement patch."""

        return self.old_text if self.old_text is not None else self.target_text

    def insertion_text(self) -> str | None:
        """Return text inserted/replaced into a section for text-level patches."""

        return self.new_text if self.new_text is not None else self.content

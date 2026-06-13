"""Schema objects for section-oriented patches.

The patch model supports both section-level operations and text-level operations.
Text-level operations carry an explicit locator and payload so callers cannot
silently fall back to appending when a target cannot be found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


TEXT_LEVEL_OPERATIONS = frozenset(
    {
        "replace_in_section",
        "insert_after",
        "insert_before",
    }
)


@dataclass(frozen=True)
class PatchLocator:
    """Location information used to find text inside a section.

    Attributes:
        old_text: Text that must be replaced for ``replace_in_section``.
        target_text: Anchor text used by insertion operations, and optionally
            by replacement operations as an alias for ``old_text``.
    """

    old_text: str | None = None
    target_text: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PatchLocator":
        if value is None:
            return cls()
        return cls(
            old_text=value.get("old_text"),
            target_text=value.get("target_text"),
        )


@dataclass(frozen=True)
class PatchPayload:
    """Replacement or insertion content for a patch."""

    new_text: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PatchPayload":
        if value is None:
            return cls()
        return cls(new_text=value.get("new_text"))


@dataclass(frozen=True)
class Patch:
    """A single patch targeting a named section.

    The top-level ``old_text``, ``target_text``, and ``new_text`` attributes are
    intentionally duplicated from the nested locator/payload objects for a
    compact API and backward-compatible construction from dictionaries.
    """

    operation: str
    section: str
    old_text: str | None = None
    target_text: str | None = None
    new_text: str | None = None
    locator: PatchLocator | None = None
    payload: PatchPayload | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        locator = PatchLocator(
            old_text=(
                self.old_text
                if self.old_text is not None
                else (self.locator.old_text if self.locator else None)
            ),
            target_text=(
                self.target_text
                if self.target_text is not None
                else (self.locator.target_text if self.locator else None)
            ),
        )
        payload = PatchPayload(
            new_text=(
                self.new_text
                if self.new_text is not None
                else (self.payload.new_text if self.payload else None)
            )
        )

        object.__setattr__(self, "locator", locator)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "old_text", locator.old_text)
        object.__setattr__(self, "target_text", locator.target_text)
        object.__setattr__(self, "new_text", payload.new_text)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Patch":
        """Create a patch from a dictionary-like object."""

        return cls(
            operation=value["operation"],
            section=value["section"],
            old_text=value.get("old_text"),
            target_text=value.get("target_text"),
            new_text=value.get("new_text"),
            locator=(
                PatchLocator.from_mapping(value.get("locator"))
                if value.get("locator") is not None
                else None
            ),
            payload=(
                PatchPayload.from_mapping(value.get("payload"))
                if value.get("payload") is not None
                else None
            ),
            metadata=value.get("metadata"),
        )

    @property
    def replacement_target(self) -> str | None:
        """Return replacement locator text, accepting ``target_text`` as alias."""

        return self.old_text if self.old_text is not None else self.target_text

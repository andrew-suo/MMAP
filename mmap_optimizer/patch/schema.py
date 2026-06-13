"""Schema objects for optimizer patches.

The schema intentionally accepts both the historical flat text fields and the
new nested ``locator`` / ``payload`` representation so callers can migrate
incrementally without losing payload information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class Patch:
    """A patch request targeting a document section.

    Text-level patch operations may identify their location either with the
    flat locator fields (``old_text`` / ``target_text``) or with a nested
    ``locator`` mapping. Replacement/insert content may likewise be supplied
    through flat fields (``new_text`` / ``insert_text`` / ``patch_text``) or a
    nested ``payload`` mapping.
    """

    operation_mode: str
    section_id: str | None = None
    patch_text: str | None = None

    # Flat locator/payload fields for text-level operations.
    old_text: str | None = None
    target_text: str | None = None
    new_text: str | None = None
    insert_text: str | None = None

    # Nested representation. These are preserved and never flattened away.
    locator: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    # Compatibility/extension fields used by existing callers.
    target_section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Patch":
        """Build a :class:`Patch` from a dict-like object."""

        known = {
            "operation_mode",
            "section_id",
            "patch_text",
            "old_text",
            "target_text",
            "new_text",
            "insert_text",
            "locator",
            "payload",
            "target_section",
            "metadata",
        }
        kwargs = {key: data[key] for key in known if key in data}
        metadata = dict(kwargs.pop("metadata", {}) or {})
        for key, value in data.items():
            if key not in known:
                metadata[key] = value
        kwargs["metadata"] = metadata
        return cls(**kwargs)

    def locator_value(self, key: str) -> Any:
        """Return a locator value, preferring flat fields over nested data."""

        flat_value = getattr(self, key, None)
        if flat_value is not None:
            return flat_value
        return self.locator.get(key)

    def payload_value(self, *keys: str) -> Any:
        """Return the first available payload value from flat or nested data."""

        for key in keys:
            flat_value = getattr(self, key, None)
            if flat_value is not None:
                return flat_value
            if key in self.payload:
                return self.payload[key]
        return None

    @property
    def effective_section_id(self) -> str | None:
        """Return the section identifier accepted by current and legacy callers."""

        return self.section_id or self.target_section or self.locator.get("section_id")

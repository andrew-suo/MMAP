"""Section and exact-text alignment helpers for patch application."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectionRange:
    """Byte-offset range for a Markdown section body."""

    start: int
    end: int
    heading_start: int
    heading_end: int
    heading_text: str


def normalize_section_id(value: str) -> str:
    """Normalize heading text into a stable slug-like identifier."""

    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def find_section_range(document: str, section_id: str) -> SectionRange:
    """Find a Markdown section by exact heading text or normalized slug.

    Raises:
        ValueError: If no matching Markdown heading can be found.
    """

    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", document))
    wanted = normalize_section_id(section_id)

    for index, heading in enumerate(headings):
        text = heading.group(2).strip()
        if text != section_id and normalize_section_id(text) != wanted:
            continue

        level = len(heading.group(1))
        end = len(document)
        for next_heading in headings[index + 1 :]:
            if len(next_heading.group(1)) <= level:
                end = next_heading.start()
                break

        return SectionRange(
            start=heading.end()
            + (
                1
                if heading.end() < len(document) and document[heading.end()] == "\n"
                else 0
            ),
            end=end,
            heading_start=heading.start(),
            heading_end=heading.end(),
            heading_text=text,
        )

    raise ValueError(f"Section not found: {section_id}")


def ensure_exact_text(section_text: str, locator: str, *, field_name: str = "target_text") -> int:
    """Return the first exact locator offset, rejecting failed alignment."""

    position = section_text.find(locator)
    if position == -1:
        raise ValueError(f"{field_name} was not found in the target section")
    return position

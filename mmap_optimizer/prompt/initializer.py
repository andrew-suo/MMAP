"""Initialize imported prompts without running optimization passes by default."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from .refactor import fix_ordered_list_numbering
from .standardizer import normalize_markdown_spacing, unique_heading_titles

_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_SCHEMA_TITLE_RE = re.compile(r"\bschema\b", re.IGNORECASE)


@dataclass(frozen=True)
class PromptSection:
    """A Markdown section imported from a prompt."""

    title: str
    content: str
    level: int = 0
    frozen: bool = False


def initialize_prompt(
    markdown: str,
    *,
    standardize: bool = False,
    fix_numbering: bool = False,
    normalize_spacing: bool = False,
) -> dict[str, Any]:
    """Import prompt Markdown into sections.

    The import path is intentionally conservative: unless one of the optional
    lossless import-tool flags is enabled, the input Markdown is preserved
    exactly in ``legacy_unmapped`` and in section content.
    """

    sections = _split_sections(markdown)
    should_fix_numbering = fix_numbering or standardize
    should_normalize_spacing = normalize_spacing or standardize

    processed_sections = [
        _process_section(
            section,
            fix_numbering=should_fix_numbering,
            normalize_spacing=should_normalize_spacing,
        )
        for section in sections
    ]
    if should_normalize_spacing:
        processed_sections = _make_heading_titles_unique(processed_sections)
    processed_markdown = _join_sections(processed_sections)

    return {
        "legacy_unmapped": processed_markdown,
        "sections": [asdict(section) for section in processed_sections],
    }


def initialize(
    markdown: str,
    *,
    standardize: bool = False,
    fix_numbering: bool = False,
    normalize_spacing: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`initialize_prompt`."""

    return initialize_prompt(
        markdown,
        standardize=standardize,
        fix_numbering=fix_numbering,
        normalize_spacing=normalize_spacing,
    )


def _split_sections(markdown: str) -> list[PromptSection]:
    sections: list[PromptSection] = []
    current_title = "legacy_unmapped"
    current_level = 0
    current_lines: list[str] = []

    for line in markdown.splitlines(keepends=True):
        heading = _HEADING_RE.match(line.rstrip("\n"))
        if heading:
            if current_lines:
                sections.append(
                    PromptSection(
                        title=current_title,
                        level=current_level,
                        content="".join(current_lines),
                        frozen=_is_frozen_title(current_title),
                    )
                )
            current_title = heading.group("title").strip()
            current_level = len(heading.group("level"))
            current_lines = [line]
            continue
        current_lines.append(line)

    sections.append(
        PromptSection(
            title=current_title,
            level=current_level,
            content="".join(current_lines),
            frozen=_is_frozen_title(current_title),
        )
    )
    return sections


def _process_section(
    section: PromptSection,
    *,
    fix_numbering: bool,
    normalize_spacing: bool,
) -> PromptSection:
    if section.frozen:
        return section

    content = section.content
    if fix_numbering:
        content = fix_ordered_list_numbering(content)
    if normalize_spacing:
        content = normalize_markdown_spacing(content)
        content = unique_heading_titles(content)

    return PromptSection(
        title=section.title,
        level=section.level,
        content=content,
        frozen=section.frozen,
    )


def _make_heading_titles_unique(sections: list[PromptSection]) -> list[PromptSection]:
    seen: dict[str, int] = {}
    unique_sections: list[PromptSection] = []

    for section in sections:
        if section.frozen:
            unique_sections.append(section)
            continue

        content = _unique_heading_titles_with_seen(section.content, seen)
        unique_sections.append(
            PromptSection(
                title=section.title,
                level=section.level,
                content=content,
                frozen=section.frozen,
            )
        )

    return unique_sections


def _unique_heading_titles_with_seen(markdown: str, seen: dict[str, int]) -> str:
    output: list[str] = []
    for line in markdown.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        heading = _HEADING_RE.match(body)
        if not heading:
            output.append(line)
            continue

        title = heading.group("title").strip()
        key = title.casefold()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            title = f"{title} ({seen[key]})"
        output.append(f"{heading.group('level')} {title}{newline}")

    return "".join(output)


def _join_sections(sections: list[PromptSection]) -> str:
    return "".join(section.content for section in sections)


def _is_frozen_title(title: str) -> bool:
    return bool(_SCHEMA_TITLE_RE.search(title))

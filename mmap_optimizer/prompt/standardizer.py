"""Markdown standardization helpers for prompts."""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
_OUTPUT_SCHEMA_TITLE_RE = re.compile(r"^output\s+schema\b", re.IGNORECASE)
_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def _heading_level(line: str) -> int | None:
    match = _HEADING_RE.match(line)
    return len(match.group("marks")) if match else None


def _is_output_schema_heading(line: str) -> tuple[bool, int | None]:
    match = _HEADING_RE.match(line)
    if not match:
        return False, None
    title = re.sub(r"\s+", " ", match.group("title").strip())
    return bool(_OUTPUT_SCHEMA_TITLE_RE.match(title)), len(match.group("marks"))


def _output_schema_mask(lines: list[str]) -> list[bool]:
    """Return True for lines inside an Output Schema section.

    The section begins at a heading named "Output Schema" (case-insensitive)
    and continues until the next heading of the same or higher level.
    """
    mask = [False] * len(lines)
    frozen_level: int | None = None
    for index, line in enumerate(lines):
        if frozen_level is not None:
            level = _heading_level(line)
            if level is not None and level <= frozen_level:
                frozen_level = None
            else:
                mask[index] = True
                continue

        is_schema, level = _is_output_schema_heading(line)
        if is_schema:
            frozen_level = level
            mask[index] = True
    return mask


def normalize_markdown_spacing(markdown: str) -> str:
    """Normalize common Markdown blank-line spacing.

    The function intentionally skips fenced code blocks and any ``Output
    Schema`` section so schemas remain byte-for-byte frozen.
    """
    has_trailing_newline = markdown.endswith("\n")
    lines = markdown.splitlines()
    frozen = _output_schema_mask(lines)

    output: list[str] = []
    in_fence = False

    def append_blank_once() -> None:
        if output and output[-1] != "":
            output.append("")

    for index, line in enumerate(lines):
        stripped = line.strip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")

        if frozen[index] or in_fence:
            output.append(line)
            if is_fence:
                in_fence = not in_fence
            continue
        if is_fence:
            append_blank_once()
            output.append(line.rstrip())
            in_fence = not in_fence
            continue

        if stripped == "":
            if output and output[-1] != "":
                output.append("")
            continue

        is_heading = bool(_HEADING_RE.match(line))
        is_list = bool(_LIST_RE.match(line))
        previous = output[-1] if output else None

        if is_heading:
            append_blank_once()
            output.append(line.rstrip())
            output.append("")
        elif is_list:
            if previous not in (None, "") and not _LIST_RE.match(previous):
                output.append("")
            output.append(line.rstrip())
        else:
            output.append(line.rstrip())

    while output and output[-1] == "":
        output.pop()

    result = "\n".join(output)
    if has_trailing_newline and result:
        result += "\n"
    return result


def unique_heading_titles(markdown: str) -> str:
    """Make duplicate Markdown heading titles unique by appending `` (n)``.

    Output Schema sections are deliberately left unchanged to avoid altering the
    schema contract section.
    """
    lines_without_newlines = markdown.splitlines()
    frozen = _output_schema_mask(lines_without_newlines)
    counts: dict[tuple[int, str], int] = {}
    output: list[str] = []

    for index, raw_line in enumerate(markdown.splitlines(keepends=True)):
        if frozen[index]:
            output.append(raw_line)
            continue

        line = raw_line[:-1] if raw_line.endswith("\n") else raw_line
        newline = "\n" if raw_line.endswith("\n") else ""
        if line.endswith("\r"):
            line = line[:-1]
            newline = "\r" + newline

        match = _HEADING_RE.match(line)
        if not match:
            output.append(raw_line)
            continue

        title = re.sub(r"\s+", " ", match.group("title").strip())
        key = (len(match.group("marks")), title.casefold())
        counts[key] = counts.get(key, 0) + 1
        if counts[key] == 1:
            output.append(raw_line)
        else:
            output.append(f"{match.group('marks')} {title} ({counts[key]}){newline}")

    return "".join(output)

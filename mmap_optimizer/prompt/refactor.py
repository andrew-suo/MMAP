"""Prompt refactoring helpers."""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
_OUTPUT_SCHEMA_TITLE_RE = re.compile(r"^output\s+schema\b", re.IGNORECASE)
_ORDERED_LIST_RE = re.compile(r"^(?P<indent>\s*)(?P<number>\d+)(?P<marker>[.)])(?P<rest>\s+.*)$")


def _heading_level(line: str) -> int | None:
    match = _HEADING_RE.match(line)
    return len(match.group("marks")) if match else None


def _output_schema_mask(lines: list[str]) -> list[bool]:
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

        match = _HEADING_RE.match(line)
        if match and _OUTPUT_SCHEMA_TITLE_RE.match(match.group("title").strip()):
            frozen_level = len(match.group("marks"))
            mask[index] = True
    return mask


def fix_ordered_list_numbering(markdown: str) -> str:
    """Renumber ordered Markdown list items in each contiguous list block.

    Numbering is tracked independently by indentation level and resets when a
    non-list line is encountered. The original marker style (``.`` or ``)``),
    indentation, and item text are preserved.
    """
    lines = markdown.splitlines(keepends=True)
    frozen = _output_schema_mask(markdown.splitlines())
    counters: dict[int, int] = {}
    output: list[str] = []

    for index, raw_line in enumerate(lines):
        line = raw_line[:-1] if raw_line.endswith("\n") else raw_line
        newline = "\n" if raw_line.endswith("\n") else ""
        if line.endswith("\r"):
            line = line[:-1]
            newline = "\r" + newline

        if frozen[index]:
            counters.clear()
            output.append(raw_line)
            continue

        match = _ORDERED_LIST_RE.match(line)
        if not match:
            if line.strip():
                counters.clear()
            output.append(raw_line)
            continue

        indent = len(match.group("indent").replace("\t", "    "))
        # A shallower item starts/continues its own level and discards deeper
        # counters so nested lists restart naturally when re-entered later.
        for level in list(counters):
            if level > indent:
                del counters[level]
        counters[indent] = counters.get(indent, 0) + 1
        output.append(
            f"{match.group('indent')}{counters[indent]}{match.group('marker')}{match.group('rest')}{newline}"
        )

    return "".join(output)

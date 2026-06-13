"""Lossless Markdown standardization helpers used during prompt import."""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(?P<level>#{1,6})(?P<spacing>\s+)(?P<title>.*?)(?P<trailing>\s*)$")


def normalize_markdown_spacing(markdown: str) -> str:
    """Normalize conservative Markdown spacing while preserving content.

    The function trims trailing whitespace, collapses runs of three or more
    blank lines to a single blank line, and ensures headings are separated by a
    blank line from surrounding non-blank content.
    """

    had_trailing_newline = markdown.endswith("\n")
    raw_lines = markdown.splitlines()
    lines = [line.rstrip() for line in raw_lines]

    spaced: list[str] = []
    for line in lines:
        is_heading = bool(_HEADING_RE.match(line))
        if is_heading and spaced and spaced[-1] != "":
            spaced.append("")
        spaced.append(line)

    with_after_heading: list[str] = []
    for index, line in enumerate(spaced):
        with_after_heading.append(line)
        if _HEADING_RE.match(line):
            next_line = spaced[index + 1] if index + 1 < len(spaced) else None
            if next_line not in (None, ""):
                with_after_heading.append("")

    collapsed: list[str] = []
    blank_seen = False
    for line in with_after_heading:
        if line == "":
            if not blank_seen:
                collapsed.append(line)
            blank_seen = True
        else:
            collapsed.append(line)
            blank_seen = False

    result = "\n".join(collapsed)
    if had_trailing_newline and result:
        result += "\n"
    return result


def unique_heading_titles(markdown: str) -> str:
    """Make duplicate Markdown heading titles unique without reordering text."""

    seen: dict[str, int] = {}
    output: list[str] = []

    for line in markdown.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        match = _HEADING_RE.match(body)
        if not match:
            output.append(line)
            continue

        title = match.group("title").strip()
        key = title.casefold()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            title = f"{title} ({seen[key]})"

        output.append(f"{match.group('level')} {title}{newline}")

    return "".join(output)

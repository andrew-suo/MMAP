"""Lossless prompt refactoring helpers used during prompt import."""

from __future__ import annotations

import re

_ORDERED_LIST_RE = re.compile(r"^(?P<indent>\s*)(?P<number>\d+)(?P<marker>[.)])(?P<rest>\s+.*)$")


def fix_ordered_list_numbering(markdown: str) -> str:
    """Renumber ordered Markdown lists without changing list item text.

    Numbering is tracked independently for each indentation level and marker
    style (``.`` or ``)``). Counters reset when a non-list line is reached so
    separate ordered lists remain independent.
    """

    fixed_lines: list[str] = []
    counters: dict[tuple[int, str], int] = {}

    for line in markdown.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""
        match = _ORDERED_LIST_RE.match(body)

        if not match:
            if body.strip():
                counters.clear()
            fixed_lines.append(line)
            continue

        indent = match.group("indent")
        marker = match.group("marker")
        key = (len(indent.expandtabs(4)), marker)
        counters[key] = counters.get(key, 0) + 1

        # A shallower/equal list item starts a new context for deeper levels.
        for existing_key in list(counters):
            if existing_key[0] > key[0]:
                del counters[existing_key]

        fixed_lines.append(
            f"{indent}{counters[key]}{marker}{match.group('rest')}{newline}"
        )

    return "".join(fixed_lines)

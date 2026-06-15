from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def normalize_markdown_spacing(prompt_text: str) -> str:
    lines = prompt_text.splitlines()
    output: list[str] = []
    for line in lines:
        if _HEADING.match(line):
            if output and output[-1] != "":
                output.append("")
            output.append(line.rstrip())
            output.append("")
        else:
            output.append(line.rstrip())
    return _collapse_blank_lines("\n".join(output)).strip()


def unique_heading_titles(prompt_text: str) -> str:
    counts: dict[tuple[str, str], int] = {}
    output: list[str] = []
    for line in prompt_text.splitlines():
        match = _HEADING.match(line)
        if not match:
            output.append(line)
            continue
        level, title = match.groups()
        key = (level, title)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] == 1:
            output.append(line)
        else:
            output.append(f"{level} {title} ({counts[key]})")
    return "\n".join(output)


def _collapse_blank_lines(text: str) -> str:
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text

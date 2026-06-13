from __future__ import annotations

import re

_ORDERED_ITEM = re.compile(r"^(?P<indent>\s*)(?P<number>\d+)(?P<suffix>[.)])(?P<body>\s+.*)$")


def fix_ordered_list_numbering(prompt_text: str) -> str:
    counters: dict[int, int] = {}
    output: list[str] = []
    for line in prompt_text.splitlines():
        match = _ORDERED_ITEM.match(line)
        if not match:
            output.append(line)
            continue
        indent = len(match.group("indent"))
        counters[indent] = counters.get(indent, 0) + 1
        for deeper in [level for level in counters if level > indent]:
            del counters[deeper]
        output.append(f"{match.group('indent')}{counters[indent]}{match.group('suffix')}{match.group('body')}")
    return "\n".join(output)

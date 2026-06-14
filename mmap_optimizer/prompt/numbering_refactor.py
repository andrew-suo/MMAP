"""Deterministic numbering-only prompt refactor utility.

Explicit invocation only. This module exposes a small, pure-text utility
that renumbers Markdown headings, ordered-list markers, and ``Step N:``
lines inside a prompt body. It never calls a language model, never
modifies anything outside the numbering tokens, and never touches
fenced code blocks, ICL delimited regions, or ``{placeholder}`` tokens.

The module lives at :mod:`mmap_optimizer.prompt.numbering_refactor` next
to the existing :mod:`mmap_optimizer.prompt.refactor` helper so prompt
utilities stay co-located.

Default enabled: **false**. Nothing in the optimizer loop, CLI, or
scenario pipeline imports this module automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


# ---------------------------------------------------------------------------
# Data contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumberingIssue:
    """A single numbering mismatch detected by :func:`detect_numbering_issues`.

    ``line_number`` is 1-based and matches the line in the *original*
    text. ``original`` is the numeric token as it appeared; ``expected``
    is the numeric token the deterministic refactor would emit.
    """

    line_number: int
    original: str
    expected: str
    issue_type: str


# ---------------------------------------------------------------------------
# Internal regex building blocks
# ---------------------------------------------------------------------------

# Markdown heading with an optional leading numeric marker.
# Examples:
#   "## 1. Task"        -> hashes="##", marker="1. ", text="Task"
#   "### 2) Rules"      -> hashes="###", marker="2) ", text="Rules"
#   "## No number here" -> no match (text does not start with a number)
_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,6})(?P<space>\s+)(?P<marker>\d+)(?P<suffix>[.)])(?P<rest>\s+.*)$"
)

# Ordered list at a given indentation level.
# Examples: "1. foo", "  2) bar"
_ORDERED_LIST_RE = re.compile(
    r"^(?P<indent>\s*)(?P<number>\d+)(?P<suffix>[.)])(?P<body>\s+.*)$"
)

# "Step N: ..." / "step N: ..." at an optional indentation level.
# We intentionally anchor on "Step " (case-insensitive) followed by a
# digit and a colon so we do not touch the word "step" in free text.
_STEP_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>[Ss]tep)(?P<space>\s+)(?P<number>\d+)(?P<colon>\s*:\s*)(?P<body>.*)$"
)

# Fenced code block opener / closer.
# We accept the classic ``` and ~~~ variants. An optional language tag
# on the opening fence is allowed (e.g. ```json).
_FENCE_RE = re.compile(r"^(?P<indent>\s*)(?P<fence>```+|~~~+)(?P<info>.*)$")

# ICL block delimiters used in the legacy prompt bundle.
_ICL_START_RE = re.compile(r"^\s*===+\s*ICL.*开始.*===+\s*$", re.IGNORECASE)
_ICL_END_RE = re.compile(r"^\s*===+\s*ICL.*结束.*===+\s*$", re.IGNORECASE)

# Placeholder tokens: anything inside {curly_braces}. This is a loose
# scanner; we do not touch placeholders in any context.
_PLACEHOLDER_RE = re.compile(r"\{[^{}\n]*\}")


# ---------------------------------------------------------------------------
# Protection helpers
# ---------------------------------------------------------------------------


@dataclass
class _ProtectionState:
    in_fence: Optional[str] = None  # the fence opener string, e.g. "```"
    in_icl: bool = False


def _classify_lines(lines: List[str]) -> List[_ProtectionState]:
    """Return a parallel list indicating per-line protection state.

    A line is considered "protected" when it sits inside a fenced code
    block or inside an explicit ICL delimited region. Protection state
    is computed *after* processing the line's own opener/closer so the
    fence line itself is also considered protected.
    """

    state = _ProtectionState()
    result: List[_ProtectionState] = []
    for line in lines:
        fence_match = _FENCE_RE.match(line)
        # A closing fence must match the opening fence in kind and
        # length; we approximate by comparing the leading fence token.
        if state.in_fence is None and fence_match is not None and fence_match.group("info").strip().lower() != "markdown":
            state = _ProtectionState(in_fence=fence_match.group("fence"), in_icl=state.in_icl)
        elif state.in_fence is not None and fence_match is not None:
            # Closing fence: at least three backticks/tildes on its own.
            closing = fence_match.group("fence")
            if closing.startswith(state.in_fence[0]) and len(closing) >= len(state.in_fence):
                state = _ProtectionState(in_fence=None, in_icl=state.in_icl)
        if _ICL_START_RE.match(line) and not state.in_fence:
            state = _ProtectionState(in_fence=state.in_fence, in_icl=True)
        elif _ICL_END_RE.match(line) and not state.in_fence:
            state = _ProtectionState(in_fence=state.in_fence, in_icl=False)

        result.append(_ProtectionState(in_fence=state.in_fence, in_icl=state.in_icl))
    return result


def _is_protected(state: _ProtectionState) -> bool:
    return state.in_fence is not None or state.in_icl


# ---------------------------------------------------------------------------
# Individual refactor operations
# ---------------------------------------------------------------------------


def refactor_markdown_heading_numbering(text: str) -> str:
    """Renumber ``#{1,6} N.`` / ``#{1,6} N)`` heading markers.

    Only lines that already *have* a leading numeric marker are touched.
    Headings without a numeric marker are preserved verbatim. The
    numbering is tracked independently per heading level.
    """

    lines = text.splitlines(keepends=True)
    raw_lines = [line.rstrip("\r\n") for line in lines]
    newlines = [line[len(raw):] for line, raw in zip(lines, raw_lines)]
    protection = _classify_lines(raw_lines)
    per_level_counters: dict[int, int] = {}
    output: List[str] = []

    for line, state, nl in zip(raw_lines, protection, newlines):
        if _is_protected(state):
            output.append(line + nl)
            continue
        match = _HEADING_RE.match(line)
        if not match:
            output.append(line + nl)
            continue
        level = len(match.group("hashes"))
        per_level_counters[level] = per_level_counters.get(level, 0) + 1
        new_number = per_level_counters[level]
        for deeper in [lvl for lvl in per_level_counters if lvl > level]:
            del per_level_counters[deeper]
        rebuilt = (
            match.group("hashes")
            + match.group("space")
            + str(new_number)
            + match.group("suffix")
            + match.group("rest")
        )
        output.append(rebuilt + nl)
    return "".join(output)


def refactor_ordered_list_numbering(text: str) -> str:
    """Renumber ``N.`` / ``N)`` ordered-list markers at each indent level.

    Bullet lists, plain prose, and protected blocks are preserved
    verbatim. Counters are keyed by indentation level so nested lists
    restart independently.
    """

    lines = text.splitlines(keepends=True)
    raw_lines = [line.rstrip("\r\n") for line in lines]
    newlines = [line[len(raw):] for line, raw in zip(lines, raw_lines)]
    protection = _classify_lines(raw_lines)
    counters: dict[int, int] = {}
    output: List[str] = []

    for line, state, nl in zip(raw_lines, protection, newlines):
        if _is_protected(state):
            output.append(line + nl)
            continue
        match = _ORDERED_LIST_RE.match(line)
        if not match:
            output.append(line + nl)
            continue
        indent = len(match.group("indent"))
        counters[indent] = counters.get(indent, 0) + 1
        for deeper in [level for level in counters if level > indent]:
            del counters[deeper]
        output.append(
            f"{match.group('indent')}{counters[indent]}{match.group('suffix')}{match.group('body')}{nl}"
        )
    return "".join(output)


def refactor_step_numbering(text: str) -> str:
    """Renumber ``Step N: ...`` lines.

    Only lines whose first non-whitespace content is ``Step`` followed
    by a digit and a colon are renumbered. The counter restarts from 1
    per call. Protected content is never touched.
    """

    lines = text.splitlines(keepends=True)
    raw_lines = [line.rstrip("\r\n") for line in lines]
    newlines = [line[len(raw):] for line, raw in zip(lines, raw_lines)]
    protection = _classify_lines(raw_lines)
    counter = 0
    output: List[str] = []

    for line, state, nl in zip(raw_lines, protection, newlines):
        if _is_protected(state):
            output.append(line + nl)
            continue
        match = _STEP_RE.match(line)
        if not match:
            output.append(line + nl)
            continue
        counter += 1
        rebuilt = (
            match.group("indent")
            + match.group("prefix")
            + match.group("space")
            + str(counter)
            + match.group("colon")
            + match.group("body")
        )
        output.append(rebuilt + nl)
    return "".join(output)


# ---------------------------------------------------------------------------
# Detection API
# ---------------------------------------------------------------------------


def detect_numbering_issues(text: str) -> List[NumberingIssue]:
    """Return a deterministic list of numbering issues in *text*.

    Issues detected inside protected regions are intentionally omitted.
    """

    lines = text.splitlines(keepends=False)
    protection = _classify_lines(lines)

    issues: List[NumberingIssue] = []

    # --- headings ----------------------------------------------------------
    per_level_counters: dict[int, int] = {}
    for idx, (line, state) in enumerate(zip(lines, protection), start=1):
        if _is_protected(state):
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group("hashes"))
        per_level_counters[level] = per_level_counters.get(level, 0) + 1
        for deeper in [lvl for lvl in per_level_counters if lvl > level]:
            del per_level_counters[deeper]
        expected = per_level_counters[level]
        original = int(match.group("marker"))
        if original != expected:
            issues.append(
                NumberingIssue(
                    line_number=idx,
                    original=str(original),
                    expected=str(expected),
                    issue_type=(
                        "heading_duplicate" if original == per_level_counters.get(level - 1, original) else "heading_gap"
                    ),
                )
            )

    # --- ordered lists -----------------------------------------------------
    counters: dict[int, int] = {}
    for idx, (line, state) in enumerate(zip(lines, protection), start=1):
        if _is_protected(state):
            continue
        match = _ORDERED_LIST_RE.match(line)
        if not match:
            continue
        indent = len(match.group("indent"))
        counters[indent] = counters.get(indent, 0) + 1
        for deeper in [level for level in counters if level > indent]:
            del counters[deeper]
        expected = counters[indent]
        original = int(match.group("number"))
        if original != expected:
            issues.append(
                NumberingIssue(
                    line_number=idx,
                    original=str(original),
                    expected=str(expected),
                    issue_type="ordered_list_duplicate" if original < expected else "ordered_list_gap",
                )
            )

    # --- steps -------------------------------------------------------------
    counter = 0
    for idx, (line, state) in enumerate(zip(lines, protection), start=1):
        if _is_protected(state):
            continue
        match = _STEP_RE.match(line)
        if not match:
            continue
        counter += 1
        original = int(match.group("number"))
        if original != counter:
            issues.append(
                NumberingIssue(
                    line_number=idx,
                    original=str(original),
                    expected=str(counter),
                    issue_type="step_duplicate" if original < counter else "step_gap",
                )
            )

    issues.sort(key=lambda i: i.line_number)
    return issues


# ---------------------------------------------------------------------------
# Composition API
# ---------------------------------------------------------------------------


def _preserve_placeholders(text: str) -> str:
    """Return *text* with ``{placeholder}`` tokens unchanged.

    This function is a no-op; it exists as an explicit safety guard and
    a hook for future instrumentation. The refactor operations above
    never modify placeholder tokens because their regexes anchor on
    specific line-start structures that placeholders never satisfy.
    """

    return text


def refactor_prompt_numbering_only(text: str) -> str:
    """Apply heading, ordered-list, and step renumbering.

    The composition order is intentionally stable: heading markers are
    fixed first, then ordered-list markers, then step markers. Each
    pass preserves protected content verbatim, and every pass is
    idempotent — running the composition twice produces the same text.

    Parameters
    ----------
    text:
        Raw prompt text to refactor.

    Returns
    -------
    str
        A new string with numbering-only fixes applied. Protected
        regions (fenced code blocks, ICL delimited blocks, and
        ``{placeholder}`` tokens) are byte-preserved.
    """

    if text is None:
        raise ValueError("refactor_prompt_numbering_only: text must not be None")
    if not isinstance(text, str):
        raise TypeError("refactor_prompt_numbering_only: text must be str")

    step1 = refactor_markdown_heading_numbering(text)
    step2 = refactor_ordered_list_numbering(step1)
    step3 = refactor_step_numbering(step2)
    return _preserve_placeholders(step3)


__all__: Iterable[str] = (
    "NumberingIssue",
    "refactor_prompt_numbering_only",
    "refactor_markdown_heading_numbering",
    "refactor_ordered_list_numbering",
    "refactor_step_numbering",
    "detect_numbering_issues",
)

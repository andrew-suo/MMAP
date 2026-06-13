"""Prompt health checks for MMAP prompt templates.

The checker is intentionally conservative: it reports structural risks and only
ships safe autofixes that do not rewrite business meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Iterable, Sequence


class Severity(str, Enum):
    """Prompt health issue severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IssueType(str, Enum):
    """Stable issue types emitted by the prompt health checker."""

    DUPLICATE_HEADING = "duplicate_heading"
    NUMBERING_JUMP = "numbering_jump"
    EMPTY_SECTION = "empty_section"
    LONG_SECTION = "long_section"
    FROZEN_SCHEMA_MODIFIED = "frozen_schema_modified"
    MISSING_OUTPUT_FORMAT = "missing_output_format"
    LEGACY_UNMAPPED_TOO_LARGE = "legacy_unmapped_too_large"
    SECTION_MARKER_INCONSISTENT = "section_marker_inconsistent"


@dataclass(frozen=True)
class PromptHealthIssue:
    """A single prompt health finding."""

    severity: Severity
    issue_type: IssueType
    section_id: str | None
    suggested_fix: str
    message: str = ""


@dataclass(frozen=True)
class PromptHealthReport:
    """Structured output for prompt health checks."""

    issues: tuple[PromptHealthIssue, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """Return True when no error-level findings were emitted."""

        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def severity(self) -> Severity:
        """Highest severity in the report."""

        if any(issue.severity is Severity.ERROR for issue in self.issues):
            return Severity.ERROR
        if any(issue.severity is Severity.WARNING for issue in self.issues):
            return Severity.WARNING
        return Severity.INFO

    def to_dict(self) -> dict[str, object]:
        """Serialize the report to a JSON-friendly dictionary."""

        return {
            "passed": self.passed,
            "severity": self.severity.value,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "issue_type": issue.issue_type.value,
                    "section_id": issue.section_id,
                    "suggested_fix": issue.suggested_fix,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True)
class _Section:
    heading: str
    section_id: str
    level: int
    number: tuple[int, ...] | None
    start_line: int
    content: str
    marker_id: str | None = None


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_MARKER_RE = re.compile(r"<!--\s*SECTION:\s*([A-Za-z0-9_.:-]+)\s*-->")
_LEGACY_RE = re.compile(r"legacy[_ -]?unmapped", re.IGNORECASE)
_OUTPUT_FORMAT_RE = re.compile(r"output\s+format|输出格式", re.IGNORECASE)
_SCHEMA_RE = re.compile(r"schema|json\s*schema|output\s+schema", re.IGNORECASE)
_NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+")
_WORD_RE = re.compile(r"\S+")


def normalize_section_id(heading: str) -> str:
    """Normalize a heading into a stable section identifier."""

    text = _NUMBER_PREFIX_RE.sub("", heading).strip().lower()
    text = re.sub(r"[`*_\[\]()]", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text).strip("_")
    return text or "section"


def _parse_number(heading: str) -> tuple[int, ...] | None:
    match = _NUMBER_PREFIX_RE.match(heading.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def parse_sections(prompt: str) -> list[_Section]:
    """Parse Markdown headings into sections."""

    matches = list(_HEADING_RE.finditer(prompt))
    sections: list[_Section] = []
    for index, match in enumerate(matches):
        marker_text = prompt[: match.start()].splitlines()[-1:] or [""]
        marker_match = _MARKER_RE.search(marker_text[0])
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        heading = match.group(2).strip()
        sections.append(
            _Section(
                heading=heading,
                section_id=normalize_section_id(heading),
                level=len(match.group(1)),
                number=_parse_number(heading),
                start_line=prompt.count("\n", 0, match.start()) + 1,
                content=prompt[content_start:content_end],
                marker_id=marker_match.group(1) if marker_match else None,
            )
        )
    return sections


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _find_numbering_jumps(sections: Sequence[_Section]) -> Iterable[PromptHealthIssue]:
    previous_by_parent: dict[tuple[int, ...], int] = {}
    for section in sections:
        if section.number is None:
            continue
        parent = section.number[:-1]
        current = section.number[-1]
        expected = previous_by_parent.get(parent, 0) + 1
        if current != expected:
            expected_number = ".".join(str(part) for part in (*parent, expected))
            actual_number = ".".join(str(part) for part in section.number)
            yield PromptHealthIssue(
                Severity.WARNING,
                IssueType.NUMBERING_JUMP,
                section.section_id,
                f"Renumber this heading to {expected_number}, or insert the missing section before {actual_number}.",
                f"Heading numbering jumps from expected {expected_number} to {actual_number}.",
            )
        previous_by_parent[parent] = current


def _is_empty_section(section: _Section) -> bool:
    content = _MARKER_RE.sub("", section.content).strip()
    return not content


def _extract_schema_sections(sections: Sequence[_Section]) -> dict[str, str]:
    return {
        section.section_id: section.content.strip()
        for section in sections
        if _SCHEMA_RE.search(section.heading) or section.section_id in {"schema", "output_schema", "frozen_schema"}
    }


def check_prompt_health(
    prompt: str,
    *,
    baseline_prompt: str | None = None,
    max_section_words: int = 500,
    legacy_unmapped_max_words: int = 120,
) -> PromptHealthReport:
    """Run conservative prompt health checks.

    Args:
        prompt: Markdown prompt text to inspect.
        baseline_prompt: Optional frozen/baseline prompt text. When provided,
            schema-like sections are compared to detect accidental changes.
        max_section_words: Word-count threshold for long sections.
        legacy_unmapped_max_words: Word-count threshold for legacy_unmapped.
    """

    sections = parse_sections(prompt)
    issues: list[PromptHealthIssue] = []

    seen: dict[str, _Section] = {}
    for section in sections:
        previous = seen.get(section.section_id)
        if previous is not None:
            issues.append(
                PromptHealthIssue(
                    Severity.ERROR,
                    IssueType.DUPLICATE_HEADING,
                    section.section_id,
                    "Rename or merge the duplicate heading so each section has a unique purpose and id.",
                    f"Heading duplicates line {previous.start_line}.",
                )
            )
        else:
            seen[section.section_id] = section

        if _is_empty_section(section):
            issues.append(
                PromptHealthIssue(
                    Severity.WARNING,
                    IssueType.EMPTY_SECTION,
                    section.section_id,
                    "Add content to this section, remove it, or mark it as intentionally empty.",
                    "Section has no non-marker content.",
                )
            )

        words = _word_count(section.content)
        if words > max_section_words:
            issues.append(
                PromptHealthIssue(
                    Severity.WARNING,
                    IssueType.LONG_SECTION,
                    section.section_id,
                    f"Split this section into focused subsections under {max_section_words} words.",
                    f"Section has {words} words.",
                )
            )

        if _LEGACY_RE.search(section.heading) or _LEGACY_RE.search(section.section_id):
            legacy_words = _word_count(section.content)
            if legacy_words > legacy_unmapped_max_words:
                issues.append(
                    PromptHealthIssue(
                        Severity.WARNING,
                        IssueType.LEGACY_UNMAPPED_TOO_LARGE,
                        section.section_id,
                        "Refactor legacy_unmapped into explicit standard sections; do not silently keep expanding it.",
                        f"legacy_unmapped contains {legacy_words} words.",
                    )
                )

        if section.marker_id and section.marker_id != section.section_id:
            issues.append(
                PromptHealthIssue(
                    Severity.WARNING,
                    IssueType.SECTION_MARKER_INCONSISTENT,
                    section.section_id,
                    f"Change the marker to <!-- SECTION: {section.section_id} --> or rename the heading to match the marker.",
                    f"Marker '{section.marker_id}' does not match heading id '{section.section_id}'.",
                )
            )

    issues.extend(_find_numbering_jumps(sections))

    if sections and not any(_OUTPUT_FORMAT_RE.search(section.heading) for section in sections):
        issues.append(
            PromptHealthIssue(
                Severity.ERROR,
                IssueType.MISSING_OUTPUT_FORMAT,
                None,
                "Add an explicit Output Format section describing the expected response shape.",
                "No heading declares an output format.",
            )
        )

    if baseline_prompt is not None:
        baseline_schema = _extract_schema_sections(parse_sections(baseline_prompt))
        current_schema = _extract_schema_sections(sections)
        for section_id, baseline_content in baseline_schema.items():
            if section_id in current_schema and current_schema[section_id] != baseline_content:
                issues.append(
                    PromptHealthIssue(
                        Severity.ERROR,
                        IssueType.FROZEN_SCHEMA_MODIFIED,
                        section_id,
                        "Restore the frozen schema from baseline or perform an explicit schema migration.",
                        "Frozen schema section differs from the baseline prompt.",
                    )
                )

    return PromptHealthReport(tuple(issues))


def safe_autofix(prompt: str) -> str:
    """Apply safe formatting-only fixes that do not alter business content.

    Currently this only normalizes SECTION marker ids to match the immediately
    following Markdown heading. It intentionally does not rename headings,
    renumber sections, split content, or edit schemas.
    """

    lines = prompt.splitlines(keepends=True)
    for index, line in enumerate(lines[:-1]):
        marker = _MARKER_RE.fullmatch(line.strip())
        if not marker:
            continue
        heading = _HEADING_RE.match(lines[index + 1].rstrip("\n"))
        if heading:
            section_id = normalize_section_id(heading.group(2).strip())
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"<!-- SECTION: {section_id} -->{newline}"
    return "".join(lines)

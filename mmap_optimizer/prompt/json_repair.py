"""Explicit utility: JSON repair / position-valid output.

This module provides deterministic text-level JSON repair. It accepts
input that may contain Markdown fences, surrounding prose, trailing
commas, and leading / trailing junk characters, and returns a
position-valid JSON string that can be parsed by ``json.loads``.

Position-valid contract (see ``repair_json_output`` docstring):
- The FIRST non-whitespace character is ``{`` or ``[``.
- The LAST non-whitespace character is ``}`` or ``]``.
- No code fences, no prologue, no trailing remarks.
- Strict JSON only — no single quotes, no bare keys, no Python literals,
  no NaN / Infinity, no inline comments.

The utility does NOT call any LLM, does NOT write files, is NOT wired
into the optimizer loop, and performs only text / format-level repairs
— never semantic field addition. Callers invoke it explicitly.

Typical usage::

    from mmap_optimizer.prompt.json_repair import (
        JsonRepairIssue,
        JsonRepairResult,
        repair_json_output,
        parse_json_strict,
    )

    raw = '```json\n{"a": 1,}\n```'
    result = repair_json_output(raw)

    if result.ok:
        assert result.repaired_text == '{"a": 1}'
        value = parse_json_strict(result.repaired_text)
        assert value == {"a": 1}
    else:
        for issue in result.issues:
            print(issue.issue_type, "-", issue.detail)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JsonRepairIssue:
    """A single defect detected / corrected during repair."""

    issue_type: str
    detail: str
    original_fragment: str | None = None
    repaired_fragment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "detail": self.detail,
            "original_fragment": self.original_fragment,
            "repaired_fragment": self.repaired_fragment,
        }


@dataclass(frozen=True)
class JsonRepairResult:
    """Complete output of a repair attempt."""

    ok: bool
    repaired_text: str
    parsed: Any
    issues: tuple[JsonRepairIssue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "repaired_text": self.repaired_text,
            "parsed": self.parsed,
            "issues": [i.to_dict() for i in self.issues],
        }


def _find_top_level_candidates(text: str) -> list[tuple[int, int, str]]:
    """Find balanced ``{...}`` and ``[...]`` spans in *text*.

    Returns a list of ``(start, end_past, opener_char)`` tuples.
    Only counts braces inside JSON strings by tracking quote state.
    """

    candidates: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in "{[":
            opener = ch
            closer = "}" if ch == "{" else "]"
            depth = 1
            j = i + 1
            in_str = False
            quote: str | None = None
            while j < n and depth > 0:
                c = text[j]
                if in_str:
                    if c == "\\" and j + 1 < n:
                        j += 2
                        continue
                    if c == quote:
                        in_str = False
                    j += 1
                    continue
                if c in ('"', "'"):
                    in_str = True
                    quote = c
                    j += 1
                    continue
                if c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                j += 1
            if depth == 0:
                candidates.append((i, j, opener))
            i = j
        else:
            i += 1
    return candidates


def _strip_code_fence(text: str) -> tuple[str, list[JsonRepairIssue]]:
    """Remove Markdown code-fence wrappers if present."""

    lines = text.split("\n")
    issues: list[JsonRepairIssue] = []

    open_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.rstrip("\r")
        if re.match(r"^\s*```", stripped):
            open_idx = i
            break
        if stripped.strip() != "":
            break

    close_idx: int | None = None
    if open_idx is not None:
        for j in range(len(lines) - 1, open_idx, -1):
            stripped = lines[j].rstrip("\r")
            if re.match(r"^\s*```", stripped):
                close_idx = j
                break
            if stripped.strip() != "":
                break

    if open_idx is not None and close_idx is not None and close_idx > open_idx:
        original = "\n".join(lines[open_idx : close_idx + 1])
        body = "\n".join(lines[open_idx + 1 : close_idx])
        issues.append(
            JsonRepairIssue(
                issue_type="code_fence_removed",
                detail="Removed Markdown code fence around JSON body.",
                original_fragment=original[:200],
                repaired_fragment=body[:200],
            )
        )
        result = "\n".join(lines[:open_idx] + [body] + lines[close_idx + 1 :])
        return result, issues

    return text, issues


def _find_exterior(text: str) -> tuple[str, list[JsonRepairIssue]]:
    """Locate the primary JSON span and drop surrounding prose."""

    issues: list[JsonRepairIssue] = []
    stripped = text.strip("\r\n \t")
    if not stripped:
        return text, issues

    candidates = _find_top_level_candidates(stripped)
    if not candidates:
        return text, issues

    start, end, _ = min(candidates, key=lambda kv: (kv[0], kv[0] - kv[1]))
    prefix = stripped[:start]
    suffix = stripped[end:]

    if prefix.strip() or suffix.strip():
        issues.append(
            JsonRepairIssue(
                issue_type="exterior_text_removed",
                detail="Stripped prose before / after JSON body.",
                original_fragment=(prefix[-60:] + "..." + suffix[:60]).strip() or None,
                repaired_fragment=None,
            )
        )

    return stripped[start:end], issues


def _remove_trailing_commas(text: str) -> tuple[str, list[JsonRepairIssue]]:
    """Remove trailing commas inside objects / arrays."""

    issues: list[JsonRepairIssue] = []
    out: list[str] = []
    n = len(text)
    i = 0
    in_str = False
    quote: str | None = None

    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                in_str = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}])":
                issues.append(
                    JsonRepairIssue(
                        issue_type="trailing_comma_removed",
                        detail="Removed trailing comma before closing brace / bracket / paren.",
                        original_fragment=text[i : min(i + 8, n)],
                        repaired_fragment=text[i + 1 : min(i + 8, n)],
                    )
                )
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out), issues


def _reject_pythonisms(text: str) -> list[JsonRepairIssue]:
    """Detect Python-isms that should block strict parsing."""

    issues: list[JsonRepairIssue] = []

    nan_infinity_re = re.compile(r"\b(?:NaN|Infinity)\b")
    if nan_infinity_re.search(text):
        issues.append(
            JsonRepairIssue(
                issue_type="strict_parse_failed",
                detail="Input contains NaN / Infinity (not valid JSON).",
                original_fragment=nan_infinity_re.search(text).group(0),
            )
        )

    py_literal_re = re.compile(r"\b(?:None|True|False)\b")
    m = py_literal_re.search(text)
    if m:
        issues.append(
            JsonRepairIssue(
                issue_type="unsupported_python_literal",
                detail="Python None / True / False are not valid JSON.",
                original_fragment=m.group(0),
            )
        )

    if "//" in text or "/*" in text:
        issues.append(
            JsonRepairIssue(
                issue_type="strict_parse_failed",
                detail="JSON comments (// or /*) are not valid JSON.",
                original_fragment=text[:200],
            )
        )

    single_quote_re = re.compile(r"(?:'[A-Za-z0-9_]+'\s*:)")
    m2 = single_quote_re.search(text)
    if m2:
        issues.append(
            JsonRepairIssue(
                issue_type="unsupported_single_quotes",
                detail="Single-quoted JSON strings are not valid JSON.",
                original_fragment=text[:200],
            )
        )

    bare_key_re = re.compile(r"(?:\{|,)\s*[A-Za-z_][A-Za-z0-9_]*\s*:")
    m3 = bare_key_re.search(text)
    if m3:
        issues.append(
            JsonRepairIssue(
                issue_type="unsupported_bare_key",
                detail="JSON object keys must be double-quoted strings.",
                original_fragment=m3.group(0),
            )
        )

    return issues


def parse_json_strict(text: str) -> Any:
    """Parse *text* as strict JSON.

    Raises ``TypeError`` if *text* is not a string, and the usual
    ``json.JSONDecodeError`` if it cannot be parsed.
    """

    if not isinstance(text, str):
        raise TypeError(
            "parse_json_strict expected str, got %s" % type(text).__name__
        )
    return json.loads(text)


def strip_json_code_fence(text: str) -> tuple[str, tuple[JsonRepairIssue, ...]]:
    """Public wrapper for code-fence stripping only."""

    if not isinstance(text, str):
        raise TypeError(
            "strip_json_code_fence expected str, got %s" % type(text).__name__
        )
    body, issues = _strip_code_fence(text)
    return body, tuple(issues)


def extract_position_valid_json_candidate(
    text: str,
) -> tuple[str, tuple[JsonRepairIssue, ...]]:
    """Find a balanced ``{...}`` / ``[...]`` JSON span in *text*."""

    if not isinstance(text, str):
        raise TypeError(
            "extract_position_valid_json_candidate expected str, "
            "got %s" % type(text).__name__
        )

    body, fence_issues = _strip_code_fence(text)
    candidate, prose_issues = _find_exterior(body)
    return candidate, tuple(fence_issues + prose_issues)


def ensure_position_valid_json(text: str) -> tuple[str, tuple[JsonRepairIssue, ...]]:
    """Apply all supported text-level repairs to *text*.

    Pipeline:
    1. Strip Markdown code fences.
    2. Extract the balanced JSON span and drop surrounding prose.
    3. If the span changed, emit a position_invalid_repaired issue.
    4. Strip trailing commas inside objects / arrays.
    """

    if not isinstance(text, str):
        raise TypeError(
            "ensure_position_valid_json expected str, got %s" % type(text).__name__
        )

    all_issues: list[JsonRepairIssue] = []

    current, fence = _strip_code_fence(text)
    all_issues.extend(fence)

    before = current
    candidate, prose = _find_exterior(current)
    all_issues.extend(prose)

    if candidate != before:
        all_issues.append(
            JsonRepairIssue(
                issue_type="position_invalid_repaired",
                detail="Trimmed non-JSON leading / trailing characters.",
                original_fragment=before[:120],
                repaired_fragment=candidate[:120],
            )
        )

    current_after, trailing = _remove_trailing_commas(candidate)
    all_issues.extend(trailing)

    return current_after, tuple(all_issues)


def repair_json_output(text: str) -> JsonRepairResult:
    """Deterministic text-level JSON repair.

    See module docstring for the position-valid contract.
    """

    if not isinstance(text, str):
        raise TypeError(
            "repair_json_output expected str, got %s" % type(text).__name__
        )

    if not text.strip():
        return JsonRepairResult(
            ok=False,
            repaired_text="",
            parsed=None,
            issues=(
                JsonRepairIssue(
                    issue_type="empty_input",
                    detail="Empty or whitespace-only input; nothing to repair.",
                ),
            ),
        )

    all_issues: list[JsonRepairIssue] = []

    python_issues = _reject_pythonisms(text)
    if python_issues:
        all_issues.extend(python_issues)
        repaired, pos_issues = ensure_position_valid_json(text)
        all_issues.extend(pos_issues)
        return JsonRepairResult(
            ok=False,
            repaired_text=repaired,
            parsed=None,
            issues=tuple(all_issues),
        )

    candidates = _find_top_level_candidates(text.strip("\r\n \t"))
    if len(candidates) > 1:
        all_issues.append(
            JsonRepairIssue(
                issue_type="multiple_json_candidates",
                detail=(
                    "More than one balanced {...} or [...] span in input; "
                    "refusing to pick one."
                ),
                original_fragment=text[:200],
            )
        )
        repaired, pos_issues = ensure_position_valid_json(text)
        all_issues.extend(pos_issues)
        return JsonRepairResult(
            ok=False,
            repaired_text=repaired,
            parsed=None,
            issues=tuple(all_issues),
        )

    repaired, pos_issues = ensure_position_valid_json(text)
    all_issues.extend(pos_issues)

    try:
        parsed = parse_json_strict(repaired)
    except (ValueError, TypeError) as exc:
        all_issues.append(
            JsonRepairIssue(
                issue_type="strict_parse_failed",
                detail="json.loads failed after repair: %s" % str(exc),
                original_fragment=repaired[:200],
            )
        )
        return JsonRepairResult(
            ok=False,
            repaired_text=repaired,
            parsed=None,
            issues=tuple(all_issues),
        )

    return JsonRepairResult(
        ok=True,
        repaired_text=repaired,
        parsed=parsed,
        issues=tuple(all_issues),
    )

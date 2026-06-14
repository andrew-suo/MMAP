"""Explicit utility: immutable-payload validation.

This module is a deterministic text comparison utility. It checks that an
"immutable payload" — i.e., business content that must survive prompt
rewriting / formatting / JSON repair / patch translation — is preserved
byte-for-byte (up to a small, safe set of normalizations) between an
original prompt and a rewritten version.

The caller invokes this explicitly. Nothing in ``mmap_optimizer`` calls it
by default, no optimizer-loop hook exists, and no LLM call is made.

Typical usage::

    from mmap_optimizer.prompt.immutable_payload import (
        validate_immutable_payload,
    )

    result = validate_immutable_payload(original_text, rewritten_text)
    if not result.ok:
        for issue in result.issues:
            print(issue.issue_type, issue.detail)

Safe normalizations
-------------------
* Line ending normalization (CRLF / CR -> LF)
* Trailing whitespace on each line stripped
* Final newline normalization (text ends with exactly one '\n')

Explicitly forbidden normalizations
-----------------------------------
* Lower-casing
* Punctuation removal
* Line reordering
* Any semantic-level normalization
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImmutablePayloadIssue:
    """A single immutable-payload discrepancy.

    Fields are deliberately narrow so callers can rely on stable names.
    ``payload_id`` is only set when multiple payload blocks were detected;
    ``expected`` / ``actual`` are optional and only populated when the
    discrepancy naturally maps to a pair of values (e.g., the set of
    placeholders).
    """

    issue_type: str
    detail: str
    payload_id: str | None = None
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type,
            "payload_id": self.payload_id,
            "detail": self.detail,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class ImmutablePayloadValidationResult:
    """Full result of a single ``validate_immutable_payload`` call.

    ``ok`` is a simple ``len(issues) == 0`` invariant; both hashes are
    computed on the ``normalize_payload_for_comparison`` view of the input
    so that trivial whitespace differences do not by themselves produce
    spurious failures. (Real content differences still produce different
    hashes and are reported as ``hash_changed``.)
    """

    ok: bool
    issues: tuple[ImmutablePayloadIssue, ...]
    original_hash: str
    rewritten_hash: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [i.to_dict() for i in self.issues],
            "original_hash": self.original_hash,
            "rewritten_hash": self.rewritten_hash,
        }


# ---------------------------------------------------------------------------
# Regexes / constants
# ---------------------------------------------------------------------------


# {anything} where 'anything' contains word chars, digits, and underscore.
# Does NOT match nested braces.
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# --- PAYLOAD START ---
# --- PAYLOAD 1 START ---
# === PAYLOAD START ===
# === PAYLOAD 1 START ===
_PAYLOAD_START_RE = re.compile(
    r"^\s*(?:(?:===)|(?:---))\s*PAYLOAD(?:\s+(\d+))?\s+START\s*(?:(?:===)|(?:---))\s*$",
    re.IGNORECASE,
)
_PAYLOAD_END_RE = re.compile(
    r"^\s*(?:(?:===)|(?:---))\s*PAYLOAD(?:\s+(\d+))?\s+END\s*(?:(?:===)|(?:---))\s*$",
    re.IGNORECASE,
)

# Markdown heading lines (h2/h3/h4). We use these as structural anchors.
_HEADING_RE = re.compile(r"^\s{0,3}(#{2,4})\s+(.+?)\s*#*\s*$")

# Ordered / unordered list marker at start of line (common rule patterns).
_RULE_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+.+")

# JSON-like ``"field_name":`` at start of line or after whitespace.
_JSON_FIELD_RE = re.compile(r'(?<!\\)"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:')

# Default protected placeholders. These are "obvious business payload"
# names; callers may override or extend via ``protected_placeholders``.
_DEFAULT_PROTECTED_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "question",
        "answer",
        "label",
        "prediction",
        "reference",
        "context",
        "input",
        "output",
    }
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def normalize_payload_for_comparison(text: str) -> str:
    """Safe normalization for immutable-payload comparison.

    Allowed transforms
    ------------------
    * Line ending normalization (CRLF / CR -> LF)
    * Per-line trailing whitespace removal
    * Final newline normalization (exactly one trailing '\n' if non-empty)

    Forbidden transforms
    --------------------
    * Lower-casing
    * Punctuation removal
    * Line reordering
    * Semantic-level normalization
    """
    if not isinstance(text, str):
        raise TypeError("text must be str, got %s" % type(text).__name__)

    # Line endings: CRLF -> LF; lone CR -> LF.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Per-line trailing whitespace removal.
    lines = [line.rstrip(" \t") for line in normalized.split("\n")]
    out = "\n".join(lines)

    # Final newline normalization.
    if out == "":
        return out
    if not out.endswith("\n"):
        out = out + "\n"
    # Collapse multiple trailing newlines to a single one.
    while out.endswith("\n\n"):
        out = out[:-1]
    return out


def stable_payload_hash(text: str) -> str:
    """Deterministic sha256 over the normalized view of ``text``."""
    if not isinstance(text, str):
        raise TypeError("text must be str, got %s" % type(text).__name__)
    normalized = normalize_payload_for_comparison(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_placeholders(text: str) -> tuple[str, ...]:
    """Return every ``{name}`` token in text, in order.

    Duplicates are preserved (order matters). If you want a set, call
    ``set(extract_placeholders(text))`` at the call site.
    """
    if not isinstance(text, str):
        raise TypeError("text must be str, got %s" % type(text).__name__)
    return tuple(_PLACEHOLDER_RE.findall(text))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def _extract_heading_labels(text: str) -> tuple[str, ...]:
    out: list[str] = []
    for line in text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            out.append(m.group(2).strip())
    return tuple(out)


def _extract_rule_lines(text: str) -> tuple[str, ...]:
    out: list[str] = []
    for line in text.split("\n"):
        if _RULE_LINE_RE.match(line):
            out.append(line.strip())
    return tuple(out)


def _extract_json_field_names(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(_JSON_FIELD_RE.findall(text))))


@dataclass
class _PayloadBlock:
    payload_id: str | None
    content: str
    start_marker: str
    end_marker: str


def _extract_payload_blocks(text: str) -> list[_PayloadBlock] | None:
    """Parse explicit PAYLOAD blocks if present.

    Returns ``None`` when no markers were found — in that case the caller
    should treat the entire input as a single anonymous payload.
    """
    lines = text.split("\n")
    blocks: list[_PayloadBlock] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _PAYLOAD_START_RE.match(lines[i])
        if m:
            start_marker = lines[i].strip()
            payload_id = m.group(1)  # may be None for unnumbered blocks
            j = i + 1
            while j < n and not _PAYLOAD_END_RE.match(lines[j]):
                j += 1
            if j >= n:
                # Unterminated block — treat the remainder as content
                # but still surface it; callers will see "missing marker".
                end_marker = ""
                content = "\n".join(lines[i + 1 :])
            else:
                end_marker = lines[j].strip()
                content = "\n".join(lines[i + 1 : j])
            blocks.append(
                _PayloadBlock(
                    payload_id=payload_id,
                    content=content,
                    start_marker=start_marker,
                    end_marker=end_marker,
                )
            )
            i = j + 1
        else:
            i += 1
    return blocks if blocks else None


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def _validate_single_payload(
    original: str,
    rewritten: str,
    protected_placeholders: Iterable[str] | None,
    payload_id: str | None,
) -> list[ImmutablePayloadIssue]:
    issues: list[ImmutablePayloadIssue] = []
    normalized_orig = normalize_payload_for_comparison(original)
    normalized_new = normalize_payload_for_comparison(rewritten)

    # --- hash check (early exit on exact match) --------------------------
    if normalized_orig == normalized_new:
        return issues

    # --- placeholder check ----------------------------------------------
    orig_ph = extract_placeholders(normalized_orig)
    new_ph = extract_placeholders(normalized_new)
    orig_set = set(orig_ph)
    new_set = set(new_ph)

    # Decide the effective "protected" set. If caller passed an explicit
    # iterable, use it; otherwise default to every placeholder that
    # appeared in the original (they all matter for round-trip).
    if protected_placeholders is not None:
        protected = {p.strip().lstrip("{").rstrip("}") for p in protected_placeholders}
        protected = {p for p in protected if p}
    else:
        protected = orig_set | _DEFAULT_PROTECTED_PLACEHOLDERS

    removed = sorted(protected & (orig_set - new_set))
    added = sorted(new_set - orig_set)
    reordered = orig_ph != new_ph and not removed and not added

    for name in removed:
        issues.append(
            ImmutablePayloadIssue(
                issue_type="placeholder_removed",
                payload_id=payload_id,
                detail="Placeholder {%s} was in the original but is missing from the rewritten text." % name,
                expected="{%s}" % name,
                actual="(missing)",
            )
        )
    for name in added:
        issues.append(
            ImmutablePayloadIssue(
                issue_type="placeholder_added",
                payload_id=payload_id,
                detail="Placeholder {%s} appears in rewritten text but was not in the original." % name,
                expected="(not present)",
                actual="{%s}" % name,
            )
        )
    if reordered:
        issues.append(
            ImmutablePayloadIssue(
                issue_type="placeholder_reordered",
                payload_id=payload_id,
                detail="Placeholder order differs between original and rewritten text.",
                expected=", ".join("{%s}" % p for p in orig_ph),
                actual=", ".join("{%s}" % p for p in new_ph),
            )
        )

    # --- structural lines (headings / rule lines) -----------------------
    orig_headings = _extract_heading_labels(normalized_orig)
    new_headings = _extract_heading_labels(normalized_new)
    orig_headings_set = set(orig_headings)
    new_headings_set = set(new_headings)
    for heading in sorted(orig_headings_set - new_headings_set):
        issues.append(
            ImmutablePayloadIssue(
                issue_type="line_removed",
                payload_id=payload_id,
                detail='Markdown heading removed: "%s".' % heading,
                expected=heading,
                actual="(missing)",
            )
        )
    for heading in sorted(new_headings_set - orig_headings_set):
        issues.append(
            ImmutablePayloadIssue(
                issue_type="line_added",
                payload_id=payload_id,
                detail='New markdown heading appeared: "%s".' % heading,
                expected="(not present)",
                actual=heading,
            )
        )

    orig_rules = _extract_rule_lines(normalized_orig)
    new_rules = _extract_rule_lines(normalized_new)
    orig_rules_set = set(orig_rules)
    new_rules_set = set(new_rules)
    for rule in sorted(orig_rules_set - new_rules_set):
        # Very long rule lines are less meaningful to report verbatim;
        # truncate at 120 chars for readability.
        truncated = rule if len(rule) <= 120 else rule[:117] + "..."
        issues.append(
            ImmutablePayloadIssue(
                issue_type="line_removed",
                payload_id=payload_id,
                detail='Rule/list line removed: "%s".' % truncated,
                expected=truncated,
                actual="(missing)",
            )
        )
    for rule in sorted(new_rules_set - orig_rules_set):
        truncated = rule if len(rule) <= 120 else rule[:117] + "..."
        issues.append(
            ImmutablePayloadIssue(
                issue_type="line_added",
                payload_id=payload_id,
                detail='New rule/list line appeared: "%s".' % truncated,
                expected="(not present)",
                actual=truncated,
            )
        )

    # --- JSON-like field names ------------------------------------------
    orig_fields = _extract_json_field_names(normalized_orig)
    new_fields = _extract_json_field_names(normalized_new)
    orig_fs = set(orig_fields)
    new_fs = set(new_fields)
    for name in sorted(orig_fs - new_fs):
        issues.append(
            ImmutablePayloadIssue(
                issue_type="field_name_changed",
                payload_id=payload_id,
                detail='JSON field "%s" disappeared from rewritten text.' % name,
                expected=name,
                actual="(missing)",
            )
        )
    for name in sorted(new_fs - orig_fs):
        issues.append(
            ImmutablePayloadIssue(
                issue_type="field_name_changed",
                payload_id=payload_id,
                detail='New JSON field "%s" appeared in rewritten text.' % name,
                expected="(not present)",
                actual=name,
            )
        )

    # --- line-count drift check ------------------------------------------
    orig_line_count = sum(1 for _ in _iter_nonempty_lines(normalized_orig))
    new_line_count = sum(1 for _ in _iter_nonempty_lines(normalized_new))
    if orig_line_count > 0:
        ratio = new_line_count / orig_line_count
        # Only surface as an issue when the change is dramatic AND no
        # more specific issue was already reported above. The rationale:
        # if we already caught specific removed/added lines, this summary
        # would be redundant.
        if (ratio <= 0.75 or ratio >= 1.4) and not issues:
            issues.append(
                ImmutablePayloadIssue(
                    issue_type="line_count_changed",
                    payload_id=payload_id,
                    detail="Non-empty line count changed from %d to %d (%.0f%%)."
                    % (orig_line_count, new_line_count, ratio * 100),
                    expected=str(orig_line_count),
                    actual=str(new_line_count),
                )
            )

    # --- final hash discrepancy (catch-all) -----------------------------
    if stable_payload_hash(original) != stable_payload_hash(rewritten):
        # Only add a generic hash_changed if we have no specific issues,
        # and the texts are genuinely different beyond the above checks.
        if not issues:
            issues.append(
                ImmutablePayloadIssue(
                    issue_type="hash_changed",
                    payload_id=payload_id,
                    detail="Normalized payload hash differs between original and rewritten; no more specific issue detected.",
                    expected=stable_payload_hash(original),
                    actual=stable_payload_hash(rewritten),
                )
            )

    return issues


def validate_immutable_payload(
    original: str,
    rewritten: str,
    *,
    protected_placeholders: Iterable[str] | None = None,
) -> ImmutablePayloadValidationResult:
    """Validate that ``rewritten`` preserves the immutable payload of ``original``.

    This is a deterministic text utility — it does not call the LLM and
    has no dependency on optimizer-loop / orchestration modules.

    Behavior
    --------
    1. If either argument is not a ``str``, a ``TypeError`` is raised
       (type-error guardrail; this is not reported through ``result.ok``).
    2. If explicit ``=== PAYLOAD ... ===`` / ``--- PAYLOAD ... ---``
       markers are present, each block is validated independently and
       the payload count / order / marker shape is also checked.
    3. Otherwise, the whole input is treated as a single payload.
    4. Within each payload, we check: placeholders (default + custom),
       structural markdown headings, rule/list lines, JSON-like field
       names, and non-empty-line count drift.
    5. The result is a ``ImmutablePayloadValidationResult`` with
       ``ok=True`` iff no issues were found.
    """
    if not isinstance(original, str):
        raise TypeError("original must be str, got %s" % type(original).__name__)
    if not isinstance(rewritten, str):
        raise TypeError("rewritten must be str, got %s" % type(rewritten).__name__)

    issues: list[ImmutablePayloadIssue] = []

    orig_blocks = _extract_payload_blocks(original)
    new_blocks = _extract_payload_blocks(rewritten)

    # --- N-in-N-out contract ---------------------------------------------
    if orig_blocks is not None or new_blocks is not None:
        orig_count = len(orig_blocks) if orig_blocks else 0
        new_count = len(new_blocks) if new_blocks else 0
        if orig_count != new_count:
            issues.append(
                ImmutablePayloadIssue(
                    issue_type="payload_count_changed",
                    payload_id=None,
                    detail="Payload block count differs: original had %d blocks, rewritten has %d."
                    % (orig_count, new_count),
                    expected=str(orig_count),
                    actual=str(new_count),
                )
            )

        # Marker-pair check: each original block's START/END marker must
        # appear in the rewritten text (as a substring, in order). This
        # catches marker renaming / removal.
        if orig_blocks is not None:
            for idx, block in enumerate(orig_blocks):
                if block.start_marker and block.start_marker not in rewritten:
                    issues.append(
                        ImmutablePayloadIssue(
                            issue_type="payload_marker_changed",
                            payload_id=block.payload_id or str(idx + 1),
                            detail='Original start marker missing from rewritten: "%s".'
                            % block.start_marker,
                            expected=block.start_marker,
                            actual="(missing)",
                        )
                    )
                if block.end_marker and block.end_marker not in rewritten:
                    issues.append(
                        ImmutablePayloadIssue(
                            issue_type="payload_marker_changed",
                            payload_id=block.payload_id or str(idx + 1),
                            detail='Original end marker missing from rewritten: "%s".'
                            % block.end_marker,
                            expected=block.end_marker,
                            actual="(missing)",
                        )
                    )

        # Validate matching blocks in order.
        if orig_blocks and new_blocks:
            for idx in range(min(len(orig_blocks), len(new_blocks))):
                ob = orig_blocks[idx]
                nb = new_blocks[idx]
                pid = ob.payload_id or nb.payload_id or str(idx + 1)
                # Order check: numbered-payload id should match.
                if (
                    ob.payload_id is not None
                    and nb.payload_id is not None
                    and ob.payload_id != nb.payload_id
                ):
                    issues.append(
                        ImmutablePayloadIssue(
                            issue_type="payload_marker_changed",
                            payload_id=pid,
                            detail="Payload id changed from %s to %s at position %d."
                            % (ob.payload_id, nb.payload_id, idx + 1),
                            expected=ob.payload_id,
                            actual=nb.payload_id,
                        )
                    )
                issues.extend(
                    _validate_single_payload(
                        ob.content,
                        nb.content,
                        protected_placeholders,
                        payload_id=pid,
                    )
                )
    else:
        # No markers — single payload.
        issues.extend(
            _validate_single_payload(
                original,
                rewritten,
                protected_placeholders,
                payload_id=None,
            )
        )

    original_hash = stable_payload_hash(original)
    rewritten_hash = stable_payload_hash(rewritten)
    ok = len(issues) == 0

    return ImmutablePayloadValidationResult(
        ok=ok,
        issues=tuple(issues),
        original_hash=original_hash,
        rewritten_hash=rewritten_hash,
    )
